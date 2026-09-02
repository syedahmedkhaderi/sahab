#!/usr/bin/env bash
# =============================================================================
# Sahab — add this GPU server to an existing Sahab.
#
# Run this on a NEW machine to hand its GPUs to a Sahab that is already running
# somewhere else. It installs Docker and the NVIDIA toolkit if they are missing,
# joins the cluster, opens a mutually authenticated Docker API for the control
# plane, pulls the workspace images and reports its GPUs — after which they show
# up on the website and get handed out automatically.
#
# Get the command (with its token) from the admin console: Admin -> VMs -> Add VM.
#
#   curl -fsSL https://raw.githubusercontent.com/syedahmedkhaderi/sahab/main/scripts/join_node.sh \
#     | sudo bash -s -- --server https://sahab.example.com --token <TOKEN>
#
# Safe to re-run: every step checks before it acts, so this doubles as the
# upgrade and repair path.
#
# Flags / env vars (flags win over env):
#   --server <URL>       SAHAB_SERVER        the running Sahab's base URL   (required)
#   --token <TOKEN>      SAHAB_ENROLL_TOKEN  one-time join token            (required)
#   --advertise <IP>     NODE_ADVERTISE_ADDR address the manager dials back on
#                                            (default: this host's LAN address)
#   --docker-port <N>    NODE_DOCKER_PORT    Docker API port (default 2376)
#   --vpn tailscale      NODE_VPN            join a VPN first — for a machine that
#                                            is NOT on the same network as the manager
#   --vpn-key <KEY>      NODE_VPN_KEY        Tailscale auth key
#   --dir <PATH>         SAHAB_DIR           install dir (default: /opt/sahab)
#   --branch <NAME>      SAHAB_BRANCH        git branch (default: main)
#   --repo <URL>         SAHAB_REPO          git remote
#   --skip-prereqs       SAHAB_SKIP_PREREQS=1  don't try to install docker/toolkit
#   --skip-preflight     SAHAB_SKIP_PREFLIGHT=1 skip the GPU preflight gate
#   --uninstall                              leave the cluster and undo the changes
#   -h | --help                              show this help
# =============================================================================
set -euo pipefail

# ----------------------------------------------------------------------------- defaults
SAHAB_REPO="${SAHAB_REPO:-https://github.com/syedahmedkhaderi/sahab.git}"
SAHAB_BRANCH="${SAHAB_BRANCH:-main}"
SAHAB_DIR="${SAHAB_DIR:-/opt/sahab}"
SAHAB_SERVER="${SAHAB_SERVER:-}"
SAHAB_ENROLL_TOKEN="${SAHAB_ENROLL_TOKEN:-}"
NODE_ADVERTISE_ADDR="${NODE_ADVERTISE_ADDR:-}"
NODE_DOCKER_PORT="${NODE_DOCKER_PORT:-2376}"
NODE_VPN="${NODE_VPN:-}"
NODE_VPN_KEY="${NODE_VPN_KEY:-}"
SAHAB_SKIP_PREREQS="${SAHAB_SKIP_PREREQS:-0}"
SAHAB_SKIP_PREFLIGHT="${SAHAB_SKIP_PREFLIGHT:-0}"
DO_UNINSTALL=0

CERT_DIR="/etc/docker/sahab-certs"
DAEMON_JSON="/etc/docker/daemon.json"

# ----------------------------------------------------------------------------- bootstrap logging
# The shared library lives in the repo, which is not on disk yet when this runs
# via `curl | bash`. Define the minimum here; load_shared_lib replaces it.
if [[ -t 1 ]]; then
  B=$'\033[1m'; G=$'\033[0;32m'; Y=$'\033[0;33m'; R=$'\033[0;31m'; C=$'\033[0;36m'; N=$'\033[0m'
else
  B=""; G=""; Y=""; R=""; C=""; N=""
fi
step() { printf "\n%s==>%s %s%s%s\n" "$C" "$N" "$B" "$1" "$N"; }
ok()   { printf "%s[ ok ]%s %s\n" "$G" "$N" "$1"; }
warn() { printf "%s[warn]%s %s\n" "$Y" "$N" "$1"; }
die()  { printf "%s[fail]%s %s\n" "$R" "$N" "$1" >&2; exit 1; }
have() { command -v "$1" >/dev/null 2>&1; }

usage() { sed -n '2,/^set -euo/p' "$0" | sed 's/^# \{0,1\}//; s/^#$//' | sed '$d'; exit 0; }

# ----------------------------------------------------------------------------- arg parse
while [[ $# -gt 0 ]]; do
  case "$1" in
    --server)         SAHAB_SERVER="${2:-}"; shift 2 ;;
    --token)          SAHAB_ENROLL_TOKEN="${2:-}"; shift 2 ;;
    --advertise)      NODE_ADVERTISE_ADDR="${2:-}"; shift 2 ;;
    --docker-port)    NODE_DOCKER_PORT="${2:-}"; shift 2 ;;
    --vpn)            NODE_VPN="${2:-}"; shift 2 ;;
    --vpn-key)        NODE_VPN_KEY="${2:-}"; shift 2 ;;
    --dir)            SAHAB_DIR="${2:-}"; shift 2 ;;
    --branch)         SAHAB_BRANCH="${2:-}"; shift 2 ;;
    --repo)           SAHAB_REPO="${2:-}"; shift 2 ;;
    --skip-prereqs)   SAHAB_SKIP_PREREQS=1; shift ;;
    --skip-preflight) SAHAB_SKIP_PREFLIGHT=1; shift ;;
    --uninstall)      DO_UNINSTALL=1; shift ;;
    -h|--help)        usage ;;
    *) die "Unknown option: $1  (try --help)" ;;
  esac
done

SUDO=""
if [[ "$(id -u)" -ne 0 ]]; then
  have sudo || die "Run this as root, or install sudo. It edits /etc/docker and restarts the Docker daemon."
  SUDO="sudo"
fi

load_shared_lib() {
  # shellcheck source=lib/common.sh
  source "$SAHAB_DIR/scripts/lib/common.sh"
  export SAHAB_SKIP_PREREQS
}

# ----------------------------------------------------------------------------- 0. VPN (optional)
# Only for a machine that is NOT on the same network as the manager. On the
# university LAN this is skipped entirely and the private address is used.
join_vpn() {
  [[ -z "$NODE_VPN" ]] && return 0
  [[ "$NODE_VPN" != "tailscale" ]] && die "Only --vpn tailscale is supported."
  [[ -z "$NODE_VPN_KEY" ]] && die "--vpn tailscale needs --vpn-key."

  step "Joining the VPN (Tailscale)"
  have tailscale || curl -fsSL https://tailscale.com/install.sh | $SUDO sh
  $SUDO tailscale up --authkey "$NODE_VPN_KEY" --accept-routes
  local ts_ip
  ts_ip="$(tailscale ip -4 2>/dev/null | head -n1)"
  [[ -z "$ts_ip" ]] && die "Tailscale came up but reported no address."
  NODE_ADVERTISE_ADDR="$ts_ip"
  ok "on the VPN as $ts_ip"
}

# ----------------------------------------------------------------------------- 1. repo
# Minimum needed to fetch the repo, before the shared library exists on disk.
# Everything else (Docker, compose, the NVIDIA toolkit) is installed by
# install_prereqs() from scripts/lib/common.sh once the clone is present.
ensure_clone_tools() {
  have git && have curl && return 0
  if ! have apt-get; then
    die "git and curl are required to fetch Sahab, and this host has no apt-get to install them with."
  fi
  if [[ "$(id -u)" -ne 0 ]]; then
    have sudo || die "Need root or sudo to install git/curl."
    SUDO="sudo"
  fi
  $SUDO apt-get update -y
  $SUDO apt-get install -y git curl ca-certificates
  ok "installed git and curl"
}

clone_or_update() {
  step "Fetching Sahab into $SAHAB_DIR"
  if [[ -d "$SAHAB_DIR/.git" ]]; then
    $SUDO git -C "$SAHAB_DIR" fetch --depth 1 origin "$SAHAB_BRANCH"
    $SUDO git -C "$SAHAB_DIR" checkout "$SAHAB_BRANCH"
    $SUDO git -C "$SAHAB_DIR" reset --hard "origin/$SAHAB_BRANCH"
    ok "updated existing clone to origin/$SAHAB_BRANCH"
  else
    $SUDO mkdir -p "$(dirname "$SAHAB_DIR")"
    $SUDO git clone --branch "$SAHAB_BRANCH" --depth 1 "$SAHAB_REPO" "$SAHAB_DIR"
    ok "cloned $SAHAB_REPO"
  fi
}

# ----------------------------------------------------------------------------- 2. preflight
run_preflight() {
  step "Host preflight (driver / Docker / GPU-in-container)"
  if [[ "$SAHAB_SKIP_PREFLIGHT" == "1" ]]; then warn "skipping preflight (--skip-preflight)"; return; fi
  if bash "$SAHAB_DIR/scripts/preflight.sh"; then
    ok "preflight passed"
  else
    die "Preflight found blocking issues (see above). Fix them, or re-run with --skip-preflight to override."
  fi
}

# ----------------------------------------------------------------------------- 3. enrol
# Introduce this machine and collect what it needs to join. The response is
# written to a root-only file because it carries the swarm join token and this
# machine's Docker server key.
ENROLL_JSON=""
enroll() {
  step "Registering with $SAHAB_SERVER"

  local gpus
  gpus="$(bash "$SAHAB_DIR/scripts/discover_gpus.sh" --json 2>/dev/null || echo '[]')"
  local gpu_count
  gpu_count="$(printf '%s' "$gpus" | jq 'length' 2>/dev/null || echo 0)"
  ok "found $gpu_count GPU(s) on this machine"

  local driver docker_version
  driver="$(nvidia-smi --query-gpu=driver_version --format=csv,noheader 2>/dev/null | head -n1 || true)"
  docker_version="$(docker version --format '{{.Server.Version}}' 2>/dev/null || true)"

  local payload
  payload="$(jq -nc \
    --arg token "$SAHAB_ENROLL_TOKEN" \
    --arg hostname "$(hostname)" \
    --arg addr "$NODE_ADVERTISE_ADDR" \
    --argjson port "$NODE_DOCKER_PORT" \
    --arg driver "$driver" \
    --arg dockerv "$docker_version" \
    --argjson gpus "$gpus" \
    '{token:$token, hostname:$hostname, advertise_addr:$addr, docker_port:$port,
      driver_version:$driver, docker_version:$dockerv, gpus:$gpus}')"

  local tmp; tmp="$(mktemp)"; chmod 600 "$tmp"
  local code
  code="$(curl -sS -o "$tmp" -w '%{http_code}' \
    -X POST "$SAHAB_SERVER/api/nodes/enroll" \
    -H 'Content-Type: application/json' \
    --data "$payload")" || { rm -f "$tmp"; die "Could not reach $SAHAB_SERVER. Check the URL and that this machine can reach it."; }

  if [[ "$code" != "200" ]]; then
    local detail; detail="$(jq -r '.detail // empty' <"$tmp" 2>/dev/null || true)"
    rm -f "$tmp"
    die "Sahab refused the registration (HTTP $code)${detail:+: $detail}"
  fi

  ENROLL_JSON="$tmp"
  ok "registered as $(jq -r .node_name <"$ENROLL_JSON")"
}

_field() { jq -r ".$1" <"$ENROLL_JSON"; }

# ----------------------------------------------------------------------------- 4. certificates
install_certs() {
  step "Installing the cluster certificates"
  $SUDO mkdir -p "$CERT_DIR"
  $SUDO chmod 700 "$CERT_DIR"

  _field ca_cert     | $SUDO tee "$CERT_DIR/ca.crt"     >/dev/null
  _field server_cert | $SUDO tee "$CERT_DIR/server.crt" >/dev/null
  _field server_key  | $SUDO tee "$CERT_DIR/server.key" >/dev/null
  $SUDO chmod 644 "$CERT_DIR/ca.crt" "$CERT_DIR/server.crt"
  $SUDO chmod 600 "$CERT_DIR/server.key"

  # Trust the registry, which is signed by the same CA. Without this, pulling a
  # workspace image fails with an unhelpful x509 error.
  local registry; registry="$(_field registry_addr)"
  if [[ -n "$registry" && "$registry" != "null" ]]; then
    $SUDO mkdir -p "/etc/docker/certs.d/$registry"
    $SUDO cp "$CERT_DIR/ca.crt" "/etc/docker/certs.d/$registry/ca.crt"
    ok "registry $registry trusted"
  fi
  ok "certificates installed in $CERT_DIR"
}

# ----------------------------------------------------------------------------- 5. Docker API
# Open the Docker API on the advertise address with mutual TLS, so the control
# plane can start containers here. Bound to that one address rather than
# 0.0.0.0: on the LAN path there is no reason for it to listen anywhere else.
configure_dockerd() {
  step "Opening the Docker API on $NODE_ADVERTISE_ADDR:$NODE_DOCKER_PORT (mutual TLS)"

  local existing='{}'
  [[ -f "$DAEMON_JSON" ]] && existing="$($SUDO cat "$DAEMON_JSON")"

  local updated
  updated="$(printf '%s' "$existing" | jq \
    --arg host "tcp://$NODE_ADVERTISE_ADDR:$NODE_DOCKER_PORT" \
    --arg ca "$CERT_DIR/ca.crt" \
    --arg cert "$CERT_DIR/server.crt" \
    --arg key "$CERT_DIR/server.key" \
    '. + {
        hosts: (((.hosts // []) + ["unix:///var/run/docker.sock", $host]) | unique),
        tls: true, tlsverify: true, tlscacert: $ca, tlscert: $cert, tlskey: $key
     }')"

  printf '%s\n' "$updated" | $SUDO tee "$DAEMON_JSON" >/dev/null
  ok "wrote $DAEMON_JSON"

  # systemd's unit file passes its own -H, which conflicts with daemon.json's
  # "hosts" and makes dockerd refuse to start. Clearing ExecStart in a drop-in is
  # the documented fix; without it the daemon dies on restart with
  # "unable to configure the Docker daemon with file /etc/docker/daemon.json".
  if [[ -d /etc/systemd/system ]]; then
    $SUDO mkdir -p /etc/systemd/system/docker.service.d
    printf '[Service]\nExecStart=\nExecStart=/usr/bin/dockerd\n' \
      | $SUDO tee /etc/systemd/system/docker.service.d/sahab-hosts.conf >/dev/null
    $SUDO systemctl daemon-reload
  fi

  $SUDO systemctl restart docker
  # Give dockerd a moment to come back before anything talks to it.
  local tries=0
  until docker info >/dev/null 2>&1; do
    tries=$((tries + 1))
    [[ $tries -gt 30 ]] && die "Docker did not come back after the restart. Check: journalctl -u docker -n 50"
    sleep 1
  done
  ok "Docker API listening with mutual TLS"
}

# ----------------------------------------------------------------------------- 6. cluster
join_swarm() {
  step "Joining the cluster"
  local state; state="$(docker info --format '{{.Swarm.LocalNodeState}}' 2>/dev/null || echo unknown)"
  if [[ "$state" == "active" ]]; then
    ok "already a member of a swarm"
    return 0
  fi
  $SUDO docker swarm join \
    --token "$(_field swarm_join_token)" \
    --advertise-addr "$NODE_ADVERTISE_ADDR" \
    "$(_field manager_addr):2377" \
    || die "Could not join the cluster. The manager must be reachable on ports 2377/tcp, 7946/tcp+udp and 4789/udp from this machine."
  ok "joined the cluster"
}

# ----------------------------------------------------------------------------- 7. images
pull_images() {
  step "Pulling the workspace images"
  local img
  for img in "$(_field gpu_image)" "$(_field cpu_image)"; do
    [[ -z "$img" || "$img" == "null" ]] && continue
    if $SUDO docker pull "$img"; then
      ok "pulled $img"
    else
      warn "could not pull $img — the first workspace on this machine will be slow, or fail if the image is unavailable."
    fi
  done
}

# ----------------------------------------------------------------------------- 8. exporters
start_node_services() {
  step "Starting the metrics exporters"
  NODE_ADVERTISE_ADDR="$NODE_ADVERTISE_ADDR" $SUDO -E docker compose \
    -f "$SAHAB_DIR/infra/docker-compose.node.yml" up -d \
    || warn "exporters did not all start; the machine still works, but its GPU usage will not be visible to the scheduler."
  ok "dcgm-exporter, node-exporter and cAdvisor running"
}

# ----------------------------------------------------------------------------- 9. hand back
complete() {
  step "Handing the machine over to Sahab"
  local tmp; tmp="$(mktemp)"
  local code
  code="$(curl -sS -o "$tmp" -w '%{http_code}' \
    -X POST "$SAHAB_SERVER/api/nodes/enroll/complete" \
    -H 'Content-Type: application/json' \
    --data "$(jq -nc --arg token "$SAHAB_ENROLL_TOKEN" '{token:$token}')")" || true

  if [[ "$code" != "200" ]]; then
    local detail; detail="$(jq -r '.detail // empty' <"$tmp" 2>/dev/null || true)"
    rm -f "$tmp"
    die "Sahab could not confirm this machine${detail:+: $detail}"
  fi

  local gpus; gpus="$(jq -r '.gpus_registered' <"$tmp")"
  rm -f "$tmp"
  ok "$gpus GPU(s) are now in the pool"
}

summary() {
  step "This machine is part of Sahab 🎉"
  printf "  Machine  : %s%s%s (%s)\n" "$B" "$(hostname)" "$N" "$NODE_ADVERTISE_ADDR"
  printf "  Sahab    : %s\n" "$SAHAB_SERVER"
  printf "  GPUs     : now allocated automatically to users of that site\n"
  echo
  echo "  Check on it:  Admin -> VMs in the Sahab console"
  echo "  Re-run this command any time to update or repair this machine."
}

# ----------------------------------------------------------------------------- uninstall
uninstall() {
  step "Removing this machine from the cluster"
  $SUDO docker swarm leave --force 2>/dev/null || warn "not in a swarm"
  [[ -f "$SAHAB_DIR/infra/docker-compose.node.yml" ]] && \
    $SUDO docker compose -f "$SAHAB_DIR/infra/docker-compose.node.yml" down 2>/dev/null || true

  if [[ -f "$DAEMON_JSON" ]] && have jq; then
    $SUDO cat "$DAEMON_JSON" \
      | jq 'del(.tls, .tlsverify, .tlscacert, .tlscert, .tlskey)
            | .hosts = ((.hosts // []) | map(select(startswith("unix://"))))
            | if (.hosts | length) == 0 then del(.hosts) else . end' \
      | $SUDO tee "$DAEMON_JSON.new" >/dev/null
    $SUDO mv "$DAEMON_JSON.new" "$DAEMON_JSON"
    $SUDO rm -f /etc/systemd/system/docker.service.d/sahab-hosts.conf
    $SUDO systemctl daemon-reload 2>/dev/null || true
    $SUDO systemctl restart docker
    ok "Docker API closed again"
  fi

  $SUDO rm -rf "$CERT_DIR"
  ok "certificates removed"
  warn "Remove the machine from the Sahab console too: Admin -> VMs."
  echo "Note: the clone at $SAHAB_DIR was left in place; delete it by hand if you want it gone."
}

# ----------------------------------------------------------------------------- main
main() {
  printf "%s\n  Sahab — adding this GPU server to an existing Sahab\n%s\n" "$B" "$N"

  if [[ "$DO_UNINSTALL" == "1" ]]; then
    uninstall
    return 0
  fi

  [[ -z "$SAHAB_SERVER" ]] && die "Missing --server. Get the full command from Admin -> VMs -> Add VM in the Sahab console."
  [[ -z "$SAHAB_ENROLL_TOKEN" ]] && die "Missing --token. Get the full command from Admin -> VMs -> Add VM in the Sahab console."
  SAHAB_SERVER="${SAHAB_SERVER%/}"

  ensure_clone_tools
  clone_or_update
  load_shared_lib
  install_prereqs
  join_vpn

  if [[ -z "$NODE_ADVERTISE_ADDR" ]]; then
    NODE_ADVERTISE_ADDR="$(detect_advertise_addr)"
    [[ -z "$NODE_ADVERTISE_ADDR" ]] && die "Could not work out this machine's address. Pass it with --advertise <ip>."
    ok "this machine will be reached at $NODE_ADVERTISE_ADDR"
  fi

  run_preflight
  # Clean up the enrollment response (it holds the join token and this
  # machine's Docker key) however the script exits from here on.
  trap 'rm -f "${ENROLL_JSON:-}"' EXIT
  enroll
  install_certs
  configure_dockerd
  join_swarm
  pull_images
  start_node_services
  complete
  summary
}

# Only auto-run when executed directly (allows sourcing for tests).
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
  main "$@"
fi

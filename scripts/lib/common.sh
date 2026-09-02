#!/usr/bin/env bash
# =============================================================================
# Sahab — helpers shared by bootstrap.sh (set up the control plane) and
# join_node.sh (add a GPU server to an existing one).
#
# Both scripts install exactly the same host prerequisites, and both have to
# survive being re-run. Keeping one copy here is the same discipline
# scripts/lib/tunnel.sh already enforces for the two tunnel paths: the two ways
# of standing up a machine cannot drift apart if there is only one of them.
#
# Sourced, never executed.
# =============================================================================

# ----------------------------------------------------------------------------- logging
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

SUDO="${SUDO:-}"
need_root() {
  if [[ "$(id -u)" -eq 0 ]]; then SUDO=""
  elif have sudo && sudo -n true 2>/dev/null; then SUDO="sudo"
  elif have sudo; then SUDO="sudo"; warn "sudo may prompt for your password."
  else die "Need root or sudo to install system packages. Re-run as root, or pass --skip-prereqs if Docker + the NVIDIA toolkit are already installed."
  fi
}

# ----------------------------------------------------------------------------- prereqs
# Install git/curl/openssl, Docker Engine + compose v2, and the NVIDIA Container
# Toolkit. Idempotent: every step checks before it acts.
install_prereqs() {
  step "Checking host prerequisites"
  if [[ "${SAHAB_SKIP_PREREQS:-0}" == "1" ]]; then warn "skipping prereq install (--skip-prereqs)"; return; fi

  if ! have apt-get; then
    warn "Non-apt host: cannot auto-install. Ensure git, openssl, Docker (with compose v2) and the NVIDIA Container Toolkit are present."
    return
  fi

  local missing=()
  have git || missing+=(git)
  have curl || missing+=(curl)
  have openssl || missing+=(openssl)
  have jq || missing+=(jq)
  if ((${#missing[@]})); then
    need_root
    $SUDO apt-get update -y
    $SUDO apt-get install -y "${missing[@]}" ca-certificates
    ok "installed: ${missing[*]}"
  else ok "git, curl, openssl, jq present"; fi

  if ! have docker; then
    need_root
    step "Installing Docker Engine (get.docker.com)"
    curl -fsSL https://get.docker.com | $SUDO sh
    $SUDO usermod -aG docker "${SUDO_USER:-$USER}" 2>/dev/null || true
    ok "Docker installed (you may need to re-login for group membership)"
  else ok "Docker present: $(docker --version)"; fi

  if ! docker compose version >/dev/null 2>&1; then
    warn "Docker Compose v2 plugin not found; attempting install."
    need_root; $SUDO apt-get install -y docker-compose-plugin || \
      die "Could not install docker compose v2. Install it, then re-run."
  fi
  ok "Docker Compose v2 present"

  # NVIDIA Container Toolkit — only if a GPU/driver is present and toolkit missing.
  if have nvidia-smi; then
    if docker info 2>/dev/null | grep -qi nvidia || \
       docker run --rm --gpus all nvidia/cuda:12.4.1-base-ubuntu22.04 nvidia-smi -L >/dev/null 2>&1; then
      ok "NVIDIA Container Toolkit already working"
    else
      need_root
      step "Installing NVIDIA Container Toolkit"
      curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey | \
        $SUDO gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg
      curl -fsSL https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list | \
        sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' | \
        $SUDO tee /etc/apt/sources.list.d/nvidia-container-toolkit.list >/dev/null
      $SUDO apt-get update -y
      $SUDO apt-get install -y nvidia-container-toolkit
      $SUDO nvidia-ctk runtime configure --runtime=docker
      $SUDO systemctl restart docker
      ok "NVIDIA Container Toolkit installed and wired into Docker"
    fi
  else
    warn "nvidia-smi not found — host has no NVIDIA driver. GPU sessions will not work until a driver is installed."
  fi
}

# ----------------------------------------------------------------------------- ownership
# The backend container runs as this uid (backend/Dockerfile: useradd -u 1001).
# The secrets directory is a host bind mount, so it keeps the host's ownership
# rather than the image's — which means the host has to hand it to that uid, or
# the backend cannot write the node map or issue a node's certificate.
SAHAB_CONTAINER_UID="${SAHAB_CONTAINER_UID:-1001}"

# Give a directory to the container's uid, using root only if we are not it.
chown_to_container() {
  local path="$1"
  [[ -e "$path" ]] || return 0
  local owner; owner="$(stat -c '%u' "$path" 2>/dev/null || echo "")"
  [[ "$owner" == "$SAHAB_CONTAINER_UID" ]] && return 0

  if [[ "$(id -u)" -eq 0 ]] || sudo -n true 2>/dev/null; then
    need_root
    $SUDO chown -R "$SAHAB_CONTAINER_UID:$SAHAB_CONTAINER_UID" "$path"
    # Keep the directories traversable after the change of owner. Without this,
    # the host can no longer read its own ca.crt — which breaks the image push
    # and every later bootstrap re-run.
    $SUDO find "$path" -type d -exec chmod 711 {} +
    ok "handed $path to the backend's user"
  else
    warn "could not change the owner of $path (needs root)."
    warn "The backend cannot write there, so adding a GPU server will fail. Run:"
    warn "  sudo chown -R $SAHAB_CONTAINER_UID:$SAHAB_CONTAINER_UID '$path'"
  fi
}

# ----------------------------------------------------------------------------- addresses
# Best guess at the address other machines should use to reach this one.
#
# Prefers the interface that carries the default route, which on a university VM
# is the private LAN address (10.x / 172.16-31.x / 192.168.x) — the one the other
# GPU servers can actually reach. Docker's own bridges are excluded: 172.17.0.1
# means something different on every machine.
detect_advertise_addr() {
  local addr
  addr="$(ip -4 route get 1.1.1.1 2>/dev/null | awk '{for(i=1;i<=NF;i++) if($i=="src") print $(i+1); exit}')"
  if [[ -n "$addr" && "$addr" != 172.1[7-9].* && "$addr" != 172.2*.* ]]; then
    printf '%s' "$addr"; return 0
  fi
  # Fall back to the first private, non-docker address on the box.
  ip -4 -o addr show scope global 2>/dev/null \
    | awk '{print $4}' | cut -d/ -f1 \
    | grep -vE '^(172\.1[7-9]\.|172\.2[0-9]\.|172\.3[0-1]\.|169\.254\.)' \
    | head -n1
}

# ----------------------------------------------------------------------------- swarm
# Make this host a swarm manager, idempotently, and echo the worker join token.
#
# Swarm is used here for exactly two things: knowing which machines are in the
# cluster, and giving us an encrypted overlay network that spans them. Workspace
# containers are still ordinary containers started by DockerSpawner, not swarm
# services — see jupyterhub/jupyterhub_config.py for why.
# The token is this function's *return value* on stdout, so every human-facing
# line here goes to stderr. Logging to stdout would splice "[ ok ] swarm
# initialised" into the token the caller stores in .env, and the failure would
# only surface much later, when a machine tried to join with it.
ensure_swarm_manager() {
  local advertise="$1"
  local state
  state="$(docker info --format '{{.Swarm.LocalNodeState}}' 2>/dev/null || echo unknown)"

  case "$state" in
    active)
      if [[ "$(docker info --format '{{.Swarm.ControlAvailable}}' 2>/dev/null)" != "true" ]]; then
        die "This host is already a swarm *worker* of another cluster. Run 'docker swarm leave' first if it should be the Sahab control plane."
      fi
      ok "swarm already initialised" >&2
      ;;
    *)
      docker swarm init --advertise-addr "$advertise" >/dev/null 2>&1 \
        || docker swarm init --advertise-addr "$advertise" >&2 \
        || die "docker swarm init failed. Check that $advertise is a real address on this host."
      ok "swarm initialised on $advertise" >&2
      ;;
  esac

  docker swarm join-token -q worker
}

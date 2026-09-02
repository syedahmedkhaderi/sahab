#!/usr/bin/env bash
# =============================================================================
# Sahab — one-command bootstrap
#
# Turns a fresh university GPU VM into a fully working, publicly-reachable Sahab
# instance with a single command. Safe to re-run (idempotent): it updates the
# repo, fills only missing secrets, rebuilds what changed, and re-publishes the
# public URL.
#
# Quick start (zero config — gets you a public https URL with no domain):
#   curl -fsSL https://raw.githubusercontent.com/syedahmedkhaderi/sahab/main/scripts/bootstrap.sh | bash
#
# Or, once you have a named Cloudflare tunnel + domain:
#   curl -fsSL .../bootstrap.sh | bash -s -- \
#       --token eyJ... --hostname sahab.yourdomain.com
#
# Common flags / env vars (flags win over env):
#   --token <TOKEN>        CLOUDFLARE_TUNNEL_TOKEN   named-tunnel token (else quick tunnel)
#   --hostname <HOST>      PUBLIC_HOSTNAME           public hostname for the named tunnel
#   --dir <PATH>           SAHAB_DIR                 install dir (default: ~/sahab)
#   --branch <NAME>        SAHAB_BRANCH              git branch (default: main)
#   --repo <URL>           SAHAB_REPO                git remote (default: this repo)
#   --no-tunnel            SAHAB_NO_TUNNEL=1         LAN-only; no public URL
#   --skip-build           SAHAB_SKIP_BUILD=1        reuse existing images (don't rebuild)
#   --skip-prereqs         SAHAB_SKIP_PREREQS=1      don't try to install docker/toolkit
#   --skip-preflight       SAHAB_SKIP_PREFLIGHT=1    skip the host GPU preflight gate
#   --admin-email <EMAIL>  BOOTSTRAP_ADMIN_EMAIL     seeded admin login
#   --signup-domains <CSV> ALLOWED_SIGNUP_DOMAINS    e.g. udst.edu.qa
#   -h | --help                                      show this help
# =============================================================================
set -euo pipefail

# ----------------------------------------------------------------------------- defaults
SAHAB_REPO="${SAHAB_REPO:-https://github.com/syedahmedkhaderi/sahab.git}"
SAHAB_BRANCH="${SAHAB_BRANCH:-main}"
SAHAB_DIR="${SAHAB_DIR:-$HOME/sahab}"
CLOUDFLARE_TUNNEL_TOKEN="${CLOUDFLARE_TUNNEL_TOKEN:-}"
PUBLIC_HOSTNAME="${PUBLIC_HOSTNAME:-}"
SAHAB_NO_TUNNEL="${SAHAB_NO_TUNNEL:-0}"
SAHAB_SKIP_BUILD="${SAHAB_SKIP_BUILD:-0}"
SAHAB_SKIP_PREREQS="${SAHAB_SKIP_PREREQS:-0}"
SAHAB_SKIP_PREFLIGHT="${SAHAB_SKIP_PREFLIGHT:-0}"
BOOTSTRAP_ADMIN_EMAIL_OVERRIDE="${BOOTSTRAP_ADMIN_EMAIL:-}"
ALLOWED_SIGNUP_DOMAINS_OVERRIDE="${ALLOWED_SIGNUP_DOMAINS:-}"

# ----------------------------------------------------------------------------- shared helpers
# Logging, .env editing, the compose wrapper and the tunnel logic all live in
# scripts/lib/tunnel.sh so that bootstrap and scripts/tunnel.sh publish a URL
# exactly the same way. When run via `curl | bash` the repo is not on disk yet,
# so the library is sourced after the clone (see load_shared_lib below).
if [[ -t 1 ]]; then
  B=$'\033[1m'; G=$'\033[0;32m'; Y=$'\033[0;33m'; R=$'\033[0;31m'; C=$'\033[0;36m'; N=$'\033[0m'
else
  B=""; G=""; Y=""; R=""; C=""; N=""
fi
step() { printf "\n%s==>%s %s%s%s\n" "$C" "$N" "$B" "$1" "$N"; }
ok()   { printf "%s[ ok ]%s %s\n" "$G" "$N" "$1"; }
warn() { printf "%s[warn]%s %s\n" "$Y" "$N" "$1"; }
die()  { printf "%s[fail]%s %s\n" "$R" "$N" "$1" >&2; exit 1; }

# Replaces the definitions above (and set_env/get_env/dc below) with the shared
# ones, once the repo is present.
load_shared_lib() {
  # shellcheck source=lib/tunnel.sh
  source "$SAHAB_DIR/scripts/lib/tunnel.sh"
  # install_prereqs, need_root, detect_advertise_addr, ensure_swarm_manager —
  # shared verbatim with scripts/join_node.sh so the two ways of standing up a
  # machine cannot drift apart.
  # shellcheck source=lib/common.sh
  source "$SAHAB_DIR/scripts/lib/common.sh"
  # shellcheck source=lib/pki.sh
  source "$SAHAB_DIR/scripts/lib/pki.sh"
  export SAHAB_SKIP_PREREQS
}

usage() { sed -n '2,/^set -euo/p' "$0" | sed 's/^# \{0,1\}//; s/^#$//' | sed '$d'; exit 0; }

# ----------------------------------------------------------------------------- arg parse
while [[ $# -gt 0 ]]; do
  case "$1" in
    --token)          CLOUDFLARE_TUNNEL_TOKEN="${2:-}"; shift 2 ;;
    --hostname)       PUBLIC_HOSTNAME="${2:-}"; shift 2 ;;
    --dir)            SAHAB_DIR="${2:-}"; shift 2 ;;
    --branch)         SAHAB_BRANCH="${2:-}"; shift 2 ;;
    --repo)           SAHAB_REPO="${2:-}"; shift 2 ;;
    --admin-email)    BOOTSTRAP_ADMIN_EMAIL_OVERRIDE="${2:-}"; shift 2 ;;
    --signup-domains) ALLOWED_SIGNUP_DOMAINS_OVERRIDE="${2:-}"; shift 2 ;;
    --no-tunnel)      SAHAB_NO_TUNNEL=1; shift ;;
    --skip-build)     SAHAB_SKIP_BUILD=1; shift ;;
    --skip-prereqs)   SAHAB_SKIP_PREREQS=1; shift ;;
    --skip-preflight) SAHAB_SKIP_PREFLIGHT=1; shift ;;
    -h|--help)        usage ;;
    *) die "Unknown argument: $1 (use --help)" ;;
  esac
done

[[ -n "$CLOUDFLARE_TUNNEL_TOKEN" && -z "$PUBLIC_HOSTNAME" ]] && \
  die "--token requires --hostname (the public hostname mapped to that tunnel)."

# ----------------------------------------------------------------------------- helpers
# have() / need_root() / SUDO are defined in scripts/lib/common.sh, which is
# sourced once the repo is on disk. This minimal copy covers the pre-clone stage.
have() { command -v "$1" >/dev/null 2>&1; }
SUDO=""

# set_env / get_env / dc / publish_quick_tunnel come from scripts/lib/tunnel.sh,
# sourced by load_shared_lib once the repo is on disk.
ENV_FILE=""

# Generate a strong secret into KEY only if it's empty or still a placeholder.
gen_secret() {
  local key="$1" cur; cur="$(get_env "$key")"
  if [[ -z "$cur" || "$cur" == *change-me* || "$cur" == *example* ]]; then
    set_env "$key" "$(openssl rand -hex 32)"
    ok "generated $key"
  else
    ok "$key already set (kept)"
  fi
}

# ----------------------------------------------------------------------------- 1. prereqs
# install_prereqs() and need_root() come from scripts/lib/common.sh, shared with
# join_node.sh. They are only available after the clone, so main() calls them
# after clone_or_update rather than before.

# ----------------------------------------------------------------------------- 2. repo
# Minimum needed to fetch the repo, before the shared library exists on disk.
# Everything else (Docker, compose, the NVIDIA toolkit) is installed by
# install_prereqs() from scripts/lib/common.sh once the clone is present.
ensure_clone_tools() {
  have git && have curl && have tar && return 0
  if ! have apt-get; then
    die "git, curl and tar are required to fetch Sahab, and this host has no apt-get to install them with."
  fi
  if [[ "$(id -u)" -ne 0 ]]; then
    have sudo || die "Need root or sudo to install git/curl."
    SUDO="sudo"
  fi
  $SUDO apt-get update -y
  $SUDO apt-get install -y git curl tar ca-certificates
  ok "installed git, curl and tar"
}

# GitHub serves a plain HTTPS tarball of any public repo. Used only as a
# fallback below, so a self-hosted or otherwise non-GitHub SAHAB_REPO is left
# to git alone.
tarball_url() {
  case "$SAHAB_REPO" in
    https://github.com/*)
      local slug="${SAHAB_REPO#https://github.com/}"
      printf 'https://codeload.github.com/%s/tar.gz/refs/heads/%s\n' "${slug%.git}" "$SAHAB_BRANCH"
      ;;
    *) return 1 ;;
  esac
}

clone_or_update() {
  step "Fetching Sahab into $SAHAB_DIR"

  if [[ -d "$SAHAB_DIR/.git" ]]; then
    env GIT_TERMINAL_PROMPT=0 git -C "$SAHAB_DIR" fetch --depth 1 origin "$SAHAB_BRANCH"
    git -C "$SAHAB_DIR" checkout "$SAHAB_BRANCH"
    git -C "$SAHAB_DIR" reset --hard "origin/$SAHAB_BRANCH"
    ok "updated existing clone to origin/$SAHAB_BRANCH"
    return 0
  fi

  if [[ ! -e "$SAHAB_DIR" ]]; then
    mkdir -p "$(dirname "$SAHAB_DIR")"
    if env GIT_TERMINAL_PROMPT=0 git clone --branch "$SAHAB_BRANCH" --depth 1 "$SAHAB_REPO" "$SAHAB_DIR"; then
      ok "cloned $SAHAB_REPO"
      return 0
    fi
  fi

  # Git could not fetch it. That is not always a network fault: some stock
  # images ship a git old enough to choke on GitHub's protocol v2 ("expected
  # flush after ref listing") and then prompt for a password that does not
  # exist for a public repo. A tarball is the same code over the same HTTPS
  # and asks nothing of git, so the install should not stop here. Only reached
  # when there is no clone to damage -- an existing checkout is left to git.
  local url
  url="$(tarball_url)" \
    || die "Could not fetch $SAHAB_REPO with git, and it is not a GitHub URL to download as a tarball."
  warn "git could not fetch the repo; downloading the source instead"
  mkdir -p "$SAHAB_DIR"
  curl -fsSL "$url" | tar xz -C "$SAHAB_DIR" --strip-components=1 \
    || die "Could not download $url either. Check this machine's outbound HTTPS access."
  ok "downloaded $SAHAB_BRANCH from $SAHAB_REPO"
}

# ----------------------------------------------------------------------------- 3. .env
generate_env() {
  step "Generating configuration (.env)"
  ENV_FILE="$SAHAB_DIR/.env"
  # The repo is on disk by now, so switch to the shared helpers.
  load_shared_lib
  if [[ ! -f "$ENV_FILE" ]]; then
    cp "$SAHAB_DIR/.env.example" "$ENV_FILE"
    ok "created .env from .env.example"
  else
    ok "existing .env found — keeping your values, filling only what's missing"
  fi

  gen_secret JWT_SECRET
  gen_secret OAUTH_CLIENT_SECRET
  gen_secret JUPYTERHUB_API_TOKEN

  # Passwords: keep alnum-safe (hex) so they're shell/URL-safe everywhere.
  local key
  for key in POSTGRES_PASSWORD GRAFANA_ADMIN_PASSWORD BOOTSTRAP_ADMIN_PASSWORD; do
    local cur; cur="$(get_env "$key")"
    if [[ -z "$cur" || "$cur" == *change-me* || "$cur" == *example* ]]; then
      set_env "$key" "$(openssl rand -hex 16)"; ok "generated $key"
    else ok "$key already set (kept)"; fi
  done

  # DATABASE_URL must always match the postgres creds — rebuild it from them.
  local pu pp pd
  pu="$(get_env POSTGRES_USER)"; pp="$(get_env POSTGRES_PASSWORD)"; pd="$(get_env POSTGRES_DB)"
  set_env DATABASE_URL "postgresql+psycopg://${pu}:${pp}@postgres:5432/${pd}"
  ok "DATABASE_URL aligned to postgres credentials"

  [[ -n "$BOOTSTRAP_ADMIN_EMAIL_OVERRIDE" ]] && set_env BOOTSTRAP_ADMIN_EMAIL "$BOOTSTRAP_ADMIN_EMAIL_OVERRIDE"
  [[ -n "$ALLOWED_SIGNUP_DOMAINS_OVERRIDE" ]] && set_env ALLOWED_SIGNUP_DOMAINS "$ALLOWED_SIGNUP_DOMAINS_OVERRIDE"

  # Named-tunnel inputs (quick-tunnel mode fills PUBLIC_HOSTNAME later, post-handoff).
  [[ -n "$CLOUDFLARE_TUNNEL_TOKEN" ]] && set_env CLOUDFLARE_TUNNEL_TOKEN "$CLOUDFLARE_TUNNEL_TOKEN"
  [[ -n "$PUBLIC_HOSTNAME" ]] && set_env PUBLIC_HOSTNAME "$PUBLIC_HOSTNAME"
  return 0
}

# ----------------------------------------------------------------------------- 3b. cluster
# Everything needed before another GPU server can join: swarm membership, the
# cluster CA, the private registry, and the overlay network.
#
# All of it is harmless on a machine that stays single-VM forever — a one-node
# swarm behaves exactly like no swarm — so it runs unconditionally rather than
# behind a flag nobody would remember to set.
setup_cluster() {
  step "Preparing this machine to accept other GPU servers"

  local advertise
  advertise="$(get_env MANAGER_ADVERTISE_ADDR)"
  if [[ -z "$advertise" ]]; then
    advertise="$(detect_advertise_addr)"
    [[ -z "$advertise" ]] && die "Could not work out this machine's address. Set MANAGER_ADVERTISE_ADDR in .env and re-run."
  fi
  set_env MANAGER_ADVERTISE_ADDR "$advertise"
  set_env MANAGER_NODE_NAME "$(hostname)"
  ok "other machines will reach this one at $advertise"

  local worker_token
  worker_token="$(ensure_swarm_manager "$advertise")"
  # A token that is not a token is worse than no token: it is written to .env,
  # handed to a machine that tries to join, and fails there instead of here.
  [[ "$worker_token" == SWMTKN-* ]] \
    || die "Could not read the swarm worker join token (got: ${worker_token:0:40})."
  set_env SWARM_WORKER_TOKEN "$worker_token"

  # The overlay network is what lets a container on another machine reach the hub
  # (and the hub reach it) without publishing a single port.
  set_env DOCKER_NETWORK_DRIVER overlay
  migrate_network_driver

  local registry_port; registry_port="$(get_env REGISTRY_PORT)"
  [[ -z "$registry_port" ]] && { registry_port=5000; set_env REGISTRY_PORT "$registry_port"; }
  set_env REGISTRY_ADDR "${advertise}:${registry_port}"

  ensure_pki "$SAHAB_DIR/secrets" "$advertise"
  # ensure_pki writes as whoever ran bootstrap; the backend reads and writes the
  # same directory from inside its container as uid 1001.
  chown_to_container "$SAHAB_DIR/secrets"

  # The images must be named for the registry, or another machine cannot pull them.
  set_env WORKSPACE_GPU_IMAGE "${advertise}:${registry_port}/sahab-gpu-pytorch:latest"
  set_env WORKSPACE_CPU_IMAGE "${advertise}:${registry_port}/sahab-cpu-base:latest"

  trust_own_registry "$advertise" "$registry_port"
}

# Docker only trusts a registry whose CA sits under /etc/docker/certs.d, which is
# root-owned. Not being able to write it is not fatal — it costs the image push,
# and everything else still works — so it warns with the exact command instead of
# stopping a bootstrap that is otherwise fine.
trust_own_registry() {
  local advertise="$1" registry_port="$2"
  local dest="/etc/docker/certs.d/${advertise}:${registry_port}"
  local src="$SAHAB_DIR/secrets/docker-ca/ca.crt"

  if [[ -f "$dest/ca.crt" ]] && cmp -s "$src" "$dest/ca.crt"; then
    ok "this machine already trusts its own registry"
    return 0
  fi

  if [[ "$(id -u)" -eq 0 ]] || sudo -n true 2>/dev/null; then
    need_root
    $SUDO mkdir -p "$dest"
    $SUDO cp "$src" "$dest/ca.crt"
    ok "this machine trusts its own registry"
    return 0
  fi

  warn "could not write $dest (needs root)."
  warn "Workspace images will not reach the other GPU servers until you run:"
  warn "  sudo mkdir -p '$dest' && sudo cp '$src' '$dest/ca.crt'"
  return 0
}

# Compose refuses to change an existing network's driver in place. Switching from
# bridge to overlay therefore needs the old network removed, which needs the
# containers on it stopped first.
migrate_network_driver() {
  local net; net="$(get_env DOCKER_NETWORK_NAME)"; net="${net:-sahab-network}"
  local current
  current="$(docker network inspect "$net" --format '{{.Driver}}' 2>/dev/null || echo "")"
  [[ -z "$current" || "$current" == "overlay" ]] && return 0

  warn "the $net network is a $current network and has to be recreated as an overlay"
  warn "this restarts the platform once; running sessions will be stopped"
  dc down --remove-orphans 2>/dev/null || true
  docker network rm "$net" >/dev/null 2>&1 || true
  ok "network removed; it will be recreated as an overlay"
}

# ----------------------------------------------------------------------------- 3c. schema
# Bring the database schema up to date.
#
# Historically the app relied on create_all at startup, which can create tables
# but cannot add a column to one that already exists — so an existing install
# would never gain gpu_inventory.node_id. Migrations run here, before the backend
# starts, so both a fresh database and an existing one end up in the same place.
migrate_database() {
  step "Applying database migrations"
  dc up -d postgres
  local tries=0
  until dc exec -T postgres pg_isready -q 2>/dev/null; do
    tries=$((tries + 1)); [[ $tries -gt 60 ]] && die "Postgres did not become ready."
    sleep 1
  done

  if dc run --rm --no-deps -T backend alembic upgrade head; then
    ok "schema up to date"
  else
    warn "alembic could not apply migrations cleanly."
    warn "If this database was built by an older Sahab, the tables may already"
    warn "match the latest schema. Check with:"
    warn "  dc exec postgres psql -U \$POSTGRES_USER -d \$POSTGRES_DB -c '\\d gpu_inventory'"
    die "Refusing to continue with an uncertain schema."
  fi
}

# ----------------------------------------------------------------------------- 4. preflight
run_preflight() {
  step "Host preflight (driver / Docker / GPU-in-container)"
  if [[ "$SAHAB_SKIP_PREFLIGHT" == "1" ]]; then warn "skipping preflight (--skip-preflight)"; return; fi
  if bash "$SAHAB_DIR/scripts/preflight.sh"; then ok "preflight passed"; else
    die "Preflight found blocking issues (see above). Fix them, or re-run with --skip-preflight to override."
  fi
}

# ----------------------------------------------------------------------------- 5. images
build_images() {
  step "Building workspace images"
  if [[ "$SAHAB_SKIP_BUILD" == "1" ]]; then warn "skipping image build (--skip-build)"; return; fi
  warn "first build downloads CUDA + PyTorch (~5 GB, 15-25 min). Re-runs are cached."
  bash "$SAHAB_DIR/scripts/build_images.sh"
  ok "images built and smoke-tested"
}

# Push the workspace images to the private registry so every other GPU server can
# pull them instead of rebuilding a 5 GB CUDA image of its own.
push_images() {
  step "Publishing the workspace images to the registry"
  if [[ "$SAHAB_SKIP_BUILD" == "1" ]]; then warn "skipping push (--skip-build)"; return 0; fi

  dc up -d registry
  local tries=0
  until curl -fsS --cacert "$SAHAB_DIR/secrets/docker-ca/ca.crt" \
        "https://$(get_env REGISTRY_ADDR)/v2/" >/dev/null 2>&1; do
    tries=$((tries + 1))
    if [[ $tries -gt 30 ]]; then
      warn "the registry did not come up; other machines will not be able to pull images."
      return 0
    fi
    sleep 1
  done

  local pair
  for pair in "sahab-gpu-pytorch:latest $(get_env WORKSPACE_GPU_IMAGE)" \
              "sahab-cpu-base:latest $(get_env WORKSPACE_CPU_IMAGE)"; do
    local local_ref remote_ref
    local_ref="${pair%% *}"; remote_ref="${pair##* }"
    [[ -z "$remote_ref" ]] && continue
    docker tag "$local_ref" "$remote_ref" 2>/dev/null || { warn "no local $local_ref to push"; continue; }
    if docker push "$remote_ref" >/dev/null; then ok "pushed $remote_ref"; else warn "could not push $remote_ref"; fi
  done
}

# ----------------------------------------------------------------------------- compose wrapper
# dc() is defined in scripts/lib/tunnel.sh.

# Bring up only the core data/proxy plane (needed before the tunnel handoff).
up_core() { dc up -d postgres redis traefik; }

# Bring up everything (uses whatever PUBLIC_HOSTNAME is in .env now).
up_all() {
  local profile_args=()
  [[ -n "$CLOUDFLARE_TUNNEL_TOKEN" ]] && profile_args+=(--profile cloudflare)
  dc "${profile_args[@]}" up -d --remove-orphans
}

# ----------------------------------------------------------------------------- 6. expose + handoff
quick_tunnel_handoff() {
  up_core
  publish_quick_tunnel   # shared with scripts/tunnel.sh
}

expose() {
  if [[ "$SAHAB_NO_TUNNEL" == "1" ]]; then
    step "Exposure: LAN-only (--no-tunnel)"
    [[ -z "$(get_env PUBLIC_HOSTNAME)" || "$(get_env PUBLIC_HOSTNAME)" == *example* ]] && set_public_hostname "localhost"
  elif [[ -n "$CLOUDFLARE_TUNNEL_TOKEN" ]]; then
    step "Exposure: named Cloudflare tunnel -> https://$PUBLIC_HOSTNAME"
    set_public_hostname "$PUBLIC_HOSTNAME"
    ok "using token; PUBLIC_HOSTNAME=$PUBLIC_HOSTNAME"
  else
    quick_tunnel_handoff
  fi
  return 0
}

# ----------------------------------------------------------------------------- 7. health
wait_healthy() {
  step "Bringing up the full stack and waiting for health"
  up_all
  if wait_for_health postgres redis traefik backend frontend jupyterhub; then
    ok "core services healthy"
  else
    warn "Not all services reported healthy in time. Inspect with: dc ps  /  dc logs <service>"
  fi
}

# ----------------------------------------------------------------------------- 8. summary
summary() {
  local host; host="$(get_env PUBLIC_HOSTNAME)"
  local admin_email admin_pass
  admin_email="$(get_env BOOTSTRAP_ADMIN_EMAIL)"; admin_pass="$(get_env BOOTSTRAP_ADMIN_PASSWORD)"
  step "Sahab is up 🎉"
  if [[ "$SAHAB_NO_TUNNEL" == "1" ]]; then
    printf "  Local URL : %shttp://<this-vm-ip>%s  (on the university network)\n" "$B" "$N"
  else
    printf "  Public URL: %shttps://%s%s\n" "$B" "$host" "$N"
  fi
  printf "  Admin login: %s  /  %s\n" "${admin_email:-<see .env>}" "${admin_pass:-<see .env>}"
  printf "  Install dir: %s\n" "$SAHAB_DIR"
  echo
  echo "  Manage:  docker compose -f $SAHAB_DIR/infra/docker-compose.yml --env-file $SAHAB_DIR/.env ps"
  echo "  Re-run this script any time to update + re-publish."
}

# ----------------------------------------------------------------------------- main
main() {
  printf "%s\n  Sahab bootstrap — one-command GPU platform deploy\n%s\n" "$B" "$N"
  ensure_clone_tools
  clone_or_update
  # install_prereqs lives in the repo (shared with join_node.sh), so the clone
  # has to come first.
  load_shared_lib
  install_prereqs
  generate_env
  setup_cluster
  run_preflight
  build_images
  push_images
  migrate_database
  expose
  wait_healthy
  summary
}
# Only auto-run when executed directly (allows sourcing for tests).
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
  main "$@"
fi

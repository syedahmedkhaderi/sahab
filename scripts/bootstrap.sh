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
have() { command -v "$1" >/dev/null 2>&1; }

SUDO=""
need_root() {
  if [[ "$(id -u)" -eq 0 ]]; then SUDO=""
  elif have sudo && sudo -n true 2>/dev/null; then SUDO="sudo"
  elif have sudo; then SUDO="sudo"; warn "sudo may prompt for your password."
  else die "Need root or sudo to install system packages. Re-run as root, or pass --skip-prereqs if Docker + NVIDIA toolkit are already installed."
  fi
}

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
install_prereqs() {
  step "Checking host prerequisites"
  if [[ "$SAHAB_SKIP_PREREQS" == "1" ]]; then warn "skipping prereq install (--skip-prereqs)"; return; fi

  if ! have apt-get; then
    warn "Non-apt host: cannot auto-install. Ensure git, openssl, Docker (with compose v2) and the NVIDIA Container Toolkit are present."
    return
  fi

  local missing=()
  have git || missing+=(git)
  have curl || missing+=(curl)
  have openssl || missing+=(openssl)
  if ((${#missing[@]})); then
    need_root
    $SUDO apt-get update -y
    $SUDO apt-get install -y "${missing[@]}" ca-certificates
    ok "installed: ${missing[*]}"
  else ok "git, curl, openssl present"; fi

  if ! have docker; then
    need_root
    step "Installing Docker Engine (get.docker.com)"
    curl -fsSL https://get.docker.com | $SUDO sh
    $SUDO usermod -aG docker "$USER" 2>/dev/null || true
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

# ----------------------------------------------------------------------------- 2. repo
clone_or_update() {
  step "Fetching Sahab into $SAHAB_DIR"
  if [[ -d "$SAHAB_DIR/.git" ]]; then
    git -C "$SAHAB_DIR" fetch --depth 1 origin "$SAHAB_BRANCH"
    git -C "$SAHAB_DIR" checkout "$SAHAB_BRANCH"
    git -C "$SAHAB_DIR" reset --hard "origin/$SAHAB_BRANCH"
    ok "updated existing clone to origin/$SAHAB_BRANCH"
  else
    git clone --branch "$SAHAB_BRANCH" --depth 1 "$SAHAB_REPO" "$SAHAB_DIR"
    ok "cloned $SAHAB_REPO"
  fi
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
  install_prereqs
  clone_or_update
  generate_env
  run_preflight
  build_images
  expose
  wait_healthy
  summary
}
# Only auto-run when executed directly (allows sourcing for tests).
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
  main "$@"
fi

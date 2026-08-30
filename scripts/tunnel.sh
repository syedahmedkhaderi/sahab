#!/usr/bin/env bash
# =============================================================================
# Sahab — publish (or re-publish) the public URL, in one command.
#
#   ./scripts/tunnel.sh
#       Start a fresh zero-config Cloudflare quick tunnel, adopt the URL it is
#       assigned, and restart everything that bakes the hostname in.
#
#   ./scripts/tunnel.sh --named <TOKEN> <HOSTNAME>
#       Use a named Cloudflare tunnel and your own domain. The URL is permanent,
#       so this only needs running again when the token or hostname changes.
#
# Re-publishing used to be four manual steps, and the one that was easiest to
# forget -- updating JUPYTERHUB_PUBLIC_URL alongside PUBLIC_HOSTNAME -- left the
# workspace handoff pointing at a tunnel that no longer existed.
# =============================================================================
set -euo pipefail

SAHAB_DIR="${SAHAB_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
ENV_FILE="$SAHAB_DIR/.env"

# shellcheck source=lib/tunnel.sh
source "$SAHAB_DIR/scripts/lib/tunnel.sh"

MODE="quick"
NAMED_TOKEN=""
NAMED_HOSTNAME=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --named)
      MODE="named"
      NAMED_TOKEN="${2:-}"
      NAMED_HOSTNAME="${3:-}"
      [[ -z "$NAMED_TOKEN" || -z "$NAMED_HOSTNAME" ]] && die "Usage: $0 --named <TOKEN> <HOSTNAME>"
      shift 3
      ;;
    -h|--help)
      sed -n '2,/^# ====/p' "$0" | sed 's/^# \{0,1\}//; s/^#$//' | sed '$d'
      exit 0
      ;;
    *) die "Unknown argument: $1 (see --help)" ;;
  esac
done

[[ -f "$ENV_FILE" ]] || die "No .env at $ENV_FILE. Run scripts/bootstrap.sh first."

printf "%s\n  Sahab — publishing the public URL\n%s\n" "$B" "$N"

# The tunnel fronts Traefik, so the proxy and its data plane have to be up
# before Cloudflare has anything to connect to.
step "Starting the core data and proxy plane"
dc up -d postgres redis traefik
ok "postgres, redis and traefik are up"

if [[ "$MODE" == "named" ]]; then
  step "Configuring the named Cloudflare tunnel"
  set_env CLOUDFLARE_TUNNEL_TOKEN "$NAMED_TOKEN"
  set_public_hostname "$NAMED_HOSTNAME"
  # A named tunnel and a quick tunnel are mutually exclusive; drop the other one.
  dc --profile cloudflare-quick rm -sf cloudflared-quick >/dev/null 2>&1 || true
  dc --profile cloudflare up -d cloudflared
  ok "named tunnel running for $NAMED_HOSTNAME"
else
  publish_quick_tunnel
fi

HOST="$(get_env PUBLIC_HOSTNAME)"

# Recreate rather than restart: these read the hostname from the environment at
# container-create time, and the frontend bakes NEXT_PUBLIC_* into its bundle.
step "Restarting the services that depend on the hostname"
dc up -d --force-recreate "${HOSTNAME_DEPENDENT_SERVICES[@]}"

step "Waiting for health"
if wait_for_health postgres redis traefik backend frontend jupyterhub; then
  ok "core services healthy"
else
  warn "Not all services reported healthy in time. Inspect with: docker compose -f $SAHAB_DIR/infra/docker-compose.yml --env-file $ENV_FILE ps"
fi

# A working URL is the whole point of this script, so check it rather than
# assuming it. Cloudflare sometimes needs a few seconds past container health.
step "Checking the public URL"
CODE=""
for _ in $(seq 1 20); do
  CODE="$(curl -s -o /dev/null -w '%{http_code}' --max-time 10 "https://${HOST}/api/health" || true)"
  [[ "$CODE" == "200" ]] && break
  sleep 3
done
if [[ "$CODE" == "200" ]]; then
  ok "https://${HOST} is serving"
else
  warn "https://${HOST} did not answer /api/health yet (last status: ${CODE:-none}). Give it a moment, then reload."
fi

step "Sahab is published"
printf "  Public URL : %shttps://%s%s\n" "$B" "$HOST" "$N"
printf "  Admin login: %s  /  %s\n" "$(get_env BOOTSTRAP_ADMIN_EMAIL)" "$(get_env BOOTSTRAP_ADMIN_PASSWORD)"
echo
echo "  Re-run this script any time you need a new link."

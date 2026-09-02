#!/usr/bin/env bash
# =============================================================================
# Sahab — shared tunnel + env helpers.
#
# Sourced by both scripts/bootstrap.sh and scripts/tunnel.sh so there is exactly
# one implementation of "publish a public URL and write it into .env". They used
# to be separate, and the copy that only bootstrap knew about set PUBLIC_HOSTNAME
# without JUPYTERHUB_PUBLIC_URL -- which left the OAuth redirect pointing at a
# tunnel that no longer existed.
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

# ----------------------------------------------------------------------------- env file
# Update KEY=VALUE in $ENV_FILE (append if absent). Values must not contain '|' or '&'.
#
# A value containing a newline is refused rather than written. sed treats a
# newline in the replacement as a line break, so one would silently split the
# value across two lines and leave an orphan line that is not a KEY=VALUE pair —
# which every consumer of the file then chokes on, far away from the cause. This
# is not hypothetical: a helper that logged to stdout once had its log line
# captured into a token and written here exactly that way.
ENV_FILE="${ENV_FILE:-}"
set_env() {
  local key="$1" val="$2"
  if [[ "$val" == *$'\n'* ]]; then
    die "Refusing to write a multi-line value into .env for $key: ${val%%$'\n'*}…"
  fi
  if grep -qE "^${key}=" "$ENV_FILE"; then
    sed -i -E "s|^${key}=.*|${key}=${val}|" "$ENV_FILE"
  else
    printf '%s=%s\n' "$key" "$val" >>"$ENV_FILE"
  fi
}
get_env() { grep -E "^$1=" "$ENV_FILE" | head -n1 | cut -d= -f2- || true; }

# ----------------------------------------------------------------------------- compose
dc() { docker compose -f "$SAHAB_DIR/infra/docker-compose.yml" --env-file "$SAHAB_DIR/.env" "$@"; }

# Services that bake the public hostname into their configuration or their built
# assets. Every one of them has to be recreated when the hostname changes.
HOSTNAME_DEPENDENT_SERVICES=(backend worker jupyterhub frontend traefik)

# -----------------------------------------------------------------------------
# Write the public hostname everywhere it is needed.
#
# PUBLIC_HOSTNAME and JUPYTERHUB_PUBLIC_URL must always name the same host: the
# first is what the browser reaches, the second is where the workspace handoff
# sends it. Setting one without the other is silent -- login works, and the
# workspace redirect lands on a dead tunnel.
# -----------------------------------------------------------------------------
set_public_hostname() {
  local host="$1"
  set_env PUBLIC_HOSTNAME "$host"
  set_env JUPYTERHUB_PUBLIC_URL "https://${host}"
}

# -----------------------------------------------------------------------------
# Start a zero-config Cloudflare quick tunnel and adopt the URL it is assigned.
# Requires postgres/redis/traefik to already be running (the tunnel fronts them).
# Echoes nothing; sets PUBLIC_HOSTNAME in the environment and in .env.
# -----------------------------------------------------------------------------
publish_quick_tunnel() {
  step "Starting zero-config Cloudflare quick tunnel"
  # A quick tunnel keeps its URL for the life of the process, so an existing one
  # would just hand back the URL we are trying to replace.
  dc --profile cloudflare-quick rm -sf cloudflared-quick >/dev/null 2>&1 || true
  dc --profile cloudflare-quick up -d cloudflared-quick

  step "Waiting for Cloudflare to assign a public URL"
  local url=""
  for _ in $(seq 1 60); do
    url="$(dc logs cloudflared-quick 2>&1 | grep -oE 'https://[a-z0-9-]+\.trycloudflare\.com' | tail -n1 || true)"
    [[ -n "$url" ]] && break
    sleep 2
  done
  [[ -z "$url" ]] && die "Quick tunnel did not produce a URL in time. Check: docker compose -f $SAHAB_DIR/infra/docker-compose.yml logs cloudflared-quick"

  PUBLIC_HOSTNAME="${url#https://}"
  set_public_hostname "$PUBLIC_HOSTNAME"
  ok "public URL assigned: $url"
  warn "Quick-tunnel URLs rotate whenever the tunnel restarts. Re-run scripts/tunnel.sh to re-publish, or use --named for a permanent URL."
}

# -----------------------------------------------------------------------------
# Wait until the named services report healthy. Returns non-zero on timeout.
# -----------------------------------------------------------------------------
wait_for_health() {
  local services=("$@") svc state all_ok
  for _ in $(seq 1 60); do
    all_ok=1
    for svc in "${services[@]}"; do
      state="$(dc ps --format '{{.Service}} {{.Status}}' 2>/dev/null | grep -E "^${svc} " || true)"
      [[ "$state" == *healthy* || ( "$svc" == traefik && "$state" == *Up* ) ]] || all_ok=0
    done
    [[ "$all_ok" == 1 ]] && return 0
    sleep 5
  done
  return 1
}

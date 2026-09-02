#!/usr/bin/env bash
# =============================================================================
# Sahab — the cluster's own certificate authority.
#
# The manager talks to every other GPU server over that machine's Docker API,
# which must be mutually authenticated: an unprotected Docker API is root on the
# machine to anyone who can reach the port. A public CA cannot help here — the
# machines have private IPs and no public DNS names — so Sahab signs its own.
#
# This script only creates the CA and the registry's certificate, both on the
# manager and both once. Per-node certificates are issued by the backend at
# enrollment time (backend/app/services/node_certs.py), because that is when the
# node's address is known.
#
# Sourced by bootstrap.sh, never executed.
# =============================================================================

# ensure_pki <secrets_dir> <registry_host>
#
# Creates <secrets_dir>/docker-ca/{ca.crt,ca.key} and a registry certificate
# valid for the manager's address. Idempotent: existing files are left alone, so
# re-running bootstrap never invalidates the certificates already handed out to
# machines that have joined.
ensure_pki() {
  local secrets_dir="$1" registry_host="$2"
  local ca_dir="$secrets_dir/docker-ca"

  mkdir -p "$ca_dir" 2>/dev/null || true
  # 0711, not 0700: the backend container writes here as its own uid while the
  # host's scripts (and Docker, pushing to the registry) read ca.crt as another.
  # Execute-only lets a known filename be opened without letting the directory be
  # listed, and every private key inside is 0600 regardless.
  #
  # Tolerated when it fails: after the first run these directories belong to the
  # backend container's uid, because the backend is what issues per-node
  # certificates. Re-tightening a directory we no longer own returns non-zero,
  # and under `set -e` that would abort bootstrap on its second run — precisely
  # the run the "re-run it any time" promise is about. The mode is already what
  # this line would set, so failing to set it again costs nothing.
  chmod 711 "$secrets_dir" "$ca_dir" 2>/dev/null || true

  if [[ -d "$ca_dir" && ! -w "$ca_dir" ]]; then
    # Nothing below this point can write. Say so here, with the remedy, rather
    # than dying two steps later on an openssl error that names no cause.
    if [[ -f "$ca_dir/ca.crt" && -f "$ca_dir/registry.crt" ]]; then
      ok "CA already present, owned by the platform (kept)"
      return 0
    fi
    die "Cannot write to $ca_dir, which belongs to $(stat -c '%U' "$ca_dir" 2>/dev/null || echo 'another user').
     Re-run as root, or hand it back:  sudo chown -R \$(id -u):\$(id -g) '$secrets_dir'"
  fi

  if [[ ! -f "$ca_dir/ca.key" || ! -f "$ca_dir/ca.crt" ]]; then
    step "Creating the cluster certificate authority"
    openssl genrsa -out "$ca_dir/ca.key" 4096 2>/dev/null
    chmod 600 "$ca_dir/ca.key"
    openssl req -new -x509 -sha256 -days 3650 \
      -key "$ca_dir/ca.key" -out "$ca_dir/ca.crt" \
      -subj "/O=Sahab/CN=Sahab Node CA" \
      -addext "basicConstraints=critical,CA:TRUE,pathlen:0" \
      -addext "keyUsage=critical,digitalSignature,keyCertSign,cRLSign" 2>/dev/null
    chmod 644 "$ca_dir/ca.crt"
    ok "CA created at $ca_dir/ca.crt"
  else
    ok "CA already present (kept — reissuing it would lock out every joined machine)"
  fi

  _ensure_registry_cert "$ca_dir" "$registry_host"
}

# The registry serves TLS with a certificate from this CA, so a joining machine
# installs one CA file and gets both a trusted registry and a trusted Docker API.
_ensure_registry_cert() {
  local ca_dir="$1" host="$2"

  if [[ -f "$ca_dir/registry.crt" ]] && \
     openssl x509 -in "$ca_dir/registry.crt" -noout -checkend 2592000 >/dev/null 2>&1 && \
     openssl x509 -in "$ca_dir/registry.crt" -noout -text 2>/dev/null | grep -q "$host"; then
    ok "registry certificate already covers $host"
    return 0
  fi

  step "Issuing the registry certificate for $host"
  local san="DNS:localhost,IP:127.0.0.1"
  if [[ "$host" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
    san="$san,IP:$host"
  elif [[ -n "$host" ]]; then
    san="$san,DNS:$host"
  fi

  openssl genrsa -out "$ca_dir/registry.key" 2048 2>/dev/null
  chmod 600 "$ca_dir/registry.key"
  openssl req -new -key "$ca_dir/registry.key" -out "$ca_dir/registry.csr" \
    -subj "/O=Sahab/CN=${host:-localhost}" 2>/dev/null
  openssl x509 -req -in "$ca_dir/registry.csr" \
    -CA "$ca_dir/ca.crt" -CAkey "$ca_dir/ca.key" -CAcreateserial \
    -out "$ca_dir/registry.crt" -days 825 -sha256 \
    -extfile <(printf 'subjectAltName=%s\nextendedKeyUsage=serverAuth\n' "$san") 2>/dev/null
  rm -f "$ca_dir/registry.csr"
  chmod 644 "$ca_dir/registry.crt"
  # registry:2 runs as root in the container, so 0600 is readable there and stays
  # unreadable to anyone else on the host.
  chmod 600 "$ca_dir/registry.key"
  ok "registry certificate issued for $host"
}

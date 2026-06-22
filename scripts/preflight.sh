#!/usr/bin/env bash
# Sahab — Phase 0 preflight (blueprint §18, §21)
# Verifies host prerequisites on the GPU server before installing the platform.
# Safe to run repeatedly. Exits non-zero if a hard requirement is missing.
set -euo pipefail

# --- Minimum NVIDIA driver for the container CUDA version we ship -------------
# Image base is CUDA 12.4 userspace. The host kernel driver must satisfy the
# minimum for CUDA 12.4 (driver >= 550.x on Linux). The CUDA *userspace* ships
# inside the container; only the kernel driver lives on the host.
MIN_DRIVER_MAJOR=550

GREEN=$'\033[0;32m'; RED=$'\033[0;31m'; YELLOW=$'\033[0;33m'; NC=$'\033[0m'
ok()   { printf "%s[ OK ]%s %s\n"   "$GREEN" "$NC" "$1"; }
warn() { printf "%s[WARN]%s %s\n"   "$YELLOW" "$NC" "$1"; }
fail() { printf "%s[FAIL]%s %s\n"   "$RED" "$NC" "$1"; FAILED=1; }

FAILED=0
echo "=== Sahab preflight ==="
echo

# 1. OS ------------------------------------------------------------------------
if [[ -r /etc/os-release ]]; then
  . /etc/os-release
  echo "OS: ${PRETTY_NAME:-unknown}"
  case "${ID:-}" in
    ubuntu) ok "Ubuntu detected (${VERSION_ID:-?})" ;;
    *)      warn "Non-Ubuntu host (${ID:-?}); blueprint targets Ubuntu LTS. Proceed with care." ;;
  esac
else
  warn "Cannot read /etc/os-release"
fi
echo

# 2. Privileges ----------------------------------------------------------------
if [[ "$(id -u)" -eq 0 ]]; then
  ok "Running as root"
elif sudo -n true 2>/dev/null; then
  ok "Passwordless sudo available"
elif id -nG "$USER" | tr ' ' '\n' | grep -qx docker; then
  ok "User '$USER' is in the 'docker' group (Docker usable without sudo)"
else
  warn "No root/sudo and not in 'docker' group. Installing driver/toolkit/Docker needs root; otherwise IT must pre-install them and add you to 'docker'."
fi
echo

# 3. NVIDIA driver + GPUs ------------------------------------------------------
if command -v nvidia-smi >/dev/null 2>&1; then
  DRIVER_VER="$(nvidia-smi --query-gpu=driver_version --format=csv,noheader 2>/dev/null | head -n1 || true)"
  DRIVER_MAJOR="${DRIVER_VER%%.*}"
  echo "NVIDIA driver: ${DRIVER_VER:-unknown}"
  if [[ -n "${DRIVER_MAJOR:-}" && "$DRIVER_MAJOR" =~ ^[0-9]+$ ]]; then
    if (( DRIVER_MAJOR >= MIN_DRIVER_MAJOR )); then
      ok "Driver >= ${MIN_DRIVER_MAJOR} (satisfies CUDA 12.4 container requirement)"
    else
      fail "Driver ${DRIVER_VER} < ${MIN_DRIVER_MAJOR}.x required for CUDA 12.4 containers. Update the host driver."
    fi
  fi
  echo "Detected GPUs:"
  nvidia-smi --query-gpu=index,name,memory.total,uuid --format=csv,noheader | sed 's/^/  /'
  GPU_COUNT="$(nvidia-smi -L | wc -l | tr -d ' ')"
  if (( GPU_COUNT >= 1 )); then ok "${GPU_COUNT} GPU(s) visible to the driver"; else fail "No GPUs visible"; fi
  if nvidia-smi -L | grep -qi 'L4'; then
    ok "NVIDIA L4 present (whole-GPU allocation model; L4 has no MIG)"
  else
    warn "No L4 found by name; smoke test asserts 'L4' — adjust if this host differs."
  fi
else
  fail "nvidia-smi not found. Install the NVIDIA driver first."
fi
echo

# 4. Docker --------------------------------------------------------------------
if command -v docker >/dev/null 2>&1; then
  ok "Docker present: $(docker --version)"
  if docker compose version >/dev/null 2>&1; then
    ok "Docker Compose v2 present: $(docker compose version --short 2>/dev/null || echo present)"
  else
    fail "Docker Compose v2 plugin missing (need 'docker compose')."
  fi
  if docker info >/dev/null 2>&1; then
    ok "Docker daemon reachable"
  else
    fail "Cannot talk to the Docker daemon (permissions or daemon down)."
  fi
else
  fail "Docker not installed."
fi
echo

# 5. NVIDIA Container Toolkit (the real GPU-in-container gate) ------------------
if command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1; then
  if docker info 2>/dev/null | grep -qi 'nvidia'; then
    ok "NVIDIA runtime registered with Docker"
  else
    warn "NVIDIA runtime not listed in 'docker info'; the test below is authoritative."
  fi
  echo "Testing GPU passthrough into a container (docker run --gpus all ... nvidia-smi)..."
  if docker run --rm --gpus all nvidia/cuda:12.4.1-base-ubuntu22.04 nvidia-smi -L >/tmp/sahab_gpu_test 2>/tmp/sahab_gpu_err; then
    ok "Containers can use the GPU. Devices seen inside container:"
    sed 's/^/  /' /tmp/sahab_gpu_test
  else
    fail "Container GPU test failed. Install/configure the NVIDIA Container Toolkit:"
    echo "  https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/install-guide.html"
    sed 's/^/  /' /tmp/sahab_gpu_err 2>/dev/null || true
  fi
  rm -f /tmp/sahab_gpu_test /tmp/sahab_gpu_err
else
  warn "Skipping GPU-in-container test (Docker not usable)."
fi
echo

# 6. Outbound connectivity (Strategy A / package installs) ---------------------
if curl -fsS -m 8 https://api.cloudflare.com/client/v4/ips >/dev/null 2>&1; then
  ok "Outbound HTTPS to Cloudflare works (Strategy A tunnel viable)"
else
  warn "No outbound HTTPS to Cloudflare. Use Strategy B (university-network-only) until egress is allowed."
fi
echo

# 7. Disk ----------------------------------------------------------------------
AVAIL_GB="$(df -P / | awk 'NR==2 {printf "%d", $4/1024/1024}')"
echo "Free space on /: ${AVAIL_GB} GB"
if (( AVAIL_GB >= 60 )); then
  ok "Sufficient disk for images + initial user volumes (>= 60 GB free)"
else
  warn "Low disk (< 60 GB free). Images (~5 GB each) + per-user volumes need room; consider a data partition for ${USER_VOLUMES_PATH:-/data/users}."
fi
echo

echo "=== Summary ==="
if [[ "$FAILED" -eq 0 ]]; then
  ok "Preflight passed. You can proceed to build images: bash scripts/build_images.sh"
  exit 0
else
  fail "Preflight found blocking issues. Resolve the [FAIL] items above before continuing."
  exit 1
fi

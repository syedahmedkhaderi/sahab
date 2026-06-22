#!/usr/bin/env bash
# Sahab — build and smoke-test workspace images (blueprint §15, §22)
# An image cannot be marked "enabled" in the catalog until its smoke test passes.
# This script enforces that gate locally.
#
# Usage:
#   scripts/build_images.sh                # build + smoke-test all images
#   scripts/build_images.sh gpu-pytorch    # build + smoke-test one image
#   SKIP_SMOKE=1 scripts/build_images.sh   # build only (CI without a GPU)
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
IMAGES_DIR="$REPO_ROOT/images"

GREEN=$'\033[0;32m'; RED=$'\033[0;31m'; YELLOW=$'\033[0;33m'; NC=$'\033[0m'
ok()   { printf "%s[ OK ]%s %s\n" "$GREEN" "$NC" "$1"; }
warn() { printf "%s[WARN]%s %s\n" "$YELLOW" "$NC" "$1"; }
fail() { printf "%s[FAIL]%s %s\n" "$RED" "$NC" "$1"; }

# image dir name -> "<docker tag>:<gpu|cpu>"
declare -A IMAGE_TAG=(
  [gpu-pytorch]="sahab-gpu-pytorch:latest"
  [cpu-base]="sahab-cpu-base:latest"
)
declare -A IMAGE_KIND=(
  [gpu-pytorch]="gpu"
  [cpu-base]="cpu"
)

build_one() {
  local name="$1"
  local dir="$IMAGES_DIR/$name"
  local tag="${IMAGE_TAG[$name]:-}"
  local kind="${IMAGE_KIND[$name]:-cpu}"

  [[ -z "$tag" ]] && { fail "Unknown image '$name'"; return 1; }
  [[ -d "$dir" ]] || { fail "Image dir not found: $dir"; return 1; }

  echo "=== Building $name -> $tag ($kind) ==="
  docker build -t "$tag" "$dir"
  ok "Built $tag"

  if [[ "${SKIP_SMOKE:-0}" == "1" ]]; then
    warn "SKIP_SMOKE=1 set; skipping smoke test for $tag (NOT eligible to enable in catalog)."
    return 0
  fi

  echo "--- Smoke test: $tag ---"
  if [[ "$kind" == "gpu" ]]; then
    if ! command -v nvidia-smi >/dev/null 2>&1; then
      warn "No GPU on this host; cannot run the GPU smoke test. Run on the GPU server before enabling."
      return 0
    fi
    docker run --rm --gpus device=0 "$tag" python /tmp/smoke_test.py
  else
    docker run --rm "$tag" python /tmp/smoke_test.py
  fi
  ok "Smoke test passed for $tag — image may be enabled in the catalog."
}

main() {
  command -v docker >/dev/null 2>&1 || { fail "Docker not installed"; exit 1; }
  local targets=()
  if [[ $# -gt 0 ]]; then
    targets=("$@")
  else
    targets=(gpu-pytorch cpu-base)
  fi
  local rc=0
  for t in "${targets[@]}"; do
    build_one "$t" || rc=1
    echo
  done
  if [[ $rc -eq 0 ]]; then
    ok "All requested images built (and smoke-tested unless skipped)."
  else
    fail "One or more images failed. See output above."
  fi
  exit $rc
}

main "$@"

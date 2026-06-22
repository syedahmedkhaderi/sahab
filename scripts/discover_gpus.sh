#!/usr/bin/env bash
# Sahab — GPU discovery (blueprint §7, §25)
# Emits the GPU inventory for this host. Default output is CSV matching
# gpu_inventory columns; pass --json for the control-plane seeder, or --sql
# to print INSERT statements.
#
# Usage:
#   scripts/discover_gpus.sh            # CSV: uuid,name,memory_total
#   scripts/discover_gpus.sh --json     # JSON array [{gpu_uuid,model,vram_mb}]
#   scripts/discover_gpus.sh --sql      # idempotent INSERTs into gpu_inventory
set -euo pipefail

if ! command -v nvidia-smi >/dev/null 2>&1; then
  echo "nvidia-smi not found; cannot discover GPUs" >&2
  exit 1
fi

MODE="${1:-csv}"

# uuid, name, memory.total (in MiB) — stable UUIDs are the lease key.
RAW="$(nvidia-smi --query-gpu=uuid,name,memory.total --format=csv,noheader,nounits)"

case "$MODE" in
  csv|--csv)
    echo "gpu_uuid,model,vram_mb"
    echo "$RAW" | awk -F', *' '{printf "%s,%s,%s\n", $1, $2, $3}'
    ;;
  --json)
    printf '['
    first=1
    while IFS=',' read -r uuid name mem; do
      uuid="$(echo "$uuid" | xargs)"; name="$(echo "$name" | xargs)"; mem="$(echo "$mem" | xargs)"
      [[ -z "$uuid" ]] && continue
      [[ $first -eq 0 ]] && printf ','
      printf '{"gpu_uuid":"%s","model":"%s","vram_mb":%s}' "$uuid" "$name" "$mem"
      first=0
    done <<< "$RAW"
    printf ']\n'
    ;;
  --sql)
    while IFS=',' read -r uuid name mem; do
      uuid="$(echo "$uuid" | xargs)"; name="$(echo "$name" | xargs)"; mem="$(echo "$mem" | xargs)"
      [[ -z "$uuid" ]] && continue
      printf "INSERT INTO gpu_inventory (id, gpu_uuid, model, vram_mb, status) VALUES (gen_random_uuid(), '%s', '%s', %s, 'free') ON CONFLICT (gpu_uuid) DO UPDATE SET model=EXCLUDED.model, vram_mb=EXCLUDED.vram_mb;\n" "$uuid" "$name" "$mem"
    done <<< "$RAW"
    ;;
  *)
    echo "Unknown mode: $MODE (use csv|--json|--sql)" >&2
    exit 2
    ;;
esac

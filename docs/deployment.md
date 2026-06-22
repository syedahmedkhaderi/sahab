# Sahab — Deployment

Single-host MVP via Docker Compose on the GPU server (blueprint §18). Kubernetes is a Phase-6 concern, not an MVP requirement.

## Prerequisites (host)

1. Ubuntu LTS.
2. NVIDIA driver new enough for CUDA 12.4 containers (≥ 550.x). Verify with `nvidia-smi`.
3. Docker Engine + Docker Compose v2.
4. NVIDIA Container Toolkit configured (`docker run --gpus all nvidia/cuda:12.4.1-base-ubuntu22.04 nvidia-smi` lists the L4s).
5. Disk for images (~5 GB each) + per-user volumes; ideally a data partition for `USER_VOLUMES_PATH` and the shared datasets volume.

Installing the driver, toolkit, and Docker, and running `--gpus`, requires **root/sudo**. If only an unprivileged account exists, IT must pre-install Docker + the NVIDIA Container Toolkit and add the account to the `docker` group.

Run the gate first:

```bash
bash scripts/preflight.sh
```

## Step-by-step

```bash
# 0. Configure
cp .env.example .env
# Edit .env: set strong POSTGRES_PASSWORD, JWT_SECRET (openssl rand -hex 32),
# OAUTH_CLIENT_SECRET, JUPYTERHUB_API_TOKEN, BOOTSTRAP_ADMIN_*, PUBLIC_HOSTNAME,
# and CLOUDFLARE_TUNNEL_TOKEN (Strategy A only).

# 1. Preflight (Phase 0)
bash scripts/preflight.sh

# 2. Build + smoke-test the workspace images (Phase 1). Long: downloads CUDA + PyTorch.
bash scripts/build_images.sh
# The GPU smoke test must print OK and show the L4 before the image is usable.

# 3. Bring up the platform stack (Phases 2-4)
docker compose -f infra/docker-compose.yml up -d --build

# 4. Initialize the database (first run)
docker compose -f infra/docker-compose.yml exec backend alembic upgrade head

# 5. Seed GPU inventory from the real hardware
scripts/discover_gpus.sh --sql | docker compose -f infra/docker-compose.yml exec -T postgres psql -U "$POSTGRES_USER" -d "$POSTGRES_DB"
```

## Exposure strategies (blueprint §6)

- **Strategy A (target): Cloudflare Tunnel.** Set `CLOUDFLARE_TUNNEL_TOKEN`; the `cloudflared` service makes an outbound-only connection mapping `PUBLIC_HOSTNAME` to Traefik. No inbound ports, no public IP. Optionally gate with Cloudflare Access. Users no longer need the VPN.
- **Strategy B (day-one fallback): university network only.** Skip cloudflared; reach the platform via the existing VPN at `http://<server-ip>`. Migrate to A later by adding the token — nothing else changes.

## Internal routing

One public hostname → Traefik, routed by path on a single domain so auth cookies are shared:

- `/` → Next.js frontend
- `/api/*` → FastAPI
- `/hub/*` and `/user/*` → JupyterHub (and the spawned user servers)

## Persistence & backup

- `pgdata` volume — Postgres (users, credits, sessions). **Back this up.**
- `sahab-user-<username>` volumes — per-user notebooks/files.
- `sahab-hub-db` — JupyterHub state.

Restarting the stack must not lose user data or balances (acceptance criterion). Verify with `docker compose down && docker compose up -d` and confirm balances/files survive.

## Updating workspace images

Rebuild, smoke-test, then add/enable a new catalog entry via the admin console or `POST /api/admin/images`. Never enable an image whose smoke test did not pass.

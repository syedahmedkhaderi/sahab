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
docker compose --env-file .env -f infra/docker-compose.yml up -d --build
# Add --profile cloudflare once CLOUDFLARE_TUNNEL_TOKEN is set.

# 4. Initialize the database (first run, and after every update)
docker compose --env-file .env -f infra/docker-compose.yml run --rm --no-deps -T backend alembic upgrade head
```

Nothing seeds `gpu_inventory` by hand any more. The control-plane machine is
registered as the first node at startup, and its GPUs — like every other
machine's — are registered when the machine enrols. `scripts/discover_gpus.sh`
still exists, and the join script uses it, but you should not need to pipe SQL
into Postgres to add a GPU.

## Adding another GPU server

Two ways, both running the same script so they cannot drift apart.

**From the machine.** Admin console → VMs → Add VM → *Give me a command*. Paste
the one-liner it shows on the new server. It installs Docker and the NVIDIA
toolkit, joins the cluster, opens a mutually authenticated Docker API for the
control plane, pulls the workspace images and registers its GPUs. About ten
minutes.

**From the console.** Admin console → VMs → Add VM → *Install over SSH*. Give the
IP, an account with sudo, and a password or private key; Sahab runs the same
command itself and streams the output. The credential is stored encrypted (with
`SECRETS_KEY`) so upgrades can be re-run later.

What has to be reachable between the machines:

| Port | Direction | Why |
|---|---|---|
| 2377/tcp, 7946/tcp+udp, 4789/udp | node → manager | swarm membership and the encrypted overlay network |
| 2376/tcp | manager → node | the spawner starts and stops containers there (mutual TLS) |
| 9400, 9100, 8080 | manager → node | DCGM, host and container metrics |
| 5000/tcp | node → manager | pulling workspace images from the private registry |
| 443/tcp | node → manager | the enrollment API |

A machine on a **different network** cannot reach a manager published only
through a Cloudflare quick tunnel. For that case the join script takes
`--vpn tailscale --vpn-key <key>`, which puts both machines on one network first;
the console exposes it as the optional Tailscale field.

### Trust, briefly

The manager runs a small certificate authority (`secrets/docker-ca/`, created by
`bootstrap.sh`). It signs each machine's Docker API certificate and the
registry's, because a public CA cannot issue for private IPs. The join token is
single-use, expires in 24 hours, and is stored only as a SHA-256 hash. A
machine's GPUs enter the pool only after the control plane has proved it can
open a mutually authenticated connection to that machine — so a node that reads
"Ready" is one that can actually start a workspace.

The `secrets/` directory is owned by the backend container's uid (1001) and is
mode 0711: private keys inside stay 0600, while `ca.crt` — a public certificate —
can still be read by the host's own scripts.

## Exposure strategies (blueprint §6)

- **Strategy A (target): Cloudflare Tunnel.** Set `CLOUDFLARE_TUNNEL_TOKEN` and start Compose with `--profile cloudflare`; the `cloudflared` service makes an outbound-only connection mapping `PUBLIC_HOSTNAME` to Traefik. No inbound ports, no public IP. Optionally gate with Cloudflare Access. Users no longer need the VPN.
- **Strategy B (day-one fallback): university network only.** Leave the token blank and omit the Cloudflare profile; reach the platform via the existing VPN at `http://<server-ip>`. Migrate to A later by adding the token and the profile.

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

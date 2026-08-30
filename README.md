# Sahab — University GPU Compute Platform

> "Sahab" (سحاب, "cloud") — a self-hosted, browser-based GPU compute platform. A private Google Colab for a university: users log in through a website, click **Launch Workspace**, and get a full in-browser IDE (JupyterLab + VS Code) running on the institution's GPUs, metered by a credit system.

This repository is the MVP implementation of the [build blueprint](./Sahab_GPU_Platform_MVP_Blueprint.md). Read the blueprint top to bottom for the full rationale; this README is the operational map.

## Architecture (three planes)

1. **Product plane** — Next.js web app (landing, auth, dashboard, billing, admin) + FastAPI control-plane API.
2. **Workspace plane** — JupyterHub spawning one Docker container per session (JupyterLab + code-server). GPU containers get exactly one L4 pinned.
3. **Platform services** — PostgreSQL, Redis, metering/scheduler worker, Traefik, cloudflared, and the monitoring stack (Prometheus, Grafana, DCGM/node-exporter/cAdvisor).

```
        Browser ── Cloudflare edge ── cloudflared ── Traefik
                                                       │
            ┌──────────────────┬─────────────────────┬┘
         Next.js            FastAPI               JupyterHub
        (product UI)   (auth, credits,        (DockerSpawner +
                        sessions, OAuth)        NVIDIA runtime)
                            │   │                     │
                       Postgres Redis        per-user GPU/CPU container
                            │                  (JupyterLab + code-server)
                     metering/scheduler worker        │
                                                 1× NVIDIA L4 pinned
        Monitoring: Prometheus + Grafana + DCGM/node-exporter/cAdvisor
```

## Repository layout

```
sahab/
  backend/      FastAPI app, SQLAlchemy models, Alembic migrations, OAuth provider, metering/scheduler worker
  frontend/     Next.js (App Router, TS, Tailwind) product shell
  jupyterhub/   JupyterHub image + config (DockerSpawner, NVIDIA runtime, OAuth)
  images/       Workspace images: gpu-pytorch (CUDA+PyTorch), cpu-base
  infra/        docker-compose.yml + Traefik, cloudflared, Prometheus, Grafana config
  scripts/      preflight.sh, discover_gpus.sh, build_images.sh
  docs/         architecture, deployment, runbook
  .env.example  configuration template
```

## Build phases (blueprint §21)

- **Phase 0** — Preflight: confirm root, driver, Docker, NVIDIA Container Toolkit (`scripts/preflight.sh`).
- **Phase 1** — Workspace core: JupyterHub + GPU image. (Bootstrapped by `sahab_phase1_setup.sh`; productionized under `jupyterhub/` + `images/`.)
- **Phase 2** — Control plane: Postgres + Redis + FastAPI + worker, sessions/credits/queue, SSO.
- **Phase 3** — Product UI: Next.js full happy path.
- **Phase 4** — Exposure + monitoring: cloudflared, Prometheus/Grafana, hardening.
- **Phase 5** — Payments (deferred until a legal merchant exists). Admin-granted credits until then.
- **Phase 6** — Polish + k3s scale path.

## One-command deploy (any GPU server)

Turn a fresh university GPU VM into a fully working, publicly-reachable Sahab in a
single command. No domain, no Cloudflare account, no manual `.env` editing:

```bash
curl -fsSL https://raw.githubusercontent.com/syedahmedkhaderi/sahab/main/scripts/bootstrap.sh | bash
```

`scripts/bootstrap.sh` installs Docker + the NVIDIA Container Toolkit (if missing),
clones this repo to `~/sahab`, generates all secrets into `.env`, runs the Phase 0
preflight, builds + smoke-tests the workspace images, then exposes the platform via a
**zero-config Cloudflare quick tunnel** and prints the public `https://…trycloudflare.com`
URL plus the seeded admin login. It is **idempotent** — re-run it any time to update the
repo and re-publish.

Quick-tunnel URLs rotate on restart. For a **permanent** URL, register a domain on
Cloudflare, create a named tunnel (Public Hostname → `HTTPS` → `traefik:443`, *No TLS
Verify* ON), then pass its token + hostname:

```bash
curl -fsSL https://raw.githubusercontent.com/syedahmedkhaderi/sahab/main/scripts/bootstrap.sh \
  | bash -s -- --token eyJ... --hostname sahab.yourdomain.com
```

Useful flags: `--no-tunnel` (LAN-only), `--skip-build` (reuse images), `--dir <path>`,
`--admin-email <email>`, `--signup-domains <csv>`. Run with `--help` for the full list.

### Getting a new public link

Quick-tunnel URLs rotate whenever the tunnel restarts. To publish a fresh one
without re-running the whole bootstrap:

```bash
cd ~/sahab && ./scripts/tunnel.sh
```

It starts a new tunnel, writes the hostname into **both** `PUBLIC_HOSTNAME` and
`JUPYTERHUB_PUBLIC_URL` (they must always match — setting only the first is silent,
and leaves the workspace handoff pointing at a tunnel that no longer exists),
restarts the services that bake the hostname in, checks the URL actually answers,
and prints it with the admin login.

For the permanent-domain path, `./scripts/tunnel.sh --named <TOKEN> <HOSTNAME>`
does the same thing with a named tunnel. Both share one implementation with
`bootstrap.sh` (`scripts/lib/tunnel.sh`), so the two paths cannot drift.

## Quick start (development)

```bash
cp .env.example .env          # then edit secrets
# Phase 0 — on the GPU server, verify host prerequisites:
bash scripts/preflight.sh
# Build the workspace images (long; downloads CUDA + PyTorch):
bash scripts/build_images.sh
# Bring up the full platform:
docker compose --env-file .env -f infra/docker-compose.yml up -d
# Add --profile cloudflare once CLOUDFLARE_TUNNEL_TOKEN is set.
```

Open `https://$PUBLIC_HOSTNAME` (Strategy A) or `http://<server-ip>` on the VPN (Strategy B).

### Backend only (local dev)

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -e '.[dev]'
alembic upgrade head
uvicorn app.main:app --reload      # API at http://localhost:8000
python -m app.worker               # metering/scheduler worker
pytest
```

### Frontend only (local dev)

```bash
cd frontend
npm install
npm run dev                        # http://localhost:3000
```

## Single-server Phase 1 quick path

The original `sahab_phase1_setup.sh` writes a minimal JupyterHub-only stack to `~/sahab` on the GPU server. The productionized equivalent lives in `jupyterhub/` and `images/gpu-pytorch/` here and is wired into `infra/docker-compose.yml`.

## Security & operations

See [docs/](./docs/): `architecture.md`, `deployment.md`, `runbook.md`. Key invariants: whole-GPU allocation (one L4 per session, no MIG on L4), append-only credit ledger as source of truth, unprivileged user containers with no Docker socket, admin actions audited.

## License

Internal MVP — license TBD.

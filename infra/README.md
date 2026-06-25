# Sahab — infra

Everything needed to run the full platform stack on a single GPU server via Docker Compose.

## Directory layout

```
infra/
  docker-compose.yml          Full stack definition (§18)
  traefik/
    traefik.yml               Traefik v3 static config (entrypoints, ACME, providers)
    dynamic/
      middlewares.yml          Shared middlewares (strip-api-prefix, secure headers)
  prometheus/
    prometheus.yml            Scrape config for DCGM, node-exporter, cAdvisor, backend, Traefik
  grafana/
    provisioning/
      datasources/
        prometheus.yml        Auto-provisions the Prometheus datasource
      dashboards/
        dashboards.yml        Points Grafana at the JSON dashboard files
        sahab-gpu-sessions.json  GPU/session/host dashboard (§17)
  cloudflared/
    README.md                 Token-based tunnel setup guide
    config.example.yml        File-based tunnel config alternative
```

## How the stack fits together

```
Internet
   |
Cloudflare Edge (TLS termination, optional Access SSO)
   | (outbound tunnel via cloudflared)
Traefik :443
   |-- / --> frontend:3000         (Next.js product UI)
   |-- /api/* --> backend:8000     (FastAPI — strip /api prefix middleware)
   |-- /hub/* --> jupyterhub:8000  (JupyterHub hub routes)
   |-- /user/* --> jupyterhub:8000 (JupyterHub user server routes)
   |-- /grafana/* --> grafana:3000 (monitoring dashboards)
   |
   +-- Traefik metrics on :8080/metrics (scraped by Prometheus)

JupyterHub spawns sibling containers on sahab-network via docker.sock.
Each user container joins sahab-network but cannot reach postgres/redis (no direct
labels expose those services; Traefik has them disabled).

Prometheus scrapes:
  dcgm-exporter:9400   GPU metrics (NVIDIA L4 utilization, VRAM, temp, power)
  node-exporter:9100   Host OS metrics
  cadvisor:8080        Per-container metrics
  backend:8000/api/metrics  Application metrics (sessions, credits, queue)
  traefik:8080/metrics Request rates and latency
  jupyterhub:8000/hub/metrics  Active user servers
```

## Exposure strategies

### Strategy A — Cloudflare Tunnel (recommended)

Set `CLOUDFLARE_TUNNEL_TOKEN` in `.env`. The `cloudflared` service makes an outbound
connection to Cloudflare; no inbound ports need to be opened on the GPU server.
Users reach the platform at `https://$PUBLIC_HOSTNAME` without a VPN.

See `cloudflared/README.md` for full setup instructions.

### Strategy B — University network only (day-one fallback)

Leave `CLOUDFLARE_TUNNEL_TOKEN` blank. Traefik listens on ports 80/443 on the host.
Users must be on the university network (VPN) to reach the platform, but once
connected they use a browser instead of SSH — still a significant UX improvement.
Migrate to Strategy A later by adding the token; nothing else changes.

## Ports (host)

| Port | Service | Notes |
|------|---------|-------|
| 80   | Traefik | Redirects to 443 |
| 443  | Traefik | All public HTTPS traffic |
| 8080 | Traefik internal | Metrics + dashboard (not exposed to internet) |

All other services communicate on the internal `sahab-network` bridge only.

## Starting the stack

```bash
# From the repo root
cp .env.example .env
# Fill in .env (secrets, domain, etc.)

docker compose --env-file .env -f infra/docker-compose.yml up -d
# Add --profile cloudflare once CLOUDFLARE_TUNNEL_TOKEN is set.
```

## Stopping / restarting

```bash
docker compose --env-file .env -f infra/docker-compose.yml down          # stop, keep volumes
docker compose --env-file .env -f infra/docker-compose.yml down -v       # stop AND delete volumes (destructive)
```

## Validating the compose file

```bash
docker compose --env-file .env -f infra/docker-compose.yml config -q
```

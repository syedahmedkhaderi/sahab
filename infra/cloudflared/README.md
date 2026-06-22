# Cloudflare Tunnel (cloudflared)

The `cloudflared` service in `docker-compose.yml` makes an **outbound-only** encrypted
connection from the GPU server to Cloudflare and maps a public hostname
(e.g. `sahab.example.com`) to the local Traefik entrypoint. No inbound ports are
opened and no public IP is required on the server (Strategy A — §6 of the spec).

## Quick setup

1. Log into the Cloudflare Zero Trust dashboard: <https://one.dash.cloudflare.com/>
2. Go to **Networks > Tunnels > Create a tunnel**.
3. Name it (e.g. `sahab-mvp`), select **Docker** as the environment, and copy the
   `--token` value shown.
4. Add the token to your `.env` file:
   ```
   CLOUDFLARE_TUNNEL_TOKEN=eyJhIjoiXXXX...
   ```
5. In the tunnel's **Public Hostname** settings add:

   | Subdomain / hostname     | Service                          |
   |--------------------------|----------------------------------|
   | `sahab.example.com`      | `http://traefik:80`              |

   Traefik then handles all path-based routing (`/`, `/api/*`, `/hub/*`, `/user/*`).

6. Start (or restart) the stack:
   ```bash
   docker compose -f infra/docker-compose.yml up -d cloudflared
   ```

The tunnel will appear as **Healthy** in the dashboard within ~30 seconds.

## Strategy B fallback

If the tunnel is not yet configured, leave `CLOUDFLARE_TUNNEL_TOKEN` blank.
The `cloudflared` service will exit immediately (it has no token) and the rest of
the stack will run normally. Access the platform directly via Traefik on port 80/443
while on the university network (VPN still required for end users — §6 Strategy B).

## Optional: Cloudflare Access

Layer Cloudflare Access in front of the public hostname for an extra authentication
gate (Google Workspace / Microsoft Entra / one-time-PIN) before traffic even reaches
the platform. Configure it in the Zero Trust dashboard under
**Access > Applications > Add an application > Self-hosted**.

## config.example.yml

See `config.example.yml` for the equivalent file-based tunnel configuration
(used instead of the `--token` flag when managing tunnels with named credential files).

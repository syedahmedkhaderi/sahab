# Sahab — Architecture

This document is the condensed engineering view. The full rationale lives in the [blueprint](../Sahab_GPU_Platform_MVP_Blueprint.md).

## Three planes

1. **Product plane** — Next.js web app + FastAPI control-plane API. Everything the user sees and the source of truth for identity, credits, and session decisions.
2. **Workspace plane** — JupyterHub + DockerSpawner spawns one container per active session (JupyterLab + code-server). GPU containers pin exactly one L4.
3. **Platform services** — PostgreSQL (system of record), Redis (locks/queue/rate limiting), the metering/scheduler worker, Traefik (reverse proxy), cloudflared (exposure), and monitoring (Prometheus, Grafana, DCGM/node-exporter/cAdvisor).

```
        Browser ── Cloudflare edge ── cloudflared ── Traefik (one domain, path routing)
                                                       │
            / ─► Next.js     /api/* ─► FastAPI     /hub/*, /user/* ─► JupyterHub
                                 │  │                     │
                            Postgres Redis          DockerSpawner + NVIDIA runtime
                                 │                        │
                        metering/scheduler worker   per-user GPU/CPU container
                                                    (JupyterLab + code-server, 1× L4)
```

## Why this split

- **JupyterHub** already solves multi-user spawning, per-user single-server lifecycle, an admin REST API, idle culling, and per-user volumes. We don't re-implement that.
- **FastAPI** owns the product experience JupyterHub lacks: identity, credits, billing, queue, and the policy decision of *whether a session may start*. FastAPI is the source of truth; JupyterHub is the engine it drives over REST.

## GPU allocation (load-bearing constraint)

The NVIDIA **L4 does not support MIG** — a single L4 cannot be safely partitioned between tenants. Therefore: **whole-GPU allocation**. At any moment one L4 belongs to exactly one session. Two L4s ⇒ at most two concurrent GPU sessions, plus unlimited lightweight CPU sessions, plus a FIFO queue for GPU demand beyond two.

Leasing is atomic (Redis lock + Postgres row update) so two racing `POST /sessions` can never double-allocate one `gpu_uuid`. The leased GPU is pinned into the container via `NVIDIA_VISIBLE_DEVICES=<uuid>`.

## Credits

A **compute credit** is the internal currency (default: 1 credit = 1 L4 GPU-minute). The `credit_ledger` is **append-only and the source of truth**; `users.credit_balance` is a cache recomputed from the ledger. The metering worker debits per minute for active sessions and triggers a graceful stop at zero balance. DCGM GPU-busy time is the audit cross-check.

## Identity / SSO

FastAPI is the identity source (Postgres). For the website ↔ workspace handoff it acts as an OAuth2/OIDC provider; JupyterHub uses `GenericOAuthenticator` against it, so the user logs in once. A one-time-token authenticator is the simpler fallback. Signup is restricted to the institution's email domain(s); accounts may require admin approval.

## Session state machine

```
requested ─►(queued ─►) starting ─► running ─► stopping ─► stopped
                                   └──────────────────────► failed
```
Metering starts at `running`. `failed` must always release any GPU lease.

## Data model

See blueprint §12 and `backend/app/models.py`: `users, gpu_inventory, images, rates, sessions, gpu_leases, credit_ledger, transactions, audit_log`.

## Key invariants (do not break)

- Whole-GPU allocation; leasing is atomic; never double-allocate a `gpu_uuid`.
- Ledger is append-only and authoritative; balance is a cache.
- Roles enforced server-side on every `/admin` endpoint.
- User containers are unprivileged, no Docker socket, on an internal network; they cannot reach Postgres, the hub admin port, or other users' containers.
- An image is enabled in the catalog **only** after its smoke test passes.

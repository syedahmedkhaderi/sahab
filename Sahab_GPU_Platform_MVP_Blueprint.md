# Sahab — University GPU Compute Platform (Build Status & Handoff)

> "Sahab" (سحاب, "cloud") — a self-hosted, browser-based GPU compute platform: a private Google Colab for a university. Users log in through a website, click **Launch Workspace**, and get a full in-browser IDE (JupyterLab + VS Code) on the institution's dual NVIDIA L4 server, metered by a credit system. No VPN/SSH for end users.
>
> **This document was originally the build blueprint. It has been rewritten to record what has actually been built, how it was verified, and exactly what remains.** It is the canonical handoff/status doc. The original blueprint's design intent is preserved inline where it still governs the work. Last updated: 2026-06-23.

---

## 0. Executive status

The **full MVP monorepo has been scaffolded, built, tested, and committed locally** — not just the Phase-1 JupyterHub slice from `sahab_phase1_setup.sh`, but the entire three-plane architecture (product plane, workspace plane, platform services). All components pass their local verification gates:

- **Backend** (FastAPI control plane + worker): **38/38 pytest tests pass** offline (SQLite + fakeredis).
- **Frontend** (Next.js product shell): **`npm run build` compiles all 12 routes**, zero type errors.
- **Infra** (full docker-compose stack): **`docker compose config` validates** (exit 0); all Traefik/Prometheus/Grafana config files parse.
- **Workspace images** (gpu-pytorch, cpu-base): Dockerfiles + pinned requirements + smoke tests written; **image build + GPU smoke test must still be run on the GPU server** (no GPU available in the build environment).

What is **not yet done** is (a) the GPU-server deployment itself (build the ~5 GB image, run the mandatory L4 smoke test, `docker compose up` on `10.125.81.52` over the VPN), and (b) a set of explicitly-deferred, future-phase features (email verification, real payments, full OAuth-SSO cutover, institutional IdP, monitoring hardening, k3s). These are enumerated in §7.

Built with parallel sub-agents (backend / frontend / infra), each component tested and committed as its own step. **6 commits, 116 tracked files.**

---

## 1. What we are building (unchanged intent)

A self-hosted GPU platform that replaces the current "GlobalProtect VPN + SSH via VS Code Remote" workflow with "open a URL and log in." Google Colab is unavailable in Qatar; the platform fills that gap on local hardware. The server runs 24/7, so unused GPU time is recoverable, metered capacity. MVP targets a single server and a single institution; multi-university is a later roadmap item.

### Primary goals (MVP) — status

| # | Goal | Status |
|---|---|---|
| 1 | Website login → dashboard | **Built** (frontend + backend auth), not yet deployed |
| 2 | Dashboard shows credit balance + usage history | **Built** |
| 3 | Launch Workspace → in-browser IDE (notebooks + VS Code) in ~60s | **Built** (launch flow + Hub spawn); needs GPU-server validation |
| 4 | Credits deducted per GPU-minute while running | **Built** (metering worker) |
| 5 | Auto-stop at zero credits / idle / time limit; GPU released | **Built** (metering + idle-culler + max-duration) |
| 6 | Admin: users, credits, rates, live GPU view, force-stop | **Built** (admin console + endpoints) |
| 7 | No end user touches VPN/SSH | **Achieved by design**; depends on exposure strategy at deploy |

### Hardware constraint (load-bearing, unchanged)

The **NVIDIA L4 does not support MIG** — one L4 cannot be safely partitioned between tenants. Therefore **whole-GPU allocation**: one L4 → one session at a time. Two L4s ⇒ at most two concurrent GPU sessions, plus unlimited CPU sessions, plus a FIFO queue. No time-slicing in the MVP. Natural billing unit: the GPU-minute.

---

## 2. Repository structure (as built)

```
Sahab/                                  (git repo, 6 commits, 116 files)
  Sahab_GPU_Platform_MVP_Blueprint.md   THIS document (build status + roadmap)
  sahab_phase1_setup.sh                 original Phase-1 generator (kept for reference)
  README.md  .env.example  .gitignore

  backend/                              FastAPI control plane (40 files)
    app/
      main.py            app factory, router mounting, startup seed (rates/images/admin)
      config.py          pydantic-settings reading every .env var
      db.py              async engine/session (postgresql+psycopg | sqlite for tests)
      models.py          SQLAlchemy models for ALL blueprint tables
      schemas.py         Pydantic v2 request/response models
      security.py        bcrypt, JWT, cookie deps, domain-restricted signup, require_admin
      worker.py          standalone APScheduler worker (metering + queue drain)
      services/          credits, scheduler (atomic leasing), jupyterhub (REST), sessions, metering
      routers/           auth, me, sessions, catalog, credits(+usage), admin, oauth, metrics
    migrations/          Alembic env + 0001_initial_schema
    tests/               test_auth, test_credits, test_scheduler, test_sessions, test_metering, test_admin
    pyproject.toml  requirements.txt  alembic.ini  Dockerfile  README.md

  frontend/                             Next.js 14 App Router (45 files)
    app/
      page.tsx                          public landing
      login/ signup/ verify/            auth screens
      (authed)/                         auth-guarded group
        layout.tsx  dashboard/ launch/ billing/ settings/ admin/
      sessions/[id]/connect/            poll-then-redirect workspace handoff
    components/  ui/ (9 hand-built primitives) + app cards
    lib/         api.ts (typed client), types.ts, utils.ts
    middleware.ts  Dockerfile  package.json  tailwind/tsconfig/postcss

  jupyterhub/                           Dockerfile + jupyterhub_config.py (OAuth/native modes, GPU pin hook, hardening)
  images/
    gpu-pytorch/   Dockerfile (CUDA 12.4 + torch 2.4) + requirements.txt + jupyter_server_config.py + smoke_test.py
    cpu-base/      CPU twin (cpu torch wheels), same stack, no-GPU smoke test
  infra/
    docker-compose.yml                  full stack (12 services)
    traefik/       traefik.yml + dynamic/middlewares.yml
    prometheus/    prometheus.yml (7 scrape jobs incl. backend /api/metrics)
    grafana/       datasource + GPU/sessions dashboard JSON
    cloudflared/   tunnel README + config.example.yml
  scripts/         preflight.sh, discover_gpus.sh, build_images.sh
  docs/            architecture.md, deployment.md, runbook.md
```

---

## 3. Architecture as implemented

Three planes (unchanged from the design):

1. **Product plane** — Next.js web app + FastAPI control-plane API. Source of truth for identity, credits, and the decision of *whether a session may start*.
2. **Workspace plane** — JupyterHub + DockerSpawner spawns one container per session (JupyterLab + code-server). GPU containers pin exactly one L4 via `NVIDIA_VISIBLE_DEVICES=<uuid>`.
3. **Platform services** — PostgreSQL (system of record), Redis (locks/queue), metering/scheduler worker, Traefik (one-domain path routing), cloudflared (exposure), Prometheus/Grafana/DCGM/node-exporter/cAdvisor (monitoring).

```
        Browser ── Cloudflare edge ── cloudflared ── Traefik (one domain, path routing)
                                                       │
            / ─► Next.js     /api/* ─► FastAPI     /hub/*, /user/* ─► JupyterHub
                                 │  │                     │
                            Postgres Redis          DockerSpawner + NVIDIA runtime
                                 │                        │
                        metering/scheduler worker   per-user GPU/CPU container
                                                    (JupyterLab + code-server, 1× L4)
        Monitoring: Prometheus + Grafana + DCGM/node-exporter/cAdvisor (backend exposes /api/metrics)
```

### Compose services (12)

`postgres:16`, `redis:7-alpine`, `backend` (uvicorn), `worker` (`python -m app.worker`, same image), `frontend`, `jupyterhub` (mounts docker.sock), `traefik:v3.0`, `cloudflared`, `prometheus:v2.53.0`, `grafana:11.1.0`, `dcgm-exporter:3.3.5`, `node-exporter:v1.8.1`, `cadvisor:v0.49.1`. Named volumes: `pgdata`, `redis-data`, `sahab-hub-db`, `grafana-data`, `prometheus-data`, `traefik-certs`. Network: `sahab-network` (bridge, attachable).

### Data model (as built — blueprint §12)

`users`, `gpu_inventory`, `images`, `rates`, `sessions`, `gpu_leases`, `credit_ledger` (append-only, source of truth), `transactions` (payments-ready, unused), `audit_log`. UUID PKs. See `backend/app/models.py`.

### Session state machine (implemented)

```
requested ─►(queued ─►) starting ─► running ─► stopping ─► stopped
                                   └──────────────────────► failed   (always releases any GPU lease)
```
Metering starts at `running`.

### Deviations from the original blueprint (intentional)

- **Auth for Phase 1 is selectable** (`AUTH_MODE` in JupyterHub config): `native` (NativeAuthenticator, standalone) or `oauth` (GenericOAuthenticator → FastAPI). The FastAPI OAuth2 provider endpoints exist (`/api/oauth/authorize|token|userinfo`); the full website↔hub SSO **cutover is not yet wired/validated end-to-end** (see §7).
- **`audit_log.detail` is `Text`** (JSON string), not `JSONB`, so tests run on SQLite. A follow-up migration switches it to `JSONB` on Postgres.
- **Dev DB convenience:** `main.py` runs `Base.metadata.create_all` on startup for dev/test. **Production must run `alembic upgrade head`** before first boot.
- **Backend exposes `/api/metrics`** in Prometheus text format (`sahab_queue_depth`, `sahab_credits_burned_total`, GPU/session/user gauges) — added during integration so the Prometheus scrape + Grafana dashboard work. Distinct from `/api/admin/metrics` (JSON, admin-gated).

---

## 4. Verification evidence (what was actually tested)

| Component | Gate | Result |
|---|---|---|
| Backend | `pip install -e '.[dev]'` then `pytest` | **38 passed** (auth, credits, scheduler atomicity, sessions, metering, admin authz) |
| Backend | `python -c "import app.main"` | OK |
| Backend | live `GET /api/metrics` against ASGI app | 200, valid Prometheus exposition format |
| Frontend | `npm install` + `npm run build` | **12 routes compiled**, 0 type errors |
| Infra | `docker compose -f infra/docker-compose.yml config` | exit 0 (only blank-var warnings) |
| Infra | YAML/JSON parse of all prometheus/grafana/traefik files | all valid |
| Scripts | `bash -n` on all three | syntax OK |
| Images | **build + smoke test** | **NOT YET RUN — requires the GPU server** |

Test coverage highlights: **no double-allocation** under a concurrent 3-sessions/2-GPUs race; ledger append-only invariant; zero-balance blocks start and auto-stops a running session; all `/admin/*` reject non-admins (403/401); domain-restricted signup.

---

## 5. How to run

### Local development (no GPU)

```bash
# Backend
cd backend && python -m venv .venv && source .venv/bin/activate
pip install -e '.[dev]' && pytest          # 38 pass
uvicorn app.main:app --reload              # API on :8000
python -m app.worker                       # metering/scheduler

# Frontend
cd frontend && npm install && npm run build && npm run dev   # :3000
```

### GPU-server deployment (the remaining manual step) — on `10.125.81.52` over the VPN

```bash
cp .env.example .env          # set strong POSTGRES_PASSWORD, JWT_SECRET (openssl rand -hex 32),
                              # OAUTH_CLIENT_SECRET, JUPYTERHUB_API_TOKEN, BOOTSTRAP_ADMIN_*, PUBLIC_HOSTNAME
bash scripts/preflight.sh                                   # Phase 0 host gate (driver≥550, Docker, NVIDIA toolkit, GPUs)
bash scripts/build_images.sh                               # build + MANDATORY GPU smoke test (must print OK + show L4)
docker compose -f infra/docker-compose.yml up -d --build   # bring up the stack
docker compose -f infra/docker-compose.yml exec backend alembic upgrade head      # init DB
scripts/discover_gpus.sh --sql | docker compose -f infra/docker-compose.yml exec -T postgres psql -U "$POSTGRES_USER" -d "$POSTGRES_DB"   # seed real GPU inventory
```

Exposure: **Strategy A** (set `CLOUDFLARE_TUNNEL_TOKEN` → public hostname, no inbound ports, no VPN) or **Strategy B** (university-network/VPN only; migrate to A later by adding the token — nothing else changes). Routing is by path on one domain: `/`→frontend, `/api/*`→backend, `/hub/*` & `/user/*`→JupyterHub.

---

## 6. Build-phase tracker

| Phase | Scope | Status |
|---|---|---|
| **0 — Preflight** | Confirm root, driver, Docker, NVIDIA toolkit, both L4s | **`scripts/preflight.sh` written**; run on server |
| **1 — Workspace core** | JupyterHub + DockerSpawner + GPU image, code-server, per-user volumes, idle-culler, GPU pin | **Built** (`jupyterhub/`, `images/`); image build + smoke test pending on server |
| **2 — Control plane** | Postgres + Redis + FastAPI + worker, sessions/credits/queue/leasing, SSO | **Built & tested** (38 tests); OAuth-SSO cutover not yet validated end-to-end |
| **3 — Product UI** | Next.js: landing, auth, dashboard, launch, billing, admin | **Built** (12 routes compile) |
| **4 — Exposure + monitoring** | cloudflared, Prometheus/Grafana/DCGM, hardening | **Configured**; needs live deploy + dashboard verification + security pass |
| **5 — Payments** | QCB-licensed gateway, webhooks, receipts | **Deferred** (table/schema in place); admin-granted credits until a legal merchant exists |
| **6 — Polish & scale** | Collab editing, more images, analytics, k3s | **Not started** (roadmap) |

---

## 7. Remaining work (detailed, prioritized)

### A. Deploy to the GPU server (blocks "live") — highest priority
1. Run `scripts/preflight.sh` on `10.125.81.52`; resolve any FAIL (driver ≥ 550 for CUDA 12.4, NVIDIA Container Toolkit, Docker, `--gpus` works, both L4s visible).
2. `scripts/build_images.sh` — build `sahab-gpu-pytorch` (~5 GB, 15–25 min) and `sahab-cpu-base`. **The GPU smoke test is the mandatory gate**: it must print OK and show the L4, or the image cannot be enabled.
3. `docker compose up -d --build`, then `alembic upgrade head`, then seed GPU inventory from `discover_gpus.sh`.
4. Confirm: JupyterHub login works, a launched session pins exactly one L4, VS Code opens in the launcher, credits deduct, idle-cull fires.
5. **Coexistence note:** GPU 1 currently runs someone else's training job. Docker containers are isolated from host processes; the platform must not touch it. Only lease GPUs reported `free`; when GPU 1 frees it becomes available to workspaces.

### B. Auth / SSO cutover (Phase 2 finish)
- Wire and validate the website↔JupyterHub OAuth flow end-to-end: `GenericOAuthenticator` → FastAPI `/api/oauth/authorize|token|userinfo`, with the hub redirecting unauthenticated users to the FastAPI login so the session cookie exists before `/authorize`. Today Phase 1 defaults to `AUTH_MODE=native` as a safe standalone.
- **Email verification** (`POST /auth/verify`): not implemented; needs a mail provider (SendGrid/SES) and verification tokens. Currently signup sets status from `REQUIRE_ADMIN_APPROVAL`.
- `POST /admin/users` (admin-create with email+password) is a **501 stub**; admins approve self-registered users via `PATCH /admin/users/{id}` (`status=active`). Implement if admin-provisioned accounts are needed.

### C. Control-plane ↔ Hub spawn integration (validate on server)
- Confirm FastAPI's `jupyterhub.py` REST driver starts/stops the right user server and that the **leased GPU UUID is actually injected** into the spawned container (via spawn options / `pre_spawn_hook`) — the pin must be the single leased UUID in production, not `all`.
- Reconciliation job for orphan leases (GPU `leased` with no live session after a crash) — add to the worker.

### D. Monitoring & security hardening (Phase 4 finish)
- Verify Grafana GPU/sessions dashboard renders against live DCGM data; confirm `dcgm-exporter` works with the host toolkit.
- Wire the alerts named in `docs/runbook.md` (GPU 100% with no session activity; temp/power; disk; session over time limit; **metering worker not ticking**).
- Security pass: confirm user containers are unprivileged, no Docker socket, on the internal network, and **cannot reach Postgres / the hub admin port / other users' containers**; enforce per-user disk quotas; egress allowlist (optional).
- Add Cloudflare Access (SSO/OTP) as an outer gate (optional).

### E. Data / migrations
- Follow-up Alembic migration: `audit_log.detail` `Text` → `JSONB` on Postgres.
- Ensure production never relies on `create_all`; gate it behind a dev flag.
- Nightly `pg_dump` backup of `sahab` DB (credits + ledger are irreplaceable); volume snapshots.

### F. Frontend polish
- Admin: add a **role-change** control (API `admin.updateUser()` already supports it; UI only does activate/disable + grant today).
- Bump `next` past the 14.2.5 advisory before any public exposure.
- De-duplicate the `GET /me` calls (authed layout + pages) via context; optionally self-host the Inter font for air-gapped installs.

### G. Phase 5 — Payments (deferred until a legal merchant entity exists)
- Integrate a QCB-licensed gateway (MyFatoorah / Dibsy / Tap / PayTabs / QPay): `POST /payments/checkout` → redirect → success webhook → positive ledger entry → receipt. Stripe is **not** available in Qatar. The `transactions` table and flow are pre-built; until then, admin-granted credits.

### H. Phase 6 — Scale & roadmap
- k3s + NVIDIA GPU Operator for multi-node; per-institution tenancy; institutional IdP federation (SAML/Azure AD/Okta/LDAP); reservations/priority/preemption; image marketplace; collaborative editing.

---

## 8. Key invariants (do not break)

- **Whole-GPU allocation only** (L4 has no MIG); leasing is **atomic** (Redis lock + Postgres row update); **never double-allocate a `gpu_uuid`**. (Covered by `test_scheduler`.)
- **`credit_ledger` is append-only and the source of truth**; `users.credit_balance` is a cache recomputed from it. (Covered by `test_credits`.)
- **Roles enforced server-side** on every `/admin` endpoint. (Covered by `test_admin`.)
- **Signup restricted** to `ALLOWED_SIGNUP_DOMAINS`.
- **User containers**: unprivileged, no Docker socket, internal network; cannot reach Postgres, the hub admin port, or other users' containers.
- **An image is enabled in the catalog only after its smoke test passes.**
- **`failed` sessions always release any GPU lease.**

---

## 9. Known assumptions & risks

- Builder has, or can obtain, **root/sudo** on the GPU server (required for driver, NVIDIA Container Toolkit, Docker, `--gpus`). If only unprivileged access exists, IT must pre-install Docker + the toolkit and add the account to the `docker` group.
- Server has **outbound internet** (package installs; Strategy A tunnel).
- **Admin-granted credits** for MVP; real payments deferred until a legal merchant entity exists.
- Only the **two L4s** are in scope; whole-GPU allocation accepted.
- **Email/password + domain restriction** acceptable for MVP auth; institutional SSO later.
- JupyterHub username derived as `email.split("@")[0]` — unique within one institution, could collide in future multi-tenant.
- `next@14.2.5` has an npm advisory — fine for internal dev, patch before public exposure.

Open questions to confirm with IT/project (carried over): root/sudo availability; outbound + a Cloudflare-hosted domain (else Strategy B first); build email/password vs. integrate the university IdP now; acceptable to install Docker and dedicate/schedule both GPUs while coexisting with existing non-Docker GPU usage; expected day-one concurrency vs. two GPU slots + queue.

---

## 10. Appendix

### Commits (chronological)
```
Foundation: monorepo skeleton, .gitignore, .env.example, README
Scripts (preflight, discover_gpus, build_images) and docs (architecture, deployment, runbook)
Infra + JupyterHub + workspace images
Backend: FastAPI control plane + metering/scheduler worker
Frontend: Next.js product shell
Integration: add ACME_EMAIL to .env.example; close backend<->monitoring gap
```

### Key commands
```
scripts/preflight.sh                 # Phase-0 host gate
scripts/build_images.sh [name]       # build + smoke-test workspace images (SKIP_SMOKE=1 to build only)
scripts/discover_gpus.sh --sql       # emit gpu_inventory INSERTs from nvidia-smi
docker compose -f infra/docker-compose.yml up -d --build
docker compose -f infra/docker-compose.yml exec backend alembic upgrade head
cd backend && pytest                 # 38 tests
cd frontend && npm run build         # 12 routes
```

### Config
All environment variables are documented in `.env.example` (domain/exposure, Postgres/Redis, JWT/auth, OAuth, JupyterHub integration, policy defaults — `GPU_SESSION_MAX_MINUTES=240`, `IDLE_TIMEOUT_MINUTES=45`, `CREDITS_PER_MINUTE_L4=1.0`, `CREDITS_PER_MINUTE_CPU=0.0` — workspace paths, monitoring, frontend). Further operational detail lives in `docs/architecture.md`, `docs/deployment.md`, `docs/runbook.md`.

### Glossary
**L4** NVIDIA Ada GPU, 24 GB, no MIG · **MIG** hardware GPU partitioning (A100/H100-class only) · **whole-GPU allocation** one GPU ↔ one session · **JupyterHub/DockerSpawner** multi-user spawner running each session in a container · **code-server** browser VS Code · **jupyter-server-proxy** proxies code-server behind authenticated paths · **cloudflared** outbound-only tunnel to a public hostname, no inbound ports · **DCGM exporter** NVIDIA GPU metrics for Prometheus · **compute credit** internal billing unit, default 1 credit = 1 L4 GPU-minute.

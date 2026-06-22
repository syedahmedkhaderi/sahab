# Sahab — University GPU Compute Platform (MVP Build Blueprint)

> "Sahab" (سحاب, "cloud") is a placeholder codename. Rename freely.
> This is a self-contained build specification. A coding agent (Claude Code, Codex, or GLM) should be able to build the MVP from this document with minimal additional context. Read it top to bottom before writing any code.

## 0. What we are building (one paragraph)

A self-hosted, browser-based GPU compute platform for a university. It is, in spirit, a private Google Colab: users log in through a website, click "Launch Workspace," and get a full in-browser IDE (Jupyter notebooks plus a complete VS Code editor) running on the university's GPU server. Access is metered by a credit system (compute credits per minute of GPU time). The university's existing dual NVIDIA L4 server is the compute backend. The platform abstracts away the current VPN-plus-SSH workflow entirely: end users never touch GlobalProtect or SSH, they only use a web browser. The long-term goal is to expand the same platform to other universities; the MVP targets a single server and a single institution.

## Table of contents

1. Goals, non-goals, and success criteria
2. Why not just use Colab / the existing SSH flow
3. The hardware reality (L4 GPUs) and what it forces
4. High-level architecture
5. Component breakdown
6. Networking and exposure (the VPN/SSH replacement)
7. GPU allocation and scheduling model
8. The workspace (the in-browser IDE)
9. Authentication and user management
10. Credit and billing system
11. Session lifecycle (end-to-end flow)
12. Data model (PostgreSQL schema)
13. Backend API surface
14. Frontend (product shell)
15. Dependency and version strategy (zero-clash mandate)
16. Security model
17. Monitoring and observability
18. Deployment topology and prerequisites
19. Repository structure
20. Configuration and environment variables
21. Build phases and milestones
22. Testing and acceptance criteria
23. Known risks, assumptions, and open questions
24. Future roadmap (multi-university)
25. Appendix A: key config snippets
26. Appendix B: glossary

## 1. Goals, non-goals, and success criteria

### Primary goals (MVP)

1. A user opens a website, signs in with a university account, and lands on a dashboard.
2. The dashboard shows their compute credit balance and usage history.
3. The user clicks "Launch Workspace," picks a runtime (GPU or CPU) and an environment image, and within ~60 seconds is dropped into a working in-browser IDE with notebooks and VS Code.
4. While a GPU session runs, credits are deducted per minute at a defined rate.
5. When credits hit zero, or a time/idle limit is reached, the session stops automatically and the GPU is released for the next user.
6. An admin can create users, grant credits, set rates, see live GPU utilization, and stop any session.
7. No end user ever uses the VPN or SSH directly.

### Non-goals (explicitly out of scope for MVP)

- Real money payment processing (deferred; see Section 10). MVP uses admin-granted credits.
- Multi-node / multi-server scheduling. MVP is one server.
- Multi-university tenancy. MVP is single-tenant.
- Fractional GPU sharing of a single L4 between users (not safely possible on this hardware; see Section 3).
- Mobile-native apps. The web app should be responsive, but native apps are out of scope.

### Success criteria (definition of done for the MVP)

- Two users can each hold one of the two L4 GPUs concurrently, each in their own isolated container, each seeing exactly one GPU.
- A third user requesting a GPU is either queued (with a visible position) or offered a CPU session, and is auto-assigned a GPU when one frees.
- Credit deduction is accurate to within one minute of actual GPU hold time.
- Killing the platform and restarting it does not lose user data (notebooks, files) or credit balances.
- A new pre-built GPU image passes an automated smoke test (CUDA visible, all libraries import) before it can be used.

## 2. Why not just use Colab / the existing SSH flow

- Google Colab is not available in Qatar. This is the core motivation. The platform fills that gap using local hardware.
- The current flow (GlobalProtect VPN, then SSH via VS Code Remote-SSH) works for one technical user but does not scale to dozens of students and professors. It requires every user to be granted SSH access, to install and configure a VPN, to manage SSH keys/passwords, and to share a single multi-user Linux box with no isolation, no quotas, and no usage accounting. There is also no way to fairly allocate or charge for the GPUs.
- The platform turns "one shared Linux box behind a VPN" into "a metered, isolated, self-service product." The server is on 24/7 regardless, so unused GPU time is wasted capacity. The platform recovers that value.

## 3. The hardware reality (L4 GPUs) and what it forces

This section is load-bearing. The chosen GPU is the NVIDIA L4 (Ada Lovelace, 24 GB). This dictates the entire sharing model.

- MIG (Multi-Instance GPU), which hardware-partitions one physical GPU into several isolated sub-GPUs, is supported only on data-center GPUs starting at the A100/A30 level and on Hopper/Blackwell (H100, H200, B200, GB200) and a few Blackwell workstation cards. The L4 does not support MIG. You cannot carve one L4 into isolated slices.
- Therefore, the only safe multi-user model on this hardware is whole-GPU allocation: at any moment, one L4 belongs to exactly one user session. Two L4s means a maximum of two concurrent GPU sessions.
- Other "GPU sharing" techniques exist but are not appropriate for a paid, multi-tenant MVP:
  - Time-slicing (the NVIDIA device-plugin oversubscription feature) lets multiple processes share a GPU by interleaving in time, but provides no memory isolation. One user can exhaust VRAM and crash or stall everyone else on that GPU. Unacceptable when users are paying and untrusted relative to each other.
  - MPS (Multi-Process Service) improves co-scheduling of cooperative processes from a single trust domain; it is not a tenant-isolation mechanism.
  - vGPU (NVIDIA AI Enterprise / vGPU software) can partition by software but requires paid NVIDIA licensing and hypervisor support. Out of scope for MVP.

Decision for MVP: whole-GPU allocation, two GPU slots, plus an unlimited number of lightweight CPU-only sessions and a queue for GPU demand beyond two. Time-slicing may be offered later, only for explicitly low-risk/low-VRAM workloads and only with per-process memory caps, clearly labeled as best-effort and non-isolated. Do not build time-slicing in the MVP.

Billing consequence: the natural billing unit is the GPU-hour (one L4 held for one hour). This keeps metering simple and honest.

## 4. High-level architecture

Three planes:

1. Product plane (what the user sees): a Next.js web app (landing page, auth, dashboard, billing, admin) backed by a FastAPI control-plane API.
2. Workspace plane (where work happens): JupyterHub spawning one Docker container per active user session. Each container runs JupyterLab plus code-server (VS Code in the browser). GPU containers get exactly one L4 pinned to them.
3. Platform services: PostgreSQL (system of record), Redis (locks, queue, rate limiting), a metering/scheduler worker, a reverse proxy (Traefik), Cloudflare Tunnel (public exposure), and a monitoring stack (Prometheus, Grafana, NVIDIA DCGM exporter).

Text diagram:

```
                         Internet user (browser only)
                                    |
                          Cloudflare edge (TLS, optional Access SSO)
                                    | (cloudflared outbound tunnel)
                          Traefik reverse proxy (single domain)
            ----------------------------------------------------------------
            |                       |                          |
        Next.js                FastAPI API                 JupyterHub
      (product UI)         (auth, credits, sessions)   (spawns user containers)
                                    |                          |
                              PostgreSQL  Redis        DockerSpawner + NVIDIA runtime
                                    |                          |
                          Metering / Scheduler         Per-user GPU/CPU container
                                worker                 (JupyterLab + code-server)
                                                              |
                                                        1x NVIDIA L4 pinned
                              Monitoring: Prometheus + Grafana + DCGM exporter
```

Why JupyterHub instead of orchestrating containers by hand: JupyterHub already solves multi-user spawning, per-user single-server lifecycle, an admin REST API, idle culling, and per-user volumes. It is the proven backbone for exactly this (multi-user notebooks on Docker with GPUs). The custom FastAPI plus Next.js layer adds the product experience (identity, credits, billing, polished UI) that JupyterHub does not provide. FastAPI is the source of truth for credits and decides when a session may start; JupyterHub is the engine that physically starts and stops the containers, driven through its REST API.

## 5. Component breakdown

| Component | Tech | Responsibility |
|---|---|---|
| Frontend | Next.js (React, TypeScript), Tailwind, shadcn/ui | Landing page, auth screens, dashboard, launch flow, billing, admin console |
| Control-plane API | FastAPI (Python 3.11+) | Identity, roles, credit ledger, session lifecycle, GPU leasing, queue, admin actions, OAuth provider for JupyterHub |
| Workspace orchestrator | JupyterHub + DockerSpawner | Spawn/stop one container per user session, idle culling, per-user volumes |
| Workspace image (GPU) | Docker, NGC CUDA base | JupyterLab + code-server + pinned ML stack with a working CUDA toolchain |
| Workspace image (CPU) | Docker, slim Python base | JupyterLab + code-server, no CUDA |
| Database | PostgreSQL 16 | System of record for users, credits, sessions, usage, inventory, audit |
| Cache / locks / queue | Redis 7 | GPU allocation locks, session locks, rate limiting, job queue |
| Metering + scheduler worker | Python (APScheduler or Celery beat) | Per-minute credit deduction, enforce limits, assign freed GPUs to queued requests |
| Reverse proxy | Traefik 3 | Single-domain routing and TLS to all services |
| Public exposure | cloudflared (Cloudflare Tunnel) | Expose the platform without opening inbound ports or a public IP |
| Monitoring | Prometheus, Grafana, DCGM exporter, node-exporter, cAdvisor | GPU/system metrics, dashboards, alerts, metering cross-check |

## 6. Networking and exposure (the VPN/SSH replacement)

This is the part that feels complicated, so here is the mental model: the platform itself sits next to the GPU server and speaks plain HTTPS to the outside world. End users only ever load a web page. They do not run GlobalProtect and do not SSH. The VPN-and-SSH dance is replaced by "open a URL and log in."

There are two viable exposure strategies. Pick based on what university IT allows.

### Strategy A (recommended target): Cloudflare Tunnel

- Run `cloudflared` on the GPU server (or a co-located host). It makes an outbound-only encrypted connection to Cloudflare and maps a public hostname (for example `sahab.example.com`) to the local Traefik entrypoint.
- No inbound ports are opened and no public IP is needed on the server. This is ideal for a machine behind an institutional firewall.
- Optionally layer Cloudflare Access (SSO, one-time-PIN, or Google/Microsoft login) as an outer gate before traffic ever reaches the platform.
- Requirements and caveats to verify with IT:
  - The server must be allowed outbound to Cloudflare (HTTPS / QUIC). Many research VMs already allow outbound (they need it for `pip`/`apt`). Confirm this.
  - A domain must be on Cloudflare (free plan is sufficient).
  - Cloudflare's free tunnel terms restrict serving large non-HTML media. Normal app traffic, notebooks, and modest file transfers are fine; very large dataset downloads through the tunnel may hit terms. For heavy data movement, prefer in-workspace download from source, or a later dedicated ingress.
- If outbound to Cloudflare is allowed, users no longer need the VPN at all. This is the "real Colab" experience.

### Strategy B (fallback for day one): keep it on the university network

- Host the platform on the university network and have it reachable only when on that network (still via the existing VPN). The difference from today is that users now get a browser IDE and a credit system instead of raw SSH. This is strictly simpler for end users than configuring SSH, even though the VPN is still in the loop.
- This is a fine starting point if IT has not yet approved a public hostname. Migrate to Strategy A when ready by adding `cloudflared`; nothing else in the architecture changes.

### Internal routing (both strategies)

- A single public hostname maps to Traefik. Traefik routes by path on one domain so that authentication cookies are shared across the product UI and the workspace:
  - `/` -> Next.js frontend
  - `/api/*` -> FastAPI
  - `/hub/*` and `/user/*` -> JupyterHub (and therefore the spawned user servers)
- Using one parent domain is important: JupyterHub user servers live under `/user/<name>/...`, and SSO between the product UI and the workspace relies on cookies on the shared domain.

## 7. GPU allocation and scheduling model

### Inventory

- On startup, the scheduler discovers GPUs by their stable UUIDs (`nvidia-smi -L`) and records them in a `gpu_inventory` table: `{uuid, model, vram_mb, status}` where status is `free`, `leased`, or `disabled`.
- For the MVP server this yields two rows, both L4 / 24 GB.

### Leasing (whole-GPU)

- When a session needs a GPU, the scheduler atomically (Redis lock plus a PostgreSQL row update, or a Postgres advisory lock) finds a `free` GPU, marks it `leased`, and records a `gpu_lease {session_id, gpu_uuid, started_at}`.
- The container is spawned with that single GPU pinned via the environment variable `NVIDIA_VISIBLE_DEVICES=<gpu_uuid>`. Inside the container the user sees exactly one GPU.
- On session stop (manual, idle, timeout, or out-of-credits), the lease is closed and the GPU returns to `free`. The scheduler then checks the queue.

### Queue and CPU fallback

- If no GPU is free, the request goes into a FIFO queue (per-priority if you implement roles; otherwise plain FIFO). The user sees their position and an estimated wait.
- The user may instead start a CPU-only session immediately (cheaper or free), and is notified (and optionally auto-upgraded) when a GPU frees.
- When a GPU is released, the scheduler pops the next queued GPU request, leases the GPU, and starts that session. Notify the waiting user.

### Fair rotation limits (configurable)

- Maximum GPU session duration (default suggestion: 4 hours) after which the session stops and the user must relaunch (re-queueing if others are waiting).
- Idle timeout (default suggestion: 30–60 minutes of no kernel/CPU/GPU activity) enforced by JupyterHub's idle-culler plus the platform's own check.
- These limits prevent one user from parking on a GPU indefinitely and starving others.

### Anti-abuse

- Detect and stop sustained GPU saturation with no notebook/editor activity (a signal of background crypto mining), and make the terms of use prohibit non-research workloads. Cross-reference DCGM metrics with kernel activity.

## 8. The workspace (the in-browser IDE)

The MVP must feel like a real, modern IDE, not a bare notebook. Achieve this by running two front-ends inside one container and letting the user switch between them.

### Inside each user container

- JupyterLab as the default surface: notebooks, file browser, integrated terminal, text/markdown editor, extensions, a Git extension, and a variable inspector.
- code-server (the open-source build of VS Code for the browser) exposed alongside JupyterLab through `jupyter-server-proxy`. A launcher button in JupyterLab opens full VS Code at `/user/<name>/proxy/<port>/` with extensions, IntelliSense, debugging, and an integrated terminal. This delivers the "Cursor / VS Code" standard the project is aiming for. (Reference pattern: the `jupyter-server-proxy` ecosystem plus a code-server proxy plugin.)
- A small GPU status panel/extension or a starter notebook cell that prints the allocated GPU and live VRAM usage, so users can see what they are paying for.
- Pre-installed, version-pinned ML stack (see Section 15). Users may still `pip install` extra packages within their session; the base is curated so common stacks work out of the box.

### Persistence

- Each user gets a persistent Docker volume mounted at their home/work directory. Files and notebooks survive session stop/restart and platform restarts.
- A shared, read-only datasets volume is mounted into every workspace for common datasets, so they are not duplicated per user.
- Per-user disk quota (suggested default 50 GB) enforced at the volume level.

### Power-user SSH (optional, later)

- The current SSH/VS Code-Remote workflow can remain available for advanced users as an opt-in, but routed and authorized through the platform (so it is still gated and accounted), not as a parallel ungoverned path. Not required for MVP.

## 9. Authentication and user management

### Roles

- `student`, `researcher`, `professor`, `admin`. Roles drive queue priority, default credit grants, and session limits. Admins manage everything.

### MVP authentication

- Email and password handled by FastAPI, with email verification.
- Restrict signup to the university email domain(s) (for example `@udst.edu.qa`) so only institutional users can register. Optionally require admin approval before a new account becomes active.
- FastAPI issues signed JWTs and sets a session cookie scoped to the parent domain.

### SSO between the product and JupyterHub (the clean path)

- FastAPI acts as an OAuth2 / OIDC provider (use Authlib). JupyterHub is configured with `GenericOAuthenticator` pointing at FastAPI. This is the standard, secure way to make the website and the workspace share one identity. The user logs in once on the website; JupyterHub trusts that identity through the OAuth flow.
- Simpler fallback if the OAuth provider work is too heavy for the first pass: a custom JupyterHub `Authenticator` that validates a short-lived one-time token minted by FastAPI on "Launch" (passed on the redirect and verified server-to-server). One identity source (PostgreSQL), no second password store. Acceptable for MVP; migrate to full OAuth later.

### Future (real institutional auth)

- Integrate the university's identity provider (the same system behind GlobalProtect, likely SAML / Azure AD / Okta / LDAP). This requires IT cooperation and is the production-grade path. Not required for MVP, but design the auth layer so the identity provider can be swapped without touching billing or sessions.

## 10. Credit and billing system

### Model

- A compute credit is the platform's internal currency. Define a clear conversion, for example: 1 credit = 1 GPU-minute on an L4. Pick round numbers and make them configurable.
- A `rates` table maps each resource type to credits-per-minute, for example `l4_gpu = 1.0`, `cpu = 0.0` (free) or a small number. Store rates in the DB so admins can change them without redeploying.
- A `credit_ledger` is an append-only list of entries: grants (positive), debits (negative, from metering), and refunds. Each entry records amount, reason, optional `session_id`, timestamp, and resulting balance. The user's balance is the running sum (cache it on the user row for fast reads, recompute from the ledger as the source of truth).

### Metering (the core loop)

- The metering worker runs every minute. For each active session, it computes elapsed minutes since the last tick multiplied by the session's resource rate, writes a debit ledger entry, and updates the cached balance.
- If a balance reaches zero (or a configurable low-water mark), the worker triggers a graceful stop: warn the user in-session if possible, then stop the container and release the GPU. Optionally allow a small negative grace buffer to avoid abrupt mid-operation kills, then settle.
- Cross-check metered GPU-minutes against DCGM-reported GPU busy time for auditing.

### Top-up (MVP vs later)

- MVP: admins grant credits (a button in the admin console writes a positive ledger entry). Optionally support department cost-codes or batch grants (for example, "give every student in CS101 100 credits").
- Later (real money): integrate a payment gateway. Important Qatar-specific constraint: Stripe is not officially available in Qatar. QCB-licensed local gateways are the realistic options, for example MyFatoorah, Dibsy, Tap Payments, PayTabs, or QPay. Taking real money also requires a registered merchant entity (commercial registration, and for some gateways a QNB account), which a student-led MVP usually cannot hold alone. Plan to either (a) operate under the university/department as the legal merchant, or (b) keep credits admin-granted until a legal entity exists. When you do integrate, the flow is: create a pending transaction -> redirect/checkout -> on the gateway's success webhook, write a positive ledger entry and mark the transaction paid. Build the ledger now so payments slot in later without rework.

### Invoices and receipts

- Generate a simple receipt per grant/top-up and a usage statement per period. Plain records are enough for MVP.

## 11. Session lifecycle (end-to-end flow)

1. User clicks "Launch Workspace" on the dashboard, selects runtime (GPU or CPU) and an environment image.
2. Frontend calls `POST /api/sessions`.
3. FastAPI checks: is the user active, do they have a positive balance, are they under their concurrent-session limit?
   - If insufficient credits: reject with a clear message and a top-up prompt.
4. If GPU requested:
   - Scheduler attempts to lease a free GPU (atomic).
   - If none free: create the session in `queued` state, return queue position; or, if the user opted for CPU fallback, proceed as a CPU session.
5. FastAPI ensures the JupyterHub user exists, then calls the JupyterHub REST API to start that user's single-user server, passing the chosen image and (for GPU) `NVIDIA_VISIBLE_DEVICES=<uuid>`, plus CPU/RAM limits.
6. FastAPI records the session as `starting`, then `running` once JupyterHub reports the server is up. Metering begins at `running`.
7. Frontend redirects the browser to the user server URL (`/user/<name>/lab`). The shared-domain cookie / OAuth identity carries the login through.
8. Metering worker deducts credits each minute. Idle-culler and limit checks run continuously.
9. Session ends when: user clicks "Stop," idle timeout fires, max duration is hit, balance reaches zero, or an admin stops it. FastAPI calls JupyterHub to stop the server, closes the GPU lease, sets the session `stopped`, writes the final debit, and triggers the queue check.
10. If a queued request exists and a GPU just freed, the scheduler starts the next session and notifies that user.

State machine: `requested -> (queued ->) starting -> running -> stopping -> stopped` (plus `failed` for spawn errors, which must release any lease).

## 12. Data model (PostgreSQL schema)

Use a migration tool (Alembic). Suggested core tables (types are indicative):

```sql
-- users and identity
users (
  id              uuid primary key,
  email           text unique not null,
  full_name       text,
  role            text not null default 'student',  -- student|researcher|professor|admin
  status          text not null default 'pending',  -- pending|active|disabled
  password_hash   text not null,
  credit_balance  numeric not null default 0,        -- cached; ledger is source of truth
  created_at      timestamptz not null default now()
);

-- compute resources on this server
gpu_inventory (
  id          uuid primary key,
  gpu_uuid    text unique not null,   -- from nvidia-smi -L
  model       text not null,          -- 'NVIDIA L4'
  vram_mb     integer not null,
  status      text not null default 'free'  -- free|leased|disabled
);

-- available workspace images
images (
  id          uuid primary key,
  name        text not null,          -- 'GPU - PyTorch 2.x (CUDA 12)'
  docker_ref  text not null,          -- registry image reference
  kind        text not null,          -- gpu|cpu
  is_default  boolean default false,
  enabled     boolean default true
);

-- pricing
rates (
  id                 uuid primary key,
  resource_type      text unique not null,   -- l4_gpu|cpu
  credits_per_minute numeric not null
);

-- sessions
sessions (
  id            uuid primary key,
  user_id       uuid references users(id),
  image_id      uuid references images(id),
  resource_type text not null,                -- l4_gpu|cpu
  state         text not null,                -- requested|queued|starting|running|stopping|stopped|failed
  queue_pos     integer,
  started_at    timestamptz,                  -- when running began (metering start)
  ended_at      timestamptz,
  last_metered_at timestamptz,
  created_at    timestamptz not null default now()
);

-- gpu leases (one open lease per leased GPU)
gpu_leases (
  id          uuid primary key,
  session_id  uuid references sessions(id),
  gpu_uuid    text references gpu_inventory(gpu_uuid),
  started_at  timestamptz not null default now(),
  ended_at    timestamptz
);

-- append-only credit ledger (source of truth for balance)
credit_ledger (
  id            uuid primary key,
  user_id       uuid references users(id),
  delta         numeric not null,            -- positive grant, negative debit
  reason        text not null,               -- grant|metering|refund|adjustment
  session_id    uuid references sessions(id),
  balance_after numeric not null,
  created_at    timestamptz not null default now()
);

-- payment transactions (used in payments phase; harmless to create now)
transactions (
  id            uuid primary key,
  user_id       uuid references users(id),
  amount_qar    numeric,
  credits       numeric,
  provider      text,                        -- myfatoorah|dibsy|manual
  provider_ref  text,
  status        text not null default 'pending', -- pending|paid|failed|refunded
  created_at    timestamptz not null default now()
);

-- admin/audit trail
audit_log (
  id          uuid primary key,
  actor_id    uuid references users(id),
  action      text not null,
  target      text,
  detail      jsonb,
  created_at  timestamptz not null default now()
);
```

## 13. Backend API surface

Indicative REST endpoints (all under `/api`, JSON, JWT-authenticated except where noted). Adjust naming to taste but keep the resource boundaries.

Auth and identity

- `POST /auth/signup` (domain-restricted) — create account, send verification.
- `POST /auth/verify` — verify email.
- `POST /auth/login` — returns JWT, sets cookie.
- `POST /auth/logout`.
- `GET /me` — current user, role, balance.

OAuth provider (for JupyterHub) — if using the OAuth path

- `GET /oauth/authorize`, `POST /oauth/token`, `GET /oauth/userinfo` (Authlib).

Sessions

- `POST /sessions` — request a session (body: resource_type, image_id, options). Returns session with state and queue position.
- `GET /sessions` — list my sessions (active and history).
- `GET /sessions/{id}` — session detail and live state.
- `POST /sessions/{id}/stop` — stop my session.
- `GET /sessions/{id}/connect` — returns the workspace URL to redirect to.

Catalog and account

- `GET /images` — available workspace images.
- `GET /rates` — current pricing.
- `GET /credits/ledger` — my ledger entries.
- `GET /usage` — my usage summary by period.

Payments (later)

- `POST /payments/checkout` — start a top-up (returns gateway redirect).
- `POST /payments/webhook` — gateway callback (no JWT; verify signature).

Admin (role=admin)

- `GET /admin/users`, `POST /admin/users`, `PATCH /admin/users/{id}` — manage users and roles.
- `POST /admin/users/{id}/credits` — grant/adjust credits.
- `GET /admin/sessions` — all sessions, live.
- `POST /admin/sessions/{id}/stop` — force-stop any session.
- `GET /admin/gpus` — inventory and current leases.
- `PUT /admin/rates` — set pricing.
- `POST /admin/images` , `PATCH /admin/images/{id}` — manage images.
- `GET /admin/metrics` — utilization summary (can proxy Prometheus).

## 14. Frontend (product shell)

Next.js (App Router, TypeScript), Tailwind, shadcn/ui. Aim for a clean, modern, professional aesthetic comparable to leading developer tools. Keep it uncluttered and fast.

Pages and key components:

- Public landing page: what it is, who it is for (students for hackathons, researchers for experiments, professors for coursework/projects), pricing explainer, login/signup call to action.
- Auth: sign up (domain-restricted), verify, log in.
- Dashboard (authenticated home): credit balance card, active session card (with "Open" and "Stop"), recent usage, "Launch Workspace" button.
- Launch flow: pick runtime (GPU or CPU), pick image, see the credit cost per hour, confirm. If GPUs are busy, show the queue option and the CPU-now option.
- Workspace handoff: on launch, poll session state, then redirect to the in-browser IDE. Provide a persistent header/breadcrumb or an "exit to dashboard" affordance.
- Billing/credits: ledger history, top-up button (admin-grant request now; gateway later).
- Settings/profile: name, password, email.
- Admin console: users and roles, grant credits, live sessions and GPU inventory with force-stop, set rates, manage images, utilization charts.

Design and quality notes:

- Responsive and accessible. No emojis in the product UI.
- Real-time-ish updates for session state and queue position (polling is fine for MVP; WebSocket later).
- Clear empty states and error states (especially "out of credits" and "all GPUs busy").

## 15. Dependency and version strategy (zero-clash mandate)

This is a hard requirement: workspace images must never ship with package or CUDA/driver version conflicts. Build images so that a user can open a fresh GPU notebook and immediately run a model with no setup.

Rules for the builder:

1. Base GPU images on a vendor image that already ships a matched CUDA/cuDNN/framework toolchain (for example an NVIDIA NGC PyTorch image, or PyTorch's official CUDA image). Do not hand-assemble CUDA from scratch.
2. Pin every Python dependency to an exact version and commit a lockfile. Use `uv` or `pip-tools` to produce a fully resolved lock. No unpinned `pip install` lines in the Dockerfile.
3. Keep frameworks in separate images rather than forcing PyTorch, TensorFlow, and JAX into one environment (mixing CUDA-linked frameworks in a single env is the most common source of clashes). Offer, for example, a "PyTorch" image and a "TensorFlow" image as separate catalog entries.
4. Every image must pass an automated smoke test before being marked enabled in the catalog. The smoke test, run in CI or by a setup script, must at minimum:
   - assert the GPU is visible (`torch.cuda.is_available()` is true, and the device name contains "L4");
   - import every advertised top-level library without error;
   - run a tiny GPU tensor op to confirm the CUDA path actually works.
   Fail the build if any check fails.
5. Match the framework's required CUDA against the host driver. The host NVIDIA driver must be new enough for the CUDA version inside the container (the container ships its own CUDA userspace, but the kernel driver on the host must meet the minimum). Document the driver minimum in the setup script and check it.
6. The platform's own services (FastAPI, worker, frontend) also pin dependencies and ship lockfiles. Use a clean, reproducible build for each.

Provide at least two MVP images: one GPU image (CUDA + PyTorch + common data-science and `transformers` stack) and one CPU image (data science, no CUDA). Both include JupyterLab, code-server, and `jupyter-server-proxy`.

## 16. Security model

- Container isolation: spawn user containers unprivileged. Drop unneeded Linux capabilities, set no-new-privileges, apply a sane seccomp profile, set PID limits, and never mount the Docker socket inside a user container.
- Resource limits: per-container CPU and RAM caps and per-user disk quota. Prevents one user from starving the host.
- Network isolation: place user containers on an internal Docker network. They may reach the internet for package installs (optionally via an egress allowlist/proxy), but must not reach the host's other services, the database, the hub's admin port, or other users' containers.
- Identity and authorization: enforce roles on every admin endpoint server-side (never trust the client). Verify the OAuth/JWT on every request. Short-lived tokens, rotated secrets.
- Secrets: keep all secrets in environment files or Docker secrets, never baked into images or committed. Provide `.env.example` with placeholders only.
- Do not re-expose the institution: the platform replaces SSH; it must not become a general tunnel to the host or the university network. Keep the attack surface to the published web app, gated by Cloudflare Access plus platform auth.
- Abuse and acceptable use: terms of use prohibiting mining and non-research workloads; monitor for GPU saturation without interactive activity; admin force-stop.
- Audit: log all admin actions and all credit changes to `audit_log`.
- Data: per-user volumes are private to that user; the shared datasets volume is read-only.

## 17. Monitoring and observability

- NVIDIA DCGM exporter for per-GPU metrics (utilization, memory, temperature, power) into Prometheus.
- node-exporter (host metrics) and cAdvisor (per-container metrics).
- Prometheus scrapes; Grafana dashboards for: GPU utilization per device, active sessions, queue depth, credits burned per hour, per-user usage, host health.
- Alerts (Grafana/Prometheus): GPU stuck at 100% with no session activity, GPU temperature/power thresholds, disk filling, a session exceeding its time limit, metering worker not ticking.
- Use DCGM GPU-busy data to audit the credit metering for honesty.

## 18. Deployment topology and prerequisites

### Single-host MVP via Docker Compose

All platform services run as containers via Docker Compose on the GPU server. The per-user JupyterLab/code-server containers are launched by JupyterHub/DockerSpawner as siblings on the same host Docker. Compose services:

- `postgres`, `redis`
- `backend` (FastAPI), `worker` (metering/scheduler)
- `frontend` (Next.js)
- `jupyterhub`
- `traefik`
- `cloudflared`
- `prometheus`, `grafana`, `dcgm-exporter`, `node-exporter`, `cadvisor`

### Host prerequisites (the setup script must verify or install)

1. Ubuntu (current LTS).
2. NVIDIA driver new enough for the chosen container CUDA version (verify with `nvidia-smi`; document the minimum).
3. Docker Engine and Docker Compose.
4. NVIDIA Container Toolkit configured so containers can use the GPU (verify with a `docker run --gpus all <cuda-image> nvidia-smi` that succeeds and lists both L4s).
5. Sufficient disk for images and per-user volumes; a data partition for user volumes and the shared datasets volume.

Critical access requirement: installing the driver, the NVIDIA Container Toolkit, and Docker, and running containers with `--gpus`, requires root/sudo on the GPU server. Confirm this is available (see open questions). If only an unprivileged account is available, the platform cannot be installed as specified and IT must either grant sudo or pre-install Docker plus the NVIDIA Container Toolkit and add the account to the `docker` group.

### Why not Kubernetes for MVP

For one host with two GPUs, Docker Compose plus JupyterHub is dramatically simpler and fully sufficient. Kubernetes (k3s) is the right tool when expanding to multiple servers or universities; treat it as a Phase-6 migration, not an MVP requirement.

## 19. Repository structure

Monorepo:

```
sahab/
  backend/            FastAPI app, models, migrations, OAuth provider, worker
    app/
    migrations/
    pyproject.toml
    requirements.lock
  frontend/           Next.js app
    app/
    components/
    package.json
  jupyterhub/
    jupyterhub_config.py
    Dockerfile
  images/
    gpu-pytorch/
      Dockerfile
      requirements.lock
      smoke_test.py
    cpu-base/
      Dockerfile
      requirements.lock
      smoke_test.py
  infra/
    docker-compose.yml
    traefik/
    cloudflared/
    prometheus/
    grafana/
  scripts/
    preflight.sh        verify driver, docker, nvidia toolkit, GPUs
    discover_gpus.sh     populate gpu_inventory
    build_images.sh      build and smoke-test workspace images
  docs/
  .env.example
  README.md
```

## 20. Configuration and environment variables

Provide `.env.example` with placeholders. Indicative variables:

```
# Domain and exposure
PUBLIC_HOSTNAME=sahab.example.com
CLOUDFLARE_TUNNEL_TOKEN=

# Database / cache
POSTGRES_USER=
POSTGRES_PASSWORD=
POSTGRES_DB=sahab
DATABASE_URL=postgresql://...
REDIS_URL=redis://redis:6379/0

# Auth
JWT_SECRET=
ALLOWED_SIGNUP_DOMAINS=udst.edu.qa
OAUTH_CLIENT_ID=jupyterhub
OAUTH_CLIENT_SECRET=

# JupyterHub integration
JUPYTERHUB_API_URL=http://jupyterhub:8081/hub/api
JUPYTERHUB_API_TOKEN=

# Policy defaults
GPU_SESSION_MAX_MINUTES=240
IDLE_TIMEOUT_MINUTES=45
DEFAULT_USER_DISK_QUOTA_GB=50
CREDITS_PER_MINUTE_L4=1.0
CREDITS_PER_MINUTE_CPU=0.0

# Workspace
SHARED_DATASETS_PATH=/data/shared
USER_VOLUMES_PATH=/data/users
```

## 21. Build phases and milestones

Build in this order. Each phase is independently demoable.

Phase 0 — Preflight and decisions
- Confirm root access and exposure strategy (A or B). Run `preflight.sh`: driver, Docker, NVIDIA Container Toolkit, and a `--gpus all nvidia-smi` that lists both L4s.

Phase 1 — Workspace core (highest value, ship first)
- JupyterHub + DockerSpawner + NVIDIA runtime. One GPU image (JupyterLab + code-server + jupyter-server-proxy, pinned stack). Per-user volumes, idle-culler, CPU/RAM limits, whole-GPU pinning via `NVIDIA_VISIBLE_DEVICES`. Manually create a couple of users.
- Done when: a user logs into JupyterHub, gets a GPU notebook, sees exactly one L4, and can open VS Code in the browser. This already beats the SSH flow.

Phase 2 — Control plane
- PostgreSQL + Redis. FastAPI: users/roles, credit ledger, rates, GPU inventory + leasing, session lifecycle driving JupyterHub's REST API, queue, metering/scheduler worker. SSO between FastAPI and JupyterHub (OAuth provider, or the one-time-token fallback).
- Done when: starting/stopping sessions and credit deduction all flow through FastAPI; out-of-credits and all-GPUs-busy behave correctly; balances survive restart.

Phase 3 — Product UI
- Next.js: landing, auth, dashboard, launch flow, billing view, admin console. Polished, responsive, professional.
- Done when: the entire happy path is click-only in the browser, including admin credit grants and force-stop.

Phase 4 — Exposure and monitoring
- cloudflared tunnel (Strategy A) plus optional Cloudflare Access. Prometheus + Grafana + DCGM + node-exporter + cAdvisor. Security hardening pass.
- Done when: reachable on a public hostname with no inbound ports opened, with dashboards and alerts live.

Phase 5 — Payments (deferred until a legal merchant exists)
- Integrate a QCB-licensed gateway (MyFatoorah / Dibsy / Tap / PayTabs / QPay): checkout, success webhook -> ledger grant, receipts. Until then, admin-granted credits.

Phase 6 — Polish and scale prep
- Collaborative editing, more images, usage analytics, and a k3s migration path for multi-server / multi-university.

## 22. Testing and acceptance criteria

- Image smoke tests (mandatory gate): CUDA visible, all libraries import, tiny GPU op succeeds. An image cannot be enabled in the catalog without passing.
- Concurrency: two simultaneous GPU sessions each pin a distinct L4; a third GPU request queues or falls back to CPU and is auto-promoted when a GPU frees. No double-allocation under race (test by hammering `POST /sessions`).
- Metering accuracy: hold a GPU for a known duration; verify debited credits match within one minute; verify auto-stop at zero balance.
- Persistence: restart the whole stack; user files and credit balances are intact.
- Security: user container cannot reach the database, the hub admin port, or another user's container; no Docker socket inside user containers; quotas and resource limits enforced.
- Idle and time limits: idle session is culled; a session over the max duration is stopped.
- Auth: only allowed-domain emails can sign up; admin endpoints reject non-admins.

## 23. Known risks, assumptions, and open questions

Assumptions baked into this blueprint (correct them if wrong):

- The builder has, or can obtain, root/sudo on the GPU server (required for driver, NVIDIA Container Toolkit, Docker, and `--gpus`).
- The server has outbound internet (for package installs and, in Strategy A, for the Cloudflare tunnel).
- MVP uses admin-granted credits; real payment processing is deferred until a legal merchant entity exists.
- Only the two L4 GPUs are in scope; whole-GPU allocation is acceptable (no fractional sharing).
- Email/password with domain restriction is acceptable for MVP auth; institutional SSO comes later.

Open questions to confirm before/at build time (see chat):

1. Do you (or the project) have root/sudo on the GPU server, or is Docker plus the NVIDIA Container Toolkit already installed with your account in the `docker` group?
2. Exposure: can the server make outbound connections to the internet for a Cloudflare tunnel, and is there a domain you can put on Cloudflare? If not, we ship Strategy B (university-network-only) first.
3. Auth: build email/password for MVP, or do you already have access to integrate the university IdP (SAML/Azure AD/Okta/LDAP)?
4. The GPU server currently has multiple users and presumably runs other work. Is it acceptable to install Docker and dedicate (or schedule) both GPUs to this platform, or must the platform coexist with existing non-Docker GPU usage on the same box?
5. Expected concurrent demand at launch: is two GPU slots plus a CPU fallback and a queue enough for the initial pilot cohort, or do you expect frequent contention from day one?

## 24. Future roadmap (multi-university)

- Move from Docker Compose to k3s/Kubernetes with the NVIDIA GPU Operator for multi-node scheduling.
- Per-institution tenancy: isolate users, images, billing, and GPU pools per university; one control plane, many compute clusters.
- Institution-level SSO federation.
- Richer scheduling: reservations, priority tiers, spot-style preemption, and (only on MIG-capable hardware such as A100/H100, if acquired) true fractional GPUs.
- Marketplace of curated, versioned images contributed by departments.
- Real billing with local gateways, invoicing, and department cost-center reconciliation.

## 25. Appendix A: key config snippets

These are illustrative starting points, not final code. The builder should expand, pin versions, and harden.

JupyterHub: DockerSpawner with one GPU pinned per user, idle culling, per-user volume, resource limits. Real implementation should pin the leased GPU UUID per session (set by the control plane at spawn time, for example via the spawn options or a pre-spawn hook) rather than exposing all GPUs.

```python
# jupyterhub_config.py (essentials)
import os

c.JupyterHub.spawner_class = "dockerspawner.DockerSpawner"
c.DockerSpawner.image = os.environ["WORKSPACE_GPU_IMAGE"]
c.DockerSpawner.network_name = os.environ["DOCKER_NETWORK_NAME"]

# Give the container access to the NVIDIA runtime. The specific GPU UUID
# should be injected per session by the control plane (whole-GPU allocation).
c.DockerSpawner.extra_host_config = {
    "runtime": "nvidia",
}
# NVIDIA_VISIBLE_DEVICES is set per-user/per-session to the leased GPU UUID,
# e.g. via c.Spawner.environment or a pre_spawn_hook that reads the lease.

# Per-user persistent storage and shared read-only datasets
notebook_dir = "/home/jovyan/work"
c.DockerSpawner.notebook_dir = notebook_dir
c.DockerSpawner.volumes = {
    "sahab-user-{username}": notebook_dir,
    os.environ["SHARED_DATASETS_PATH"]: {"bind": "/home/jovyan/shared", "mode": "ro"},
}

# Resource limits (per container)
c.DockerSpawner.mem_limit = "32G"
c.DockerSpawner.cpu_limit = 8.0

# Stop idle servers (saves GPU and credits). Run jupyterhub-idle-culler as a service.
c.JupyterHub.services = [
    {
        "name": "idle-culler",
        "command": [
            "python", "-m", "jupyterhub_idle_culler",
            "--timeout=2700",  # 45 minutes
        ],
    },
]

# Authentication: GenericOAuthenticator pointing at the FastAPI OAuth provider
# (preferred), or a custom token-validating Authenticator (fallback).
```

Workspace GPU image: vendor CUDA base, JupyterLab, code-server, server-proxy, pinned stack, smoke test.

```dockerfile
# images/gpu-pytorch/Dockerfile (illustrative; pin exact versions in the lock)
FROM <ngc-or-official-pytorch-cuda-base>:<pinned-tag>

# JupyterLab + server proxy + a code-server proxy plugin + git extension
# code-server (VS Code in the browser) installed and proxied via jupyter-server-proxy
# Install from requirements.lock only (no unpinned installs)
COPY requirements.lock /tmp/requirements.lock
RUN pip install --no-cache-dir -r /tmp/requirements.lock

# Smoke test at build time; fail the build if GPU/imports break
COPY smoke_test.py /tmp/smoke_test.py
# (run smoke_test.py in CI on a GPU runner; at minimum import-check at build)

EXPOSE 8888
```

Smoke test contract:

```python
# images/gpu-pytorch/smoke_test.py (must exit non-zero on any failure)
import torch
assert torch.cuda.is_available(), "CUDA not available"
name = torch.cuda.get_device_name(0)
assert "L4" in name, f"unexpected GPU: {name}"
# import every advertised library here ...
x = torch.randn(1024, 1024, device="cuda")
assert (x @ x).is_cuda
print("OK", name)
```

GPU discovery (populate inventory):

```bash
# scripts/discover_gpus.sh
nvidia-smi --query-gpu=uuid,name,memory.total --format=csv,noheader
```

Cloudflare tunnel (compose service, token-based):

```yaml
# infra: cloudflared service
cloudflared:
  image: cloudflare/cloudflared:latest
  command: tunnel --no-autoupdate run --token ${CLOUDFLARE_TUNNEL_TOKEN}
  restart: unless-stopped
  depends_on:
    - traefik
```

## 26. Appendix B: glossary

- L4: NVIDIA data-center GPU (Ada Lovelace, 24 GB). Does not support MIG.
- MIG (Multi-Instance GPU): hardware partitioning of one GPU into isolated sub-GPUs; only on A100/A30/H100/Hopper/Blackwell-class hardware.
- Whole-GPU allocation: one physical GPU assigned to exactly one session at a time.
- JupyterHub: multi-user server that spawns a per-user notebook server.
- DockerSpawner: JupyterHub spawner that runs each user's server in a Docker container.
- code-server: open-source build of VS Code that runs in the browser.
- jupyter-server-proxy: lets a Jupyter server proxy other local web apps (such as code-server) behind authenticated paths.
- Cloudflare Tunnel (cloudflared): outbound-only connector that publishes a local service to a public hostname without opening inbound ports.
- DCGM exporter: NVIDIA tool that exposes GPU metrics to Prometheus.
- Compute credit: the platform's internal billing unit; one credit defined as one GPU-minute on an L4 (configurable).

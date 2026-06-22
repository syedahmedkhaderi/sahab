# Sahab Frontend

Next.js 14 (App Router) product shell for the Sahab university GPU compute platform.

## Stack

- **Next.js 14** — App Router, TypeScript, standalone output
- **Tailwind CSS** — utility-first styling with CSS variable theming
- **shadcn/ui-style primitives** — hand-built Button, Card, Input, Badge, Dialog, Table, Select, Alert, Label (no shadcn CLI dependency)
- **lucide-react** — icons
- **zod** — available for form validation
- **clsx + tailwind-merge** — class composition

## Development

```bash
cp .env.local.example .env.local
# Edit BACKEND_URL to point at your running FastAPI instance
npm install
npm run dev
```

The dev server runs on http://localhost:3000. API requests to `/api/*` are proxied to `BACKEND_URL` (default `http://localhost:8000`) via `next.config.js` rewrites.

## Production build

```bash
npm run build
npm start
```

## Docker

```bash
docker build -t sahab-frontend .
docker run -p 3000:3000 \
  -e NEXT_PUBLIC_API_BASE=/api \
  -e NEXT_PUBLIC_SITE_NAME=Sahab \
  sahab-frontend
```

The Dockerfile uses a multi-stage build (`deps -> builder -> runner`) and the Next.js `standalone` output for a minimal runtime image.

## Environment variables

| Variable | Default | Description |
|---|---|---|
| `NEXT_PUBLIC_API_BASE` | `/api` | Base URL for API calls from the browser |
| `NEXT_PUBLIC_SITE_NAME` | `Sahab` | Display name in the nav and page titles |
| `NEXT_PUBLIC_ALLOWED_DOMAIN` | `udst.edu.qa` | University domain shown on the signup page |
| `BACKEND_URL` | `http://localhost:8000` | Backend origin for dev-server rewrites |

## Pages

| Route | Description |
|---|---|
| `/` | Public landing page |
| `/login` | Sign-in form |
| `/signup` | Registration (domain-restricted) |
| `/verify` | Email verification (token from query string) |
| `/dashboard` | Credit balance, active session, recent history |
| `/launch` | Launch workspace — pick runtime + image |
| `/billing` | Ledger history, top-up request |
| `/settings` | Name and password |
| `/admin` | Admin console (role-guarded) |
| `/sessions/[id]/connect` | Polls session state then redirects to workspace |

## Key files

```
frontend/
  app/                    Next.js App Router pages
    (authed)/             Route group — shares Nav layout, client-side auth guard
      dashboard/
      launch/
      billing/
      settings/
      admin/
    sessions/[id]/connect/  Workspace handoff (poll + redirect)
    login/ signup/ verify/  Public auth pages
    layout.tsx              Root HTML shell
    page.tsx                Public landing page
    globals.css             Tailwind base + CSS variables
  components/
    ui/                   Primitive components (Button, Card, Input, ...)
    Nav.tsx               Top navigation bar
    BalanceCard.tsx        Credit balance display
    SessionCard.tsx        Active session with Open/Stop actions
    LaunchForm.tsx         Full launch flow with GPU/CPU picker
    LedgerTable.tsx        Transaction history table
    GpuInventoryTable.tsx  GPU status table
    SessionStateBadge.tsx  Coloured state badge
  lib/
    api.ts                Typed fetch client for all backend endpoints
    types.ts              TypeScript types mirroring the DB schema
    utils.ts              Formatting helpers
  middleware.ts           Cookie-presence redirect guard
  next.config.js          Standalone output + /api rewrite
  tailwind.config.ts
  Dockerfile              Multi-stage build
```

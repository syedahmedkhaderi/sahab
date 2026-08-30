# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

Students, researchers and faculty at the University of Doha for Science and
Technology (UDST). They are domain people first — an engineering student
training a model for a course project, a researcher running an experiment —
not infrastructure engineers. Most reach Sahab from a personal laptop on
campus or at home, needing a GPU for an afternoon, not a cluster account for a
year. They have low tolerance for setup friction and no appetite for SSH keys,
CUDA installs or queue schedulers.

A much smaller second audience is the platform administrator (currently one
person), who approves accounts, grants credits, sets rates and watches
utilisation. They use the same product, in a different room, with real
operational stakes.

## Product Purpose

Sahab turns a pair of NVIDIA L4 GPUs in a university server into
self-service, browser-based JupyterLab workspaces. A student signs in with
their UDST email, asks for a GPU workspace, and gets a running notebook with
CUDA available — no VPN, no terminal, no ticket to IT.

Success is that a student who has never provisioned a machine gets to working
code quickly, and that the administrator can see where the GPU hours and
credits went without reading logs.

## Positioning

The scheduler assigns GPUs; users never pick one. That is the mechanism worth
protecting. It lets Sahab honour work it did not start — a researcher's job
running directly on the host — because it cross-checks live per-GPU
utilisation before leasing, rather than trusting its own database. A
neighbouring "spin up a notebook" product that owns its whole machine cannot
truthfully make that claim.

Credits, not hours, are the unit of fairness: usage is metered per minute
against a balance an administrator grants, so a course can be allocated
compute without anyone rationing by hand.

## Operating Context

- Two NVIDIA L4 GPUs (23 GB each) in one university-run host, shared with
  research work that runs outside the platform.
- Reached over a public HTTPS URL fronted by a Cloudflare tunnel; on the quick
  tunnel the hostname rotates whenever the tunnel restarts.
- Sign-up is restricted to `udst.edu.qa` addresses and gated by administrator
  approval, so a new account is pending before it is active.
- One concurrent session per user by default; sessions idle-cull after 45
  minutes and are capped at 240 minutes.
- When no GPU is free a user is queued, or can take a CPU workspace instead.
- The workspace itself is JupyterLab, reached by an OAuth handoff from Sahab
  to JupyterHub.

## Capabilities and Constraints

Confirmed today: email sign-up and admin approval; a launch flow that picks
between a GPU and a CPU workspace and a container image; a session list with
live state; connect-to-workspace; a credit balance and per-transaction ledger;
an admin console covering users, sessions, GPU inventory, rates and images;
Prometheus and Grafana behind the scenes.

Terminology used throughout and worth keeping consistent: **workspace** (the
running JupyterLab container), **session** (the platform's record of one), and
**credits** (the metered unit, charged per minute).

Constraints: there is no top-up or payment flow — credits are granted by an
administrator, and the UI must not imply otherwise. There is no email
delivery, so approval is a manual administrative act. Session state is
polled, not pushed.

## Brand Commitments

The product is named **Sahab** (سحاب, "clouds") and presents as its own
product wearing the university's colours, not as an official UDST system: the
header reads Sahab, with the university named in a supporting line. No UDST
logo or wordmark asset exists in the repository and none may be fabricated.

Binding visual constraint carried over from the brief: the UDST palette —
`#0055B8` primary with warm (not cool) neutrals — extracted from the
university's live theme CSS.

Voice: plain, concrete and specific to this university and this hardware. It
must not read as generated marketing copy. Explicitly named anti-patterns to
avoid: negation tricolons ("No VPN. No SSH. No setup."), three-word abstract
feature titles, emoji headings, hedging qualifiers, and contraction-stripped
stiffness ("Do not have an account?").

## Evidence on Hand

Real: the hardware (two L4s, named and specified), the metered rates, the
credit ledger, the actual session history in the database, and live GPU
utilisation from a DCGM exporter.

Absent, and not to be invented: testimonials, user counts, named courses or
research groups, uptime or benchmark figures, partner or funding claims,
pricing in any currency, and any logo.

## Product Principles

1. **The scheduler decides, and says why.** Users never choose a GPU. When
   none is available the product explains which situation it is — queue,
   externally busy, or out of credits — in words, and offers the CPU path.
2. **Never claim something happened that did not.** No success confirmations
   for actions that send nothing; no invented numbers; no error text that
   hides the real state.
3. **Operate before persuade.** This is a tool people use weekly, not a
   campaign. Scanability, consistent state language and honest data outrank
   expression; the brand lives in precise details.
4. **Name the real thing.** "NVIDIA L4", "JupyterLab", "credits per minute" —
   concrete nouns beat abstractions, for students and administrators alike.
5. **The failure paths are the product.** A queued session, a busy GPU, a
   failed launch and an empty ledger are the states most likely to appear in
   front of someone judging this, and get designed, not defaulted.

## Accessibility & Inclusion

Dark mode is declared in the codebase but has never worked, and is expected to
work. Numeric data (credits, balances, GPU UUIDs, durations) must use tabular
figures so columns align. Interface text is English; the audience is
multilingual, so plain vocabulary and full sentences matter more than idiom.

# Design

Recorded from the built interface, not from intention. Everything below is in
the code today.

## Visual world

Sahab looks like university infrastructure: a warm grey canvas, white panels,
hairline borders, and one saturated blue used only where something is
actionable or selected. It refuses the centred marketing hero, the grid of
same-size icon cards, and the eyebrow label above a heading — the shapes that
made the previous scaffold read as generic.

The greys are warm (a little yellow in every one). That is the single most
recognisable trait: set the same layout in the cool slate Tailwind ships by
default and it stops looking like this product.

**Colour strategy: Restrained.** Neutrals plus one accent. The blue carries
primary actions, the current selection, and focus. It is never decoration.

## Tokens

All colour lives in CSS custom properties in `frontend/app/globals.css` and is
surfaced through `tailwind.config.ts`. A literal Tailwind colour in a component
(`bg-green-100`, `text-violet-700`) is outside the system — that is what broke
dark mode before, and there are none left.

| Token | Light | Role |
|---|---|---|
| `--primary` | `#0055B8` | UDST royal blue. Actions, selection, focus. |
| `--primary-hover` | `#00459A` | The deliberate darker step, not `primary/90`. |
| `--background` | `#F7F7F6` | Warm canvas. |
| `--card` | `#FFFFFF` | Panels sitting on the canvas. |
| `--border` | `#D9D8D6` | Warm hairline. Structure comes from these, not shadows. |
| `--border-strong` | — | Dashed empty states, outline buttons, scrollbar thumb. |
| `--foreground` | `#343434` | Body text. |
| `--muted-foreground` | `#767676` | Secondary text. |
| `--success` | `#17795E` | |
| `--warning` | `#B26B00` | |
| `--destructive` | `#B42318` | |
| `--info` | `#0055B8` | |

Every semantic colour has three companions: `DEFAULT` (the solid), `subtle`
(the tinted ground a badge or alert sits on) and `strong` (the darkened text
that stays legible on `subtle`). Use the pair, never `success` text on a
`success` background.

**Dark** redefines the same variables in `.dark`. It is a warm-neutral dark, so
the greys stay related to the light theme's rather than turning blue, and
`--primary` lifts to a much lighter blue — `#0055B8` on a dark ground fails
contrast badly.

**Radius** is `0.375rem`, down from the shadcn default of `0.5rem`.
Institutional, not consumer-soft.

## Type

One family throughout: **Inter** for everything, **JetBrains Mono** for every
measured number — credits, durations, GPU UUIDs, rates, hardware names. Both
are loaded through `next/font` in the root layout, self-hosted at build time.
Mono is for data and measurement, never as a costume for "technical".

The scale is fixed rem, not fluid, at a ratio near 1.15 — this is product UI
viewed at a consistent DPI, and a heading that shrinks inside a panel looks
worse. `base` is `0.9375rem`.

Tabular figures are on for every `th`/`td` and anything marked
`.tabular-figures`, so a balance that ticks does not reflow.

## Layout

Three container widths and no others:

- `max-w-content` (72rem) — the app shell and every full-width page.
- `max-w-prose` (42rem) — reading and single-column forms (launch, settings).
- `max-w-form` (26rem) — the signed-out pages.

Wide tables scroll inside their own panel (`TablePanel`, or an
`overflow-x-auto` wrapper), never the page body. Verified: no page scrolls
horizontally at 375, 768 or 1440.

## Components

`frontend/components/ui/` is the vocabulary. The primitives that exist because
pages kept re-inventing them:

- `PageHeader` — title, description, actions. Every page used to write its own `<h1>`.
- `Tabs` / `TabPanel` — a real tablist with arrow-key navigation. The admin console hand-rolled a pill bar out of buttons.
- `Spinner` — one spinner. `<Loader2 className="animate-spin">` was inlined five times at four sizes.
- `EmptyState` — teaches the interface and carries the action that ends the emptiness.
- `Skeleton` — holds the page's shape while data loads, instead of a spinner in an empty container.
- `ToastProvider` / `useToast` — there was no toast system at all, so an action finishing anywhere but inside a form reported nothing. Errors persist until dismissed; everything else clears after six seconds.
- `Wordmark`, `SiteHeader`, `AuthShell` — the shells that were duplicated between the landing page, Nav, and the three signed-out pages.

`Button` carries `loading` (spinner, disabled, `aria-busy`) and a working
`asChild` — the prop was previously declared and ignored, which leaked it to
the DOM.

## Motion

150ms on state transitions; users are in a task. The only authored motion is
the skeleton sweep and a fade on tab-panel change. A `prefers-reduced-motion`
block reduces all of it to nothing.

## Browser surfaces

Selection, caret, `accent-color`, focus ring, scrollbar and underline offset
are all themed from the palette in `globals.css`. Left at browser defaults they
belong to no design system.

## Voice

Plain, concrete, specific to this university and this hardware. Named
anti-patterns, all removed and not to be reintroduced: negation tricolons ("No
VPN. No SSH. No setup."), three-word abstract feature titles, emoji headings,
hedges ("may vary"), and contraction-stripped stiffness ("Do not have an
account?").

Two rules that are about honesty rather than style, and outrank it:

1. **A control never claims something happened that did not.** The billing
   page's "Request top-up" showed a success alert and sent nothing; the signup
   screen said a verification email had been sent when no email is ever sent.
   Both now say what actually happens.
2. **An error names the problem and the recovery.** Raw exceptions stay in the
   log. "No GPU is free right now — another job is using them. Start a CPU
   workspace, or queue for the next free GPU." — and both of those offers do
   something.

State language is one vocabulary everywhere, in `SessionStateBadge`: Running,
Starting, Queued, Stopping, Stopped, Failed, each with a coloured dot so the
meaning survives without colour.

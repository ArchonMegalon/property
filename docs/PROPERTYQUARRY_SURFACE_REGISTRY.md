# PropertyQuarry Surface Registry

This file defines "all surfaces" for product polish, SEO/content optimization, screenshots, accessibility checks, link audits, performance work, and failure-state reviews.

## Definition

A PropertyQuarry surface is any user-visible, shareable, generated, delivered, or operator-facing interface that can affect trust in the property decision loop.

That includes:

- a rendered browser page
- an authenticated app panel
- a route alias or redirect that users can click
- an empty, loading, degraded, repairing, failed, or completed-partial state
- a generated PDF, tour, video, packet, email, Telegram message, or WhatsApp message
- a public share manifest and its assets
- a management screen that changes provider, fleet, account, billing, or repair behavior

## Surface Groups

### Public Acquisition

Routes and pages used before an app session:

- `/`
- `/?home=1`
- `/pricing`
- `/security`
- `/privacy`
- `/terms`
- `/imprint`
- `/cookies`
- `/subprocessors`
- `/support`
- `/docs`
- `/integrations`
- `/guides`
- `/markets`
- `/blog`
- `/compare`

Rules:

- ClickRank can run here when configured.
- NeuronWriter can be used for public-safe copy and topic optimization.
- These pages must be fast, indexable where intended, and free of private run data.

### Auth And Handoff

Routes that create or resume access:

- `/register`
- `/get-started`
- `/sign-in`
- `/workspace-link`
- `/google/connected`
- `/app/api/property/landing-handoff`

Rules:

- Do not show sign-in buttons while an active sign-in handoff is in progress.
- Logged-in users can be sent directly to `/app/search`, but `/?home=1` must remain a deliberate escape to the public home.
- No SEO optimizer should receive private auth/session context.

### Authenticated App

Core customer product screens:

- `/app`
- `/app/properties`
- `/app/search`
- `/app/shortlist`
- `/app/agents`
- `/app/account`
- `/app/account#profile`
- `/app/account#delivery`
- `/app/account#plans`
- `/app/profile`
- `/app/alerts`
- `/app/billing`

Rules:

- ClickRank is not allowed.
- NeuronWriter is not allowed to receive private app payloads unless a redacted public-safe extraction path explicitly says so.
- Every visible control that looks clickable must either navigate, submit, open a panel, toggle state, or be visibly disabled.

### Results And Research

Screens that explain candidate quality:

- ranked shortlist
- filtered breakdown
- property research detail
- selected review panel
- legacy object-detail compatibility

Rules:

- Maybe-false candidates do not belong in ranked homes.
- Hard rules such as selected area and transaction mode remain hard filters.
- Soft preferences affect score and explanation, not eligibility.
- A filtered count must open a breakdown or be plain text.

### Shared Public Artifacts

External review links and redacted shares:

- `/results/:slug`
- `/p/:slug`
- `/app/properties/packets`
- `/tours/:slug`
- `/tours/:slug/tour.json`
- `/tours/:slug/assets/:asset`

Rules:

- Public artifacts use narrow positive manifests, not broad private payloads plus best-effort redaction.
- Private source URLs, exact addresses, principal ids, packet ids, and listing receipts must stay out of public manifests.
- ClickRank is not allowed on generated/public-result artifacts unless a route is deliberately added to the public SEO allowlist.

### Generated Artifacts

Outputs users can inspect, download, or share:

- premium dossier HTML/PDF
- PDF appendix
- floorplan assets
- Matterport/3DVista/local tour receipts
- generated walkthrough receipts
- Dadan video request and status

Rules:

- Heavy media generation starts only from explicit user action.
- Video and 3D progress states must show whether work is queued, running, failed, repairable, or complete.
- Generated tours and videos must identify generated/illustrative content where applicable.

### Delivery

Outbound user-facing messages:

- email alerts and digests
- Telegram review messages
- WhatsApp alerts and templates
- delivery preferences and receipts

Rules:

- Delivery copy must not expose operator/fleet internals.
- NeuronWriter can only be used through redacted public-safe drafts.
- Every delivered candidate must satisfy hard area/mode/provider rules before sending.

### Management

Surfaces that configure or repair the product:

- provider catalog
- source readiness
- fleet repair and fetch-fail recovery
- run reliability
- admin audit trail
- LTD runtime catalog

Rules:

- Customer screens may show outcome-oriented repair status.
- Operator screens may show provider/fleet diagnostics.
- Management controls must be hidden or disabled when they are not implemented.

### System States

States that must be audited for every applicable surface:

- loading
- empty
- no results
- partially complete
- degraded
- repairing
- failed
- missing packet
- unavailable media
- permission denied
- unauthenticated redirect
- offline or timeout

Rules:

- Error states must lead to a next action or durable repair receipt.
- Loading states must not start at arbitrary progress such as 12 percent unless backed by actual completed work.
- Empty states should explain hard filters separately from soft preferences.

## Optimization Lanes

### NeuronWriter

Allowed:

- public home, pricing, trust pages, docs, guides, markets, blog, compare
- public-safe research summaries
- redacted public packet copy
- redacted dossier and delivery drafts

Blocked:

- raw authenticated app payloads
- private briefs
- source URLs
- exact addresses
- user notes
- packet internals
- run repair/fleet diagnostics

### ClickRank

Allowed:

- public SEO routes only

Blocked:

- `/app/*`
- `/api/*`
- `/v1/*`
- `/auth/*`
- `/admin/*`
- `/results/*`
- `/tours/*`
- private/generated artifacts unless explicitly promoted into the public SEO allowlist

## Audit Axes

Every surface should be reviewed against:

- navigation
- copy
- layout density
- responsive layout
- loading state
- empty state
- error state
- clickability
- accessibility
- performance
- privacy
- analytics

The executable registry lives in `ea/app/product/property_surface_registry.py`.

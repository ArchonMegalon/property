# PropertyQuarry flagship truth plane

## Purpose

The PropertyQuarry repository needs its own release truth so flagship claims do not depend on the inherited all-released `MILESTONE.json` plus checklist completion alone. The standalone proof target is PropertyQuarry; it does not reuse the intentionally skipped legacy Executive Assistant office-loop tests.

This plane is PropertyQuarry-owned release evidence. The inherited EA product canon in `.codex-design/ea/*` is a bounded design input, not the owner of this product or its release claim.
It sits below `IMPLEMENTATION_SCOPE.md` and above the release checklists.

`EA_FLAGSHIP_TRUTH_PLANE.md` is the human-readable form of this plane and retains its historical filename for compatibility.
`EA_FLAGSHIP_RELEASE_GATE.json` is the machine-readable seed that release verification consumes and likewise retains its historical filename.

## Evidence levels and claim boundary

This plane governs a source-and-browser checkpoint. It does not, by itself,
establish global launch readiness or production operation. Evidence has four
non-interchangeable levels:

1. source contract
2. exact-candidate proof
3. production-like proof
4. protected live proof

A lower level cannot be relabelled as a higher one. The terminal outcome and its
measurable acceptance criteria are defined in
`docs/PROPERTYQUARRY_GLOBAL_FLAGSHIP_GOAL.md`. The machine-readable
`global_launch_contract` in `EA_FLAGSHIP_RELEASE_GATE.json` binds that outcome to
the launch-tier Gold command and to a separate governed market-envelope receipt.

"Global" means global-grade operation within an explicit supported-market and
locale envelope. It is not a claim that every country, language, currency,
provider, or legal regime is supported. Catalog, preview, private-beta, and
browser-state-only evidence cannot make a market launch-supported.

## What counts as source-and-browser truth

A flagship claim for the current standalone PropertyQuarry surface must be supported by:

1. the PropertyQuarry implementation scope plus the bounded navigation, journey, copy, and LTD standards inherited from `.codex-design/ea/START_HERE.md`
2. the browser workflow proof that exercises seeded product objects and real workspace actions
3. the machine-readable gate seed in `EA_FLAGSHIP_RELEASE_GATE.json`
4. release asset verification that knows how to validate the gate seed
5. release checklists that point at this plane instead of treating `MILESTONE.json` as the oracle

## What does not count as truth

- `MILESTONE.json` alone
- checklist completion alone
- polished shell copy without browser proof
- endpoint inventory without real workspace behavior

## Evidence base

Use the standalone PropertyQuarry browser proof as the release evidence base:

- `tests/test_propertyquarry_workspace_redesign.py`
- `tests/e2e/test_propertyquarry_greenfield_browser.py`

Those tests prove the PropertyQuarry workspace renders seeded search and research state, opens ranked candidate packets in a real browser, and remains usable on desktop and mobile. The legacy assistant browser files are intentionally skipped in standalone PropertyQuarry mode and therefore do not count as release proof.

## Source-and-browser claim rule

The standalone PropertyQuarry source/browser checkpoint is green only when the
workspace behaves like the property decision system described by the current
proof target and the browser proof, gate seed, and release verification agree.

If those three disagree, the checkpoint is blocked. If they agree, the result is
still not global launch authority.

## Global terminal rule

Global Core Gold requires all of the following on one exact committed SHA and
immutable image:

- the governed market envelope passes and only calls full end-to-end markets
  launch-supported;
- the global-experience gate passes from fresh independently attested native
  review, WCAG 2.2 AA automated/manual, contracted browser/device, field-CWV,
  degraded-network, and localized-SEO evidence for the exact release;
- the jurisdiction/privacy/provider-rights gate passes from current independent
  local legal approval, privacy/residency controls, an exact provider/capability
  inventory, technical enforcement, and current contract/market-envelope
  digests for the exact release;
- Chromium, Firefox, and WebKit candidate evidence plus manual assistive-
  technology review supports WCAG 2.2 Level AA;
- the complete customer loop, field/lab performance, privacy, security,
  reliability, capacity, recovery, incident, and support controls pass;
- optional paid Advanced Visual providers remain additive and cannot block Core;
- protected live evidence binds deployment, monitoring, customer journeys, and
  rollback readiness to the exact release identity; and
- `/usr/libexec/propertyquarry/propertyquarry-global-launch-terminal --manifest
  /run/propertyquarry/release-evidence/global-launch-core-manifest.v1.json`
  passes. The closed manifest pins the exact SHA/image, product-data
  origins/hashes, every Core receipt including all four global-governance
  receipts, all six raw observability inputs, and exact-release
  preflight/disaster-recovery/capacity/observability-operations receipts. A
  fresh active-challenge Ed25519 controller signature binds every artifact
  digest and product-data value; the observability authority must include
  fresh correlation-ID log-query, W3C API-to-search/provider/render trace,
  versioned dashboard, alert-delivery, and immutable runbook evidence.

The repository copy at `scripts/propertyquarry_global_launch_terminal.py` is a
non-authoritative developer validator. Production authority requires the
root-controlled installed entrypoint and controller-signed digest contract for
the installed wrapper, Python, Gold, supporting code, and policy bundle.
Only the wrapper result binding the controller-attestation, complete artifact
map, invocation contract, and Gold-result digests is terminal evidence; direct
Gold JSON is not global launch authority.

Until that terminal rule passes, the only truthful decision is `BLOCKED` for
global launch, even when this source/browser checkpoint is green.

The checked-in source contracts for those two gates are definitions, not live
evidence. With no governed live receipts, both gates and therefore Launch/Core
Gold remain blocked; source/browser materialization must preserve that boundary.

## Operating rule

Treat `MILESTONE.json` as supporting delivery history.
Treat this plane as the source/browser release truth for the explicitly named
standalone proof target; it is not evidence for intentionally skipped legacy
surfaces and is not protected live launch authority.

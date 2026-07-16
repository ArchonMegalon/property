# PropertyQuarry flagship truth plane

## Purpose

The PropertyQuarry repository needs its own release truth so flagship claims do not depend on the inherited all-released `MILESTONE.json` plus checklist completion alone. The standalone proof target is PropertyQuarry; it does not reuse the intentionally skipped legacy Executive Assistant office-loop tests.

This plane is PropertyQuarry-owned release evidence. The inherited EA product canon in `.codex-design/ea/*` is a bounded design input, not the owner of this product or its release claim.
It sits below `IMPLEMENTATION_SCOPE.md` and above the release checklists.

`EA_FLAGSHIP_TRUTH_PLANE.md` is the human-readable form of this plane and retains its historical filename for compatibility.
`EA_FLAGSHIP_RELEASE_GATE.json` is the machine-readable seed that release verification consumes and likewise retains its historical filename.

## What counts as truth

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

## Release claim rule

The standalone PropertyQuarry surface is flagship-grade only when the shipped workspace behaves like the property decision system described by the current proof target and the browser proof, gate seed, and release verification agree.

If those three disagree, the safe answer is not flagship.

## Operating rule

Treat `MILESTONE.json` as supporting delivery history.
Treat this plane as the release truth for the explicitly named standalone proof target; it is not evidence for intentionally skipped legacy surfaces.

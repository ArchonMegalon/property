# PropertyQuarry Premium UI Exit Gate

This gate defines when the customer-facing UI is allowed to be called flagship-ready. It is intentionally stricter than "the page renders". The product must feel calm, premium, direct, and usable by someone tired, distracted, or using a phone with limited finger precision.

The design bar is informed by Apple Human Interface Guidelines, Material Design, Nielsen's usability heuristics, WCAG 2.2 AA, Baymard ecommerce form research, and GOV.UK service clarity. These are references for judgment, not decoration. PropertyQuarry still needs its own quiet property-advisory voice.

Reference standards:

```text
Apple HIG: clarity, direct manipulation, consistent navigation, forgiving touch targets.
Material Design: visible hierarchy, meaningful motion, accessible states, predictable components.
Nielsen Norman Group: system status, match with the real world, user control, recognition over recall.
WCAG 2.2 AA: contrast, keyboard access, focus visibility, target sizing, reduced motion support.
Baymard Institute: low-friction forms, clear product information, transparent checkout/account handoff.
GOV.UK Design System: one primary thing per page, plain language, explicit errors, no clever labels.
```

These standards are release inputs, not brand direction. The PropertyQuarry brand direction is:

```text
calm expert
premium but not flashy
minimal but not empty
specific local evidence
one next step at a time
no internal machinery exposed to customers
```

## Release Rule

A release fails this gate if any primary customer surface feels like an internal tool, requires unnecessary interpretation, hides the next action, contains non-working controls, or wastes mobile screen space.

Primary customer surfaces:

```text
public home
pricing and sign-in
search
search history
results
shortlist
property research
3D tour
walkthrough request
saved searches
account
billing handoff
alerts and notifications
loading, empty, failed, repairing, and unavailable states
```

## Non-Negotiable Blockers

Any item below blocks "gold", presentation, and deploy promotion.

```text
clipped controls, clipped comboboxes, clipped text, or overlapping panels
tap targets below 44px on mobile, except passive text links inside prose
mobile surfaces that need precision tapping to complete the main task
bottom mobile menu bars that consume persistent vertical space
raw provider URLs used as titles or primary labels
internal terms such as OODA, lane, worker, receipt, MagicFit, score gate, run ranking, or suppressed_generic_listing_page
fake progress bars, stale ETA, or status text that does not reflect real backend state
clickable-looking UI that does nothing within 100ms of interaction feedback
more than one primary action competing in the same viewport
unnecessary intermediate pages before opening a tour, listing, map, or walkthrough
blank loading longer than 1s without a skeleton, progress, or useful status
provider, market, country, or plan choices that can produce impossible combinations
dark mode text below WCAG AA contrast or unreadable chip/button states
keyboard traps, scroll traps, map gesture traps, or hover-only actions
```

## Visual Quality Bar

Every primary screen must pass these human-review checks.

```text
The page has one obvious purpose within three seconds.
The first viewport contains the main user value, not admin proof.
The navigation is stable, short, and placed consistently.
The hierarchy is visible at a glance: title, one primary action, supporting facts.
Cards are sparse; nested cards and decorative borders are removed.
Spacing uses a deliberate rhythm, not accumulated margins from old versions.
Typography is readable on phone and desktop without cramming.
Color is restrained: neutral base, one action color, one warning/accent color.
Gold is used as a premium accent, never as visual noise.
Images and maps look intentional, cropped correctly, and never like broken placeholders.
Empty/error states tell the user what happened and what they can do next.
```

## Mobile Gate

Mobile is the default presentation gate. Desktop cannot compensate for a weak phone UI.

```text
Each primary task fits in a single-column path with no side-column dependency.
The first screen answers "where am I, what is happening, what can I do?"
One expanded section at a time for dense preference groups.
District map selection runs in a dedicated dialog; manual district selection is an alternative mode, not a competing stacked UI.
Maps support pan, pinch zoom, tap selection, and a clear close action without trapping page scroll.
Comboboxes and filters are only as wide as their content needs.
Search, results, research, account, billing, and tour controls are operable with one thumb.
Top navigation replaces wasteful persistent bottom navigation.
```

Presentation-phone minimum:

```text
320px width must remain usable.
390px width must look intentional, not squeezed.
Touch targets for primary actions are at least 44px high and spaced so accidental taps are unlikely.
Every main task is possible with one thumb and no hover.
Any map or media gesture that can steal page scroll must open in a focused dialog on mobile.
```

## Interaction Gate

Every clickable element must be audited.

```text
Buttons perform the visible action or are disabled with a clear reason.
Images that look clickable open the expected detail, map, tour, or carousel.
Opening a listing opens the provider listing, not an internal dead end.
Opening a tour opens the best available real tour directly, with no fake provider chooser.
Requesting a 3D tour or walkthrough asks for required style/context choices before queueing.
Disabled tour/walkthrough actions explain the missing input, such as no floorplan.
Search history cards open the exact ranked results they summarize.
Billing opens the real billing account or explains the handoff limitation.
```

## Content Gate

Customer copy must be specific, useful, and quiet.

```text
Say "A nearby river can cool summer evenings", not "positive climate signal".
Say "Billa is 420m away", not "supermarket distance warning".
Say "No floorplan was found, so a tour cannot be generated yet", not "media request unavailable".
Say "One source changed its page; we will check it again next week", not "repair lane retrying".
Use "Why it fits" only when the reasons are concrete, local, and sourced.
Do not expose provider names, tool names, queue names, or scoring internals unless they help the user decide.
```

## Performance Gate

Performance is part of design quality.

```text
No customer route may show a blank page for more than 1s on a normal mobile connection.
Search/results/research first paint must not wait for heavy maps, media, tour viewers, or newspaper/environment overlays.
Heavy assets lazy-load behind intentional skeletons.
Subsequent searches read cached geographic/evidence rollups, not inline crawls or indexing.
The UI shows at least the last 10 meaningful run updates when a search is active.
ETA must be recomputed from actual provider and worker state or hidden.
```

Measured thresholds:

```text
first visible skeleton or useful status: <= 1s
primary route usable shell: <= 2s on a normal mobile profile
interaction feedback after tap/click: <= 100ms
heavy media/map/tour viewer starts lazy and never blocks the route shell
customer route HTML contains no unused provider/tool chooser when only one real action is available
active search view shows the latest 10 meaningful updates, newest first or clearly grouped
```

## Accessibility Gate

The interface must pass practical accessibility, not only markup checks.

```text
WCAG 2.2 AA contrast for text, controls, chips, dark mode, and map overlays.
Keyboard reaches every primary action in visible order.
Focus states are visible and not swallowed by cards or dialogs.
Dialog focus is trapped inside the dialog and returns to the opener on close.
All icon-only actions have accessible labels.
Forms expose labels, errors, and helper text without relying on placeholder text.
At 200% browser zoom, primary tasks remain usable without horizontal scrolling.
```

## Required Receipts

A release candidate needs current receipts for all of these before "premium", "gold", or "ready to present" is allowed.

```text
mobile screenshots: search, district selection, results, research detail, account, billing, tour
desktop screenshots: search, results, research detail, tour, billing handoff
browser interaction audit: every visible clickable control on primary surfaces
axe/WCAG scan for primary surfaces
dark-mode readability pass
performance receipt for first paint, heavy-route lazy loading, and no 30s blank states
tour receipt proving direct Matterport/3DVista load where available
walkthrough receipt proving room coverage and no frame-jump artifact
search receipt proving no hard score filtering when the user selected no hard filters
copy audit proving no internal/operator language on customer surfaces
```

Required presentation-path proof:

```text
recorded mobile browser run: sign in -> search -> district selection -> results -> research -> map -> tour/walkthrough request
recorded desktop browser run: search history -> ranked results -> property detail -> direct provider listing -> billing handoff
click audit: every visible button/link/image/menu either works, opens a real destination, or is disabled with a reason
media audit: real Matterport or 3DVista tour opens directly when available; no 360-cube fallback is visible
pricing/account audit: signed-in user never sees a create-account loop and plan status matches billing source of truth
```

## Automated Gate Commands

The gate must be backed by automated checks before any deployment claim.

```bash
python3 -m pytest tests/test_propertyquarry_premium_ui_exit_gate.py -q
python3 -m pytest tests/test_propertyquarry_design_system_gate.py -q
PYTHONPATH=ea python3 scripts/propertyquarry_authenticated_performance_smoke.py --write _completion/smoke/property-auth-performance-latest.json
PYTHONPATH=ea python3 scripts/verify_property_tour_controls.py --summary-only --require-all-provider-modes --write state/artifacts/property-tour-controls-current.json
```

Passing these commands does not prove premium by itself. Failing any of them blocks "gold". Human screenshot review and click-path receipts are still required because visual craft cannot be fully captured by static tests.

## Failure Triage

When the UI fails this gate, fixes follow this order:

```text
1. Remove broken or unnecessary controls before styling them.
2. Collapse competing paths into one expected next action.
3. Replace internal language with concrete customer value.
4. Fix mobile ergonomics before desktop polish.
5. Add skeleton/progress feedback before optimizing secondary visuals.
6. Only then tune typography, spacing, color, and motion.
```

## Scoring Rubric

Every primary surface receives a 0-3 score in each category. Any 0 blocks release. Any average below 2.6 blocks "premium".

| Category | 0 | 1 | 2 | 3 |
| --- | --- | --- | --- | --- |
| Purpose | unclear | findable after reading | mostly obvious | obvious in three seconds |
| Hierarchy | noisy | competing groups | one main path | calm, elegant, inevitable |
| Mobile ergonomics | hard to use | usable with effort | usable | thumb-friendly and forgiving |
| Copy | internal/noisy | generic | useful | specific, local, concise |
| Interaction | broken/dead ends | works with hops | works | direct and expected |
| Accessibility | blocks users | partial | passes checks | robust under zoom, keyboard, and dark mode |
| Performance | blank/stuck | slow with weak feedback | acceptable | fast with honest progress |
| Visual craft | inherited/tool-like | average SaaS | polished | premium, human-designed |

## Exit Statement

PropertyQuarry passes the premium UI gate only when a new user can complete the core loop on a phone without explanation:

```text
sign in -> search -> choose districts -> understand progress -> open ranked results -> inspect a property -> view map/media/tour -> request walkthrough or 3D tour when possible -> decide next step
```

If any step feels noisy, fragile, fake, cramped, or confusing, the release is not gold.

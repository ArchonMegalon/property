# PropertyQuarry Fleet Continuous Improvement Loop

## Goal

When 1min.AI capacity is abundant, PropertyQuarry should spend that excess on product improvement instead of leaving it idle.

The loop should continuously:

- repair drift
- add coverage
- improve ranking quality
- improve country/provider support
- harden UX and contracts
- keep changes bounded and auditable

This is not a free-form autonomous coding bot. It is a governed improvement loop.

## Activation rule

Only run the improvement loop when:

```text
global live remaining credits > 200000000
and provider health is not degraded
and no active incident freeze exists
```

If credits fall below the threshold, the loop stops starting new work and only finishes in-flight tasks.

## Product rule

Fleet should spend surplus credits on work that makes customer searches more likely to succeed or become more useful.

Priority order:

1. repair broken searches
2. improve weak providers
3. add missing market coverage
4. improve ranking and underwriting evidence
5. improve UX and failure handling
6. improve public growth surfaces

## Control loop

The loop runs as a repeating cycle:

```text
observe
orient
decide
act
verify
publish receipt
repeat
```

Cadence:

- lightweight health scan every 30 minutes
- deeper gap-selection pass every 6 hours
- country/provider expansion pass once per day

## Inputs

The loop should watch:

- provider failure rates
- stale or failed search runs
- `completed_partial` frequency
- no-results runs with heavy filtering
- country coverage gaps
- market catalog gaps
- packet/research failures
- 360/tour availability misses
- underwriting evidence gaps
- browser E2E failures
- design-system gate failures
- CI failures

## Fleet lanes

### 1. Search repair lane

Purpose:

- keep live searches from ending as failures when they are repairable

Actions:

- provider workflow repair
- packet rebuild fallback
- shortlist resume from checkpoint
- stale-run recovery

Output:

- repaired run
- partial run
- bounded failure receipt

### 2. Provider improvement lane

Purpose:

- strengthen weak or drifting providers

Actions:

- discover changed DOM and selector drift
- repair extraction templates
- improve price parsing
- improve location parsing
- improve floorplan/360 detection
- tighten dedupe rules

Output:

- provider-specific patch
- provider quality delta receipt

### 3. Country expansion lane

Purpose:

- add missing countries, metros, municipalities, and provider bundles

Actions:

- detect country requests with poor or zero coverage
- propose country/provider catalog additions
- build grouped source bundles
- add location taxonomies and aliases
- add filter defaults for the market

Output:

- market catalog patch
- provider launch bundle
- smoke coverage receipt

### 4. Ranking and research lane

Purpose:

- make the shortlist smarter, not just larger

Actions:

- improve investment scoring
- improve home-fit reasoning
- improve relax suggestions
- improve source weighting by provider quality
- improve missing-evidence follow-ups

Output:

- ranking patch
- test deltas
- before/after shortlist evidence

### 5. UX hardening lane

Purpose:

- reduce ambiguity and friction in the live product

Actions:

- identify repeated support-style confusion
- tighten labels, tooltips, and empty states
- remove stale or conflicting UI branches
- fix mobile layout regressions
- fix worker/progress/status truthfulness

Output:

- UI patch
- screenshots
- browser regression receipt

### 6. Growth and public surface lane

Purpose:

- improve public acquisition quality when product reliability is healthy

Actions:

- add guides and market pages
- improve ClickRank-targeted editorial coverage
- improve structured data
- improve conversion clarity on pricing and public CTAs

Output:

- SEO/content patch
- route and metadata receipts

## Task selection

Each pass should build a ranked improvement queue.

### Score dimensions

Every candidate task gets scores for:

- user pain
- failure frequency
- revenue leverage
- coverage leverage
- confidence of automated fix
- expected credit cost
- expected test cost
- blast radius

### Selection rule

Always prefer:

```text
high user pain
high recurrence
high confidence of bounded automated fix
low to medium blast radius
```

Do not auto-select:

- deep schema rewrites
- billing model changes
- legal/compliance-sensitive policy changes
- brand/positioning changes
- destructive migrations

Those require explicit operator approval.

## Credit budgeting

Do not let the improvement loop burn unlimited capacity just because the threshold is high.

### Budget model

Use:

```text
max_daily_improvement_burn
max_task_burn
per-lane burn caps
reserve floor
```

Example:

- reserve floor: `200000000`
- daily improvement cap above the floor: `2%` of surplus
- per-task cap:
  - repair lane: low
  - provider lane: medium
  - country expansion lane: medium/high
  - UX lane: low

### Stop conditions

Stop launching new tasks if:

- credits drop below reserve
- browser E2E is red
- release gate is red
- provider health is globally degraded
- more than 3 high-severity tasks are awaiting review

## Output contract

Every Fleet task must emit:

```text
task kind
why it was selected
credit spend
files changed
tests run
before/after evidence
result
```

Possible results:

- `patched`
- `patched_pending_review`
- `blocked_external`
- `insufficient_evidence`
- `deferred_high_risk`

## Verification gates

No automatic publish without verification.

### Required gates by lane

#### Search repair lane

- focused runtime tests
- route health checks
- if UI changed, browser slice

#### Provider improvement lane

- provider extraction tests
- localized fixture tests
- one smoke search in the affected market

#### Country expansion lane

- market catalog tests
- area/filter tests
- one home run and one investment run smoke in the new market

#### Ranking lane

- shortlist contract tests
- reasoning copy tests
- before/after ranking receipt on fixture set

#### UX lane

- redesign tests
- browser screenshots desktop/mobile

## Publish policy

There are three publish levels.

### Level 1: autonomous merge allowed

Allowed when:

- low blast radius
- tests green
- no schema change
- no billing/auth/security changes
- diff stays inside one bounded product lane

Examples:

- tooltip copy fix
- provider selector drift patch
- worker status truthfulness fix

### Level 2: draft PR only

Allowed when:

- medium blast radius
- multi-file runtime work
- market expansion
- ranking changes

Examples:

- new country bundle
- investment scoring adjustment
- packet fallback changes

### Level 3: operator approval required before coding

Examples:

- commercial logic
- billing
- auth/session
- legal/compliance policy
- destructive migrations

## Observability and governance

Create a Fleet improvement ledger with:

```text
loop_run_id
started_at
ended_at
surplus_credits_at_start
task_count
patched_count
blocked_count
credit_spend
highest_value_change
open_followups
```

Also keep per-lane receipts:

- `repair`
- `provider`
- `country`
- `ranking`
- `ux`
- `growth`

## Recommended first backlog for this loop

1. auto-repair search runs via CodexEA
2. provider DOM drift repair for weak markets
3. Austria/Germany location truth and filtering audits
4. new country bundles for the most requested uncovered markets
5. underwriting evidence enrichment
6. property detail unification
7. public tour hardening
8. remaining `innerHTML` removal in live surfaces

## Anti-goals

The loop must not:

- rewrite the product endlessly because credits are available
- publish unreviewed broad refactors
- burn credits on low-value vanity improvements
- hide failures by suppressing receipts
- claim market support without smoke evidence

## Example loop

```text
observe:
- 12 Vienna runs completed_partial because one provider drifted
- Costa Rica buy searches have only 2 reliable sources
- Salzburg filters have high no-result rate

orient:
- provider drift is highest user pain
- Costa Rica coverage gap is next highest leverage
- Salzburg no-result rate is a UX/ranking rule issue

decide:
1. repair Vienna drifting provider
2. add one Costa Rica provider bundle
3. improve Salzburg relax suggestions

act:
- Fleet patches provider extractor
- Fleet adds market catalog rows and grouped source bundle
- Fleet improves suppression messaging and filter relax hints

verify:
- focused provider tests green
- market catalog tests green
- browser and runtime slices green

publish:
- patch merged or PR raised by level
- receipts written
```

## Short version

If credits are abundant, Fleet should run a governed improvement loop:

```text
use surplus credits to repair drift, expand coverage, and harden UX
only pick bounded tasks
always verify
only publish low-risk work automatically
keep receipts for every action
```

That is the way to turn surplus model credits into product quality instead of random automation churn.

# PropertyQuarry CodexEA Search Auto-Repair Design

## Goal

PropertyQuarry cannot treat a first-pass provider or rendering failure as the final customer experience.

The product goal is:

```text
one user brief
-> one visible search run
-> automatic diagnosis and repair when the run degrades
-> best possible shortlist or a precise bounded failure receipt
```

The user should not have to understand provider drift, selector breakage, packet-generation stalls, or temporary browser workflow failures.

They do need clear feedback about:

```text
what is happening
what PropertyQuarry is repairing now
whether current matches are already usable
when the next useful update is likely
```

## Product rule

The first terminal state shown to the customer should be one of:

```text
Results ready
Results ready with partial source coverage
Search interrupted after automatic repair attempts
```

Not:

```text
search failed
worker stuck
provider 401
packet not found
starting forever
```

Those are operator and repair-lane facts, not primary customer language.

## Customer feedback contract

Every degraded or repairing run must expose:

```text
status label
plain-language message
current repair step
next useful update ETA
final completion ETA
ETA confidence
```

### Required customer-visible states

```text
Searching
Repairing one source
Recovering the shortlist
Rebuilding one property page
Continuing with verified matches
Results ready with partial source coverage
Search interrupted after automatic repair attempts
```

### Required message shape

The product should always tell the customer:

1. what failed in product language
2. what the system is doing now
3. whether already-ranked homes are still usable
4. when the next useful update is expected

Example:

```text
One source stopped responding. PropertyQuarry is retrying that lane while keeping the strongest verified matches. Next update in about 3 minutes.
```

## ETA design

The ETA model must split:

```text
next useful update ETA
final expected completion ETA
```

Why:

- when a run is repairing, the next useful update matters more than the full finish time
- if a shortlist already exists, the user needs to know whether more sources are still being recovered

### ETA confidence

Each ETA should expose:

```text
high
medium
low
unknown
```

User-facing examples:

- `Next update in about 2 minutes`
- `More sources still repairing · final completion about 12 minutes`
- `ETA uncertain while one source is being repaired`

### ETA inputs

ETA should be computed from:

- current stage
- completed checkpoints
- per-source historical median durations
- provider-specific retry budget
- whether CodexEA repair is active
- whether packet rebuild is active

### ETA rules

1. If a shortlist already exists but one source is repairing:
   - prioritize `next useful update ETA`
   - do not imply the whole run is blocked

2. If CodexEA repair is active:
   - show `Repairing one source`
   - show `next useful update ETA`
   - downgrade confidence on second repair attempt

3. If the run is overdue and may stale-fail:
   - replace optimistic ETA with:
     - `Update is overdue`
     - `PropertyQuarry is checking whether the run can be recovered`

4. If partial results are already safe to inspect:
   - show:
     - `Strongest verified matches are ready now`
     - `Additional source recovery may add more homes in about X minutes`

## Scope

This design covers:

- provider fetch failures
- browser workflow breakage
- packet/research page generation failures
- shortlist compilation stalls
- stale runs that stop advancing
- per-source extraction drift

This design does not try to auto-repair:

- billing configuration
- missing external feed credentials
- hard legal/compliance suppressions
- explicit plan gating
- deliberate product policy blocks

## Core design

### 1. Search runs get a repair phase

Property search runs should move through these high-level states:

```text
queued
processing
degraded
repairing
completed
completed_partial
failed
cancelled
```

Definitions:

- `processing`: normal source fetch, enrichment, shortlist, packet work
- `degraded`: a repairable failure was detected but the run may still recover
- `repairing`: CodexEA is actively executing a bounded repair plan
- `completed`: full terminal success
- `completed_partial`: enough sources/ranking succeeded to deliver a useful shortlist, but one or more source lanes remained degraded
- `failed`: repair budget exhausted or the failure was not safely repairable

### 2. CodexEA becomes a bounded repair lane, not a hidden black box

CodexEA should run as a dedicated repair worker for PropertyQuarry failures.

It should receive:

- `run_id`
- `principal_id`
- failing source ids
- failure class
- source URLs / entry URLs
- current provider/workflow receipts
- relevant HTML snapshot or packet artifact
- prior repair attempts for this run
- strict scope boundary

CodexEA is allowed to:

- diagnose provider/browser workflow drift
- patch selector or extraction workflow specs
- retry packet generation with a safer mode
- downgrade from richer packet generation to compact packet generation
- mark a provider lane quarantined for this run
- recommend replacement providers from the same market catalog

CodexEA is not allowed to:

- broaden user filters without an explicit policy rule
- silently switch home to investment or rent to buy
- override plan gates
- invent missing listing evidence
- mutate unrelated product code during a live repair

## Repair classes

Every repairable failure should map into one repair class.

### A. Provider fetch drift

Examples:

- `401`
- `403`
- `410`
- changed result DOM
- changed pagination path
- dead entry URL

CodexEA actions:

1. retry same provider with alternate entry URL or browser workflow
2. retry same provider with cached selector fallback
3. quarantine source for this run if still broken
4. replace with approved sibling provider from the market catalog if available

### B. Extraction drift

Examples:

- listing cards found but no normalized candidates
- price parsing broken
- location parsing broken
- floorplan/360 markers missed

CodexEA actions:

1. run extractor-repair workflow on failing HTML samples
2. validate repaired output against extraction contracts
3. resume shortlist build for that source

### C. Packet / research-page generation failure

Examples:

- `property_research_packet_not_found`
- packet artifact missing
- review page generation stall

CodexEA actions:

1. rebuild packet from persisted shortlist candidate
2. retry in compact packet mode
3. if still broken, keep shortlist live and mark packet generation partial

### D. Stalled run

Examples:

- no progress delta for stale threshold
- queued summary with in-progress top-level state
- packets warmed but no terminal update

CodexEA actions:

1. inspect the last advancing stage
2. cancel the stalled stage lease
3. resume from the last durable checkpoint
4. only fail the run after checkpoint resume also fails

## Durable checkpoints

This design only works if the run can resume from real checkpoints.

Required checkpoints:

```text
sources_resolved
raw_listing_urls_collected
listing_previews_warmed
candidate_rows_normalized
shortlist_built
research_packets_built
results_delivery_ready
```

Each checkpoint should have:

- timestamp
- source coverage count
- durable receipt payload
- retry-safe input references

Without this, CodexEA is forced to restart whole runs instead of repairing slices.

## Retry budget

Repair must be bounded and visible.

Per source lane:

- `provider_fetch_retries`: 2
- `extractor_repair_attempts`: 1
- `packet_rebuild_attempts`: 1

Per run:

- `codexea_repair_attempts`: 2
- `max_repair_window_minutes`: 15

If these budgets are exhausted:

- run may still finish as `completed_partial` if shortlist quality is acceptable
- otherwise it becomes `failed`

## Customer-facing behavior

### Before repair is exhausted

The customer should see:

```text
Searching
Repairing one source lane
Recovering a review page
Continuing with the strongest verified matches
```

The customer should not see raw provider or internal workflow errors.

The customer should also see:

```text
Next update in about X minutes
Final completion about Y minutes
ETA uncertain while one source is being repaired
```

### After partial recovery

Show:

```text
Results ready with partial source coverage
One or more sources needed repair and were excluded from the final ranking.
```

Include:

- ranked shortlist
- visible filter-relax options
- visible source coverage summary

### After hard failure

Show:

```text
Search interrupted after automatic repair attempts
```

And include:

- what stage failed
- whether any shortlist was preserved
- whether retrying later is likely to help
- operator receipt id / correlation id

## Operator-facing behavior

Operators need a compact repair ledger, not a vague event trail.

For every repaired or failed run, persist:

```text
run_id
repair_status
repair_class
codexea_session_id
attempt_count
failing_source_ids
repair_actions[]
final_outcome
operator_summary
```

Example repair actions:

- `retry_provider_entry_url`
- `switch_provider_workflow=browser`
- `extractor_spec_repaired`
- `packet_rebuilt_compact`
- `source_quarantined`
- `fallback_provider_inserted`

## Proposed backend additions

### New run summary fields

Add to property search summary:

```python
repair_status: Literal["none", "degraded", "repairing", "repaired", "repair_exhausted"]
repair_class_counts: dict[str, int]
repair_attempt_count: int
repair_outcome_summary: str
partial_source_coverage: bool
source_coverage_ratio: float
next_useful_update_eta_seconds: int | None
final_completion_eta_seconds: int | None
eta_confidence: Literal["high", "medium", "low", "unknown"]
repair_step_label: str
customer_status_message: str
```

### New event types

Add events like:

```text
run_degraded
run_repair_started
source_repair_started
source_repair_succeeded
source_repair_exhausted
packet_rebuild_started
packet_rebuild_succeeded
packet_rebuild_fallback
run_completed_partial
run_failed_after_repair
```

### New repair queue

Introduce a dedicated repair queue or scheduler lane:

```text
property_search_repair_jobs
```

Each job contains:

- `run_id`
- `principal_id`
- `repair_class`
- `source_ref`
- `attempt_index`
- `checkpoint_ref`
- `prompt_payload_json`

### New CodexEA prompt contract

CodexEA should receive a strict repair prompt:

```text
You are repairing one PropertyQuarry search lane.
Do not broaden user filters.
Do not change plan gating.
Repair only the failing provider/extractor/packet workflow for this run.
Return one of:
- repaired
- quarantined
- fallback_provider_required
- unrecoverable
plus a receipt.
```

## Proposed UI changes

### Running surface

Replace vague failure language with:

- `Repairing one source lane`
- `Recovered 1 of 2 failing sources`
- `Continuing with verified matches while one source is repaired`

Add visible timing feedback:

- `Next update in about 3 minutes`
- `Final completion about 11 minutes`
- `ETA confidence: medium`

Worker lanes should show:

- `Fetching`
- `Ranking`
- `Building property page`
- `Repairing`
- `Excluded after repair`

Not:

- `Starting`
- `Needs retry`
- `Idle`

### Results surface

When partial:

- show a pill: `Partial source coverage`
- show disclosure: `2 of 5 requested sources contributed ranked matches`
- keep relaxation options visible if strict filters contributed to low result count

### Failure surface

When hard-failed:

- primary title: `Search interrupted after automatic repair attempts`
- primary action: `Retry now`
- secondary action: `Relax one rule`
- tertiary disclosure: `What failed`

## Delivery and selling posture

If this product is sold, the commercial promise should be:

```text
PropertyQuarry does not stop at the first provider failure.
Each run attempts automatic source repair and fallback routing before surfacing an interruption.
```

Do not promise:

```text
all searches always succeed
```

That is not a defensible promise in provider-dependent crawling.

Promise:

```text
automatic recovery
partial delivery when possible
bounded explicit failure when not
```

## Rollout plan

### Phase 1

- add repair states and repair events
- distinguish `completed_partial` from `failed`
- improve customer copy
- persist failing source receipts cleanly

### Phase 2

- add checkpoint resume for packet generation and shortlist compile
- add repair queue
- add CodexEA repair prompt contract

### Phase 3

- add provider workflow spec repair
- add sibling-provider substitution
- add operator repair ledger UI

### Phase 4

- add policy-driven automatic relaunch only when the original brief is unchanged and the failure class is clearly transient
- add provider quarantine windows and health scoring tied to the repair outcomes

## Acceptance criteria

This design is only complete when:

1. a provider failure no longer immediately becomes a user-visible failed search
2. stalled runs resume from checkpoints or fail with a repair receipt
3. results can terminate as `completed_partial`
4. operators can inspect exactly what CodexEA changed
5. browser E2E tests cover:
   - provider lane failure with recovery
   - packet generation stall with fallback rebuild
   - partial completion
   - final failure after exhausted repair budget

## Short version

PropertyQuarry should treat search failure like a repair workflow, not a terminal event.

The right design is:

```text
run degrades
-> checkpoint
-> CodexEA repair lane
-> retry/resume/fallback
-> partial or full delivery
-> explicit bounded failure only after repair budget is exhausted
```

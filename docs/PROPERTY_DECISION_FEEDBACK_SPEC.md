# Property Decision Feedback Spec

PropertyQuarry should behave as a property decision operating system, not only a search surface with packets attached.

Core loop:

`Find -> understand -> decide -> explain why -> learn -> improve the market signal`

## Goals

- make the user decision explicit on every serious property surface
- convert rejection and hesitation reasons into personal ranking rules
- keep missing-fact follow-up tied to the decision that caused it
- allow future anonymized market risk signals without leaking raw personal notes

## Decision states

- `unseen`
- `seen`
- `interested`
- `maybe`
- `rejected`
- `viewing_requested`
- `documents_requested`
- `offer_candidate`
- `archived`

Short-term implementation note:

- the current app feedback API still persists reactions as `like`, `maybe`, `dislike`, `hide`
- UI copy should map those to `Yes`, `Maybe`, `No`, `Hide`
- a later migration can promote these into explicit decision-state records

## Primary question

On shortlist cards, the workbench dossier, property pages, email actions, and public property surfaces where appropriate:

`Would you pursue this property?`

Primary actions:

- `Yes`
- `Maybe`
- `No`
- `Hide`

The UI should immediately explain the consequence:

- updates future ranking
- keeps missing-fact tasks visible
- only contributes to market risk after anonymization thresholds are met

## Canonical reason taxonomy

Reason keys should converge toward namespaced keys even if the current implementation still uses older snake-case keys.

- `price.too_high`
- `price.operating_cost_unclear`
- `location.wrong_area`
- `location.noise_risk`
- `location.commute_too_long`
- `layout.bad_floorplan`
- `layout.too_small`
- `layout.room_count_wrong`
- `building.no_lift`
- `building.heating_concern`
- `building.renovation_risk`
- `documents.no_floorplan`
- `documents.energy_certificate_missing`
- `documents.operating_cost_history_missing`
- `family.school_fit_weak`
- `family.playground_far`
- `investment.yield_too_low`
- `investment.capex_uncertain`
- `investment.liquidity_weak`
- `legal.auction_uncertainty`
- `legal.lease_or_title_unclear`
- `source.low_trust`
- `source.duplicate_or_stale`

Each reason key should eventually map to:

- user-facing label
- personal preference effect
- aggregate risk scope
- agent question
- investment packet effect

Example:

```yaml
documents.no_floorplan:
  label: No usable floorplan
  personal_effect: require_floorplan_for_remote_review
  aggregate_scope: provider, property_type, area
  agent_question: Can you send the floorplan with room dimensions?
  investment_effect: reduce_confidence
```

## Private learning output

Examples:

- `No + no floorplan -> require floorplan for remote review`
- `No + noise risk -> prefer quieter micro-location`
- `Maybe + missing operating costs -> create missing-fact task`
- `Yes + strong layout -> reinforce layout preference`

## Aggregate market risk output

Aggregate output is allowed only after privacy thresholds:

- minimum `10` distinct users
- minimum `3` distinct properties for area/provider-level aggregation
- no raw notes
- no exact address
- normalized reason keys only

Potential surfaces:

- `Risk Signals`
- `Provider Quality`
- `Area intelligence`
- `Investment red-flag summaries`

## Household review direction

Decision state should support multiple reviewers and conflict summaries:

- reviewer posture
- stated reasons
- household alignment score
- recommended next question for the agent

## Agent question generation

Any missing fact or blocker should be convertible into an explicit next question.

Examples:

- heating source and energy certificate
- operating-cost history
- bedroom street or courtyard orientation
- floorplan with room dimensions
- building maintenance and special assessments

Track question states:

- `asked`
- `answered`
- `needs_follow_up`
- `confirmed`
- `contradicted_listing`

## UX requirements

Flagship acceptance path:

1. user creates a brief
2. user launches search
3. user reaches shortlist
4. user opens workbench or research packet
5. user records `Yes`, `Maybe`, or `No`
6. user selects reasons
7. product confirms ranking/learning consequence
8. product keeps missing-fact next actions visible

## Test requirements

Required app-surface coverage:

- shortlist/workspace renders decision controls
- workbench renders decision controls
- research packet renders decision controls
- save action persists through the existing property-feedback API
- browser tests assert the decision wording, not only legacy feedback wording

Future required coverage:

- decision timeline rendering
- agent-question generation from blocker reasons
- aggregate-risk suppression below privacy thresholds
- aggregate-risk publication above privacy thresholds

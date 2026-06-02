# Architecture

## Extraction approach

PropertyQuarry should be extracted in phases.

## Phase 1

Dedicated brand and frontend shell.

- propertyquarry.com public site
- propertyquarry.com onboarding
- propertyquarry.com pricing
- dedicated authenticated property workspace

Backend remains shared with EA for:

- search runs
- ranking
- hosted review packets
- handoff packets
- notification triggers

## Phase 2

Isolate product-layer services.

- dedicated product configuration
- dedicated commercial state
- separate domain-aware templates
- optional separate DB namespace

## Phase 3

Full runtime separation if justified.

- dedicated deploy
- dedicated operator tooling
- separate auth/commercial stack

## Product capabilities to preserve

- source scanning
- ranking against profile preferences
- hosted property review pages
- research request escalation
- 360/tour handling when available

## Commercial capabilities to add

- free tier limits
- upgrade triggers
- billing state
- feature gating by plan

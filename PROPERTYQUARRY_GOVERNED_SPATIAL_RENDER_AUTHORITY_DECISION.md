# PropertyQuarry governed spatial-render authority decision

Review date: 2026-07-11 (Europe/Vienna)

Decision ID: propertyquarry-governed-spatial-render-authority-v1

Disposition: revise

Implementation state: blocked

## Independent review declaration

This is an independent PropertyQuarry owner, privacy, and product-bridge
authority review. The reviewer is not the EA petition author, the Chummer
decision reviewer, or an implementation worker. The Chummer decision is treated
as immutable cross-product evidence, not as authority to accept the petition or
to confer Chummer ownership.

The AGENTS-mandated vexp run_pipeline was called before repository inspection.
It returned unrelated pivots from the indexed tibor repository and no
PropertyQuarry context. It was not retried and is not authority evidence. The
review therefore used only targeted reads of the exact immutable inputs and the
named PropertyQuarry snapshots below.

No runtime, provider, account, route, browser, quota, job, build, canary,
deployment, publication, notification, or live state was accessed or changed.
The sole authorized write is this decision artifact.

## Hash-bound evidence snapshot

The controlling Chummer hash was verified before review and immediately before
this artifact was created. A byte change to any listed input invalidates this
review until the controller determines applicability and obtains independent
cross-product re-review.

### Immutable cross-product inputs

| Input | SHA-256 |
| --- | --- |
| /docker/chummercomplete/chummer-design/products/chummer/review/GOVERNED_SPATIAL_RENDER_PETITION_DECISION.md | 2a5e4888bf2e9074a93e97e83d682e385eff53dd9c5ef8961fdc2fec6c2d1d6c |
| /docker/EA/EA_GOVERNED_SPATIAL_RENDER_DESIGN_PETITION.md | ed4f8452d59760e11b6ab7784c9a35d272db4d62520d6c742740573424b3f45e |
| /docker/EA/PROPERTYQUARRY_CHUMMER_GOVERNED_SPATIAL_RENDER_HANDOFF.md | e6ceebaedf91ef50a9e6179ac8775bbdb684147ffe1ca3ccc72175abcf68ee06 |
| /docker/EA/_completion/governed-spatial-render/GOVERNED_SPATIAL_RENDER_DESIGN_REVIEW_RECEIPT.generated.json | 3226895f1946d519bf5be62e9795b81bd3985de383f8efa6113c4fa4a05deb2c |

### PropertyQuarry canonical and source inputs relied upon

| Input | SHA-256 | Authority evidence used |
| --- | --- | --- |
| /docker/property/AGENTS.md | 32cf2c849fbcb9b193056e58f49c1aca769744ad4539e3e225488dbe6184e2af | Review and workspace controls |
| /docker/property/ea/app/api/routes/landing_property_surface_contracts.py | 9c6b3b4160af2bbe2f0ec1f22df2c9072be5f390d3b105ea270e4fba3bc23ed4 | Property-owned surface and workbench contracts |
| /docker/property/ea/app/api/routes/landing_property_research.py | 59f7e0bf6e30b7c2182910052c029b5a1a372090efdfb25e6d35046857146542 | Property packet, source provenance, room facts, product-safe tour state and reason text |
| /docker/property/ea/app/api/routes/landing_view_models.py | 8cd8082875c94095149ca4b2db234507e93d5b34c29cd1cd5e3ecf88e8f17e8e | Property-owned style selection catalog |
| /docker/property/ea/app/product/property_tour_hosting.py | 1d2ab256c5c580c0d4a155b95557df1a85b6eaa518db84a6694d2ad6e70eb5ca | Tour manifest split, spatial-route checks, first-party opening, and revocation execution |
| /docker/property/ea/app/api/routes/public_tour_payloads.py | 82f673715d519587ea9cda70752be01ebedb671cb34ddf2feaeac85c7438835b | Private/public separation, minimization, privacy modes, asset allowlisting, and redacted projection |
| /docker/property/ea/app/api/routes/landing.py | 991109e406dcddb443ecb65018627e50a320678bf5186ff6763af5333235e16c | Property research surface plus privacy, support, and data-deletion intake and closeout routes |
| /docker/property/ea/app/api/routes/landing_content.py | f0df2e9fdcd47e3b9a9248154f61b2d0f85a3651ae07382a7560c730079675ba | Current public privacy, support, responsible-party, rights, and subprocessor canon |
| /docker/property/ea/app/templates/data_deletion.html | 451f981b55292a19890679a7c855de809fa5edd04b01fbb780d14878b42abc40 | Current user-visible deletion scope and legal-retention exception |
| /docker/property/ea/app/data/property_diorama_previews.json | b31fe27a128991787f6d819768a98a8cdeead7aac839cc4bc44409a266eeadc0 | Current generated-preview provenance and source-truth boundary |

These hashes bind the current heavily dirty working-tree snapshots. They do not
assert that the snapshots are committed, clean, promoted, or complete.

## Exact PropertyQuarry authority split

### Product bridge owner

The exact owner is repository /docker/property, Python package app.product,
module app.product.property_tour_hosting
(/docker/property/ea/app/product/property_tour_hosting.py).

That module owns the PropertyQuarry product-bridge boundary: the
PropertyQuarry-owned request contract, normalization from approved product
truth, and consumption of a provider-redacted product projection. Existing
provider-named helpers in the same module are evidence of a current conformance
gap, not permission for the governed bridge to consume provider shapes. Before
implementation, the neutral bridge interface must be isolated from those
helpers and independently re-reviewed without changing this owner unless a new
hash-bound PropertyQuarry decision does so.

### Privacy, retention, deletion, and takedown owner

The exact owner is repository /docker/property, Python package app.api.routes,
module app.api.routes.landing
(/docker/property/ea/app/api/routes/landing.py).

That module owns PropertyQuarry privacy-policy intake, consent and rights
escalation, retention-policy binding, data-subject and takedown intake, and
user-visible closeout through its privacy, support, and data-deletion surfaces.
The module app.api.routes.public_tour_payloads is an enforcement dependency for
minimization and redaction. The module app.product.property_tour_hosting is an
execution dependency for first-party tour revocation and deletion receipts.
Neither dependency may independently change policy, deny an authenticated
request, restore an artifact, or close a privacy case.

### PropertyQuarry-owned truth and product meaning

PropertyQuarry has final authority over:

- first-party property source packets and their source, license, provenance,
  observation-time, confidence, and immutable-reference boundaries;
- room identity and geometry, room and portal graph, walkable mesh, exclusions,
  required-room set, continuous route, revisit policy, and collision truth;
- user consent, listing and asset rights, purpose, audience, exact-location
  permission, publication permission, and revocation status;
- versioned style selection, room overrides, asset-license policy, and truthful
  non-affiliation claims;
- per-user and per-version state, including whether an optional vignette was
  seen or skipped and whether reduced motion suppresses it;
- safe product labels, bounded reason text, retry posture, and the distinction
  among captured media, generated layout aid, tour, walkthrough, blocked
  request, and rejected artifact;
- provider-redacted product projection and first-party product URLs or refs;
- deletion and takedown intake, authenticated subject matching, cascade
  initiation, publication withdrawal, and user-visible closeout.

Property source evidence remains truth. A generated diorama, tour, walkthrough,
style treatment, score, or projection cannot replace, mutate, or silently
upgrade the source packet, room graph, rights record, or user permission.

## Provider-neutral bridge and dependency direction

The allowed dependency direction is:

PropertyQuarry source and user truth
-> app.product.property_tour_hosting product bridge
-> PropertyQuarry-owned provider-neutral product contract
-> explicit boundary mapper
-> Chummer.Media.Contracts only at the Chummer boundary.

The return direction is limited to a provider-redacted state projection,
product-safe reason, approved artifact ref, deletion status, or revocation
status. Provider payloads and private execution receipts do not travel back
through the product contract.

The PropertyQuarry bridge may emit and consume its own product contract and may
map that contract at the Chummer boundary. It must not import, vendor,
source-copy, regenerate, or locally fork Chummer.Media.Contracts. It must not
consume provider-specific request, callback, task, account, balance, URL,
credential, quota, or receipt shapes. It must not select providers, enqueue
jobs, or infer capability from provider names or environment configuration.

The PropertyQuarry contract must have its own semantic version, compatibility
rules, deprecation window, field allowlist, purpose and authorization refs,
idempotency semantics, privacy-policy ref, and redacted-projection rules before
implementation. A mapper is the only permitted cross-contract dependency.
Chummer packages may not become a PropertyQuarry product dependency.

EA may supply derived, TTL-bound telemetry and synthetic, deterministic,
zero-burn compose assistance after canonical authorization. EA cannot own
PropertyQuarry truth, product projection, provider-run receipts, quota
mutation, privacy authority, user closeout, promotion, or readiness. EA cannot
turn a compose result into a job or durable execution claim.

The received Chummer decision names chummer6-media-factory as owner of the
Chummer canonical contract and Chummer execution receipts, and chummer6-hub as
owner of the Chummer bridge. This PropertyQuarry decision merely respects that
external boundary. It does not confer, expand, amend, or accept any Chummer
authority, and it does not make either Chummer repo the owner of PropertyQuarry
truth, privacy, projection, or provider-run receipts.

## Generic spatial and combat boundary

Generic PropertyQuarry spatial input must contain no combat mechanics,
initiative, damage, dice, rules_result, action-resolution, effect-resolution,
encounter-outcome, tactical, VTT, or live-session semantics. A field renamed or
wrapped around those meanings is still forbidden.

Private Chummer encounter previews are separate Chummer product meaning. They
are not PropertyQuarry input, style meaning, room truth, route truth, product
projection, public promise, or fallback. A generic spatial request must remain
complete and valid without any encounter or combat field. PropertyQuarry and EA
must not calculate, reinterpret, cache as product truth, or project Chummer
mechanics.

## Current quota and provider execution posture

Current quota authority under this proposal: none.

Current provider execution authority under this proposal: none.

This decision authorizes zero provider jobs, zero uploads, zero provider calls,
zero credit reservation or consumption, zero quota mutation, zero routes, zero
schemas or adapters, zero APIs, zero builds, zero browser runs, zero canaries,
zero deployments, zero promotions, and zero readiness projections. Historical
files, provider names, environment settings, balances, prototype output, or
handoff prose cannot change that posture.

Future quota reservation, consumption, retry, cancellation, compensation,
idempotency, and kill-switch authority remains unresolved for the cross-product
lane. It must be assigned by coherent canon and independent re-review; EA is
not eligible to own it.

## Privacy, retention, deletion, and takedown fail-closed gate

Current PropertyQuarry canon establishes contextual use, explicit sharing,
redaction, revocation, deletion intake, and subprocessor limitation, but it
does not establish an independently approved numeric spatial-media retention
schedule, numeric takedown SLA, complete provider deletion-proof contract, or
restoration authority. Implementation therefore fails closed.

No product contract, route, compose integration, build integration, live data
flow, or provider execution may be implemented until a controller-designated
PropertyQuarry spatial-media privacy policy is independently re-reviewed and
its exact path and SHA-256 are bound into the coherent cross-product packet.
That policy must contain numeric values, not provider defaults, TBDs, or
indefinite retention by silence, for every applicable item below:

- maximum retention for raw provider traces, private execution receipts,
  rejected and failed inputs, successful source packets, temporary uploads,
  previews, generated derivatives, published artifacts, caches, logs, and
  backups;
- deletion acknowledgement, completion, backup expiry, provider-deletion
  evidence, takedown response, emergency withdrawal, and user-closeout SLAs;
- legal-hold review cadence, expiry or renewal, scope, authorized role, and
  auditable release;
- restoration eligibility window and the exact authorization and dual-control
  requirements.

The approved policy must also require:

1. Data minimization. Only purpose-bound allowlisted fields and opaque refs may
   leave PropertyQuarry. Exact location, identity, preference, document,
   likeness, and rights data require a recorded need and consent or other
   authority. Provider credentials and private account data are never product
   fields.
2. Encryption and access control. Private inputs, receipts, and deletion
   evidence require encryption in transit and at rest, least privilege,
   purpose-scoped access, auditability, public/private separation, and a
   documented incident and key-revocation path.
3. Retention and deletion cascade. A verified deletion or takedown must
   withdraw product and shared refs, stop new processing, delete or tombstone
   source copies as policy permits, cascade through derivatives, previews,
   caches, logs, backups, and provider-held copies, and preserve only the
   minimal deletion proof or legal-hold record allowed by policy.
4. Provider deletion proof. The future execution owner must return a
   provider-redacted deletion receipt with request scope, timestamps,
   derivative coverage, result, bounded failure reason, retry state, and
   evidence hash. A request is not closed merely because a local link vanished.
5. Legal hold. A hold must be explicit, scoped, time-bound or periodically
   renewed, access-restricted, and visible to the privacy owner. It pauses only
   the conflicting deletion, not publication withdrawal or unrelated
   minimization.
6. Takedown and closeout. app.api.routes.landing owns authenticated intake,
   status, escalation, and user-visible closeout. Safe closeout must state what
   was withdrawn, deleted, retained under law, pending at a provider, or
   ineligible, without exposing private provider evidence.
7. Restoration. Only app.api.routes.landing, acting under the approved numeric
   policy and independently auditable authorization, may authorize restoration.
   A bridge, provider adapter, EA worker, cache, retry, rollback, or publication
   surface may not self-restore. Deleted source truth must never be recreated
   from a derivative.

## Promotion gates

The following are eligibility gates only; they do not authorize work while the
current blocked state applies:

1. A single coherent Chummer amendment set is merged, mirrored, and
   checksum-verified, covering contract ownership, Hub and media-factory
   boundaries, recipes, RUNSITE separation, numeric privacy, capability
   receipts, quota state, milestones, rollback, and mirror discipline.
2. The post-creation SHA-256 of this decision is included in that packet
   together with all input hashes above and any superseding PropertyQuarry
   canon hashes.
3. An independent cross-product re-review explicitly accepts the coherent
   hashes, the exact two PropertyQuarry owners, dependency direction, privacy
   policy, quota owner, execution-receipt owner, and staged authorization.
4. Contract and negative tests prove canonical-package use, no source copies,
   compatibility and deprecation behavior, deterministic normalization,
   idempotency, authorization, provider-field rejection, secret rejection,
   redacted projections, zero-burn compose, and absence of combat semantics in
   generic PropertyQuarry input.
5. Current capability evidence exists for the exact artifact family,
   environment, provider route digest, gate versions, issuance, expiry,
   revocation state, and requested quality posture. Historical or adjacent
   artifact evidence does not pass.
6. Privacy, provenance, consent, license, asset-rights, likeness, source
   integrity, data-minimization, retention, deletion-cascade, provider-deletion,
   takedown, legal-hold, and restoration gates pass against the approved policy.
7. Final artifacts pass required-room coverage, portal and walkable truth,
   no-cut/no-teleport, collision, spatial stability, continuity, effective
   motion, browser, mobile, keyboard, touch, reduced-motion, accessibility,
   recovery, content, and human quality review.
8. After a separate controller authorization, an isolated candidate completes
   a clean 48-hour canary with no unresolved P0/P1, privacy or provenance gap,
   rights violation, quota runaway, repeated render failure, misleading
   projection, or broken rollback. Starting the canary is not promotion.
9. PropertyQuarry promotion is a separate explicit action by the controller
   and the app.product.property_tour_hosting product owner after privacy-owner
   closeout. No evidence service, provider, Chummer repo, or EA worker may
   promote on their behalf.
10. Rollback must stop new builds, revoke affected capability and product
    projections, withdraw shared and public refs, preserve or delete evidence
    under the approved policy, leave property truth unchanged, and require
    explicit privacy-owner authorization for any restoration.

## Permitted scope while blocked

- Read-only hash verification, threat and privacy review, dependency review,
  and preparation of a coherent cross-product re-review packet.
- Design-only amendments by separately authorized canonical owners, with no
  runtime registration or product widening.
- Synthetic, non-executable examples and test plans containing no live
  identifiers, property records, provider data, credentials, or copyrighted
  source assets.
- Preservation and read-only inspection of existing historical artifacts,
  prototypes, and receipts without treating them as current capability,
  authority, or launch evidence.

## Forbidden scope while blocked

- Runtime code, schemas, routes, adapters, APIs, provider or account calls,
  uploads, jobs, quota or credit actions, builds, browser runs, canaries,
  deployments, promotions, public publishing, Telegram, notifications, or any
  live mutation under this proposal.
- Registration of a contract, capability, callback, artifact family, product
  projection, readiness projection, or provider route.
- Live property, user, consent, identity, exact-location, likeness, document,
  campaign-private, or encounter data in a compose or provider payload.
- Source-copying Chummer.Media.Contracts, importing Chummer assemblies into
  PropertyQuarry, duplicating DTOs across repos, or passing provider-specific
  shapes through the PropertyQuarry bridge.
- Letting EA own or mutate PropertyQuarry truth, product state, provider-run
  receipts, quota, privacy, deletion, takedown, readiness, or promotion.
- Adding combat, initiative, damage, dice, rules_result, outcome, tactical, or
  VTT meaning to PropertyQuarry or the generic spatial contract.
- Inferring authorization, capability, privacy compliance, or product/provider
  readiness from this decision, the petition, historical evidence, provider
  names, environment settings, a compose result, or an existing prototype.

## Unresolved dependencies and controller requirement

The exact unresolved dependencies are:

1. The ten-part coherent Chummer canonical amendment set required by the
   controlling decision, with final hashes and mirrors.
2. A PropertyQuarry-owned provider-neutral contract specification and boundary
   mapper that conform to this owner decision without using current
   provider-specific helper shapes.
3. The independently re-reviewed numeric PropertyQuarry spatial-media privacy
   policy and its bound path and SHA-256.
4. Canonical assignment of cross-product provider-run receipt ownership,
   provider-attempt state, quota reservation and consumption, compensation,
   idempotency, cancellation, and route kill-switch authority.
5. Current artifact-family capability receipts and freshness rules without
   secrets or provider-sensitive product fields.
6. Focused contract and negative-test plans and later independently reviewed
   results for bridge, privacy, combat exclusion, quota, deletion, rights,
   browser, accessibility, quality, canary, and rollback behavior.
7. A controller-assembled packet binding the coherent Chummer hashes, this
   decision hash, the numeric policy hash, capability evidence, and rollback
   plan, followed by an independent cross-product re-review receipt.

The controller must verify all hashes before dispatch, prevent parallel workers
from treating draft or dirty snapshots as canon, and obtain explicit review
authorization separately for design amendment, implementation, provider-paid
execution, canary, and promotion. This decision does not accept the EA
petition, authorize implementation, authorize a provider, establish quota
authority, or claim provider or product readiness.

## Risks and decision ceiling

Material risks are provider coupling inside the current bridge-owner module,
contract duplication, Chummer package leakage, EA authority expansion, privacy
policy without numeric limits, incomplete provider deletion proof, ambiguous
future receipt and quota ownership, combat semantics leaking into property
meaning, stale capability evidence, unlicensed style assets, exact-location or
identity exposure, partial deletion, unauthorized restoration, spatial drift,
misleading reason text, and promotion from a dirty or historical snapshot.

The maximum truthful status established by this artifact is:

property_authority_decided_implementation_blocked_pending_independent_re_review

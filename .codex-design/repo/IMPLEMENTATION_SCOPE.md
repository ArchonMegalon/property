# PropertyQuarry implementation scope

## Mission

`propertyquarry` is the standalone property discovery and decision product for people who need to find, compare, research, and revisit homes across fragmented listing markets.
Its center of gravity is the search-to-decision loop: market-aware discovery, preference-backed ranking, research packets, hosted review pages, spatial tours, feedback learning, and a clear next action.

This repository is the implementation source of truth for the PropertyQuarry application, product-facing tests, deployment system, and branded public surfaces.
It was extracted from the Executive Assistant runtime, so some compatibility names and governance artifacts still use the `EA` prefix; those inherited names do not change the product identity or broaden the release claim.

## Governance posture

PropertyQuarry is a standalone product runtime, not a Fleet control plane and not an Executive Assistant office-workflow surface.

The approved local Chummer design mirror under `.codex-design/product/*` supplies cross-repo context only; it does not make PropertyQuarry an owner of Chummer canon.
The inherited EA product surface canon under `.codex-design/ea/*` remains a bounded input to the current release truth plane for navigation, interaction, copy, accessibility, and operator-governance standards.
PropertyQuarry must consume mirrored `.codex-design/ea/*` material downstream and must not use it as evidence for Executive Assistant core eligibility.
The mirrored `.codex-design/review/REVIEW_CONTEXT.md` is the upstream Executive Assistant review checklist. It applies when changing inherited EA mirror material, but it is not PropertyQuarry product canon or local release authority.

That means:

* the PropertyQuarry gate seed, browser proof, generated receipt, live-runtime proof, and deploy receipts must all name the same PropertyQuarry target
* release claims are limited to the exact PropertyQuarry journeys and candidate identity actually proven
* inherited EA or Chummer artifacts may constrain implementation, but cannot silently redefine this repository's product or proof target

## Owns

* the PropertyQuarry landing, onboarding, sign-in, account, property desk, and research-detail surfaces
* market and provider selection, property-search dispatch, durable run state, ranking, shortlist, and failure recovery
* preference profiles, decision reasons, research enrichment, feedback learning, and revisitation workflows
* hosted property packets, governed public publication, spatial-tour presentation, and safe media fallbacks
* PropertyQuarry pricing, plan handoff, client notifications, and product-specific account posture
* product-specific storage schemas, migrations, privacy lifecycle, observability, backup/restore, rollback, and recovery contracts
* candidate build, release evidence, deployment tooling, and branded runtime behavior for `propertyquarry.com`

## Must not own

* Executive Assistant briefing, inbox, approval, commitment, handoff, people-memory, or other office-loop eligibility
* Chummer product canon, Fleet queue truth, cross-repo milestones, blockers, or release authority
* source-portal inventory truth, provider account authority, or facts that have not been retrieved and attributed
* a public media or spatial-tour claim without the corresponding source, publication state, quota posture, and receipt
* user-visible publication, billing, messaging, or destructive lifecycle actions without the required consent and authority
* a production traffic switch that bypasses the governed deploy controller, provenance checks, health gates, or rollback contract

## Required inputs

* `docs/PRODUCT_BRIEF.md`
* `docs/ARCHITECTURE.md`
* `docs/REPO_ISOLATION.md`
* `docs/PROPERTY_DECISION_WORKBENCH_GUIDE.md`
* `docs/PROPERTYQUARRY_RELEASE_MANIFEST.md`
* `.codex-design/repo/EA_FLAGSHIP_TRUTH_PLANE.md`
* `.codex-design/repo/EA_FLAGSHIP_RELEASE_GATE.json`
* inherited `.codex-design/ea/*` release-governance inputs
* generated browser, flagship, weekly-pulse, runtime, recovery, and deploy receipts bound to the candidate under review

## Boundary rules

* New PropertyQuarry product work lands here first; the broader EA repository is not its implementation home.
* Mirrored design context is read-only product input. If it conflicts with the standalone PropertyQuarry contract, fail closed and reconcile the owning truth plane instead of inventing local canon.
* Generated evidence is materialized from its source tests and current gate seed; it is never made green by hand.
* A source-level pass is not a live-runtime or production-launch claim. Live, authenticated, recovery, provider, provenance, and rollback gates must bind to the candidate being promoted.
* Search and research results must preserve source attribution, uncertainty, market context, and actionable recovery states.
* Spatial-tour generation and hosting must remain provider-safe, quota-aware, receipt-backed, accessible, mobile-usable, and resilient when WebGL or premium media is unavailable.
* Public publication and traffic promotion must use the governed controller and preserve a verified rollback path.

## Proof mode

PropertyQuarry should default to decision-workbench posture, not portal-wrapper or unsupported-chat posture.

A flagship release should answer:

* which exact search, shortlist, research, feedback, failure-recovery, mobile, and spatial-tour journeys ran
* which commit, image, configuration, data migration, and provider posture produced the evidence
* whether browser, authenticated runtime, backup/restore, monitoring, and rollback proofs agree
* what remains unavailable, degraded, preview-only, or dependent on operator action
* who has authority to promote the candidate and how production can be rolled back

## Non-goals

* a generic listing portal or MLS clone
* a luxury marketing shell without decision support
* an unsupported LLM chat surface
* a hidden Executive Assistant product surface
* a second Chummer or Fleet truth plane
* a flagship claim based only on milestone history, generated prose, or an unbound local smoke test

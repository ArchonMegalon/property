# PropertyQuarry Whole Project Scope

This is the working definition of "whole product" for hardening passes, audits, release gates, and long-running Codex work.

PropertyQuarry is a paid property decision product. A pass is not whole-project complete when it only improves one page, one provider, one visual component, or one happy path. It must check the customer journey, the operator control plane, the data lifecycle, and the safety boundaries that keep the product credible.

## Scope Rule

Whole-project work includes every system below:

1. Public entry and SEO surfaces.
2. Authentication, logout, account, sessions, data export, deletion, and share-link revocation.
3. Search setup, district and postal-code filtering, hard versus soft filter behavior, provider selection, and saved preferences.
4. Search execution, source coverage, fleet repair, retry state, ETA state, and interrupted-run recovery.
5. Results, filtered-breakdown actions, rank ordering, explanation quality, shortlist persistence, public sharing, and reruns.
6. Research detail, 360 tours, Matterport and 3DVista links, generated walkthrough requests, dossiers, videos, and missing-fact repair.
7. Automation and saved searches, including map thumbnails, edit/delete controls, delivery policy, and run history.
8. Provider governance, market readiness, rights, rate limits, cache policy, and provider-specific canaries.
9. Canonical property memory: property identity, listing instances, evidence claims, price and availability changes, documents, decisions, viewings, offers, and outcomes.
10. Ranking and learning: benchmark fixtures, hard-filter violation rate, soft-filter score impact only, feedback loops, and model-version receipts.
11. Notifications, scout thresholds, email and WhatsApp delivery governance, unsubscribe/STOP handling, and delivery receipts.
12. Billing, invoices, VAT, refunds, entitlements, plan limits, credit usage, and commercial lifecycle copy.
13. Privacy, prompt-injection boundaries, public-tour manifests, public assets, retention, exports, deletion, backups, and restore drills.
14. Accessibility, responsive layout, keyboard navigation, focus state, contrast, reduced motion, and screen-reader labels.
15. Observability: SLOs, structured logs, queue depth, provider success, cost per run, incident signals, and live smoke checks.
16. Documentation, help center, legal pages, provider attribution, generated-tour disclaimers, and localization.
17. Integration governance for LTD/provider lanes such as Subscribr, MetaSurvey, ApiX-Drive, Invoiless, Lunacal, Documentation.AI, Paperguide, Internxt, ApproveThis, Unmixr, and Brilliant Directories.

## Definition Of Done

A whole-project pass must produce at least one of these outcomes for every touched area:

- a user-visible fix;
- a state-machine or storage fix;
- a privacy, security, or rights boundary;
- a focused unit or e2e test;
- a release-gate check;
- a documented backlog item with owner, evidence gap, and fail-closed posture when implementation is larger than the current pass.

Audit prose alone is not done.

## Product Tone

The customer-facing product must be quiet, premium, specific, and property-first. Generic assistant, memo, office, queue, handoff, and operator vocabulary belongs only in internal infrastructure or quarantined archives. Customer surfaces should speak in property terms: searches, sources, listings, homes, dossiers, tours, decisions, viewings, documents, alerts, and shared results.

## Additional Goal

The additional whole-scope goal is to keep moving PropertyQuarry from run-centric search toward durable property intelligence:

- one canonical property identity across duplicate or relisted provider entries;
- claim-level evidence and freshness;
- change intelligence since the last run;
- viewing and outcome capture;
- benchmarked ranking and repair behavior;
- governed provider and content integrations.

This goal remains active until those systems are implemented, tested, and visible in the relevant customer or operator surfaces.

### Current Additional Execution Goal (active)

For this pass, the additional objective is:

1. Harden reliability semantics where user-facing state can look stale or contradictory.
2. Keep hard/soft filter semantics correct for all postal/selected-district workflows.
3. Preserve user control surfaces (logout, filtered recovery, run lifecycle, automation surfaces) across both API and live-board payloads.

Acceptance criteria before this pass is considered complete:

- Provider/source counters are always rendered as true provider count + checks, never with source-variant counts mislabeled as providers.
- Explicit selected district and postal constraints remain hard filters unless intentionally marked fuzzy/adjacent mode.
- Logout works for browser and API-driven sessions.
- Run status/repair messaging stays truthful when repair tasks are queued and when repair completes.
- Scope/automation thumbnails render usable district overlays without clipping key shapes, and map preview payloads reject unsupported image pipelines.
- Every above is covered by unit/e2e test and a smoke check.

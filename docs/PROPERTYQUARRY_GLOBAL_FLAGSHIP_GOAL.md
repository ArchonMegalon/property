# PropertyQuarry global flagship goal

## Outcome

Ship PropertyQuarry as a globally credible, production-operated property-decision
product. The release claim is earned only by an exact committed candidate whose
complete customer loop, supported market envelope, accessibility, performance,
privacy, security, reliability, and operations are all proved by reproducible
candidate-bound evidence and then re-proved on the protected live target.

"Global" does not mean that every country, language, currency, provider, or legal
regime is silently supported. It means that the product is safe to access and
operate globally while every supported market and locale is declared explicitly,
tested end to end, and prevented from inheriting assumptions from another market.
Anything outside that envelope is unavailable with a useful next action; it is
never represented as launch-ready.

## Product and claim boundaries

- Core Gold is the launchable property-search and decision loop. It includes the
  public entry, real authentication, search setup, provider-backed results,
  ranking, shortlist, research packet, first-party hosted 3D tour, feedback,
  notifications, return visit, account controls, privacy lifecycle, and recovery
  states.
- Advanced Visual Gold is additive. MagicFit, Magic, OMagic, generated
  walkthroughs, and other paid visual providers cannot block Core Gold and cannot
  be claimed without fresh provider, account, quota, playback, quality, privacy,
  and exact-candidate binding evidence.
- PropertyQuarry is a decision product for property seekers. Buyer and renter
  modes that are offered in a launch market must each pass the same end-to-end
  contract. Seller, brokerage, transaction, valuation, mortgage, legal, and
  universal-market claims remain out of scope unless separately added to the
  governed product contract and proved.

## Terminal acceptance contract

The long-running goal is complete only when every required section below passes
for the same release commit and immutable image digest.

### 1. Exact release identity and provenance

- The candidate is a clean, committed 40-character Git SHA on an intentional
  release branch; there is no staged, unstaged, or untracked release drift.
- The standalone PropertyQuarry remote contains that exact ancestry and the
  protected workflow tests the same SHA. A mirror that is behind or divergent is
  not release authority.
- Reproducible build, authenticated package, immutable image digest, dependency
  audit, CycloneDX SBOMs, vulnerability scan, signature/attestation, and source
  binding all agree on the exact candidate.
- Generated evidence is immutable, checksum-verifiable, time-bounded, and cannot
  self-attest its own authority.

### 2. Complete customer value loop

- A new customer can discover the product, understand its scope and pricing,
  authenticate with a real supported identity, create or reopen an account, and
  start a search without operator knowledge.
- Every offered launch mode completes: market and preferences -> real provider
  dispatch -> ranked results -> shortlist -> research packet -> hosted 3D tour or
  honest unavailability -> feedback/notification -> logout -> relogin -> durable
  revisit.
- Empty, delayed, partial, stale, offline, expired-session, provider-blocked,
  quota-blocked, payment-failed, missing-media, and internal-error states retain
  customer data, explain what happened in calm language, and expose a useful
  keyboard-accessible next action.
- No page invents a listing fact, price, provenance link, provider result, tour,
  walkthrough, delivery, payment, or readiness state.

### 3. Supported-market and locale envelope

- A versioned machine-readable envelope names every launch country, UI locale,
  accepted content language, currency, measurement system, timezone policy,
  address model, provider set, listing mode, privacy region, and support window.
- The envelope distinguishes full end-to-end launch support from catalog-only,
  intake-only, preview, and planned markets. Only full end-to-end markets may
  contribute to a flagship claim.
- Locale selection is deterministic. HTML language/direction, dates, numbers,
  prices, units, pluralization, sorting, address rendering, form validation, SEO
  alternates, and notification content match the selected locale. Unsupported
  locales fall back honestly to a declared language; they do not mislabel English
  copy as translated content.
- Each launch market passes representative buyer and renter journeys, provider
  isolation, text expansion, Unicode input, local address/currency/timezone cases,
  and any applicable right-to-left layout contract.

### 4. Accessibility and inclusive use

- All public, authentication, application, account, billing-handoff, error, and
  first-party-tour routes meet WCAG 2.2 Level AA for the supported envelope.
- Candidate-bound Chromium, Firefox, and WebKit evidence covers axe with a pinned
  ruleset, semantic structure, keyboard-only operation, visible/unobscured focus,
  dialogs, live status/error announcements, target size, contrast, reduced motion,
  200% and 400% reflow, and desktop/mobile touch behavior.
- A documented manual assistive-technology review covers the critical loop. An
  automated scan alone is not a conformance claim.

### 5. Performance and network resilience

- Production field data at the 75th percentile meets LCP <= 2.5 s, INP <= 200 ms,
  and CLS <= 0.1 for each supported market/device cohort with sufficient traffic;
  new or low-traffic cohorts retain labelled lab evidence instead of fabricating a
  field pass.
- Candidate lab gates cover low-end mobile, desktop, warm and cold navigation,
  slow/reliable and interrupted networks, compressed payload budgets, media
  loading, first useful value, and no unbounded polling or asset waterfalls.
- Flagship Gold requires the closed `low_end_mobile_lab_v1` profile: Chromium
  CDP applies 4x CPU slowdown and 150 ms / 1600 kbps / 750 kbps network limits,
  a 390x844 mobile viewport, explicit cold-cache and warm-repeat measurements,
  authenticated-surface observation through fresh nonce-bound signatures from
  the existing read-only release-probe credential, exact `/version`
  commit/image/deployment observation, and an exact release/manifest/replica
  identity envelope on each cold and warm `/app/search` document response.
  The controller-signed invocation contract independently pins the lowercase,
  unprefixed SHA-256 of the canonical runtime manifest and the Chromium path and
  digest; neither trust anchor may be learned from observed runtime evidence.
  The producer verifies Chromium before launch, passes that exact path explicitly
  to Playwright, and verifies it again after launch. Gold rehashes the same
  canonical, owner-safe, non-symlink executable, requires the explicit launch
  binding, and requires both `/version` and each document response to match the
  independently supplied runtime-manifest digest. It recomputes the fixed 1200 ms
  warm and 2400 ms cold server budgets, rejects
  future-dated or wrong-release receipts, and requires exactly two distinct
  signed navigations. The protected credential is accepted only over bounded
  stdin and is removed before app imports, workers, Playwright drivers, or browser
  processes are started.
  A producer `status=pass` or `flagship_status=pass` is never sufficient without
  those checks. The local workspace-access bootstrap compatibility lane cannot
  qualify flagship Gold. This lab lane does not claim field Core Web Vitals or
  physical-device performance.
- First-party 3D remains bounded and recoverable on constrained devices; optional
  advanced media degrades without blocking the core decision packet.

### 6. Privacy, security, and regional controls

- Consent, purpose limitation, data minimization, retention, export, correction,
  erasure, account deletion, publication withdrawal, audit trails, and subprocessors
  are implemented and tested for every data class in the supported envelope.
- Regional transfer and residency claims are backed by approved operational and
  legal policy. Code tests can enforce configured boundaries but cannot approve a
  jurisdiction or contract.
- Authentication, authorization, session rotation, CSRF, CSP, SSRF/URL intake,
  injection, upload/archive handling, secret isolation, rate limits, abuse controls,
  dependency posture, and security logging meet the governed application-security
  baseline. Security evidence uses defensive tests without weakening safeguards.

### 7. Reliability, capacity, and operations

- Versioned SLIs/SLOs, dashboards, alerts, synthetic journeys, logs, traces,
  correlation IDs, provider/quota telemetry, queue health, and privacy-safe product
  analytics are active and tested end to end, including alert delivery.
- Capacity and admission limits are measured for API, database, queue, scheduler,
  browser/render workers, provider quotas, memory, CPU, PIDs, disk, and network.
  Backpressure and kill switches fail closed without losing accepted work.
- Backup, encrypted off-host read-back, disposable restore drill, RPO/RTO,
  migrations, canary, rollback, feature flags, incident response, customer support,
  status communication, on-call ownership, and post-incident evidence are current
  for the exact release.

### 8. Protected live launch authority

- The independently installed release controller accepts a fresh signed request
  for the exact commit/image and proves containment, fencing, migration outcome,
  deployment identity, public and authenticated probes, monitoring continuity,
  traffic activation, and rollback readiness.
- Protected CI is green for the exact release. Public `/version`, readiness,
  browser journeys, first-party 3D, analytics delivery, and observability all bind
  to that identity.
- `/usr/libexec/propertyquarry/propertyquarry-global-launch-terminal --manifest
  /run/propertyquarry/release-evidence/global-launch-core-manifest.v1.json`
  is the sole global Launch/Core terminal command. Its private closed-schema
  manifest supplies the exact committed SHA and immutable image, every
  Gold-required product-data origin/hash, every Core receipt including the
  market-envelope, incident/support, global-experience, and
  jurisdiction/privacy/provider-rights gates, and all six raw observability
  inputs. Snapshot/probe bundle companions are basename-only, stable-read from
  the primary bundle directory, checked against their declared byte count and
  SHA-256, retained in memory, included in the controller-attested artifact map,
  and pinned beside the primaries before Gold can inspect them. It also requires
  exact-release preflight, disaster-recovery, capacity,
  and observability-operations receipts plus a fresh active-challenge Ed25519
  controller attestation over the product-data values and SHA-256 digest of
  every referenced artifact. The same signed invocation contract includes the
  exact, non-placeholder canonical runtime-manifest SHA-256 and a closed Chromium
  policy with the canonical executable path and non-placeholder SHA-256;
  `/version`, document headers, and browser observations cannot redefine their
  own expected release manifest or toolchain.
  Observability operations must prove fresh
  correlation-ID log ingestion/query, W3C trace continuity through
  API/search/provider/render, versioned Core-SLO/queue/provider dashboards,
  alert delivery, and immutable digest-bound runbooks. Missing, stale,
  placeholder, unsafe-path, digest-mismatched, identity-mismatched, or
  unsigned evidence returns structured `BLOCKED` before Gold. A local,
  source-only, or independently asserted boolean cannot substitute for this
  command. The installed entrypoint, pinned Python interpreter, Gold program,
  supporting modules, and policy/config bundle must be root-owned,
  non-writable by group/other, no-follow opened, and SHA-256 bound into the
  controller-signed invocation contract. Every bundled monitoring policy and
  evidence-overlay registry is mandatory, and the recursively inspected install
  tree must contain exactly the manifest inventory plus its bundle manifest; an
  unlisted source, bytecode, symlink, or other shadow artifact blocks authority.
  The checkout command `python3
  scripts/propertyquarry_global_launch_terminal.py --manifest <test.json>` is
  non-authoritative developer validation only and can never grant launch
  authority. Downstream consumers accept only the wrapper's
  `propertyquarry.global_launch_terminal_result.v1` receipt, which identifies
  `gold_invoked`, the exact release, controller-attestation digest, complete
  artifact-map digest, invocation-contract digest, and verified Gold-result
  digest. A direct Gold JSON document is not terminal authority.

## Evidence levels

1. **Source contract** proves that required code, tests, and policy exist.
2. **Candidate proof** runs the exact tree in bounded isolated local environments.
3. **Production-like proof** uses the immutable image, PostgreSQL, real browser
   engines, network degradation, restore/rollback drills, and monitoring topology.
4. **Protected live proof** verifies the exact deployed identity and real external
   integrations under independent release authority.

No lower level can be relabelled as a higher one.

## Current baseline on 2026-07-19

- The preserved integration tree is frozen in immutable local source commits. The
  canonical generated release manifest and receipt-only envelope carry the exact
  runtime SHA; this document deliberately does not self-reference the commit that
  contains it.
- Strong local Core evidence now includes real Chromium, Firefox, and WebKit
  operating-loop/public-tour journeys; an authenticated Chromium cold/warm probe
  with server-acknowledged nonces and observed subresource HTTP-cache reuse;
  isolated PostgreSQL; bounded resources; privacy closure; release-control models;
  and the first-party 3D journey.
- The candidate and its release branch remain local. No branch has been pushed,
  no protected CI or independent controller has authorized this exact runtime,
  and no exact-candidate protected live launch evidence exists.
- Critical search, shortlist, and research shells have explicit de-AT, de-DE, and
  es-CR localization plus deterministic currency, number, timezone, address, and
  postal contracts. The declared phase-one claim remains English-only because
  public, authentication, account, billing, legal, provider, and dynamic content
  are not fully translated or independently reviewed. Manual accessibility,
  field performance, localized SEO, live provider, and protected operations
  evidence must still be completed before widening the claim.
- Bounded local capacity evidence is a lab receipt only. Even when bound to the
  clean runtime commit it cannot establish production capacity, provider quotas,
  staffing, or field traffic behavior.
- The governed market envelope currently computes AT and DE as `private_beta`, CR
  as `browser_state_only`, and zero markets as launch-supported. Those labels are
  release inputs, not marketing copy, and cannot be promoted without the missing
  per-dimension evidence.
- Incident and support source policy is defined, but
  `scripts/propertyquarry_incident_support_gate.py` intentionally remains blocked
  until exact-release staffing, market coverage, endpoints, drills, owner
  approvals, and independent attestation exist outside the repository.
- The global-experience source contract is defined, but
  `scripts/propertyquarry_global_experience_gate.py` intentionally remains
  blocked because there is no governed live global-experience receipt. Native
  UI/content review, WCAG 2.2 AA automation and manual assistive-technology
  review, Chromium/Firefox/WebKit and mobile-device coverage, per-device field
  CWV cohorts, degraded-network recovery, localized SEO, owner approvals, and
  independent exact-release attestation remain live-evidence blockers.
- The jurisdiction/privacy/provider-rights source contract is defined, but
  `scripts/propertyquarry_jurisdiction_privacy_rights_gate.py` intentionally
  remains blocked because there is no governed live
  jurisdiction/privacy/provider-rights receipt. Current independent local legal
  approvals, privacy/residency controls, exact provider capability permissions,
  technical enforcement, and exact-release attestation are not established by
  repository policy.

## Authority boundaries

Local implementation, tests, builds, isolated containers, and non-mutating remote
inspection are in scope for this goal. Pushing a branch, opening or merging a pull
request, purchasing provider capacity, changing production data or configuration,
deploying, activating traffic, or publishing a claim requires explicit authority
from the user and the relevant independent controller. Until then the correct
release decision is `BLOCKED`, with exact remaining actions and evidence paths.

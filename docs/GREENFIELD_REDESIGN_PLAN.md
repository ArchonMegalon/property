# PropertyQuarry Greenfield Redesign Plan

This document defines what PropertyQuarry should become if designed from a clean sheet, and how to migrate the current ported runtime into that product without losing working search, ranking, billing, notification, and review capabilities.

## 1. Product Thesis

PropertyQuarry is not an executive assistant with a property module. It is a property decision product.

The product promise:

- capture what the user is actually looking for
- search relevant portals across the selected market
- rank the results against personal fit
- research missing decision factors
- present a small shortlist as decision packets
- learn from feedback so the next run is better

The primary user should never feel they are using an inherited workspace console. They should feel they are using a premium property search desk.

## 2. Greenfield Product Shape

### 2.1 Primary Surfaces

The clean product has five authenticated surfaces.

1. **Search Brief**
   - where the user defines what they are looking for
   - replaces the current generic property form and inherited workspace setup
   - includes market, region, city/district, budget, property type, must-haves, dealbreakers, lifestyle priorities, provider selection, and result cap

2. **Live Search**
   - source-by-source progress
   - visible current action
   - raw candidates found
   - shortlist candidates being scored
   - provider failures and fallbacks
   - no fake progress jumps

3. **Shortlist**
   - ranked cards for the few properties that deserve attention
   - each card shows fit score, top reasons, risk flags, unknowns, next action, review packet link, tour link if available, and source link as secondary

4. **Research Packet**
   - one property decision page
   - facts, fit, risks, missing data, researched amenities, commute, heating/lift/floorplan/tour availability, original listing, and evidence trail
   - designed as the page a paying customer would actually inspect

5. **Profile Learning**
   - explicit learned preferences
   - rejected reasons
   - hard rules
   - change history
   - controls to demote or delete learned assumptions

### 2.2 Optional Surfaces

These should exist, but not dominate the first product experience.

- **Plans and Billing**
  - current tier
  - usage left
  - upgrade path
  - billing provider status

- **Connections**
  - Google sign-in state
  - Email notification state
  - Telegram notification state if enabled
  - no Gmail/Calendar/office sync language

- **Provider Health**
  - for operators and power users only
  - shows portals, country coverage, crawl success, block/failure states

## 3. Greenfield Navigation

Top-level app navigation should be:

- `Search`
- `Shortlist`
- `Research`
- `Profile`
- `Alerts`
- `Billing`
- `Settings`

Remove or hide inherited navigation from the PropertyQuarry product:

- Today
- Queue
- Commitments
- People
- Evidence
- Activity
- Automations
- Office
- Morning Memo
- Workspace loop

Those concepts may still exist internally in the legacy runtime, but they must not be visible product primitives.

## 4. Information Architecture

### 4.1 Search Brief

The Search Brief should be a guided flow with persistent state.

Step 1: Market

- country
- region/state
- city or district cluster
- language
- rent/buy
- apartment/house/any

Step 2: Budget and Shape

- max price
- min rooms
- min area
- move-in timing
- furnished/unfurnished
- outdoor space preference
- floor level / lift requirement

Step 3: Lifestyle and Must-Haves

- transit proximity
- supermarket proximity
- pharmacy proximity
- playground proximity
- schools/kindergarten if relevant
- no gas heating
- floorplan required
- 360 tour preferred or required
- pets, parking, balcony, accessibility

Step 4: Providers

- provider multi-select scoped to selected country
- explain which portals are covered
- show known limitations per provider
- result cap per provider

Step 5: Launch

- summarize search brief
- show plan limit
- start run
- optionally save as recurring alert

### 4.2 Live Search

The run screen must explain what is happening in plain product language.

Recommended status model:

- Preparing search
- Fetching provider page
- Extracting listings
- Filtering obvious misses
- Scoring shortlist candidate
- Building research packet
- Checking tour availability
- Sending alert
- Completed
- Failed with reason

Each status event should include:

- provider
- current candidate number if applicable
- elapsed time
- what the user can expect next

### 4.3 Shortlist

The shortlist is the core daily product surface.

Each card should show:

- listing title and normalized location
- fit score
- recommendation: shortlist, inspect, maybe, reject
- price, area, rooms
- strongest match reason
- strongest risk or unknown
- review packet CTA
- tour CTA when real 360 exists
- source link as secondary
- feedback buttons:
  - good fit
  - maybe
  - bad fit
  - hide
  - reason chips

Avoid showing operational counters as the main content. Counts belong below the shortlist or in a collapsible run log.

### 4.4 Research Packet

A research packet should be structured as a decision page.

Sections:

- Decision summary
- Why it fits
- What could fail
- Facts from listing
- Researched facts
- Amenities and distances
- Transit and commute
- Building risks
- Missing information
- Original listing and evidence
- Tour or media
- Feedback

The packet should never look like a generic handoff page. It should look like a property dossier.

### 4.5 Profile Learning

This surface should make the learning loop trustworthy.

Show:

- active must-haves
- active dealbreakers
- positive preference signals
- negative preference signals
- recently learned feedback
- assumptions that need confirmation

Allow:

- delete a learned rule
- turn a soft preference into a hard rule
- turn a hard rule into a soft preference
- clear all feedback for a property

## 5. Visual Design Direction

The product should feel premium but operational.

Use:

- light or neutral base, not inherited dark console as the only mode
- quiet cards with 8px radius
- strong table/card hierarchy
- dense but readable property facts
- large property media only where it helps decision making
- clear provider/status badges
- restrained accent color

Avoid:

- generic dashboard cards as the first impression
- "console", "office", "memo", "queue" language
- decorative gradients as the main visual identity
- progress bars without detailed status
- source portal links as primary CTAs
- cards nested inside cards

Suggested page layout:

- left: search brief or filters
- center: shortlist / research packet
- right: run status, plan limit, learning summary

Mobile layout:

- sticky bottom action bar
- filter wizard as full-screen sheet
- shortlist cards first
- run log collapsible
- source links hidden behind secondary actions

## 6. Domain Model

Introduce explicit PropertyQuarry domain objects instead of reusing generic assistant objects as the product vocabulary.

### 6.1 SearchProfile

Fields:

- `profile_id`
- `principal_id`
- `display_name`
- `country_code`
- `region_code`
- `location_targets`
- `listing_mode`
- `property_type`
- `budget`
- `space_requirements`
- `must_haves`
- `dealbreakers`
- `soft_preferences`
- `provider_selection`
- `language_code`
- `notification_preferences`

### 6.2 SearchRun

Fields:

- `run_id`
- `profile_id`
- `principal_id`
- `status`
- `created_at`
- `completed_at`
- `selected_providers`
- `source_count`
- `raw_candidate_count`
- `shortlist_count`
- `progress_events`
- `failure_summary`

### 6.3 ListingCandidate

Fields:

- `candidate_id`
- `run_id`
- `provider_key`
- `source_url`
- `canonical_listing_url`
- `external_listing_id`
- `title`
- `price`
- `area`
- `rooms`
- `location`
- `raw_facts`
- `normalized_facts`
- `media`
- `tour_signals`
- `ranking_features`

### 6.4 ResearchPacket

Fields:

- `packet_id`
- `candidate_id`
- `public_url`
- `fit_score`
- `recommendation`
- `match_reasons`
- `risk_flags`
- `unknowns`
- `researched_facts`
- `amenity_distances`
- `evidence`
- `tour_url`
- `created_at`
- `updated_at`

### 6.5 FeedbackSignal

Fields:

- `feedback_id`
- `principal_id`
- `profile_id`
- `candidate_id`
- `reaction`
- `reason_keys`
- `note`
- `derived_preference_updates`
- `recorded_at`

### 6.6 Entitlement

Fields:

- `principal_id`
- `plan_key`
- `status`
- `active_until`
- `max_providers`
- `max_results_per_provider`
- `research_depth`
- `recurring_alerts_enabled`
- `agentic_research_enabled`

### 6.7 ProviderQueryPlan

Provider search must be planned before crawling. A query plan is the normalized contract between the user's brief and provider-specific URLs.

Fields:

- `provider_key`
- `country_code`
- `listing_mode`
- `location_targets`
- `min_area_m2`
- `min_rooms`
- `max_price`
- `property_type`
- `provider_filter_pushdown`
- `provider_cache_key`
- `source_urls`

Rules:

- push broad filters into provider URLs whenever the provider supports them
- keep provider-specific parameter names inside provider adapters
- store the generated `provider_cache_key` with each source so equivalent searches reuse provider result lists
- never scan the whole provider catalog when a supported coarse filter can be pushed down

### 6.8 SharedProviderListingCache

Provider listing pages are shared infrastructure, not per-user scratch data. The greenfield design uses a shared cache keyed by provider and pushed-down filters.

Fields:

- `cache_key`
- `source_url`
- `listing_urls`
- `provider_filter_pushdown`
- `stored_at_epoch`
- `ttl_seconds`
- `stale_max_seconds`
- `backend`

Backends:

- `memory` for unit tests and throwaway local runs
- `file` for single-node fallback
- `postgres` for production and multi-replica deployment
- `auto` to prefer Postgres when durable storage is configured

Rules:

- fresh hits return immediately
- stale hits may be used only as fallback when provider revalidation fails
- listings are rechecked briefly before being shown or packetized
- cached provider result lists can be reused across users, but user-specific ranking, packet privacy, and feedback learning remain principal-scoped

### 6.9 ReusablePropertyArtifact

Tours, packets, PDF receipts, and public-safe media manifests are reusable artifacts. A search run should reference existing artifacts when the canonical listing URL or provider external ID matches.

Fields:

- `artifact_id`
- `canonical_listing_url`
- `provider_key`
- `external_listing_id`
- `artifact_type`
- `artifact_ref`
- `source_hash`
- `privacy_scope`
- `created_at`
- `last_verified_at`

Rules:

- reuse completed review packets and tours where the listing identity matches
- verify that the source listing still exists before reuse
- never reuse owner-private or paid-customer artifacts across principals
- regenerate only when source hash, privacy mode, or packet renderer contract changes

### 6.10 PropertyQuarryTeableTenantProjection

Postgres remains the operational store for search runs, onboarding, billing state, and packet publication contracts. Teable is the structured operator/BI mirror for the important PropertyQuarry facts.

Projection tables:

- `propertyquarry_tenants`
- `propertyquarry_users`
- `propertyquarry_subscriptions`
- `propertyquarry_preferences`
- `propertyquarry_search_runs`
- `propertyquarry_properties`
- `propertyquarry_property_evaluations`
- `propertyquarry_research_tasks`

Rules:

- create a dedicated PropertyQuarry Teable base/tenant, not a mixed EA table set
- all rows use stable `projection_id` upsert keys
- global property facts are separated from user-specific evaluations
- subscription state is projected from the normalized commercial snapshot
- current preferences and per-run search preferences are both projected
- search-run results include provider pushdown/cache metadata through the run summary
- sync is fail-closed unless every PropertyQuarry table has a configured Teable table ID
- auto-sync may run after search completion or research-task updates, but must not block the search worker
- Teable writes are a projection; the runtime must remain correct if Teable is unavailable

## 7. API Shape

The greenfield API should use property nouns.

Recommended endpoints:

- `GET /app/api/property/profile`
- `PUT /app/api/property/profile`
- `POST /app/api/property/search-runs`
- `GET /app/api/property/search-runs/{run_id}`
- `GET /app/api/property/search-runs/{run_id}/events`
- `GET /app/api/property/shortlist`
- `GET /app/api/property/research-packets/{packet_id}`
- `POST /app/api/property/feedback`
- `GET /app/api/property/learning`
- `GET /app/api/property/providers?country=AT`
- `GET /app/api/property/billing`
- `POST /app/api/property/billing/checkout`
- `GET /app/api/property/teable-projection`
- `GET /app/api/property/teable-sync-preview`
- `POST /app/api/property/teable-sync`

Keep old endpoints as compatibility wrappers only:

- `/app/api/signals/property/search/run`
- `/v1/onboarding/property-search/preferences`
- handoff-backed review URLs

Wrappers should call the new property services and emit deprecation logs.

## 8. Migration From Current State

### Phase 0: Freeze the Working Behavior

Before redesigning screens, preserve current green paths.

Required gates:

- property search run starts
- run status emits intermediate events
- free tier allows deep research with capped results
- Google sign-in uses PropertyQuarry callback
- PropertyQuarry settings do not show EA sync language
- review packet links stay on PropertyQuarry/MyExternalBrain-hosted property pages
- feedback save updates learning summary

Existing tests already cover parts of this. Add missing tests before changing routes.

### Phase 1: Rename Product Vocabulary

Replace visible language:

- `Workspace` -> `Search profile` or `Property desk`
- `Office` -> remove
- `Morning memo` -> remove
- `Queue` -> `Shortlist` or `Review queue`
- `Handoff` -> `Research packet`
- `Google sync` -> `Google connection`
- `Signals` -> `Listings`, `Alerts`, or `Provider updates`

Implementation:

- update `landing_content.py` nav for PropertyQuarry only
- update `landing_view_models.py` properties payload titles
- update `console_shell.html` property labels
- update public templates and onboarding copy
- add regression test that `propertyquarry.com` does not render banned EA terms on core product pages

### Phase 2: Split Property Shell From Generic Console Shell

The current `console_shell.html` is doing too much. Create a property-specific shell.

New files:

- `templates/property_app_shell.html`
- `templates/property_search_brief.html`
- `templates/property_shortlist.html`
- `templates/property_run_status.html`
- `templates/property_learning.html`

Keep `console_shell.html` for inherited pages until they are removed.

Implementation:

- route `/app/properties` to the new property shell
- move property wizard CSS/JS out of `console_shell.html`
- move feedback JS into `static/property_feedback.js`
- move run polling JS into `static/property_run.js`
- keep server-rendered first paint for no-JS safety

### Phase 3: Introduce Property Domain Services

Create a service boundary that does not expose assistant concepts.

New modules:

- `app/property/profile_service.py`
- `app/property/search_run_service.py`
- `app/property/provider_catalog.py`
- `app/property/ranking_service.py`
- `app/property/research_packet_service.py`
- `app/property/feedback_service.py`
- `app/property/billing_service.py`

Move logic out of `app/product/service.py` gradually.

Migration rule:

- first add new service functions that delegate to existing logic
- then move implementation behind those functions
- then make old product-service functions wrappers

### Phase 4: Replace Handoff Review Packets With Property Packets

Current review pages still reuse generic task/handoff structures. Replace the product-facing concept.

Implementation:

- add `property_research_packets` repository/table or event projection
- generate packet IDs for shortlisted candidates
- route packet pages to `/app/property/research/{packet_id}` or `/property/{slug}`
- keep old handoff URLs redirecting to packet URLs
- update Telegram/email notifications to link to packet URLs

Packet page must include:

- fit summary
- source facts
- researched facts
- evidence
- missing data
- actions
- feedback

### Phase 5: Make Search Run Progress First-Class

Current progress is in memory and event-like state. Make it durable enough for browser refreshes.

Implementation:

- persist search run state
- persist progress events
- expose event stream endpoint or efficient polling
- record provider-level timings
- mark slow provider steps as degraded, not silent
- fail one provider without failing the whole run

Run status should explain:

- what provider is active
- what candidate is active
- whether the system is fetching, extracting, scoring, or researching
- what failed and what fallback was used

### Phase 6: Build the Shortlist-First Workspace

The default authenticated page should not be a form. It should be the property decision desk.

Layout:

- top: active search profile summary and `Start search`
- center: ranked shortlist
- side: live run status and plan usage
- below: learning summary and recent packets

The search wizard opens as a focused panel, not as the main page every time.

### Phase 7: Billing and Entitlement Productization

Billing should read as a product plan, not as provider plumbing.

Show:

- current plan
- searches left or result cap
- research depth
- recurring alerts availability
- upgrade CTA

Hide:

- raw provider names like PayFunnels/PayPal unless needed during checkout error
- webhook internals
- billing implementation details

Add tests:

- free tier can run allowed search
- free tier blocks only when beyond limits
- plus checkout route exists when configured
- webhook activation requires signature
- agent tier unlocks deep/recurring features

### Phase 8: Remove Inherited Runtime From Default Product

The standalone repo can keep inherited code only if it is invisible and gated.

Default ProductQuarry runtime should not mount:

- assistant responses API
- generic queue pages
- generic people graph
- generic commitments
- generic evidence pages
- memorial or voice surfaces
- office/admin surfaces unless explicitly enabled

Implementation:

- make `PROPERTYQUARRY_ENABLE_LEGACY_RUNTIME_SURFACES=0` the hard default
- add route registration tests proving legacy routes are absent
- move legacy tests into a separate profile
- keep only property-facing tests in the normal release gate

## 9. Target File Plan

### Add

- `ea/app/property/`
- `ea/app/api/routes/property_app.py`
- `ea/app/api/routes/property_api.py`
- `ea/app/templates/property_app_shell.html`
- `ea/app/templates/property_search_brief.html`
- `ea/app/templates/property_shortlist.html`
- `ea/app/templates/property_research_packet.html`
- `ea/app/static/property_app.css`
- `ea/app/static/property_run.js`
- `ea/app/static/property_feedback.js`
- `tests/test_property_app_shell.py`
- `tests/test_property_search_run_service.py`
- `tests/test_property_research_packets.py`
- `tests/e2e/test_propertyquarry_flagship_flow.py`

### Keep Temporarily

- `ea/app/product/service.py`
- old property endpoints
- old handoff-backed packet routes

### Remove or Gate Later

- inherited EA app sections
- generic console shell for PropertyQuarry pages
- generic office sync settings on the property host
- non-property public surfaces

## 10. E2E Flagship Flow

The flagship browser test should cover the product as a user sees it.

Scenario:

1. Open `https://propertyquarry.com`
2. Sign in with Google or test session
3. Land on PropertyQuarry decision desk
4. Open search brief wizard
5. Select Austria
6. Select Vienna region
7. Select target districts
8. Select must-haves and dealbreakers
9. Select providers
10. Start search
11. Observe progress events beyond initial source resolution
12. Wait for shortlist or provider failure state
13. Open a research packet
14. Save feedback
15. Verify learning summary updates
16. Verify no EA terms are visible

Required assertions:

- no `Morning Memo`
- no `Office signals`
- no `Workspace loop`
- no raw source portal as primary CTA
- progress events update during run
- feedback updates without full reload
- mobile viewport renders without overlap

## 11. Release Gates

Add a `make property-release-gates` target.

It should run:

- unit tests for property services
- browser surface contract tests
- API contract tests
- property E2E test
- route-mount test for no legacy surfaces
- banned-copy test for EA language on `propertyquarry.com`
- live smoke for `/`, `/register`, `/sign-in`, `/app/properties`
- live run smoke with a mocked or constrained provider set

Fail closed when:

- Google callback points to another host
- property host renders EA terms
- free tier cannot start an allowed search
- source link becomes primary CTA
- run stays at first status without further events
- Emailit/notification config claims enabled but credentials are missing
- PayFunnels claims enabled but checkout/webhook config is missing

## 12. Development Sequence

Recommended implementation order:

1. Add banned-copy tests for PropertyQuarry host.
2. Add `property_app_shell.html` and route `/app/properties` to it.
3. Move wizard markup and JS out of `console_shell.html`.
4. Rename visible navigation and copy.
5. Extract provider catalog and search profile into `app/property`.
6. Extract search run orchestration into `SearchRunService`.
7. Persist search runs and progress events.
8. Create research packet model and route.
9. Redirect old handoff review links to research packets.
10. Redesign shortlist cards and feedback controls.
11. Add profile learning management page.
12. Add property-only release gate.
13. Disable inherited legacy routes by default.
14. Prune inherited tests from the normal release lane.
15. Run full E2E on desktop and mobile.
16. Deploy and smoke the public host.

Each step should be independently shippable. Do not rewrite crawlers, billing, notifications, and UI shell in one commit.

## 13. Definition of Done

The redesign is complete when:

- a new user cannot tell the product came from an executive assistant
- `propertyquarry.com/app/properties` is a decision desk, not a generic console
- search setup is a focused property brief
- the main result is a shortlist, not counters
- every strong result has a branded research packet
- feedback visibly changes the learning model
- Google is identity-only by default
- billing is product-level, not provider-level
- all property release gates pass
- old EA routes are absent from the default PropertyQuarry runtime

## 14. Immediate Next Slice

The first implementation slice should be:

1. Create `property_app_shell.html`.
2. Move `/app/properties` onto that shell.
3. Keep existing data payload.
4. Redesign only the page hierarchy:
   - Search summary
   - Shortlist
   - Live run
   - Learning
   - Billing compact
5. Add banned-copy tests.
6. Add mobile screenshot/E2E coverage.
7. Deploy.

This gives the user the biggest visible product shift without destabilizing crawlers, ranking, billing, or notifications.

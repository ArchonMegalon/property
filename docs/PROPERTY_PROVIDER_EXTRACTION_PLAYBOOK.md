# PropertyQuarry Provider Extraction Playbook

Property providers may need provider-specific adapters, but they must feed the same generic product pipeline.

## Core Rule

Provider-specific code may only normalize access to source data. It must not decide whether a result is good, in-area, verified, publishable, or ready to notify.

Generic stages own those decisions:

1. Provider filter pushdown receipt
2. Listing URL extraction
3. Fast preview extraction
4. Source-scope tagging
5. Concrete location guard
6. Detailed preview extraction
7. Detailed concrete location guard
8. Media and document recovery
9. Floorplan/layout verification
10. Ranking and notification budget
11. Review packet, tour, fly-through, and Telegram delivery

## Provider Gimmick To Generic Stage

| Provider-specific pattern | Generic capability |
| --- | --- |
| Willhaben floorplans hidden as normal photos | Gallery media scan plus visual floorplan classifier |
| Cooperative floorplans hidden in ZIP/PDF bundles | Document/archive floorplan recovery |
| Frieden route data units | Structured listing URL extraction from embedded route data |
| Sozialbau JSF/AJAX tables | Stateful source fetch adapter, then normal listing extraction |
| Siedlungsunion attachment arrays | Context-link document extraction |
| Kalandra or broker pages with 360 links | Generic live-tour URL extraction |
| Costa Rica portals with weak search parameters | Attempted provider query plus post-filter receipt |
| Realtor/realestate international JSON payloads | Structured JSON preview facts, then generic filters |
| Judicial auction portals | Authority-fact extraction plus archive floorplan recovery |
| Broad provider search pages returning wrong cities | Source-scope tagging plus concrete-location guard |

## Non-Negotiable Gates

- A concrete address, postcode, city, district, title, or URL conflict must beat provider search scope.
- Review packets, tours, fly-throughs, and notifications must only be created after the detailed concrete-location guard.
- Near-miss prompts must never be sent for outside-area listings.
- Missing floorplans must record recoverable evidence and diagnostics, not customer-facing repair jargon.
- Provider failures and repair tasks stay operator-only.

## Adding A Provider

When adding a provider, implement only the adapter needed to expose raw candidates:

- host markers
- listing path markers
- search URL builder/filter pushdown
- optional source fetch adapter
- optional structured preview extraction

Then rely on the generic pipeline for:

- location filtering
- property type filtering
- area and availability filtering
- floorplan recovery
- scoring
- ranking
- notifications
- dossiers
- tours

## Exit Gate

Every provider must be able to answer:

- Which filters were pushed to the provider?
- Which filters were post-filtered by PropertyQuarry?
- Did a concrete-location guard run after fast preview?
- Did a concrete-location guard run after detailed preview?
- Which floorplan recovery stages ran?
- Were customer messages free of internal repair wording?


# Property Content Source Policy

PropertyQuarry content packets are positive projections. They are not redacted raw listings.

## Allowed Packet Inputs

- approved public product docs;
- approved market-source packets;
- synthetic demo dossiers;
- approved public listing projections;
- approved tour narration packets.

## Forbidden Inputs

- raw provider crawl payloads;
- portal credentials;
- private user profiles;
- private feedback history;
- payment data;
- seller or agent contact data;
- private saved-search names;
- exact private commute destinations;
- private family or medical notes.

## Content Modes

Supported modes:

- `PRODUCT_TUTORIAL`
- `MARKET_EDUCATION`
- `LOCATION_GUIDE`
- `PROPERTY_DOSSIER`
- `TOUR_NARRATION`
- `INVESTMENT_EDUCATION`
- `MARKETING_RESEARCH`

`PRIVATE_SHORTLIST_VIDEO_BETA` is intentionally disabled until explicit opt-in, retention, deletion, and review controls exist.

## Property-Bound Modes

`PROPERTY_DOSSIER` and `TOUR_NARRATION` require:

- run ID;
- candidate reference;
- listing snapshot hash;
- source list;
- explicit unknowns;
- `research_policy=provided_sources_only`;
- human review;
- publication disabled.

Every generated script remains stale if the listing snapshot, score, user priority projection, tour state, or source packet changes.


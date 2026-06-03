# PropertyQuarry

PropertyQuarry is a dedicated property discovery product built out of the Executive Assistant property-search lane.

It is aimed at renters and buyers who want:

- cross-platform property discovery
- profile-based ranking
- deeper AI research on shortlisted listings
- hosted property review pages
- optional alerts and agent-assisted follow-up

## Initial product stance

- consumer-first
- English-language product shell
- multilingual property brief defaults
- multi-country provider selection
- market-aware budget posture by country and currency
- freemium onboarding
- paid research and agent tiers
- shared backend heritage with EA during the extraction phase

## Core promise

Find properties that fit the person, not just the filter.

PropertyQuarry should turn fragmented listings into:

- ranked matches
- personalized fit reasoning
- researched property packets
- hosted review pages
- optional 360/tour enrichment when available

Current market layer targets:

- Austria
- Germany
- Switzerland
- United Kingdom
- Spain
- Italy
- France
- Netherlands
- United States

## Planned surfaces

- public landing
- public pricing
- onboarding
- authenticated search workspace
- property review pages
- alerts and saved searches
- paid upgrade flow

## Repository structure

- [docs/PRODUCT_BRIEF.md](docs/PRODUCT_BRIEF.md)
- [docs/BRAND.md](docs/BRAND.md)
- [docs/PRICING.md](docs/PRICING.md)
- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)
- [docs/ROADMAP.md](docs/ROADMAP.md)
- [docs/DOMAIN_ROLLOUT.md](docs/DOMAIN_ROLLOUT.md)

## Extraction principle

The product should be extracted as a dedicated frontend and commercial shell first, while reusing the proven EA property-search backend until the domain model and revenue loop are stable.

## Local environment

Use [.env.example](.env.example) as the local starting point for:

- `PROPERTYQUARRY_PUBLIC_BASE_URL`
- `PAYFUNNELS_API_KEY`
- `PAYFUNNELS_WEBHOOK_SECRET`
- `PAYPAL_CLIENT_ID`
- `PAYPAL_SECRET`
- `PAYPAL_ACCOUNT_EMAIL`

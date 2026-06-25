# Brilliant Directories Integration

Brilliant Directories is PropertyQuarry's governed public directory projection lane. It can support public partner, provider, agent, relocation, and local-service directories after rights and account verification pass.

It must not own property facts, listing truth, ranking, search scope, user preferences, billing truth, entitlements, or publication approval.

## Allowed Uses

- Public partner/provider directory profile projection.
- Public agent or service-resource directory records.
- Operator-reviewed import/export checks.
- Directory webhook receipts after signature and replay controls are verified.
- Governed white-label billing handoff when PropertyQuarry remains the source of truth for plans, invoices, entitlements, and access checks.

## Forbidden Inputs

- Raw provider crawl payloads.
- Portal credentials or Brilliant Directories admin credentials.
- Private user preferences, commute destinations, family or medical notes.
- Search-run payloads, ranking scores, property facts, listing truth, or shortlist decisions.
- Billing, payment, invoice, entitlement, or access-check source-of-truth data.
- Seller, agent, WhatsApp, Telegram, phone, or private email contact details unless an explicit public-directory rights review allows that field.

## Runtime Flags

All flags default to off.

```env
PROPERTYQUARRY_BRILLIANT_DIRECTORIES_ENABLED=0
PROPERTYQUARRY_BRILLIANT_DIRECTORIES_API_ENABLED=0
PROPERTYQUARRY_BRILLIANT_DIRECTORIES_DISABLED=0
PROPERTYQUARRY_BRILLIANT_DIRECTORIES_BASE_URL=
PROPERTYQUARRY_BRILLIANT_DIRECTORIES_ALLOWED_HOSTS=
PROPERTYQUARRY_BRILLIANT_DIRECTORIES_API_KEY_HEADER=X-Api-Key
PROPERTYQUARRY_BRILLIANT_DIRECTORIES_API_KEY=
PROPERTYQUARRY_BRILLIANT_DIRECTORIES_COMPLETION_DIR=_completion/brilliant_directories
```

The adapter requires HTTPS and an explicit allowed-host list before API requests can be built or executed. Customer-facing directory and pricing surfaces stay on PropertyQuarry; there is no public provider-site or provider-pricing redirect knob. API payloads are form-encoded by default because Brilliant Directories' own examples use `application/x-www-form-urlencoded` for member create, delete, search, and transaction calls.

## Implemented Local Contract

The runtime contract is intentionally narrow:

- Build redacted, host-allowlisted Brilliant Directories API requests.
- Build public member-search requests for `/api/v2/user/search`.
- Build public member-detail requests for `/api/v2/user/get/{user_id}`.
- Execute bounded JSON API requests with redirects blocked, non-JSON responses rejected, and a 2 MB response cap.
- Project returned member rows into `public_directory_profile` records only.
- Expose the authenticated white-label PropertyQuarry runtime lane at `/app/api/property/directories/members`.
- Keep `/app/api/property/directories/brilliant-directories/members` only as a compatibility/provider receipt lane, not as the product-facing endpoint.
- Expose the white-label public directory at `/directory`; the page stays on PropertyQuarry while Brilliant Directories supplies public-safe profile records.
- Expose public profile details at `/directory/profile/{profile_id}` so profile navigation stays on PropertyQuarry.
- Keep `/pricing` PropertyQuarry-hosted. If Brilliant Directories manages pricing content later, sync the content into the local pricing surface instead of redirecting customers off-domain.
- Strip provider contact, address, location-coordinate, billing, token, ranking, property-fact, and private preference fields from provider responses.
- Keep imported profile URLs only when they are relative directory paths or absolute HTTPS URLs on the configured Brilliant Directories allowed-host list.
- Keep publication disabled until rights review and human approval exist.

The runtime lane only accepts public directory search terms such as keyword, category, city, country, page, and limit. It does not send private user profile data, search-run payloads, listing facts, saved-search names, rankings, or property decisions to Brilliant Directories.

The adapter does not create users, posts, leads, invoices, reviews, property listings, or public pages. Those require a separate rights and approval gate. Billing handoff is limited to an HTTPS, allowlisted, white-label account/payment URL; local plan state and entitlement checks must continue to come from PropertyQuarry-owned records.

## Billing Handoff Contract

Brilliant Directories billing support is a premium-account convenience, not a billing authority.

PropertyQuarry owns:

- customer identity and account creation;
- current plan and agent-tier entitlement;
- invoice and payment-status display;
- search/result limits and unlimited agent-tier behavior;
- refund, cancellation, renewal, failed-payment, and support state;
- access checks for search, shortlist, research, tours, walkthroughs, notifications, and exports.

Brilliant Directories may provide only:

- a white-label HTTPS checkout or account-management handoff URL after host allowlist validation;
- public-safe directory profile data after field-rights review;
- signed webhook notifications that are stored as receipts and reconciled locally before any user-visible state changes.

Every billing state must have a local receipt. `/app/billing` is not a local plan/payment page; it redirects to the configured white-label Brilliant Directories account lane. If Brilliant Directories is unavailable, misconfigured, unsigned, replayed, returns a non-allowlisted URL, or the white-label billing host does not resolve, PropertyQuarry must fail closed instead of rendering a local billing board.

## Verification

```bash
PYTHONPATH=ea python3 scripts/verify_brilliant_directories_provider.py
```

The default verification is mostly dry and writes a redacted provider receipt that records whether configuration is disabled or ready, and whether the local request executor, redirect blocking, byte limit, public projection, billing handoff, and private-field stripping contracts are present. When a white-label billing URL is configured, the verifier performs a DNS resolution check for that host and blocks release if the target does not resolve.

## Provider Sources

The integration is based on Brilliant Directories' official developer docs for API endpoints, API key generation, member search, member posts, and webhooks:

- https://bootstrap.brilliantdirectories.com/support/solutions/articles/12000101842-brilliant-directories-api-endpoints-technical-reference
- https://bootstrap.brilliantdirectories.com/support/solutions/articles/12000088768-developer-hub-generate-api-key-overview
- https://bootstrap.brilliantdirectories.com/support/solutions/articles/12000083005-developer-hub-webhooks
- https://support.brilliantdirectories.com/support/solutions/articles/12000102884-how-to-search-for-members-through-the-api
- https://support.brilliantdirectories.com/support/solutions/articles/12000093239-member-posts-api-create-search-update-delete-and-get

## Production Promotion Checklist

- Live login and account tier receipt captured.
- API key stored only in runtime secrets.
- Base URL and allowed host point to the approved Brilliant Directories site.
- Import/export/delete behavior verified.
- Public-directory field rights reviewed.
- Webhook signature and replay controls implemented before accepting callbacks.
- Billing webhook signature, replay protection, and local entitlement reconciliation implemented before any Brilliant Directories event can change access.
- Human approval remains required before any public PropertyQuarry surface uses directory output.

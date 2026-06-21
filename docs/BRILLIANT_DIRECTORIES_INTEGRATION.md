# Brilliant Directories Integration

Brilliant Directories is PropertyQuarry's governed public directory projection lane. It can support public partner, provider, agent, relocation, and local-service directories after rights and account verification pass.

It must not own property facts, listing truth, ranking, search scope, user preferences, billing, or publication approval.

## Allowed Uses

- Public partner/provider directory profile projection.
- Public agent or service-resource directory records.
- Operator-reviewed import/export checks.
- Directory webhook receipts after signature and replay controls are verified.

## Forbidden Inputs

- Raw provider crawl payloads.
- Portal credentials or Brilliant Directories admin credentials.
- Private user preferences, commute destinations, family or medical notes.
- Search-run payloads, ranking scores, property facts, listing truth, or shortlist decisions.
- Billing, payment, invoice, or entitlement data.
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

The adapter requires HTTPS and an explicit allowed-host list before API requests can be built.

## Verification

```bash
PYTHONPATH=ea python3 scripts/verify_brilliant_directories_provider.py
```

The default verification is dry and makes no live network request. It writes a redacted provider receipt that records whether configuration is disabled or ready.

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
- Human approval remains required before any public PropertyQuarry surface uses directory output.

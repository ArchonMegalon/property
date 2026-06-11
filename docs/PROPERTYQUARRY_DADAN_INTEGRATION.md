# PropertyQuarry Dadan Integration

Dadan is the interactive video communication and feedback layer for PropertyQuarry. It captures human video evidence and reviewer reactions; PropertyQuarry decides what that evidence means.

## Role

- Agent or seller missing-fact recording requests
- Family/advisor video reactions
- Optional public education or onboarding videos
- Transcript-backed reviewer signals after owner review

Dadan must not be source of truth for property facts, legal conclusions, investment scoring, private preference logic, PDF rendering, 3D tours, or Telegram delivery.

## Runtime Modes

```env
PROPERTYQUARRY_DADAN_ENABLED=0
PROPERTYQUARRY_DADAN_MODE=manual
DADAN_API_KEY=
DADAN_BASE_URL=https://app.dadan.io/api/v1
DADAN_WEBHOOK_SECRET=
PROPERTYQUARRY_DADAN_WEBHOOK_ALLOW_BASIC_AUTH=1
PROPERTYQUARRY_DADAN_REQUIRE_OWNER_REVIEW=1
PROPERTYQUARRY_DADAN_PRIVATE_VIDEO_DOWNLOAD=0
```

Modes:

- `disabled`: fail closed
- `manual`: create local/manual request records only
- `api_dry_run`: create deterministic dry-run Dadan request URLs
- `api_live`: call Dadan's recording-request API

## Endpoints

Authenticated request creation:

```http
POST /app/api/property-video/requests/dadan
```

Public webhook ingest:

```http
POST /v1/integrations/dadan/webhooks/recording-submitted
```

Webhook auth accepts `x-propertyquarry-webhook-secret`, `x-dadan-webhook-secret`, or Basic auth when enabled. Query-string secrets are rejected.

## Trust Policy

Every Dadan webhook response is stored as:

```text
trust_state = untrusted_external
review_state = pending_owner_review
```

Raw Dadan videos and transcripts must not be sent to NeuronWriter, public reports, public PDFs, anonymous aggregate risk models, or preference learning until redacted and owner-reviewed.

## Current Implementation

- Dadan request adapter with disabled, dry-run, and live API modes
- Authenticated recording-request creation
- Public recording-submitted webhook ingest
- Event-backed request/response lifecycle using PropertyQuarry packet events
- Dadan answer/transcript normalizer for structured feedback
- Contract tests for disabled default, dry-run request creation, webhook auth, untrusted ingest, and feedback normalization

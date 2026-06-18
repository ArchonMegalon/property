# Subscribr Content Studio

Subscribr is PropertyQuarry's governed video-script and content pre-production lane. PropertyQuarry creates the approved source packet, Subscribr drafts script material, and PropertyQuarry validates every claim before a human review.

## Boundary

Subscribr may draft:

- product tutorials;
- renter, buyer, relocation, and research education;
- city and market explainers;
- source-bound dossier explainers;
- tour narration, shot lists, titles, hooks, descriptions, and thumbnail concepts.

Subscribr must not own listing truth, fit score, ranking, market-price truth, investment recommendations, neighbourhood truth, tour truth, billing, entitlement, or publication approval.

## Runtime

All switches are disabled by default:

```env
PROPERTYQUARRY_SUBSCRIBR_ENABLED=0
PROPERTYQUARRY_SUBSCRIBR_API_ENABLED=0
PROPERTYQUARRY_SUBSCRIBR_DIRECT_PUBLISH_ENABLED=0
SUBSCRIBR_PROPERTY_SCRIPT_API_TOKEN=
SUBSCRIBR_PROPERTY_WEBHOOK_SECRET=
SUBSCRIBR_PROPERTY_CHANNEL_MAP_JSON=
```

Direct publication stays disabled. Provider output is draft content until PropertyQuarry validation and human approval pass.

## Operator Flow

1. Build a sanitized PropertyQuarry content source packet.
2. Validate privacy, source binding, freshness, fair-housing, legal, financial, and media-rights posture.
3. Create a Subscribr idea/script only when both API flags are enabled.
4. Export Markdown and hash it.
5. Validate the script against the source packet.
6. Create a human-review task or receipt.
7. Hand approved copy to the media factory only after review.

Operator surface:

```http
GET /admin/property/content-studio
```

Webhook:

```http
POST /internal/providers/subscribr/webhook
```

The webhook requires an HMAC SHA-256 body signature in `x-subscribr-signature` and rejects replayed event IDs.


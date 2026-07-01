# PropertyQuarry Sendr Outreach Lane

Sendr is a governed outbound-growth lane for PropertyQuarry. It may help create reviewed B2B outreach, demo pages, and engagement receipts. It does not own property truth.

## Product Boundary

Allowed use:

- Relocation-partner outreach.
- Buyer-agent and property-scout outreach.
- Property-manager or landlord-adjacent education, with careful claims.
- Agent-tier pilot invitations.
- City-guide and viewing-prep education.
- Partner or affiliate conversations.

Forbidden use:

- Listing truth, ranking truth, market-price truth, investment suitability, legal conclusions, neighbourhood truth, tour truth, billing entitlement, user preference truth, publication approval, or private user profile data.
- Raw provider payloads, portal credentials, saved-search details, exact private commute destinations, feedback history, payment data, seller/private agent contacts, sensitive household data, or private review packets.
- Direct send, auto-reply, WhatsApp outreach, or high-volume enrollment by default.

## Architecture

```text
PropertyQuarry source packet
  -> Sendr campaign packet
  -> local policy validation
  -> human copy and recipient review
  -> Sendr preview or limited pilot
  -> engagement receipt
  -> PropertyQuarry / EA Signal Inbox review
```

PropertyQuarry remains the system of record for campaign policy, recipient basis, suppression state, reply triage, leads, and follow-up commitments.

## Campaign Packet

Use `propertyquarry.sendr_campaign_packet.v1`.

Required posture:

- Campaign type is one of `RELOCATION_PARTNER_OUTREACH`, `BUYER_SCOUT_OUTREACH`, `AGENT_TIER_PILOT`, `CITY_GUIDE_PROMOTION`, `PROPERTYQUARRY_DEMO_BOOKING`, or `PARTNER_AFFILIATE_OUTREACH`.
- Source material is reviewed public material, an approved product brief, an approved demo packet, or a synthetic/public demo dossier.
- Every recipient has `recipient_basis`, `source_url_or_note`, `jurisdiction`, `allowed_channel`, and `suppression_status`.
- `human_review_required` is true.
- `direct_send_allowed` and `auto_reply_allowed` are false.
- WhatsApp is false in channels and features.

## Validation Gates

The local policy blocks:

- Unsupported claims such as guaranteed fit, best property, safe neighbourhood, risk-free investment, exclusive inventory, legal advice, or guaranteed return.
- Private data keys such as private user profiles, portal credentials, payment data, medical/family details, private saved searches, or exact private commute destinations.
- Fair-housing and anti-steering violations.
- Recipients without documented basis, source, jurisdiction, allowed channel, and non-suppressed status.
- Any direct-send or auto-reply switch.

`forbidden_claims` and `recipient_policy.forbidden_recipient_basis` are documentation fields in the packet and are intentionally not treated as attempted claims.

## Runtime Defaults

All Sendr runtime switches are off in `.env.example`.

```env
PROPERTYQUARRY_SENDR_ENABLED=0
PROPERTYQUARRY_SENDR_API_ENABLED=0
PROPERTYQUARRY_SENDR_WEBHOOKS_ENABLED=0
PROPERTYQUARRY_SENDR_WHATSAPP_ENABLED=0
PROPERTYQUARRY_SENDR_DIRECT_SEND_ENABLED=0
PROPERTYQUARRY_SENDR_AUTO_REPLY_ENABLED=0
```

API work must not be enabled until provider verification, suppression sync, human review, and a first limited-pilot receipt pass.

## First Pilot

Start with one Vienna relocation-partner pilot:

- 50 contacts maximum.
- Email first.
- LinkedIn only after manual verification.
- WhatsApp disabled.
- Synthetic/public demo dossier.
- Short approved demo page or video.
- Manual review for every follow-up.

Success gate:

- 3 to 5 real demo conversations.
- No compliance complaints.
- Suppression sync verified.
- Reply triage produces review candidates only.
- Campaign and engagement receipts complete.

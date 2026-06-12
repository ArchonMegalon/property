# PropertyQuarry Analytics Taxonomy

Rybbit and any future analytics provider are public-safe measurement lanes. Analytics must improve the product loop without carrying exact private property payloads, raw notes, personal identifiers, or signed URLs.

## Event Names

```text
pq.search.started
pq.search.results_viewed
pq.search.agent_created
pq.search.agent_notification_sent
pq.search.suppressed_viewed
pq.property.opened
pq.property.map_opened
pq.dossier.opened
pq.tour.opened
pq.flythrough.opened
pq.decision.saved
pq.reason.selected
pq.agent_question.created
pq.document.requested
pq.packet.shared
pq.email.clicked
```

## Allowed Properties

```text
country_code
region_code
listing_mode
property_type
decision_mode
fit_bucket
provider_key
provider_family
provider_quality_bucket
surface
cta_key
```

## Forbidden Properties

```text
exact address
property URL
signed link token
email
phone
principal ID
Telegram chat ID
raw household note
raw Dadan transcript
document text
```


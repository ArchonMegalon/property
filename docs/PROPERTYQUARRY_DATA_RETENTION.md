# PropertyQuarry Data Retention

PropertyQuarry handles property facts, private packets, Telegram events, tour assets, MagicFit references, Dadan videos, signed links, and operator projections. Retention must be explicit because the product loop learns from decisions without turning every raw artifact into permanent memory.

## Default Rules

```text
personal reference images expire unless pinned by the owner
Dadan recordings remain external untrusted links until owner review
private PDFs and signed packet links must be revocable
Telegram metadata is retained only as needed for delivery receipts and decision history
Teable projections are derived views and must be deletable from the PropertyQuarry source record
public tour assets can outlive the private packet only when privacy mode allows publication
raw provider diagnostics stay operator-only
```

## Delete / Revoke Actions

```text
delete private MagicFit reference media
revoke signed PDF or packet links
remove a Dadan response from owner-review queues
delete or pause a search agent
remove Teable projection rows by source property record
export/delete owner decision history on account request
```

## Product Contract

```text
private media is never sent to public analytics
raw household feedback is owner-private by default
public market intelligence uses aggregate reason keys, not raw notes
document intake records carry privacy class and redaction state
```

## Data-Class Matrix

| Data class | Examples | Default retention | Required control |
| --- | --- | --- | --- |
| Account profile and saved defaults | identity, market defaults, delivery preferences | until account deletion | export account data, edit settings, delete account |
| Search preferences | selected areas, hard rules, What Matters preferences | until changed or account deletion | edit search, load/save What Matters, export account data |
| Search runs | run status, ranked and filtered summaries, repair receipts | compact saved results stay until the user deletes them; full payloads compact after the configured retention window | clear search history, delete individual run, export account data |
| Source listing cache | provider result URLs and normalized listing snippets | short operational cache only | TTL expiry, provider-rights review, no customer export of internal diagnostics |
| Canonical property passport | property identity, dedupe links, claim history, decisions | until user deletion or project deletion | export account data, delete property/project, revoke shared links |
| Decisions and feedback | yes/maybe/no, rejection reasons, fit feedback | owner-private until deleted | export decisions, delete decision history, aggregate only with consent and thresholds |
| Documents and evidence | uploaded PDFs, official evidence, extracted claims | until project/account deletion unless shorter source rights apply | delete document, revoke packet, preserve source/version receipts |
| Private packets and dossiers | signed PDFs, private packet manifests, appendix receipts | until user revokes or retention window expires | revoke signed PDF or packet links, delete generated dossier |
| Public packets and tours | redacted manifest, public assets, static share links | until explicit expiry/revocation | manage public links, revoke share, delete underlying static asset |
| Generated media | floorplan assets, walkthrough receipts, MagicFit/Dadan references | owner-private until reviewed; public only after privacy gate | request generation, approve publication, delete media |
| Delivery receipts | email, Telegram, WhatsApp status, quiet-hour receipts | limited operational period | delivery center, unsubscribe/STOP handling, receipt deletion by retention job |
| Access sessions and links | account access links, active sessions, revocations | until expiry plus audit window | active sessions, revoke session/link, rotate signing keys |
| External investment data | third-party valuation/rent/yield feed cache | durable protected cache with host allowlist and TTL | configured allowed hosts, cache prune, source attribution |
| Analytics events | page/control events without private payloads | aggregate operational analytics only | analytics preference, no run/listing/exact-location payloads |

## Revocation Semantics

Revocation must remove customer access and make stale artifacts undiscoverable. For public packets, tours, and generated media this means the source record and the static file or manifest both leave the public route. Hiding a link in the account UI is not enough.

Public-tour revocation is fail-closed at the origin. The owner-scoped revocation receipt is written before the bundle is removed, revoked slugs return `410`, and public responses use revalidation-safe cache headers. A durable CDN purge outbox records the affected tour page, manifest, asset paths, and surrogate key. Queuing is not completion: the receipt stays `queued` with `provider_invoked: false` until a CDN worker attaches its purge receipt.

## Account Export and Erasure Lifecycle

Account exports are subject-scoped snapshots with signed cursors. Every page carries the same snapshot time, stable collection counts, a next cursor, and an explicit `complete` flag. The downloadable form requests the complete snapshot. It includes searches, shortlists, saved and learned preferences, owned tours and their private owner receipts, artifacts, packet events, connected-provider bindings, delivery logs, account events, and access-session status. Access tokens, provider credentials, authorization headers, signed-link tokens, secrets, and cookies are always redacted.

Account erasure is a durable, idempotent workflow:

```text
request -> awaiting explicit DELETE confirmation -> revoke sessions -> revoke tours
-> queue CDN purge receipts -> remove local provider bindings
-> queue provider deletion receipts -> remove searches/shortlists/preferences
-> remove packets/artifacts/events/delivery logs -> seal digest-only tombstone
```

Before confirmation, cancellation is a real recovery path and no data is deleted. After confirmation, completed phases are irreversible; a failed retry resumes only incomplete phases. Provider retry only re-queues receipt work and must never be reported as provider deletion until a provider-issued receipt is attached.

## Backup Tombstone Policy

The primary-store closeout writes an erasure tombstone containing a keyed subject digest, phase receipts, the backup expiry deadline, and legal-hold state. It must not retain the raw principal identifier, access token, provider credential, or confirmation phrase.

Rolling backups expire by `backup_delete_by` (35 days by default, configurable for an approved infrastructure policy). Any disaster recovery restore must load erasure tombstones before customer services start and reapply each deletion before routes, search workers, delivery workers, or provider workers can see the restored rows. A legal hold is never inferred: it must be explicit, scoped, time-bounded, and visible in the lifecycle receipt. The digest-only tombstone may outlive source data solely to prevent reactivation and prove closeout.

## Aggregated Learning

Cross-customer learning can only use normalized reason keys after consent, minimum cohort thresholds, and removal of raw notes, exact locations, personal identifiers, agent accusations, and protected-attribute proxies. Owner-private feedback remains private by default.

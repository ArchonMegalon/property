# PropertyQuarry database compaction and Teable projection design v1

Date: 2026-07-12 (Europe/Vienna)

State: `design_only_no_live_database_mutation`

## Decision

Keep Postgres as the transactional source of truth, move immutable bulky
payloads to encrypted content-addressed object storage, and use Teable only as
a compact operator projection and intent-entry surface.

Teable must never contain raw preferences, source documents, scene graphs,
media bytes, provider payloads, credentials, or unrestricted error traces.
Edits made in Teable are proposals. A PropertyQuarry service validates each
proposal as an `AdminIntent` before changing canonical state.

## Measured problem

The 2026-07-12 live snapshot showed:

- database size: approximately 54 GB;
- `property_search_runs`: approximately 54 GB across about 6,096 rows;
- table heap: approximately 1.4 MB;
- indexes: approximately 28 MB;
- TOAST: approximately 53 GB;
- current logical `payload_json` values: approximately 11.5 GB; and
- compact summaries for all runs: approximately 85 MB.

The gap between current logical bytes and TOAST bytes is dead or reusable
storage caused by repeatedly updating large JSON values. Some payloads contain
`property_search_preferences.raw_preferences` recursively, amplifying a single
logical preference object to tens of megabytes before compression. Status and
progress changes then rewrite those oversized TOAST values.

## Target ownership

### Postgres

Postgres owns small, queryable, transactional records:

1. `property_search_runs_v2`
   - `run_id`, owner/tenant reference, state, progress and state version;
   - created, started, updated, completed and expiry timestamps;
   - style/tour request identifiers needed for dispatch;
   - compact result and quality summaries with strict byte limits;
   - preference snapshot digest;
   - source archive digest and execution archive digest;
   - current artifact/manifest digest references;
   - retention, deletion and legal-hold state; and
   - last event sequence and projection version.
2. `property_search_preference_snapshots`
   - one immutable canonical snapshot per SHA-256 digest;
   - bounded canonical JSON, schema version, byte length and creation time;
   - no nested `raw_preferences` member at any depth; and
   - deduplication by tenant-safe digest key.
3. `property_search_run_events`
   - append-only bounded events for state transitions and progress;
   - monotonic sequence per run and idempotency key;
   - compact typed payload with a hard byte ceiling; and
   - no full run snapshot in an event.
4. `property_search_projection_outbox`
   - transactional outbox for Teable and other projections;
   - canonical event digest, projection version, retry state and receipt; and
   - no raw archive content.

Normal progress updates touch only narrow scalar columns and append one small
event. They never rewrite an archive or preference snapshot.

### Encrypted object storage

Object storage owns full immutable payloads and media:

- canonical JSON compressed with zstd, then encrypted with an approved
  envelope-encryption key route;
- content addressed by SHA-256 of the canonical plaintext and stored under a
  controller-owned opaque key;
- immutable create-if-absent semantics and digest verification on every read;
- separate source, execution, proof and artifact objects so retention classes
  can differ;
- object metadata limited to schema version, encrypted byte length, digest,
  retention class and creation time; and
- tombstone-before-delete with deletion receipts covering replicas and
  derivatives.

Postgres stores only digest references. A digest is not a public URL and does
not grant access.

### Teable

Teable is a Class C5 admin projection. Use one row per run with only:

- `run_id`, state, progress, state version and updated time;
- style, requested output and non-sensitive dispatch class;
- room coverage, continuity, FPS and verification summaries;
- proof/capability state and public provider labels where approved;
- artifact, manifest and archive digests, never object URLs;
- retention/deletion status and operator attention reason;
- projection version, canonical event sequence and last sync receipt; and
- bounded operator actions such as retry request, hold request or review
  outcome.

Every Teable-originated action becomes a signed or authenticated `AdminIntent`
with expected state version, actor, reason, expiry and idempotency key. The
canonical service rejects stale, unauthorized or invalid intents and writes
the resulting canonical event before the projection updates.

Teable outages or stale rows must not block search, tour generation, privacy
deletion or canonical operator APIs.

## Write-time guards

Apply guards before dual-write begins:

- reject a `raw_preferences` member below the accepted top-level compatibility
  boundary;
- reject recursive object identity and depth above 12;
- reject more than 2,000 keys or 256 entries in any collection;
- reject canonical preference snapshots above 256 KiB;
- reject compact run summaries above 64 KiB;
- reject run events above 16 KiB;
- normalize once, compute the digest once and store immutable bytes once; and
- expose static validation reason codes without reflecting rejected values.

Legacy requests that exceed a limit fail explicitly or are transformed by a
versioned, audited compatibility adapter. They are never silently truncated.

## Migration

1. Freeze the v2 schemas, archive envelope and retention policy. Add metrics
   for old/new reads, logical bytes, object bytes and write amplification.
2. Deploy input guards and stop recursive preference construction on the old
   path before copying data.
3. Create v2 tables and the projection outbox without changing reads.
4. Backfill oldest terminal runs first in small idempotent batches. Canonicalize
   and deduplicate preferences, archive full payloads, verify object digests,
   then insert thin rows and events in one database transaction.
5. Dual-write new runs to v2 while preserving the old write for rollback.
   Compare state, summaries, digests and retention decisions continuously.
6. Shadow-read v2 and require byte/digest equality for every reconstructable
   field. Quarantine mismatches; do not guess or delete the old row.
7. Switch reads by stable cohort, then switch canonical writes to v2. Keep the
   old table read-only for the rollback window.
8. Verify privacy deletion against Postgres, object replicas, derivatives and
   Teable projection receipts.
9. After the rollback window and an independently reviewed deletion manifest,
   replace or drop the old table. Reclaim disk through table replacement/drop;
   ordinary `VACUUM` will not return the approximately 42 GB of excess TOAST
   space to the filesystem, and an in-place `VACUUM FULL` is not the preferred
   live migration path.

## Rollback

Before old-table deletion, rollback changes the read/write feature flags back
to v1 and stops projection consumers. Archived objects and v2 rows remain
immutable evidence and are not deleted by application rollback.

After old-table deletion, rollback uses the verified archived payload plus v2
events to reconstruct a compatibility view; it does not restore recursively
nested JSON or resume large-payload status rewrites.

## Acceptance gates

Promotion requires all of the following:

- 100% backfill coverage or an explicit quarantined-row manifest;
- zero unexplained digest, state, retention or deletion mismatches;
- p95 normal run-row size below 32 KiB and event size below 8 KiB;
- no `raw_preferences` recursion in accepted writes;
- status updates produce no archive/object rewrite;
- Teable contains no prohibited field in schema or sampled rows;
- Teable write-back cannot mutate state without canonical intent validation;
- deletion tests cover Postgres, object replicas, derivatives and Teable;
- restore drills reconstruct sampled runs from v2 plus archived objects; and
- a clean canary and rollback drill before old-table destruction.

The expected steady-state Postgres footprint for this workload is about 1-2
GB, excluding separately governed indexes and future growth. This is a target,
not a readiness claim; it must be demonstrated after backfill and table swap.

# PropertyQuarry evidence-overlay temporal contract

The machine authority is `PROPERTYQUARRY_EVIDENCE_OVERLAY_REGISTRY.json` v2. A
launch receipt must use `propertyquarry.evidence_overlay_read_model_receipt.v3`.
Older registry and receipt versions do not satisfy this contract.

## Two different clocks

- `cache_updated_at` says when PropertyQuarry materialized the cached rollup. It
  is an operational cache-recency signal only. It does not prove that the source
  itself is recent.
- `source_updated_at` says when the source observation, publication, or dataset
  release was updated. Reference rows also carry a calendar-valid
  `reference_period` such as `2024` or `2021-06/2022-08`.
- A `current_feed` row additionally carries `source_checked_at`. This is when
  the upstream feed was checked. A freshly checked feed may legitimately
  contain a 30- or 90-day-old article; the article publication time must not be
  rewritten to make the feed look fresh.

All three timestamps are retained separately in the row and receipt. Cache
recency is never labeled or rendered as source freshness.

## Cadence classes

| Layer | Cadence class | Launch-time source-age rule |
| --- | --- | --- |
| Environmental quality | `live` | Every live `source_updated_at` must satisfy the layer SLA. |
| Public mobility | `live_or_reference` | Live rows use the live SLA; stop geometry and other reference rows require a reference period and have no invented hourly SLA. |
| Media attention | `current_feed` | `source_checked_at` must satisfy the feed SLA; article `source_updated_at` remains the publication time. |
| Summer heat, traffic/noise, schools, fiber/broadband | `reference_dataset` | A valid reference period is required; cache recency does not make the source dataset current. |
| Official safety context | `annual_context` | A valid reference period is required; no invented 48-hour source SLA applies. |

The registry may set `source_max_age_hours_by_temporality` only for `live` and
`current_feed`. Reference rows deliberately have no generic maximum source age.
They can still be explicitly marked `stale` by a source steward.

## UI states

`unavailable`, `stale`, and `verified` remain the public compatibility states.
For a reference dataset, `verified` means its provenance, uncertainty, and
declared reference period passed policy; it does not mean the source was updated
recently. An expired cached copy may render `stale`, but the copy states that
cache expiry does not establish source freshness or source staleness.

## Claim boundaries

- Every row requires explicit uncertainty and source provenance.
- `property_scoring` and `person_scoring` can never be enabled. The official
  safety layer requires explicit `false` values, aggregate geographic scope,
  and a source-rights caveat.
- Municipal RSS is first-party municipal notice material. It must carry
  `media_source_class=municipal_rss` and `independent_press=false`, and the UI
  states that it is not independent press.
- Media classification fields are valid only on `media_attention`; safety claim
  fields are valid only on `official_safety_context`.

## Deliberate limitation

The contract validates timing, provenance shape, and claim boundaries. It does
not invent source-update schedules for annual or irregular official datasets.
Dataset-specific acquisition, licensing, geographic normalization, and source
withdrawal checks still require governed ingestion evidence.

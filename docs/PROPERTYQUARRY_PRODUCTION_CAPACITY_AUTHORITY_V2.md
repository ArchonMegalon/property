# PropertyQuarry production capacity authority v2

Global Launch/Core capacity authority is established only by a fresh
`propertyquarry.production_capacity_receipt.v2` artifact accepted by the
installed global-launch terminal. The repository does not contain a passing
live receipt and does not provide a command that can mint one.

The receipt contract is
`packaging/propertyquarry-global-launch-terminal/propertyquarry-production-capacity-receipt.v2.schema.json`.
The installed bundle pins the same bytes at
`/usr/libexec/propertyquarry/runtime/schema/propertyquarry-production-capacity-receipt.v2.schema.json`.
Every receipt carries that file's SHA-256; the terminal independently hashes
the packaged contract before evaluating evidence.

## Authority boundary

The receipt must be produced from the protected `propertyquarry-production`
deployment for the exact release commit and immutable image digest in the
terminal manifest. Its artifact digest is included in the release controller's
signed terminal-attestation map. `status: pass`, legacy readiness booleans, a
source-only assertion, and an unsigned or differently bound JSON file are not
capacity authority.

`scripts/propertyquarry_capacity_evidence.py` remains a bounded local diagnostic.
Its `propertyquarry.local_capacity_evidence.v1` output intentionally declares
`production_capacity_established: false`. Its schema and evidence level cannot
satisfy this v2 production contract, even if the file is renamed, rehashed, or
wrapped with passing booleans.

## Closed receipt and numeric invariants

The receipt contains no `capacity_ready`, `headroom_verified`, or
`limits_verified` switches. Unknown and missing fields fail closed. It names
exactly these resources, once each, using their governed unit:

| Resource | Unit |
| --- | --- |
| API | `requests_per_second` |
| Database | `active_connections` |
| Queue | `queued_jobs` |
| Scheduler | `jobs_per_minute` |
| Browser workers | `concurrent_workers` |
| Render workers | `concurrent_workers` |
| Provider quotas | `requests_per_quota_window` |
| Memory | `mebibytes` |
| CPU | `millicores` |
| PIDs | `processes` |
| Disk | `mebibytes_per_second` |
| Network | `kilobits_per_second` |

For every resource, the terminal recomputes and enforces all of the following:

- The resource window exactly matches the receipt window, lasts 300 to 86,400
  seconds, and contains at least two samples.
- `required_peak` is exactly the greater of observed and forecast peak.
- The operational limit is no greater than independently verified sustainable
  capacity and exceeds required peak.
- Absolute headroom is exactly `operational_limit - required_peak`; basis-point
  headroom is the integer recomputation of that value and is at least 2,500
  basis points (25%). Verified sustainable capacity has its own evidence digest.
- An over-limit test made at least one attempt, admitted none, and accounted for
  every attempt as controlled.
- A saturation test offered more than the operational limit, admitted exactly
  the limit, accounted for every excess item as deferred or rejected, recorded
  no uncontrolled failures or accepted-work loss, and recovered within 3,600
  seconds.
- Telemetry, sustainable-capacity, limit-test, and backpressure evidence have
  valid, non-placeholder, receipt-unique SHA-256 digests.

The terminal also recomputes resource count, total samples, minimum headroom,
and maximum recovery time instead of trusting the summary values.

## Freshness

The observation and measurement-window end must be no more than 900 seconds old
at terminal evaluation and no more than 30 seconds in the future. The receipt
must be emitted after the measurement window and within 300 seconds of its end.
All timestamps are explicit UTC `Z` timestamps. A stale receipt cannot be made
current by editing only `observed_at`, because every resource is bound to the
same checked window and the controller attests the complete artifact digest.

## Required live producer

The remaining live prerequisite is an independently governed capacity runner
that can observe exact-release production telemetry, execute authorized bounded
limit and saturation trials for all twelve resources, preserve the referenced
evidence objects, and hand the closed receipt to the protected release
controller. Creating that runner, choosing safe production test windows, or
changing limits/provider capacity requires separate operational authority. The
terminal deliberately remains `BLOCKED` when that evidence is absent.

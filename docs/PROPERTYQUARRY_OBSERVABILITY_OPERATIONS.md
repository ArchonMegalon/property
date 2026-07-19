# PropertyQuarry observability operations

The canonical dashboard contract is
`config/monitoring/propertyquarry_flagship_operations.v1.json`. Its byte hash
is part of the release-control challenge. Source validation is necessary but
does not prove that a dashboard, log store, or tracing backend is deployed.
Global launch remains blocked until the protected controller authenticates a
fresh, exact-release operations receipt covering dashboard rendering, a
correlated structured-log query, distributed trace continuity, and alert
delivery.

## Distributed admission

Inspect admission backend outcomes, bounded rejection dimensions, high-cost
in-flight work, and cost-unit rate together. Any production memory backend,
unavailable shared backend, or unexplained sustained rejection increase is a
stop condition. Confirm the exact release and replica labels before changing
capacity or policy.

## Admission capacity

The `admission_capacity` panel is release-bound proof of the shared PostgreSQL
v17 guard, not a tunable quota dashboard. Every production replica must expose
a valid contract sample plus the `lease` and `quota` row-count/limit gauges.
The fixed limits are `100000` lease rows and `1000000` quota rows; warning and
critical headroom thresholds are 80 and 95 percent. The panel aggregates the
shared values across replicas while the alert rules separately fail closed on
a missing or invalid per-replica contract sample. Follow the SLO runbook on
drift or pressure, and do not mutate the capacity state through observability
credentials.

## Log correlation

Start with the customer-safe `x-correlation-id`, then query the structured log
store for that exact bounded value. Pivot to `trace_id` only after confirming
the release commit, image digest, and replica fields. Logs must remain JSON,
redacted, and free of request bodies, credentials, cookies, email addresses,
listing contacts, or private property payloads. A source-code log line or local
formatter test is not evidence of ingestion.

## Trace continuity

Use a fresh sampled W3C `traceparent` challenge and verify distinct nonzero
spans with one trace ID across the customer API, durable search worker, and at
least one governed provider or render boundary. Reject traces from another
release, traces without release/replica attributes, self-authored screenshots,
or a response header without backend query evidence. The local middleware and
durable-job metadata establish propagation only; they do not claim an exporter
or trace backend received the spans.

## Dashboard and alert proof

The protected receipt must identify the deployed dashboard, its canonical
contract hash, data-source identities, exact release filters, rendered panel
set, query interval, and capture time. Alert proof must be the authenticated
operator-gateway acknowledgement already required by the canonical
observability bundle. Dashboard screenshots alone are supplemental.

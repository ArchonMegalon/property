# PropertyQuarry Runtime Observability

PropertyQuarry exposes process-local Prometheus metrics at
`/internal/metrics` and emits redacted one-line JSON logs automatically when
`EA_RUNTIME_MODE=prod`. No Prometheus client dependency is required.

## Structured logs

Production logs contain these stable top-level fields where applicable:

- `timestamp`, `level`, `logger`, `service`, and `message`
- `event` and `correlation_id`
- bounded HTTP `method`, route template, status, and duration
- a redacted `exception` object with type, message, and stack for unhandled
  failures

Request bodies, query strings, cookies, authorization headers, and arbitrary
raw request headers are not logged. Known credential assignments, bearer
tokens, cookies, database URL credentials, passwords, secrets, and API keys
are redacted from messages, structured fields, and exception stacks.

Clients may send `X-Correlation-ID`; accepted IDs are limited to 128 safe
ASCII characters (`A-Z`, `a-z`, digits, `.`, `_`, `:`, and `-`). Missing or
unsafe values are replaced with a UUID. The effective value is returned in
the response, including catch-all 500 responses.

Development retains the readable text formatter by default. Set
`EA_LOG_FORMAT=json` to exercise the production formatter outside production.
Production cannot opt out of JSON formatting.

## Authenticated metrics

Scrape the local/private runtime with the configured system API token and a
dedicated principal:

```bash
curl -fsS \
  -H "Authorization: Bearer ${EA_API_TOKEN}" \
  -H "X-EA-Principal-ID: propertyquarry-metrics" \
  "http://127.0.0.1:${EA_HOST_PORT:-8090}/internal/metrics"
```

Cloudflare Access identities may scrape only when they satisfy the existing
operator allowlist. Ordinary workspace sessions, anonymous development
requests, absent tokens, and incorrect tokens are rejected. The route is
excluded from OpenAPI and returns `Cache-Control: no-store`.

Keep this endpoint on a private scrape path or an ingress allowlist even
though application authentication is mandatory. Do not create a public
Cloudflare bypass for it. Prometheus should load the bearer credential from a
mounted secret file, not place it directly in checked-in configuration.

The exposition includes:

- `propertyquarry_http_requests_total`
- `propertyquarry_http_request_errors_total`
- `propertyquarry_http_request_duration_seconds` histogram
- `propertyquarry_readiness`
- `propertyquarry_runtime_heartbeat_required{role="worker|scheduler"}`
- `propertyquarry_runtime_heartbeat_age_seconds{role="worker|scheduler"}`
- `propertyquarry_runtime_heartbeat_present{role="worker|scheduler"}`
- `propertyquarry_runtime_heartbeat_stale{role="worker|scheduler"}`
- `propertyquarry_scheduler_delivery_outbox_events_total{outcome="queued|claimed|claim_conflicts|sent|retried|dead_lettered|failed"}`
- `propertyquarry_content_ledger_events_total{outcome="claimed|recovered|duplicate|replay_conflict|completed|failed|corruption"}`

HTTP labels use the declared route template rather than the requested URL, so
property IDs and unmatched attacker-controlled paths do not create cardinality
or privacy leaks. Counts and latency are process-local; scrape every API
replica and aggregate in Prometheus if the runtime is scaled horizontally.

Heartbeat metrics read the same files and age thresholds as the fail-closed
worker/scheduler healthchecks:

- `EA_WORKER_HEARTBEAT_PATH`
- `EA_WORKER_HEARTBEAT_MAX_AGE_SECONDS`
- `EA_SCHEDULER_HEARTBEAT_PATH`
- `EA_SCHEDULER_HEARTBEAT_MAX_AGE_SECONDS`

A missing, malformed, wrong-role, future-dated, or over-age heartbeat reports
`stale=1`; missing or invalid age reports `NaN`. Alert on readiness `0`, a
sustained 5xx increase, latency objectives, and stale required-role heartbeats.
The bounded delivery-outbox series comes from the latest scheduler heartbeat.
Alert on any `dead_lettered` increase, repeated `failed`/`retried` growth, or
sustained `claim_conflicts` without corresponding `sent` progress. A
dead-lettered Telegram delivery may represent an intentionally suppressed
duplicate after an ambiguous provider outcome and requires operator
reconciliation, not an automatic resend.

The content-ledger series uses a fixed outcome set. A `replay_conflict`
indicates the same provider event ID arrived with a different canonical payload and
must be investigated rather than retried automatically. Sustained `recovered`
without `completed`, any `corruption`, or growing `failed` also blocks release
promotion; development file corruption is preserved for diagnosis.

The scheduler is required by default. The worker is deliberately optional for
the standalone PropertyQuarry Compose topology and becomes required only when
`PROPERTYQUARRY_WORKER_HEARTBEAT_REQUIRED=1` (or `true`, `yes`, or `on`). The
scheduler requirement can be stated explicitly with
`PROPERTYQUARRY_SCHEDULER_HEARTBEAT_REQUIRED=1`. Alerts join stale/present
state to the required-role gauge, so a deliberately disabled worker does not
page while an enabled worker still fails closed.

Result finalization is intentionally bounded. In no-send scheduler mode,
already-ready runs are skipped before notification-event lookups, and tour
events are loaded once per principal per reconciliation cycle. Storage filters
known-ready projections before applying the terminal-run limit. Delivery work
is ordered by compact schema version and then the durable oldest-checked cursor,
so newer work cannot permanently starve older pending runs. Legacy rows and
truncated projections each have an independent two-row hydration budget by
default; compact-only writes use both the full-row timestamp and delivery cursor
as compare-and-swap fences. Set
`EA_SCHEDULER_PROPERTY_RESULTS_LEGACY_HYDRATION_LIMIT` between 0 and 10 to tune
legacy backfill, and set
`EA_SCHEDULER_PROPERTY_RESULTS_TRUNCATED_HYDRATION_LIMIT` between 0 and 10 to
tune full-state reconciliation for truncated projections. Delivery projections
contain at most 256 minimal candidate rows; unresolved truncated projections
stay on the bounded hydration lane instead of claiming completeness. Compact UI
candidate arrays contain at most 40 rows, source arrays at most 64 rows, and
nested fields are cardinality- and text-bounded.

The default global cycle limits are 40 terminal runs, five provider-repair
tasks, and one tour follow-up task across all principals. Empty or failed
principal scans consume one unit, and principal order advances each cycle so a
large tenant set cannot make cycle cost unbounded or permanently favor the
same tenant. Operators may lower or raise those bounded values with
`EA_SCHEDULER_PROPERTY_RESULTS_FINALIZE_LIMIT` (maximum 200),
`EA_SCHEDULER_PROPERTY_PROVIDER_REPAIR_LIMIT` (maximum 40), and
`EA_SCHEDULER_PROPERTY_TOUR_FOLLOWUP_LIMIT` (maximum 20). Raising them requires
fresh scheduler-latency, database-load, and heartbeat evidence. Scheduler logs
use process-local non-reversible references for principals, accounts, chats,
and messages; formatted logs also redact email addresses from messages and
exception stacks.

## Launch SLO and alert evidence

The versioned objective, rule, and synthetic injection contracts are:

- `config/monitoring/propertyquarry_slo.v1.json`
- `config/monitoring/propertyquarry_alert_rules.v1.yml`
- `config/monitoring/propertyquarry_alert_rule_tests.v1.yml`
- `config/monitoring/propertyquarry_prometheus.v1.yml`
- `config/monitoring/propertyquarry_alertmanager.v1.yml`
- `config/monitoring/propertyquarry_monitoring_topology.v1.json`
- `config/monitoring/propertyquarry_monitoring_tools.v1.json`

Prometheus uses the direct per-replica file-SD document at
`/etc/prometheus/propertyquarry_targets.json`; it does not infer replica
coverage from an IPv4-only service name. Each target must carry one unique
`replica_id`. The checked-in example demonstrates both private IPv4 and IPv6
targets. The topology and tool manifests intentionally contain
`UNCONFIGURED` sentinels. Launch proof fails closed until the deployment pins
private Prometheus, Alertmanager, and proof-receiver endpoints, immutable
Prometheus/Alertmanager image digests, the exact expected replica IDs, and
SHA-256 identities for the binaries at the manifest's absolute paths.

Capture `/internal/metrics` with
`scripts/propertyquarry_slo_capture.py` as documented in
`docs/PROPERTYQUARRY_SLO_RELEASE_EVIDENCE.md`. The accompanying JSON probe uses
schema `propertyquarry.metrics_probe.v1` and binds the snapshot hash to the
full candidate release SHA, immutable image digest, exact replica identity and
positive replica count. It must also prove the authenticated private route,
HTTP `200`, Prometheus text, `Cache-Control: no-store`, and
`credential_persisted: false`. The capture must be no more than 15 minutes old;
the token and target URL are never persisted.

Run the offline gate with a preinstalled `promtool`:

```bash
python3 scripts/propertyquarry_slo_evidence.py \
  --flagship \
  --release-sha '<full-40-character-candidate-sha>' \
  --image-digest 'sha256:<64-hex-image-digest>' \
  --metrics-snapshot '<private-captured-metrics.prom>' \
  --metrics-probe '<metrics-probe-receipt.json>' \
  --receipt '_completion/propertyquarry_slo_evidence/receipt.json'
```

The gate contacts no monitoring endpoint. It verifies probe provenance and
hash, required metric families, passing readiness and required heartbeats,
all versioned rule/runbook links, then runs `promtool check rules` and
`promtool test rules` to inject synthetic failure series for every required
alert. The rule-test file must sit beside and reference the exact rule file,
preventing a syntax-checked candidate from being paired with tests for a
different ruleset. Missing `promtool`, series, rules, injection cases, or
passing tests fails flagship mode closed. Without `--flagship`, unavailable
promtool is advisory and exits zero; that receipt is not launch evidence.

Database-pool and queue alerts are conditional because the current API does
not expose those families. Complete absence is recorded as `not_exposed`; if
any family in a conditional capability appears, every companion family and a
finite, launch-safe sample become mandatory. Provider/quota alerting uses the
existing bounded HTTP error series on provider, quota, and balance route
templates.

Incident actions and escalation boundaries are linked from every alert in
`docs/PROPERTYQUARRY_SLO_ALERT_RUNBOOK.md`.

## Deployed monitoring proof

Offline rule injection is necessary but is not proof that Prometheus loaded
the config, that every deployed replica is currently healthy, or that
Alertmanager can deliver. The active release proof is implemented by:

- `scripts/propertyquarry_monitoring_runtime_proof.py`
- `scripts/propertyquarry_alert_proof_receiver.py`
- `scripts/propertyquarry_observability_receipts.py`

Run the proof receiver on a loopback or private-IP listener with private
`0600` token and instance-identity files. Put its `/v1/alerts` URL in
`propertyquarry_alert_proof_webhook_url`; the URL itself remains a mounted
secret. The proof route matches `proof="propertyquarry-release"`, groups by a
unique nonce, is evaluated before the operator route, and has
`continue: false`. Consequently the synthetic release alert is delivered to
the private receiver and never sent to the operator channel.

After the protected monitoring APIs and receiver are ready, an explicitly
authorized release process runs:

```bash
python3 scripts/propertyquarry_monitoring_runtime_proof.py \
  --execute \
  --release-sha "${PROPERTYQUARRY_RELEASE_COMMIT_SHA}" \
  --image-digest "${PROPERTYQUARRY_RELEASE_IMAGE_DIGEST}" \
  --receipt '_completion/propertyquarry_monitoring/runtime-proof.json' \
  --alert-delivery-receipt '_completion/propertyquarry_monitoring/alert-delivery.json'
```

The command takes no URL or tool-path overrides. It structurally validates
the source YAML, recomputes binary hashes, invokes the absolute pinned tools,
queries Prometheus's loaded config, active targets, alert rules, and
per-replica expected-count gauge, then queries Alertmanager's loaded config
and ready status. It requires the exact topology replica set healthy before
injecting one release-SHA/image-digest/nonce-bound proof alert. Successful
authenticated delivery is the proof that the proof webhook secret was active.
All receipts are atomic private files; no token, endpoint, or webhook URL is
written to them.

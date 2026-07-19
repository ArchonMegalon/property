# PropertyQuarry bounded local capacity evidence

`scripts/propertyquarry_capacity_evidence.py` produces a reproducible,
closed-schema receipt for one bounded local workload. It is evidence about the
measured fixture only. It does not establish a production traffic limit, a
replica count, a scaling factor, or global-launch capacity.

## What the producer measures

- forty concurrent GET requests to an explicitly supplied loopback API route,
  including raw latency samples, response status counts, request/error counts,
  response bytes, throughput, and the sample window;
- four loopback PostgreSQL connections in a probe-owned pool and forty `SELECT
  1` transactions, with default and transaction-local read-only enforcement,
  statement/connect timeouts, connection/acquire/query timings, peak checkout,
  throughput, and verified cleanup;
- 240 jobs through
  `InMemoryPropertySearchWorkQueue`, separating scheduler/enqueue and
  worker/drain windows and recording initial, peak, and final depth;
- producer CPU time, normalized CPU percentage, RSS, threads, cgroup memory/PID
  headroom when available, repository-filesystem free space, and process I/O
  counters when `/proc` exposes them.

The API and PostgreSQL targets are restricted to loopback IP literals; hostnames
and alternate non-loopback `hostaddr` values are rejected. The API workload never follows redirects. PostgreSQL credentials are
read from a caller-owned no-follow file outside the source repository, with mode `0600` or stricter; the file
contents and database name are never emitted. Provider services, production
traffic, and external browser/render fleets are never contacted.

## Candidate binding

The producer hashes a stable manifest of every current Git-tracked and
non-ignored untracked file, including path, kind, mode, byte count, and content
digest. It records the HEAD commit, source digest, file/byte counts, and clean or
dirty state. The complete source identity is collected again after the workload;
any change aborts receipt generation. This permits an honest dirty developer
measurement while allowing release gates to require a clean candidate.

## Run against isolated local fixtures

Prepare a private DSN file for a disposable loopback PostgreSQL database, then
run the bounded profile against a local candidate API route:

```bash
chmod 600 /tmp/propertyquarry-capacity-postgres.dsn
python3 scripts/propertyquarry_capacity_evidence.py measure \
  --repo-root "$PWD" \
  --api-url http://127.0.0.1:18090/readyz \
  --postgres-dsn-file /tmp/propertyquarry-capacity-postgres.dsn \
  --require-clean-source \
  --output /tmp/propertyquarry-capacity.json
```

The output must also be outside the source repository so creating the receipt
cannot immediately change the candidate it identifies. The fixed v1 workload and thresholds are embedded in the receipt. Omitting the
API URL or DSN produces explicit `not_measured` checks and
`partial_local_measurement`; it never turns missing evidence into a pass.

Verify against values obtained independently from the frozen candidate:

```bash
python3 scripts/propertyquarry_capacity_evidence.py verify \
  --receipt /tmp/propertyquarry-capacity.json \
  --expected-commit-sha COMMIT_SHA \
  --expected-source-tree-sha256 SOURCE_TREE_SHA256
```

The verifier rejects duplicate keys, non-finite values, unknown fields,
modified profiles/thresholds, stale timestamps, mismatched source identity,
inconsistent counts/windows/percentiles/throughput/cleanup, forged stored
checks or summaries, and canonical-payload hash mismatches. It always returns
`production_capacity_established: false`.

## Evidence that still requires governed production authority

Before global launch, independently authenticated evidence must still measure
the deployed image under representative traffic and topology: API replicas and
autoscaling, the application database pool and durable queue, scheduler and
worker fleets, browser/render workers, provider quotas, production cgroups and
storage/network limits, backpressure, saturation, and recovery. This local
receipt is an input to that work, never a substitute for it.

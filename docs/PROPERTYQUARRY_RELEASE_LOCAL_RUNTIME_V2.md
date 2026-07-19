# PropertyQuarry local persistent runtime v2

## Status and authority

This lane is an opt-in, local-Docker lifecycle proof for the authenticated
PropertyQuarry release-control package. It is authoritative only for the local
runtime-gate receipt it emits. It is not production-ready, is not public launch
authority, and is not authoritative for release effects.

Importing the gate or running its unit tests does not contact Docker. Invoking
`scripts/propertyquarry_release_local_runtime_gate.py` is the explicit Docker
mutation boundary. Do not invoke it until live-Docker execution is authorized.

The runtime compose file is
`compose.propertyquarry-release-runtime-v2.yml`. It is separate from the frozen
six-test compose file, `compose.propertyquarry-release-control-v2.yml`; the gate
pins both the runtime compose bytes and their exact parsed contract.

## Inputs

The gate requires all of the following:

- a daemonless OCI layout that passes the pinned authenticated-layout verifier;
- the exact native build receipt bound into that OCI receipt;
- the immutable local image ID from the OCI receipt already present in the
  local Docker store;
- the authenticated package wrapper and its external public authority anchor;
- an unused output path under a controlled receipt directory; and
- an absolute Docker binary plus a local `unix:///` Docker host.

The public anchor is a durable host input, not a temporary staging file. Its
path must avoid conventional volatile trees, every opened ancestor must be a
root-owned directory with no group/other write bit, and the leaf must be a
root-owned, root-group, `0444`, single-link, bounded regular file. The gate also
checks the filesystem type through each opened descriptor and rejects tmpfs,
ramfs, and Linux pseudo-filesystems. Operators must place the anchor on storage
that survives Docker daemon and host restarts. The gate pins descriptor, name,
path, bytes, metadata, and filesystem assumptions throughout the proof.

Inside each container the anchor is mounted read-only at:

```text
/run/secrets/propertyquarry-package-authority-v2.pem
```

The image contains an inert empty `0444` mount target at that path so Docker
does not need to create it in a read-only root filesystem. It is not an
authority key. The authenticated package itself is retained in the image at:

```text
/usr/share/propertyquarry-release-control-v2/local-authority
```

## Runtime isolation

The compose project contains only `release-supervisor` and `release-watchdog`.
Both services have:

- `network_mode: none`, no ports, and no host or application network;
- a read-only root filesystem;
- the exact numeric image user `65534:<validated-service-gid>`;
- all Linux capabilities dropped and `no-new-privileges:true`;
- no stdin, TTY, init process, devices, or Docker socket, and no
  Compose-supplied environment or credential values; the only image
  environment value is the audited fixed public
  `PATH=/usr/libexec/propertyquarry-release-control`;
- a one-CPU cap, 32-process limit, measured 256 MiB memory limit, 16 MiB reservation, and
  memory plus swap capped at 256 MiB; the limit covers concurrent installed-
  authority revalidation during health and framed-request smoke;
- `restart: on-failure:3`, `SIGTERM`, and a ten-second stop grace period; and
- only the read-only public anchor plus the dedicated socket and state volumes.

The socket and state volumes use the local driver with exact tmpfs options:

```text
uid=65534,gid=<validated-service-gid>,mode=0700,nosuid,nodev,noexec,size=1048576
```

They are mounted with long syntax and `nocopy: true` at:

```text
/run/propertyquarry-release-control-v2
/var/lib/propertyquarry-release-control-v2
```

No application volume, repository path, port, host network, or Docker socket is
mounted. The host gate contacts only the configured local Unix Docker socket.

"Persistent" means the two processes remain running and are supervised by
Docker restart policies. It does not mean tmpfs state survives Docker daemon or
host restart. The two tmpfs volumes start fresh after their backing mounts are
lost; the native processes must then reconstruct an exact empty, authenticated,
fail-closed runtime. Do not claim daemon-restart durability for socket or state
data.

## Exact native modes

The supervisor runs as:

```text
/usr/libexec/propertyquarry-release-control/propertyquarry-release-supervisor-v2 --installed-local-authority --docker-broker
```

The persistent watchdog runs as:

```text
/usr/libexec/propertyquarry-release-control/propertyquarry-release-watchdog-v2 --installed-local-authority --docker-watchdog
```

The Compose healthcheck and the gate's independent health probe run:

```text
/usr/libexec/propertyquarry-release-control/propertyquarry-release-watchdog-v2 --installed-local-authority --health-json
```

Successful health output is one exact canonical JSON line with empty stderr.
It binds the package authentication digest, payload tree digest, authority key
ID, source manifest digest, installed-authority verification, and socket
acceptance. It explicitly reports `performs_release_effects:false`,
`authoritative_for_release_effects:false`, and `production_ready:false`.

## Lifecycle proof

For each run the gate creates a random validated Compose project and gate-only
container names. It uses a fresh isolated Docker configuration and passes the
pinned runtime compose through a sealed memory file. The image has
`pull_policy: never`; the gate uses no build or pull operation.

Before startup, the gate inventories every pre-existing container's immutable
ID, name, state, health, and restart count. Existing unhealthy or exited state
is recorded rather than adopted as this gate's responsibility; the exact
baseline must remain byte-for-byte unchanged after cleanup. It then performs
the following proof:

1. Inspect the expected immutable image ID.
2. Start only the supervisor and watchdog with `compose up --detach --no-build
   --pull never --wait`.
3. Require both containers to be running and healthy with zero restarts.
4. Require the watchdog's sole initial log line and independent one-shot health
   output to equal the exact canonical health document; require empty supervisor
   logs.
5. Run the in-container request proof without a TTY:

   ```text
   docker compose ... exec -T release-supervisor /usr/libexec/propertyquarry-release-control/propertyquarry-release-supervisor-v2 --installed-local-authority --request-smoke
   ```

   The native smoke mode validates the installed authority and socket, sends
   one fixed canonical framed request with one write-only pipe descriptor via
   `SCM_RIGHTS`, requires EOF with zero response bytes, and revalidates its
   inputs. Success is exit zero with exact empty stdout and stderr. This proves
   the broker remains fail-closed and performs no release effect.
6. Hold the healthy zero-restart state for eleven seconds so Docker's restart
   policies are active, then recheck both zero counts.
7. Use sealed non-TTY Compose exec to run the authenticated
   `--installed-local-authority --docker-restart-stimulus` mode in the
   supervisor container. It verifies its own installed supervisor executable,
   the live socket, and container PID 1 as the same authenticated supervisor,
   then sends the dedicated handled `SIGUSR2` to PID 1 and remains silent until the container stops
   the exec process with exit `137`. This is a process crash, not Docker's
   manual `container kill` operation, so `restart: on-failure:3` restores the
   broker. The persistent watchdog's pre-readiness inotify watch and pinned
   socket identity deterministically observe the unlink/rebind, exit nonzero,
   and are restored by its own restart policy. Require both restart counts to
   be at least one and both containers healthy.
8. Repeat exact health and framed-request proofs after recovery and prove the
   OCI layout did not change.

The gate always attempts teardown after startup was attempted. It runs exact
project `compose down --volumes --remove-orphans`, queries only the random
gate-labeled containers plus project-labeled volumes and networks, and
force-removes validated leftovers before requiring all three sets to be empty.
Anchor drift invalidates the proof and withholds the receipt, but cannot block
sealed-project teardown.

After removal, the gate inventories all pre-existing containers again. Their
canonical inventory must be byte-for-byte equal to the baseline. The receipt
stores only hashes of the before/after inventory and health outputs, immutable
artifact digests, restart counts, and explicit truth booleans. It never retains
container inventory details or local filesystem paths.

The successfully tested runtime containers and their two volumes are removed,
and no project network may remain. The pre-existing verified image remains in
the local Docker store.

## Invocation boundary

Once live Docker execution is explicitly authorized, invoke the executable gate
with absolute controlled paths:

```text
scripts/propertyquarry_release_local_runtime_gate.py \
  --layout /absolute/path/to/verified-oci-layout \
  --wrapper /absolute/path/to/authenticated-wrapper \
  --external-anchor /absolute/durable/path/propertyquarry-package-authority-v2.pem \
  --native-build-receipt /absolute/path/to/native-build-receipt.v2.json \
  --output-receipt /absolute/controlled/receipts/local-runtime-gate.v2.json
```

The current repository validation is static and mock-driven. A live Docker
receipt must be obtained before claiming that this host daemon completed the
runtime lifecycle proof.

## Daemonless validation

These tests do not invoke Docker:

```text
pytest -q tests/test_propertyquarry_release_local_runtime_gate.py \
  tests/test_propertyquarry_release_oci_materializer.py
```

They pin the runtime compose contract, the unchanged frozen six-test compose
digest, image mount targets and ownership, exact CLI sequencing, receipt keys
and truth values, sealed cleanup after anchor drift, forced leftover cleanup,
zero retained project networks, pre-existing container health invariance, and
fail-closed input rejection.

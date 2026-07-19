# PropertyQuarry global terminal installed bundle

The only authoritative global Launch/Core entrypoint is:

```text
/usr/libexec/propertyquarry/propertyquarry-global-launch-terminal --manifest /run/propertyquarry/release-evidence/global-launch-core-manifest.v1.json
```

The repository script is non-authoritative developer validation only. Running
it from a checkout, even as root, cannot grant launch authority.

## Build boundary

Materialize a staging bundle with an explicit new destination:

```text
python3 scripts/build_propertyquarry_global_launch_terminal_bundle.py --output /dedicated/staging/propertyquarry-global-terminal
```

This command never installs files and never mutates `/usr/libexec`. It emits a
reproducible `global-launch-terminal-bundle.v1.json` containing the fixed
`/usr/bin/python3.12` digest, every wrapper/Gold/support/policy/config file
digest, the canonical jurisdiction/privacy contract and governed market
envelope that Gold re-hashes at decision time, and the canonical artifact-set
digest. Package installation remains an external, privileged
release-controller operation.

The installed tree and every ancestor must be root-owned and not writable by
group or other. The installed entrypoint must be executable; support and policy
files must be immutable to non-root users. The terminal opens the manifest,
bundle, evidence, and Gold program without following symlinks, verifies the
signed digest contract, and executes Gold through its verified file descriptor.
Both the entrypoint shebang and the FD bootstrap require Python isolated mode;
the bootstrap inserts only the digest-pinned installed runtime package root and
its `scripts` directory, so a checkout, working-directory module, user site, or
`PYTHONPATH` cannot satisfy an import. No checkout fallback exists.

## Authority boundary

The controller-signed invocation contract binds the exact Launch/Core argv,
Chromium/Firefox/WebKit requirement, output paths, product-data values, all
evidence digests, installed bundle digest set, fixed production deployment ID,
flagship-operations policy hash, an exact non-placeholder lowercase/unprefixed
SHA-256 of the independently selected canonical runtime manifest, and a closed
Chromium executable policy with an exact canonical path and non-placeholder
SHA-256. The terminal derives Gold's expected manifest and browser identities
only from that signed policy; `/version`, document headers, and the performance
receipt cannot self-select those trust anchors. Gold then requires the producer's
explicit Playwright launch binding, independently re-hashes the owner-safe
executable, and requires both runtime identity surfaces to match the canonical
manifest digest.
Missing installation, ownership drift, digest drift, a different deployment, or
an expired/rotated active challenge returns structured `BLOCKED`.

Production capacity is a separate closed v2 authority, documented in
`docs/PROPERTYQUARRY_PRODUCTION_CAPACITY_AUTHORITY_V2.md`. The installed bundle
pins its JSON Schema, and the terminal recomputes fresh exact-release numeric
headroom, limit, and backpressure invariants for all governed resources. Legacy
passing booleans and bounded local capacity measurements cannot satisfy it.

No installed bundle or production authority is claimed by the checked-in build
contract.

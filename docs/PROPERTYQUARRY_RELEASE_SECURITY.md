# PropertyQuarry Release Security Gate

This gate covers only the PropertyQuarry Python dependency lock and the two
PropertyQuarry runtime images. It does not inspect the legacy EA Compose stack
or unrelated host images. The controller installs nothing and never pulls an
image or vulnerability database.

## Flagship runner contract

The protected `propertyquarry-flagship-security` CI job runs only for a manual
dispatch from `main` on a self-hosted runner labeled
`propertyquarry-security`. Provision that runner separately with:

- `python3`, `pip-audit`, `syft`, and `trivy` already installed at reviewed
  versions;
- the exact web and render images already present in the local Docker daemon;
- a current Trivy vulnerability database and Java database already in its
  cache; and
- no auto-discovered scanner configuration that weakens the fixed command
  flags.

Scanner installation, image loading, and vulnerability-database refresh are
separate governed runner-maintenance actions. They do not occur in this CI
job. Missing tools, local images, databases, scanner output, or valid SBOMs
fail flagship mode closed and still produce an atomic receipt where Python can
start.

Configure these protected environment variables as immutable image
references, not mutable tags:

```text
PROPERTYQUARRY_WEB_IMAGE=registry.example/propertyquarry-web@sha256:<64-hex>
PROPERTYQUARRY_RENDER_IMAGE=registry.example/propertyquarry-render@sha256:<64-hex>
```

The release commit is the workflow's full `${{ github.sha }}`. The security
job must pass before `propertyquarry-live-release-gates` can run.

## Reproducible scanner lane

The controller audits the fully pinned `ea/requirements.lock` with
`pip-audit --no-deps --disable-pip` and the OSV vulnerability service. It
generates one CycloneDX JSON SBOM per image from the local Docker daemon using
the explicit `docker:` Syft source. Trivy scans those files with database,
Java-database, VEX, and version updates disabled and with offline vulnerability
scanning selected.

```bash
python3 scripts/propertyquarry_release_security_gate.py \
  --flagship \
  --release-sha '<full-40-character-git-sha>' \
  --web-image 'registry.example/propertyquarry-web@sha256:<64-hex>' \
  --render-image 'registry.example/propertyquarry-render@sha256:<64-hex>' \
  --severity-threshold HIGH \
  --waivers config/propertyquarry_security_waivers.json \
  --artifacts-dir _completion/propertyquarry_release_security/run/artifacts \
  --receipt _completion/propertyquarry_release_security/run/receipt.json
```

`LOW`, `MEDIUM`, `HIGH`, and `CRITICAL` are accepted thresholds. A finding at
or above the selected threshold blocks flagship mode unless one exact waiver
applies. `pip-audit` JSON does not provide a normalized severity, so dependency
findings are recorded as `UNKNOWN` and conservatively evaluated as
`CRITICAL`.

Without `--flagship`, unavailable scanners and blocking findings are recorded
as advisory and exit zero. This keeps ordinary local development usable; it
does not create flagship evidence and must never be substituted for the
protected CI gate.

## Evidence

The atomic `0600` receipt records:

- the full release SHA, exact image digest references, and dependency-lock
  SHA-256;
- scanner availability, normalized versions, and version-output hashes;
- the explicit threshold and offline/no-registry command contract;
- CycloneDX component counts plus SBOM, Trivy result, and pip-audit artifact
  hashes;
- normalized findings, conservative effective severities, exact waivers, and
  blocking counts; and
- final `pass`, `failed`, `advisory_findings`, or `advisory_unavailable` state.

Raw scanner stderr is withheld from receipts. SBOM and scanner JSON artifacts
are also atomically written with mode `0600`. Preserve the entire CI artifact,
not only the summary receipt.

## Waiver format

The committed waiver file is empty by default. A waiver is an exceptional,
release-specific approval, not an ignore list. It must identify exactly one
scanner source, immutable target, vulnerability, package, and reported
severity:

```json
{
  "schema": "propertyquarry.security_waivers.v1",
  "waivers": [
    {
      "id": "PQSEC-2026-001",
      "source": "trivy:web",
      "target": "registry.example/propertyquarry-web@sha256:<64-hex>",
      "vulnerability_id": "CVE-2026-12345",
      "package": "example-package",
      "severity": "HIGH",
      "release_commit_sha": "<full-40-character-git-sha>",
      "owner": "security-owner",
      "approved_by": "release-approver",
      "reason": "Compensating control and remediation tracking reference.",
      "created_at": "2026-07-13T12:00:00Z",
      "expires_at": "2026-07-20T12:00:00Z"
    }
  ]
}
```

Allowed sources are `pip-audit`, `trivy:web`, and `trivy:render`. Their targets
must respectively equal the dependency-lock `sha256:<hash>`, the web image
reference, or the render image reference. Waivers cannot use wildcards, must
be bound to the current release SHA, require distinct security owner and
independent approver identities, cannot be created in the future, and must
expire within 30 days of creation. Expired, overlong, malformed, duplicate,
mismatched, or wrong-release waivers fail before scanning.

On a failed flagship receipt, do not loosen the threshold or reuse a waiver
from another release. Remediate and rebuild the immutable image, provision a
reviewed time-limited waiver, or stop the launch.

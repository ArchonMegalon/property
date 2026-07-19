# Repository Isolation

PropertyQuarry is the standalone product runtime. The active release surface is intentionally narrow:

- `ea/` application runtime used by the property API and scheduler
- `docker-compose.property.yml`
- `docker-compose.property-legacy-edge.yml` only when an intentional legacy edge alias is still required
- `ea/Dockerfile.property`
- `config/`, `docs/`, `scripts/`, and `tests/` that are property-facing
- `.github/workflows/smoke-runtime.yml`

The extraction still carries inherited archives from the broader EA and Chummer work. These are not part of the PropertyQuarry runtime path and must not be referenced by the property compose file, hardened Dockerfile, or property release gates:

- `.codex-design/`
- `.codex-studio/`
- `feedback/`
- `skills/`
- `docs/black_ledger_newsroom/`
- `docs/chummer5a_parity_lab/`
- `docs/chummer_explain_narration_packs/`
- `docs/chummer_governor_packets/`
- `docs/chummer_launch_followthrough/`
- `docs/chummer_operator_safe_packets/`
- `docs/chummer_organizer_packets/`
- `scripts/bootstrap_chummer6_guide_skill.py`

If one of these directories is needed for future work, move that work to the owning repository first or add a dedicated migration issue. Do not wire it into the PropertyQuarry deploy path.

Host-level recovery scripts are quarantined operator artifacts. `scripts/harden_propertyquarry_docker.sh` and `scripts/recover_host_after_reboot.sh` must stay explicitly guarded behind `PROPERTYQUARRY_HOST_RECOVERY_ALLOW=1`, support dry runs, and must not be treated as normal release/runtime entrypoints.

Use `python3 scripts/check_property_repo_isolation.py` or `make property-release-gates` before a public deploy.

## Canonical repository and public mirror

`ArchonMegalon/property` is the sole canonical source and release-authority
repository. `ArchonMegalon/propertyquarry` is a public, byte-exact mirror of
canonical `main`; it is not an independently advancing release-envelope repo.
The two `main` refs must resolve to the same commit, not merely equivalent trees.
No workflow, manifest, security policy, public-tour policy, dossier policy, or
release claim may be stronger, weaker, or newer in only one repository.

Run the offline role gate after fetching both named refs:

```text
python3 scripts/check_property_mirror_role.py \
  --canonical-ref refs/remotes/origin/main \
  --mirror-ref refs/remotes/propertyquarry/main \
  --write _completion/propertyquarry_mirror_role/receipt.json
```

The gate never fetches. Its receipt is deliberately scoped to local Git config,
objects, and refs and always reports `network_freshness_proven: false`. The
`propertyquarry-mirror-role-contract` CI lane first rejects Git URL rewrites,
fetches both public `main` refs from their exact HTTPS origins, then runs the
offline gate in a single-worktree checkout and preserves the receipt. A lagging,
ahead, diverged, same-tree/different-commit, malformed-manifest, wrong-remote,
missing-history, or extra-worktree CI state blocks the ordinary-CI aggregate and
therefore blocks release authority.

A pull request in `ArchonMegalon/propertyquarry` is a review-only fast-forward
candidate, not release evidence and not permission to create a merge or squash
commit. That PR passes only when its same-repository head SHA is the exact
canonical `main` commit and the current mirror is already an ancestor of that
commit. The reviewed candidate must then be applied through the governed
fast-forward mechanism so mirror `main` retains the canonical commit identity.
Fork PRs, diverged/ahead mirror histories, and candidate trees with different
commit identities fail closed. Push and workflow-dispatch release events never
use candidate mode: they continue to require exact remote `main` identity.

The local release bundle adds two stricter observations: checked-out `HEAD` must
equal the fetched canonical ref, and the tracked plus non-ignored untracked
worktree must be clean. Local exact-but-stale refs or a dirty candidate therefore
cannot be reported as release mirror evidence. Fetch still remains an explicit
operator step; the offline gate never claims lasting network freshness.

## Release-control v2 authority status

The checked-in v2 supervisor is non-authoritative and inert. Its
`release-preflight` and `release-run` entrypoints consume and dispose of the
bounded bearer channel, perform no release effect, and return the protocol
failure class. The workflow lane is therefore a fail-closed integration
contract, not production launch evidence. A requested legacy activation is
rejected explicitly, and an always-running requested-action result job prevents
skipped security, activation, or launch work from producing a green requested
release run. Production authority remains blocked until a separately installed,
authenticated supervisor implements and proves the complete live-evidence,
activation, rollback, and lifecycle contract.

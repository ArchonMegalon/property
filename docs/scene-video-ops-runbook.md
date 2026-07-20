# EA scene-video operator runbook

This runbook covers the shared `ea.scene_video_generate` skill used by Runsite and PropertyQuarry.

## Provider names and boundaries

Public provider choices:

- `mootion`: Mootion scene/movie lane.
- `magicfit`: MagicFit image-to-video lane.
- `omagic`: Public name for the OMagic scene-video lane.
- `magic`: Alias for `omagic`.
- `onemin_i2v`: 1min.AI image-to-video fallback/probe lane.

Provider boundary rules:

- `omagic` and `magic` must use an OMagic-specific model-upload adapter and must produce model-input consumption proof.
- `onemin_i2v`, `onemin`, and `1min` are 1min.AI. They must never satisfy an OMagic claim.
- `onemin` and `1min` are not public scene-video aliases for OMagic.
- Do not overwrite `ONEMIN_*` credentials while configuring OMagic scene-video.
- OMagic readiness is blocked until OMagic credentials and `render_omagic_property_model_walkthrough.py` exist.

## Runtime readiness

Use the deployed API container for runtime truth:

```bash
docker exec -i propertyquarry-api python - <<'PY'
import json
from app.services.scene_video_contract import scene_video_provider_runtime_readiness

for provider in ("mootion", "magicfit", "magic", "omagic", "onemin_i2v"):
    value = scene_video_provider_runtime_readiness(provider)
    print(provider, json.dumps({
        "status": value.get("status"),
        "ready": value.get("ready"),
        "provider_key": value.get("provider_key"),
        "provider_backend_key": value.get("provider_backend_key"),
        "blockers": value.get("blockers"),
        "credit_state": value.get("credit_state"),
        "runtime_account_count": value.get("runtime_account_count"),
        "execution_lane": value.get("execution_lane"),
    }, sort_keys=True))
PY
```

Expected interpretations:

- `magic` / `omagic` ready with `provider_backend_key=omagic` means the OMagic backend is dispatchable.
- `onemin_i2v` ready with `provider_backend_key=onemin_i2v` means only the 1min fallback lane is dispatchable.
- `magicfit_insufficient_credits` means MagicFit should not be rendered until credits or additional funded accounts are proven.
- `mootion_docker_socket_missing` / `mootion_docker_cli_missing` blocks the local Mootion worker lane only.
- `execution_lane=browseract_remote` means Mootion can use an explicit BrowserAct workflow/run lane without API-local Docker.

## Current PropertyQuarry provider-refresh packet

Latest refreshed receipts:

- `_completion/scene_video_readiness/release-gate.json`: `2026-07-06T19:21:49Z`
- `_completion/scene_video_readiness/release-gate-verifier.json`: `pass` at `2026-07-06T19:21:50Z`
- `_completion/scene_video_readiness/provider-refresh-packet.json`: `2026-07-06T19:21:50Z`
- `_completion/scene_video_readiness/provider-refresh-packet-verifier.json`: `pass` at `2026-07-06T19:21:50Z`
- `_completion/property_gold_status/latest.json`: `blocked` at `2026-07-06T19:21:51+00:00` only on `scene_video_provider_runtime`

Current runtime truth:

- `mootion`: ready through the remote BrowserAct lane.
- `onemin_i2v`: ready as the separate 1min fallback lane.
- `magicfit`: expected `3` accounts, runtime sees `1`, visible gap `2`, blocked by `magicfit_insufficient_credits`.
- `magic` / `omagic`: expected `8` accounts, runtime sees `0`, visible gap `8`, blocked by missing OMagic credentials, missing render endpoint or command, and disabled model-upload adapter.

Regenerate the current release-gate receipts from the deployed runtime:

```bash
docker exec propertyquarry-api python /app/scripts/property_scene_video_readiness_report.py \
  --output /data/artifacts/property-scene-video-readiness-current-container.json
docker exec propertyquarry-api python /app/scripts/verify_property_scene_video_readiness.py \
  --receipt /data/artifacts/property-scene-video-readiness-current-container.json \
  --output /data/artifacts/property-scene-video-readiness-verifier-current-container.json
docker exec propertyquarry-api python /app/scripts/materialize_scene_video_provider_refresh_packet.py \
  --receipt /data/artifacts/property-scene-video-readiness-current-container.json \
  --output /data/artifacts/property-scene-video-provider-refresh-packet-current-container.json
docker exec propertyquarry-api python /app/scripts/verify_scene_video_provider_refresh_packet.py \
  --packet /data/artifacts/property-scene-video-provider-refresh-packet-current-container.json \
  --output /data/artifacts/property-scene-video-provider-refresh-packet-verifier-current-container.json
docker cp propertyquarry-api:/data/artifacts/property-scene-video-readiness-current-container.json \
  _completion/scene_video_readiness/release-gate.json
docker cp propertyquarry-api:/data/artifacts/property-scene-video-readiness-verifier-current-container.json \
  _completion/scene_video_readiness/release-gate-verifier.json
docker cp propertyquarry-api:/data/artifacts/property-scene-video-provider-refresh-packet-current-container.json \
  _completion/scene_video_readiness/provider-refresh-packet.json
docker cp propertyquarry-api:/data/artifacts/property-scene-video-provider-refresh-packet-verifier-current-container.json \
  _completion/scene_video_readiness/provider-refresh-packet-verifier.json
PYTHONPATH=ea python3 scripts/propertyquarry_gold_status.py \
  --write _completion/property_gold_status/latest.json
```

## Telegram receipt proof

Use `delivery_probe_video_url` to prove principal binding and Telegram media delivery without spending provider credits.

```bash
docker exec propertyquarry-api ffmpeg -y \
  -f lavfi -i color=c=0x172033:s=640x360:d=1.5 \
  -f lavfi -i sine=frequency=880:duration=1.5 \
  -c:v libx264 -pix_fmt yuv420p -c:a aac -shortest \
  /tmp/ea-scene-video-telegram-probe.mp4 >/dev/null 2>&1

docker exec -i propertyquarry-api python - <<'PY'
import json
from app.main import app
from app.domain.models import ToolInvocationRequest
import app.main as main

container = getattr(getattr(app, "state", object()), "container", None) or getattr(main, "container", None)
result = container.tool_execution.execute_invocation(
    ToolInvocationRequest(
        session_id="scene-video-telegram-probe",
        step_id="telegram-probe",
        tool_name="ea.scene_video_generate",
        action_kind="video.generate",
        payload_json={
            "provider_key": "magic",
            "context_kind": "scene_briefing",
            "title": "EA scene-video Telegram delivery probe",
            "delivery_probe_video_url": "/tmp/ea-scene-video-telegram-probe.mp4",
            "telegram_delivery_requested": True,
        },
        context_json={"principal_id": "<operator-principal-id>"},
    )
)
out = dict(result.output_json or {})
receipt = dict(result.receipt_json or {})
delivery = dict(out.get("telegram_delivery_json") or receipt.get("telegram_delivery_json") or {})
print(json.dumps({
    "provider_key": out.get("provider_key"),
    "provider_backend_key": out.get("provider_backend_key"),
    "render_status": out.get("render_status"),
    "telegram_status": delivery.get("status"),
    "telegram_kind": delivery.get("kind"),
    "telegram_message_count": len(delivery.get("message_ids") or []),
}, sort_keys=True))
PY
```

Pass criteria:

- `telegram_status=sent`
- `telegram_kind=video`
- `telegram_message_count` is at least `1`

## OMagic real render proof

The delivery probe proves Telegram. Completion still needs one real provider render-to-Telegram proof when the upstream provider is stable.

Use a short OMagic render through `provider_key=magic` and require:

- `provider_key=omagic`
- `provider_backend_key=omagic`
- `model_input_consumed=true`
- `render_status=completed`
- `telegram_delivery_json.status=sent`
- `telegram_delivery_json.media_ref` is a plain URL or file path, not a JSON blob

If 1min returns HTTP `524`, do not burn through accounts. Gateway timeout retry across 1min accounts is fail-closed by default. Only opt in deliberately with:

```bash
PROPERTYQUARRY_ONEMIN_VIDEO_RETRY_GATEWAY_TIMEOUTS=1
```

## MagicFit unblock

Current blocker shape:

- `magicfit_insufficient_credits`
- credit source: render failure marker
- expected `3` accounts and one runtime account detected

Do not clear the marker just to make readiness green.

Valid unblock options:

- Add credits to the currently configured MagicFit account, then run a real MagicFit render probe.
- Configure the full MagicFit account pool through the secure account JSON merge path, then verify `runtime_account_count >= 3`.

Required account JSON shape:

```json
[
  {"email": "<magicfit-account-email>", "password": "<magicfit-account-password>"},
  {"email": "<magicfit-account-email-2>", "password": "<magicfit-account-password-2>"}
]
```

The account JSON file must be provider-only, must not include 1min credentials, and must have mode `0o600` before merge:

```bash
chmod 600 <magicfit-accounts.json>
python3 scripts/merge_scene_video_provider_accounts_env.py \
  --env-file .env \
  --magicfit-accounts-json-file <magicfit-accounts.json> \
  --expected-magicfit-count 3 \
  --magicfit-account-index <funded-account-index> \
  --write
```

This writes only:

- `PROPERTYQUARRY_MAGICFIT_ACCOUNTS_JSON`
- `PROPERTYQUARRY_MAGICFIT_ACCOUNT_INDEX`

If you want the runtime to read a stable secret file instead of inline JSON env, use file-env mode:

```bash
chmod 600 <magicfit-accounts.json>
python3 scripts/merge_scene_video_provider_accounts_env.py \
  --env-file .env \
  --magicfit-accounts-json-file <magicfit-accounts.json> \
  --expected-magicfit-count 3 \
  --magicfit-account-index <funded-account-index> \
  --write-file-env \
  --write
```

Default file-env install target:

- host file path: `state/incoming_property_tours/_operator-import-lane/scene_video_provider_accounts/magicfit-accounts.json`
- runtime env value: `/data/incoming_property_tours/_operator-import-lane/scene_video_provider_accounts/magicfit-accounts.json`

This writes only:

- `PROPERTYQUARRY_MAGICFIT_ACCOUNTS_JSON_FILE`
- `PROPERTYQUARRY_MAGICFIT_ACCOUNT_INDEX`

When `*_ACCOUNTS_JSON_FILE` is present, PropertyQuarry runtime readiness and MagicFit helper selection prefer that file over inline `*_ACCOUNTS_JSON`.

### Governed MagicFit execution and delivery

PropertyQuarry apartment video requests belong to the shared governed render
lane. `OrchestrationLane` on the Horizon capability is the source of truth. The
domain bridge composes the request through
`HorizonGovernedRenderRequestComposerService` and
`HorizonArtifactRequestService`; it must carry first-party property packet,
account-route, and continuity truth/evidence refs, not raw provider URLs,
provider IDs, or credentials. A compose-only audit sets `ConsumeQuota=false`.
Only an explicitly authorized build may consume quota.

The request-serving web image contains contract helpers but intentionally has
neither browser payloads nor FFmpeg. A local provider execution is therefore
valid only in the isolated `render-tools`/governed worker lane with its required
browser, media tools, credentials, quota, resource bounds, and durable render
receipt. Web readiness must not infer MagicFit execution from copied Python
scripts or configured credentials alone.

The canonical delivery sequence is one-way:

1. Governed render produces the exact video bytes and a strict source receipt.
2. `import_magicfit_walkthrough.py` creates only a digest-bound pending stage.
3. Private browser and human visual review produce a committed receipt bundle.
4. `accept_magicfit_delivery.py` verifies the same subject and atomically
   activates it.

The source receipt must bind every present provider alias to the lowercase
literal `magicfit`, carry an approved completed `render_status`, bind
`target_slug` (or another supported slug alias) to the exact existing
`tour.json` slug, and include exactly one agreed approved MagicFit CDN URL via
`hosted_walkthrough_video_url` or `video_output_url`. If it declares
`output_file`, that absolute path must identify the exact bytes passed with
`--video-path`. Use the same slug literal for compose, import, private review,
and acceptance; never derive or silently normalize a different slug at a later
step.

The legacy composer can produce such a handoff only after the exact composed
bytes have an approved hosted URL:

```bash
python scripts/compose_magicfit_property_walkthrough.py \
  --segment <segment-1.mp4> --segment-receipt <segment-1-receipt.json> \
  --segment <segment-2.mp4> --segment-receipt <segment-2-receipt.json> \
  --coverage-receipt <passed-walkthrough-coverage-receipt.json> \
  --property-slug <exact-tour-slug> \
  --hosted-walkthrough-video-url <approved-magicfit-cdn-url> \
  --out <composed-video.mp4> \
  --state-json <strict-source-receipt.json>
```

It emits `launch_eligible=false`, requires the importer handoff, and does not
publish. `materialize_propertyquarry_walkthrough_provider_proof.py` refuses a
MagicFit public bundle and reports the importer command instead. Do not bypass
that refusal or recreate the retired shallow `tour.magicfit.json` profile.

Stage the exact subject with one command:

```bash
EA_PUBLIC_TOUR_DIR=<public-tour-root> \
python scripts/import_magicfit_walkthrough.py \
  --slug <exact-tour-slug> \
  --video-path <composed-video.mp4> \
  --source-receipt <strict-source-receipt.json>
```

MagicFit provider-execution receipt criteria, which are not launch criteria:

- `provider_backend_key=magicfit`
- `render_status=completed`
- a playable hosted walkthrough video is returned, for example `hosted_walkthrough_video_url`
- `magicfit_insufficient_credits` is cleared only after that proof render succeeds

Provider render success is not delivery acceptance. `import_magicfit_walkthrough.py`
keeps the playable artifact and candidate manifest in private staging and writes
the strict `propertyquarry.magicfit_delivery_pending.v2` pointer with
`acceptance_status=pending` and `launch_eligible=false`. The pending pointer is a
closed transform subject: it records the requested and content-addressed final
paths, video hash and size, source-receipt hash, exact base-manifest hash,
generation time, and the source-derived coverage proof object. That object is
empty when the provider receipt has no recognized optional coverage fields.
Its delivery digest covers every one of those values. The staged manifest is never an
authority for its own contents: importer, private-review builder, accepter, and
readiness verifier all reconstruct the same canonical base-to-candidate bytes
using `propertyquarry.magicfit_manifest_transform.v1`. Extra changes to an
unowned manifest field and alternate JSON whitespace fail closed even if every
review receipt is freshly regenerated.

The private browser, operator visual-review, and aggregate evidence receipts use
their strict v3 schemas and bind the exact base-manifest hash,
staged-manifest hash, delivery digest, video identity, and evidence-artifact
hashes. Legacy receipt profiles and receipts for another pending subject fail
closed. A full review never publishes the browser and aggregate evidence as two
loose files. `build_private_magicfit_review_evidence.py` commits both under the
closed
`propertyquarry.magicfit_private_review_receipt_bundle.v1` contract at
`<private-review-root>/<delivery-digest>/`. That mode-0700 directory contains
only the following mode-0600 files:

- `browser-receipt.json`
- `evidence-receipt.json`
- `bundle-manifest.json`

The bundle manifest binds the exact delivery digest and, for both receipts, the
fixed filename, SHA-256 digest, and byte size. The private review root must
already exist, be owned by the invoking user, have mode 0700, remain outside
every public tour root, and contain no symlink path component. Full review uses:

```bash
install -d -m 0700 <private-review-root>
python scripts/build_private_magicfit_review_evidence.py \
  --allow-private-review \
  --slug <exact-tour-slug> \
  --bundle-dir <existing-tour-bundle-dir> \
  --source-receipt <strict-source-receipt.json> \
  --contact-sheet <contact-sheet.png> \
  --visual-review <visual-review.json> \
  --review-bundle-root <private-review-root>
```

Publication uses one bounded root lock and one deterministic temporary
directory, fsyncs every file and directory, then performs an atomic no-replace
rename to the digest name and fsyncs the parent. A retry either validates and
returns the exact committed bundle or safely rebuilds the recognized partial
temporary layout. Unknown, linked, or non-regular temporary entries are never
deleted and fail closed. Browser-only review remains a single exclusive private
file through `--browser-only --browser-receipt-out`; an exact existing valid
browser receipt is returned idempotently.

A separate delivery review must replace that pending state with the closed
`propertyquarry.magicfit_delivery_acceptance.v4` accepted profile. It requires
canonical MagicFit/provider state, the nonempty source-receipt hash, the active
canonical `video_relpath`, exact video hash and size, every transform input, and
a nested `propertyquarry.magicfit_delivery_review.v4` record. Before making the
manifest public, acceptance safe-copies the exact base manifest, source receipt,
browser receipt, aggregate evidence receipt, visual-review receipt,
reviewer-authority artifact, and contact sheet into deterministic private
`.magicfit-deliveries/` paths. Each mode-0600 snapshot is recorded with its
path, SHA-256 digest, and byte size under
`propertyquarry.magicfit_delivery_audit.v1`. Existing different bytes at an
audit-snapshot path or the digest-bound active-media path are a conflict; exact
bytes at those paths are idempotent for crash recovery.

Acceptance consumes browser and aggregate evidence only from the committed
bundle; `--browser-receipt` and `--evidence-receipt` loose-pair arguments fail
closed. Contact sheet, operator visual review, source receipt, and reviewer
authority remain separate safe-opened evidence inputs whose hashes are bound by
the receipt chain:

```bash
EA_PUBLIC_TOUR_DIR=<same-public-tour-root> \
python scripts/accept_magicfit_delivery.py \
  --slug <exact-tour-slug> \
  --source-receipt <strict-source-receipt.json> \
  --contact-sheet <contact-sheet.png> \
  --review-bundle <private-review-root>/<delivery-digest> \
  --visual-review <visual-review.json> \
  --reviewer-authority <signed-reviewer-authorization.json>
```

Acceptance safe-opens the digest-named directory and all three exact files,
rejects extra, missing, linked, mistyped, wrong-mode, wrong-digest, or
hash/size-mismatched content, and then independently revalidates both receipt
subjects against the pending delivery.

`--reviewer-authority` is not a reviewer name, an unsigned approval document, a
PEM key, or a digest-only assertion. It must be the strict
`propertyquarry.magicfit_reviewer_authorization.v1` document whose detached
Ed25519 signature covers the domain-separated canonical subject: delivery
digest, video SHA-256, staged-manifest SHA-256, browser-receipt SHA-256,
aggregate-evidence SHA-256, visual-review SHA-256, contact-sheet SHA-256, and
`reviewed_at`. The authorization's key and authority IDs only select an entry;
they cannot supply or redirect their own trust anchor.

Provision the verification trust separately from the image and from every
public-tour root, then expose its absolute path as
`PROPERTYQUARRY_MAGICFIT_REVIEWER_TRUST_STORE_FILE`. The trust store and each
referenced `propertyquarry.magicfit_reviewer_public_key.v1` record must be
root-owned, regular one-link files under trusted directories, mounted read-only
for the request-serving runtime, and neither group/world-writable nor
executable. Never place the signing private key in the runtime, repository,
authorization document, or public bundle. The trust entry must match the key
and authority IDs, cover the signed review/issuance/expiry window, and remain
unrevoked. Authorization lifetime defaults to at most 24 hours and can never be
configured above seven days.

The base Compose profile intentionally omits this optional trust input so Core
Gold has no Advanced Visual dependency. To enable reviewer verification for the
API and scheduler lanes, provision a verifier-only directory containing
`trust-store.json` and its relative public-key records, confirm every directory
is root-owned and non-writable and every file is root-owned, one-link,
non-executable, and non-writable, then render the explicit overlay before start:

```bash
export PROPERTYQUARRY_MAGICFIT_REVIEWER_TRUST_DIR=/etc/propertyquarry/magicfit-reviewers
test -f "$PROPERTYQUARRY_MAGICFIT_REVIEWER_TRUST_DIR/trust-store.json"
find "$PROPERTYQUARRY_MAGICFIT_REVIEWER_TRUST_DIR" -type l -print -quit | grep -q . && exit 1
find "$PROPERTYQUARRY_MAGICFIT_REVIEWER_TRUST_DIR" -type f -perm /022 -print -quit | grep -q . && exit 1
docker compose \
  -f docker-compose.property.yml \
  -f docker-compose.property-magicfit-reviewer.yml \
  config >/dev/null
```

The overlay requires the host directory explicitly, disables automatic host
path creation, mounts the complete verifier trust directory read-only, and
exposes only the in-container trust-store path. Do not put the signing key,
provider credentials, or public-tour bytes in that directory. Removing the
overlay or trust material immediately makes accepted MagicFit media ineligible;
it does not affect Core search, ranking, packets, or eligible first-party tours.

Missing trust configuration, an unknown or revoked key, an invalid signature,
an out-of-window authorization, or any subject mismatch fails closed before
publication. Public eligibility re-verifies the persisted authorization against
the current external trust material, so revocation cannot be hidden by a warm
media-validation cache. Expiry bounds the review authorization and acceptance
window; it must never be treated as permission to accept stale evidence. Once a
fresh authorization has been admitted, serve-time signature verification uses
its signed issue instant as the historical decision time while still applying
the current key identity and revocation state. Thus routine expiry does not
silently unpublish an accepted asset, but revocation, key replacement, missing
trust, or signature drift does.

The durable review record binds the tour slug, full transform subject, video and
source identities, base/staged manifest hashes, and delivery digest to a UTC
review time, signed-authorization digest and verified non-secret authority
projection, evidence digest, and literal passing checks for end-to-end playback,
walkthrough continuity, visible rotation jumps, intended property/scope, and
sensitive or trial branding. Missing, extra, stale, unbound, mistyped, future,
pre-import, or hash-mismatched fields remain ineligible; status aliases and
truthy strings are not approval. Here, stale means an artifact binding that no
longer matches the active manifest or video bytes, not age alone. The signed
authorization adds bounded independent reviewer authority; allowlisted remote
playback remains a separate live-probed control path.
The readiness verifier safe-opens and rehashes the active manifest, video,
accepted sidecar, and all seven audit snapshots; checks every cross-artifact
digest; revalidates the source-derived coverage proof and v3 receipt subjects;
and reproduces the exact base-to-active manifest bytes. Missing, replaced,
symlinked, truncated, extended, or byte-drifted audit artifacts disqualify the
walkthrough. Legacy accepted profiles have no reproducible audit basis and fail
closed.

Accepted v4 video bytes are published on a fresh mode-0444 inode, and the public
route validates then streams the same descriptor. Production should additionally
serve the public-tour volume from a read-only replica or mount owned by a
separate publication lane; mode bits are defense in depth, not a substitute for
writer/reader isolation. Until that topology is independently observed, this is
a remaining Advanced Visual production-evidence blocker, not a Core Gold blocker.

The authorization supplies reviewer authority, not provider provenance or
launch authority. Advanced Visual Gold still requires the complete governed
provider, quota, privacy, playback, quality, candidate-binding, and protected
live evidence set; digest fields and an unverified `signature` field prove none
of those facts. If signed reviewer authority or any other advanced-visual proof
is unavailable, MagicFit remains unavailable in customer copy. That condition
does not block Core Gold: the search-to-decision loop and eligible first-party
tours remain independently launchable without paid generated media.

Readiness with multiple accounts may become `constrained` rather than blocked if only one account is known depleted.

## OMagic / Magic unblock

`magic` is a public alias for `omagic`; both must resolve to `provider_backend_key=omagic`.

Current blocker shape:

- expected `8` OMagic accounts and zero runtime accounts detected
- `omagic_credentials_missing`
- `omagic_model_upload_endpoint_missing`
- `omagic_model_upload_adapter_disabled`

Required account JSON shape:

```json
[
  {"email": "<omagic-account-email>", "password": "<omagic-account-password>"},
  {"email": "<omagic-account-email-2>", "password": "<omagic-account-password-2>"}
]
```

Merge the OMagic account pool without disabling the `magic` alias:

```bash
chmod 600 <omagic-accounts.json>
python3 scripts/merge_scene_video_provider_accounts_env.py \
  --env-file .env \
  --omagic-accounts-json-file <omagic-accounts.json> \
  --expected-omagic-count 8 \
  --write
```

This writes both OMagic and Magic alias account envs:

- `PROPERTYQUARRY_OMAGIC_ACCOUNTS_JSON`
- `PROPERTYQUARRY_MAGIC_ACCOUNTS_JSON`

File-env mode installs one stable provider-only account file and points both OMagic and Magic alias envs at it:

```bash
chmod 600 <omagic-accounts.json>
python3 scripts/merge_scene_video_provider_accounts_env.py \
  --env-file .env \
  --omagic-accounts-json-file <omagic-accounts.json> \
  --expected-omagic-count 8 \
  --write-file-env \
  --write
```

Default file-env install target:

- host file path: `state/incoming_property_tours/_operator-import-lane/scene_video_provider_accounts/omagic-accounts.json`
- runtime env value: `/data/incoming_property_tours/_operator-import-lane/scene_video_provider_accounts/omagic-accounts.json`

This writes:

- `PROPERTYQUARRY_OMAGIC_ACCOUNTS_JSON_FILE`
- `PROPERTYQUARRY_MAGIC_ACCOUNTS_JSON_FILE`

When `*_ACCOUNTS_JSON_FILE` is present, PropertyQuarry runtime readiness prefers that file over inline `*_ACCOUNTS_JSON`.

Configure one real model-upload adapter target before enabling the adapter:

```bash
PROPERTYQUARRY_OMAGIC_RENDER_ENDPOINT=<provider-render-endpoint>
# or
PROPERTYQUARRY_OMAGIC_RENDER_COMMAND=<provider-render-command>
```

Only set `PROPERTYQUARRY_OMAGIC_MODEL_UPLOAD_ENABLED=1` after a successful model-upload proof render.

OMagic pass criteria:

- real model input is supplied through `--model-path` or `--model-url`
- adapter state reports `model_input_consumed=true`
- adapter state reports `provider_backend_key=omagic`
- hosted tour bundle contains the returned walkthrough video
- regenerated readiness shows `magic` and `omagic` both dispatchable through OMagic

## Mootion unblock

Mootion has two lanes.

Local worker lane:

- Requires `docker` CLI in the API runtime.
- Requires Docker socket or valid `DOCKER_HOST`.
- Current API compose intentionally does not mount `/var/run/docker.sock`.

Remote BrowserAct lane:

- Requires explicit `workflow_id`, `run_url`, or a BrowserAct binding containing Mootion workflow/run metadata.
- Bootstrap/update the bridge with `python3 scripts/bootstrap_mootion_browseract_bridge.py --submit-architect --write-env`.
- The bootstrap writes only the Mootion bridge packet/binding and `CHUMMER6_RUNSITE_VIDEO_BINDING_ID`; it refuses `ONEMIN_*` writes.
- If a principal has an enabled BrowserAct binding scoped to Mootion with workflow/run metadata, `ea.scene_video_generate` auto-selects that bridge without a caller-provided `binding_id`.
- Scene-video passes `force_browseract`, `allow_browseract_remote_fallback`, and `remote_fallback_allowed` when remote Mootion is requested.
- Readiness should report `execution_lane=browseract_remote` while preserving local worker blockers under `mootion_local_worker_blockers`.

Do not mount Docker into the public API container casually. Prefer a dedicated host-tools/sidecar worker if local Docker execution is required.

## UI picker verification

Backend contracts expose:

- PropertyQuarry provider choice: `mootion`, `magicfit`, `omagic`, `magic`
- Runsite scene-video allowed providers: `mootion`, `magicfit`, `omagic`

Manual UI smoke still needed:

- PropertyQuarry walkthrough provider selector shows the expected choices.
- Runsite scene-video request flow accepts the same provider choices.
- `magic` displays or normalizes as OMagic where appropriate.

## Teable / 1min backup boundary

1min.AI account backup is separate from OMagic public routing.

Rules:

- Do not overwrite `ONEMIN_*` values when editing OMagic scene-video.
- Treat Teable backup proof as separate recovery evidence, not runtime readiness.
- If Teable API returns `403`, report the local backup paths and the remote proof gap rather than mutating credentials.

Known local backup locations:

- `/docker/EA/config/onemin_api_keys.local.json`
- `/docker/property/config/onemin_api_keys.local.json`
- `/docker/EA/config/onemin_slot_owners.local.json`

Do not print API keys or passwords in receipts, logs, or user-visible summaries.

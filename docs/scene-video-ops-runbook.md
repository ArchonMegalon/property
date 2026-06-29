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
- one runtime account detected

Do not clear the marker just to make readiness green.

Valid unblock options:

- Add credits to the currently configured MagicFit account, then run a real MagicFit render probe.
- Configure additional MagicFit accounts through supported env shapes, then verify `runtime_account_count > 1`.

Supported account shapes:

```bash
TEAM_MAGICFIT_EMAIL=...
TEAM_MAGICFIT_PASSWORD=...

MAGICFIT_EMAIL_2=...
MAGICFIT_PASSWORD_2=...

PROPERTYQUARRY_MAGICFIT_ACCOUNTS_JSON='[{"email":"...","password":"..."}]'
```

Readiness with multiple accounts may become `constrained` rather than blocked if only one account is known depleted.

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

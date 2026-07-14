from __future__ import annotations

import re
import urllib.parse
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from fastapi.responses import JSONResponse, RedirectResponse
from pydantic import BaseModel, Field

from app.api.dependencies import RequestContext, get_container, get_request_context, require_operator_context
from app.api.routes.product_api_contracts import (
    OperatorCenterActionOut,
    OperatorCenterLaneOut,
    OperatorCenterOut,
    WorkspaceDiagnosticsOut,
    WorkspaceMorningMemoSettingsIn,
    WorkspaceOutcomesOut,
    WorkspacePlanDetailOut,
    WorkspaceSupportBundleOut,
    WorkspaceTrustOut,
    WorkspaceUsageDetailOut,
)
from app.container import AppContainer
from app.product.property_canonical_graph import build_property_passport_snapshot
from app.product.privacy_lifecycle import (
    PrivacyCursorError,
    PrivacyLifecycleConflict,
    build_property_account_export_page,
    build_property_account_privacy_lifecycle,
    redact_privacy_export,
)
from app.product.property_tour_hosting import revoke_hosted_property_tour_bundle
from app.product.service import build_product_service
from app.services.onboarding import (
    PROPERTY_NOTIFICATION_CHANNEL_LABELS,
    normalize_property_notification_channel,
    normalize_property_notification_channels,
    normalize_property_whatsapp_ai_support_phone,
)

router = APIRouter(prefix="/app/api", tags=["product"])
_PROPERTY_NOTIFICATION_PRIMARY_CHANNEL = "telegram"


class PropertyAccountErasureRequestIn(BaseModel):
    idempotency_key: str = Field(default="", max_length=200)


class PropertyAccountErasureConfirmIn(BaseModel):
    confirmation_phrase: str = Field(min_length=1, max_length=40)


def _privacy_response(payload: dict[str, object], *, status_code: int = 200) -> JSONResponse:
    return JSONResponse(
        content=payload,
        status_code=status_code,
        headers={
            "Cache-Control": "no-store",
            "Pragma": "no-cache",
            "X-Robots-Tag": "noindex, nofollow, noarchive, nosnippet",
            "X-Content-Type-Options": "nosniff",
            "Referrer-Policy": "no-referrer",
        },
    )


def _property_notification_explicit_primary(preferences: dict[str, object] | None) -> str:
    payload = dict(preferences or {})
    raw = str(payload.get("preferred_channel") or "").strip()
    if not raw:
        return ""
    try:
        normalized = normalize_property_notification_channel(raw)
    except ValueError:
        return ""
    return normalized


def _persist_property_notification_primary(
    *,
    container: AppContainer,
    principal_id: str,
    preferred_channel: str,
) -> None:
    state = container.onboarding._ensure_state(principal_id)  # noqa: SLF001
    channel_preferences = dict(state.channel_preferences_json or {})
    property_notifications = dict(channel_preferences.get("property_notifications") or {})
    if preferred_channel:
        property_notifications["preferred_channel"] = preferred_channel
    else:
        property_notifications.pop("preferred_channel", None)
        property_notifications.pop("preferred_label", None)
    channel_preferences["property_notifications"] = property_notifications
    container.onboarding._repo.upsert_state(  # noqa: SLF001
        principal_id=state.principal_id,
        onboarding_id=state.onboarding_id,
        workspace_name=state.workspace_name,
        workspace_mode=state.workspace_mode,
        region=state.region,
        language=state.language,
        timezone=state.timezone,
        selected_channels=tuple(state.selected_channels),
        property_search_preferences_json=dict(state.property_search_preferences_json),
        privacy_preferences_json=dict(state.privacy_preferences_json),
        channel_preferences_json=channel_preferences,
        brief_preview_json=dict(state.brief_preview_json),
        status=state.status,
    )


def _sanitized_property_delivery_preferences(
    status: dict[str, object],
    *,
    raw_property_notifications: dict[str, object] | None = None,
) -> dict[str, object]:
    delivery_preferences = dict(status.get("delivery_preferences") or {}) if isinstance(status.get("delivery_preferences"), dict) else {}
    property_notifications = dict(delivery_preferences.get("property_notifications") or {})
    explicit_primary = _property_notification_explicit_primary(raw_property_notifications or property_notifications)
    selected_channels = normalize_property_notification_channels(
        property_notifications.get("selected_channels"),
        fallback=None,
    )
    resolved_primary = explicit_primary
    if not resolved_primary and len(selected_channels) == 1:
        resolved_primary = selected_channels[0]
    if property_notifications:
        property_notifications["preferred_channel"] = resolved_primary
        property_notifications["preferred_label"] = (
            PROPERTY_NOTIFICATION_CHANNEL_LABELS.get(resolved_primary, "")
            if resolved_primary
            else ""
        )
        delivery_preferences["property_notifications"] = property_notifications
    return delivery_preferences


def _support_bundle_download_filename(bundle: dict[str, object]) -> str:
    workspace = dict(bundle.get("workspace") or {})
    raw_name = str(workspace.get("name") or "executive-assistant").strip().lower()
    slug = re.sub(r"[^a-z0-9]+", "-", raw_name).strip("-") or "executive-assistant"
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d")
    return f"{slug}-support-bundle-{stamp}.json"


def _property_account_export_filename(bundle: dict[str, object]) -> str:
    workspace = dict(bundle.get("workspace") or {})
    raw_name = str(workspace.get("name") or "propertyquarry").strip().lower()
    slug = re.sub(r"[^a-z0-9]+", "-", raw_name).strip("-") or "propertyquarry"
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d")
    return f"{slug}-propertyquarry-account-export-{stamp}.json"


def _property_account_export_run(row: dict[str, object]) -> dict[str, object]:
    summary = dict(row.get("summary") or {}) if isinstance(row.get("summary"), dict) else {}
    return {
        "run_id": str(row.get("run_id") or "").strip(),
        "status": str(row.get("status") or summary.get("status") or "").strip(),
        "status_label": str(row.get("status_label") or summary.get("status_label") or "").strip(),
        "created_at": str(row.get("created_at") or "").strip(),
        "updated_at": str(row.get("updated_at") or "").strip(),
        "progress": row.get("progress"),
        "message": str(row.get("message") or "").strip(),
        "summary": summary,
        "property_search_preferences": dict(row.get("property_search_preferences") or {})
        if isinstance(row.get("property_search_preferences"), dict)
        else {},
    }


def _property_account_export_session(row: dict[str, object]) -> dict[str, object]:
    return {
        "session_id": str(row.get("session_id") or "").strip(),
        "email": str(row.get("email") or "").strip(),
        "role": str(row.get("role") or "").strip(),
        "status": str(row.get("status") or "").strip(),
        "source_kind": str(row.get("source_kind") or "").strip(),
        "default_target": str(row.get("default_target") or "").strip(),
        "expires_at": str(row.get("expires_at") or "").strip(),
        "issued_at": str(row.get("issued_at") or "").strip(),
        "revoked_at": str(row.get("revoked_at") or "").strip(),
    }


@router.post("/settings/morning-memo", response_model=WorkspaceDiagnosticsOut)
def update_workspace_morning_memo_settings(
    body: WorkspaceMorningMemoSettingsIn,
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> WorkspaceDiagnosticsOut:
    status = container.onboarding.status(principal_id=context.principal_id)
    workspace = dict(status.get("workspace") or {})
    container.onboarding.start_workspace(
        principal_id=context.principal_id,
        workspace_name=str(body.workspace_name or workspace.get("name") or "PropertyQuarry account").strip() or "PropertyQuarry account",
        workspace_mode=str(workspace.get("mode") or "personal"),
        region=str(workspace.get("region") or ""),
        language=str(body.language or workspace.get("language") or "en").strip() or "en",
        timezone=str(body.timezone or workspace.get("timezone") or "Europe/Vienna").strip() or "Europe/Vienna",
        selected_channels=tuple(str(value) for value in (status.get("selected_channels") or []) if str(value).strip()),
    )
    refreshed = container.onboarding.status(principal_id=context.principal_id)
    privacy = dict(refreshed.get("privacy") or {})
    morning_memo = dict(dict(refreshed.get("delivery_preferences") or {}).get("morning_memo") or {})
    container.onboarding.finalize(
        principal_id=context.principal_id,
        retention_mode=str(privacy.get("retention_mode") or "full_bodies"),
        metadata_only_channels=tuple(str(value) for value in (privacy.get("metadata_only_channels") or []) if str(value).strip()),
        allow_drafts=bool(privacy.get("allow_drafts")),
        allow_action_suggestions=bool(privacy.get("allow_action_suggestions", True)),
        allow_auto_briefs=body.enabled,
        auto_brief_cadence=str(body.cadence or morning_memo.get("cadence") or "daily_morning").strip() or "daily_morning",
        auto_brief_delivery_time_local=str(body.delivery_time_local or morning_memo.get("delivery_time_local") or "08:00").strip() or "08:00",
        auto_brief_quiet_hours_start=str(body.quiet_hours_start or morning_memo.get("quiet_hours_start") or "20:00").strip() or "20:00",
        auto_brief_quiet_hours_end=str(body.quiet_hours_end or morning_memo.get("quiet_hours_end") or "07:00").strip() or "07:00",
        auto_brief_recipient_email=str(body.recipient_email or morning_memo.get("recipient_email") or "").strip(),
        auto_brief_delivery_channel=str(morning_memo.get("delivery_channel") or "email"),
    )
    service = build_product_service(container)
    service.record_surface_event(
        principal_id=context.principal_id,
        event_type="settings_updated",
        surface="settings_api",
        actor=str(context.operator_id or context.access_email or context.principal_id or "browser").strip(),
    )
    return WorkspaceDiagnosticsOut(**service.workspace_diagnostics(principal_id=context.principal_id))


@router.get("/property/account/export")
def export_property_account_data(
    download: bool = Query(False),
    cursor: str = Query(default="", max_length=4000),
    limit: int = Query(default=100, ge=1, le=500),
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> JSONResponse:
    service = build_product_service(container)
    actor = str(context.operator_id or context.access_email or context.principal_id or "browser").strip()
    if not cursor:
        service.record_surface_event(
            principal_id=context.principal_id,
            event_type="property_account_export_downloaded" if download else "property_account_export_opened",
            surface="property_account_export",
            actor=actor,
        )
    try:
        bundle = build_property_account_export_page(
            container=container,
            principal_id=context.principal_id,
            account_email=str(context.access_email or "").strip(),
            cursor=cursor,
            limit=50_000 if download and not cursor else limit,
        )
    except PrivacyCursorError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    status = container.onboarding.status(principal_id=context.principal_id)
    raw_state = container.onboarding._ensure_state(context.principal_id)  # noqa: SLF001
    raw_property_notifications = dict(dict(raw_state.channel_preferences_json or {}).get("property_notifications") or {})
    sanitized_delivery = redact_privacy_export(
        _sanitized_property_delivery_preferences(
            status,
            raw_property_notifications=raw_property_notifications,
        )
    )
    bundle["delivery_preferences"] = dict(sanitized_delivery) if isinstance(sanitized_delivery, dict) else {}
    raw_recent_runs = [
        dict(row)
        for row in list(bundle.get("recent_property_search_runs") or [])
        if isinstance(row, dict)
    ]
    property_passport = build_property_passport_snapshot(
        principal_id=context.principal_id,
        runs=raw_recent_runs,
    ).as_public_dict()
    bundle["property_passport_summary"] = property_passport
    headers = {
        "Cache-Control": "no-store",
        "X-Robots-Tag": "noindex, nofollow, noarchive, nosnippet",
    }
    if download:
        headers["Content-Disposition"] = f'attachment; filename="{_property_account_export_filename(bundle)}"'
    return JSONResponse(content=bundle, headers=headers)


@router.get("/property/account/privacy")
def get_property_account_privacy_status(
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> JSONResponse:
    lifecycle = build_property_account_privacy_lifecycle(container)
    return _privacy_response({"request": lifecycle.latest(principal_id=context.principal_id)})


@router.post("/property/account/erasure-requests")
def request_property_account_erasure(
    body: PropertyAccountErasureRequestIn,
    request: Request,
    idempotency_key: str = Header(default="", alias="Idempotency-Key", max_length=200),
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> JSONResponse:
    lifecycle = build_property_account_privacy_lifecycle(container)
    resolved_key = str(idempotency_key or body.idempotency_key or "").strip()
    if not resolved_key:
        resolved_key = f"browser:{context.principal_id}:active-request"
    payload = lifecycle.request_erasure(
        principal_id=context.principal_id,
        idempotency_key=resolved_key,
        actor=str(context.operator_id or context.access_email or context.principal_id or "browser").strip(),
    )
    return _privacy_response({"request": payload}, status_code=201)


@router.get("/property/account/erasure-requests/{request_id}")
def get_property_account_erasure(
    request_id: str,
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> JSONResponse:
    lifecycle = build_property_account_privacy_lifecycle(container)
    payload = lifecycle.get(principal_id=context.principal_id, request_id=request_id)
    if payload is None:
        raise HTTPException(status_code=404, detail="privacy_erasure_request_not_found")
    return _privacy_response({"request": payload})


@router.post("/property/account/erasure-requests/{request_id}/confirm")
def confirm_property_account_erasure(
    request_id: str,
    body: PropertyAccountErasureConfirmIn,
    deletion_intent: str = Header(default="", alias="X-PropertyQuarry-Deletion-Intent", max_length=80),
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> JSONResponse:
    if deletion_intent != "confirm-account-erasure":
        raise HTTPException(status_code=400, detail="privacy_erasure_intent_header_required")
    lifecycle = build_property_account_privacy_lifecycle(container)
    try:
        payload = lifecycle.confirm_and_erase(
            principal_id=context.principal_id,
            request_id=request_id,
            confirmation_phrase=body.confirmation_phrase,
            actor=str(context.operator_id or context.access_email or context.principal_id or "browser").strip(),
            account_email=str(context.access_email or "").strip(),
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc).strip("'")) from exc
    except PrivacyLifecycleConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return _privacy_response({"request": payload})


@router.post("/property/account/erasure-requests/{request_id}/cancel")
def cancel_property_account_erasure(
    request_id: str,
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> JSONResponse:
    lifecycle = build_property_account_privacy_lifecycle(container)
    try:
        payload = lifecycle.cancel(
            principal_id=context.principal_id,
            request_id=request_id,
            actor=str(context.operator_id or context.access_email or context.principal_id or "browser").strip(),
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc).strip("'")) from exc
    except PrivacyLifecycleConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return _privacy_response({"request": payload})


@router.post("/property/account/erasure-requests/{request_id}/retry-providers")
def retry_property_account_provider_erasure(
    request_id: str,
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> JSONResponse:
    lifecycle = build_property_account_privacy_lifecycle(container)
    try:
        payload = lifecycle.retry_provider_deletions(
            principal_id=context.principal_id,
            request_id=request_id,
            actor=str(context.operator_id or context.access_email or context.principal_id or "browser").strip(),
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc).strip("'")) from exc
    except PrivacyLifecycleConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return _privacy_response({"request": payload})


@router.post("/property/account/notifications")
async def update_property_account_notifications(
    request: Request,
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> RedirectResponse:
    raw_body = (await request.body()).decode("utf-8", "ignore")
    parsed_body = urllib.parse.parse_qs(raw_body, keep_blank_values=True)
    requested_channels = parsed_body.get("notification_channels")
    requested_primary = str((parsed_body.get("preferred_channel") or [""])[0] or "").strip()
    whatsapp_ai_support_phone = (
        str((parsed_body.get("whatsapp_ai_support_phone") or [""])[0] or "")
        if "whatsapp_ai_support_phone" in parsed_body
        else None
    )
    try:
        normalized_channels = normalize_property_notification_channels(requested_channels, fallback=None)
        normalized_channel = ""
        if requested_primary:
            normalized_channel = normalize_property_notification_channel(requested_primary)
            if not normalized_channels:
                normalized_channels = (normalized_channel,)
        elif not normalized_channels:
            raise ValueError("property_notification_channel_required")
        if normalized_channel and normalized_channel not in normalized_channels:
            raise ValueError("property_notification_primary_not_selected")
        normalized_support_phone = (
            normalize_property_whatsapp_ai_support_phone(whatsapp_ai_support_phone)
            if whatsapp_ai_support_phone is not None
            else ""
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    container.onboarding.update_property_notification_preferences(
        principal_id=context.principal_id,
        preferred_channel=normalized_channel or normalized_channels[0],
        selected_channels=normalized_channels,
        whatsapp_ai_support_phone=whatsapp_ai_support_phone,
    )
    if not normalized_channel:
        _persist_property_notification_primary(
            container=container,
            principal_id=context.principal_id,
            preferred_channel="",
        )
    service = build_product_service(container)
    service.record_surface_event(
        principal_id=context.principal_id,
        event_type="property_notification_preferences_updated",
        surface="property_account_lifecycle",
        actor=str(context.operator_id or context.access_email or context.principal_id or "browser").strip(),
        metadata={
            "preferred_channel": normalized_channel,
            "selected_channels": list(normalized_channels),
            "whatsapp_ai_support": bool(normalized_support_phone),
            "whatsapp_ai_support_phone_last4": "".join(ch for ch in normalized_support_phone if ch.isdigit())[-4:],
        },
    )
    return RedirectResponse(
        url="/app/account?notifications_saved=1#delivery",
        status_code=303,
    )


@router.post("/property/public-tours/{slug}/revoke")
def revoke_property_public_tour(
    slug: str,
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> JSONResponse:
    service = build_product_service(container)
    actor = str(context.operator_id or context.access_email or context.principal_id or "browser").strip()
    result = revoke_hosted_property_tour_bundle(
        slug=slug,
        principal_id=context.principal_id,
        actor=actor,
    )
    if str(result.get("status") or "").strip() != "revoked":
        raise HTTPException(status_code=404, detail="property_public_tour_not_found")
    service.record_surface_event(
        principal_id=context.principal_id,
        event_type="property_public_tour_revoked",
        surface="property_account_lifecycle",
        actor=actor,
        metadata={
            "slug": str(result.get("slug") or "").strip(),
            "removed_file_count": int(result.get("removed_file_count") or 0),
        },
    )
    return JSONResponse(
        content=result,
        headers={
            "Cache-Control": "no-store",
            "X-Robots-Tag": "noindex, nofollow, noarchive, nosnippet",
        },
    )


@router.get("/diagnostics", response_model=WorkspaceDiagnosticsOut)
def get_workspace_diagnostics(
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> WorkspaceDiagnosticsOut:
    service = build_product_service(container)
    return WorkspaceDiagnosticsOut(**service.workspace_diagnostics(principal_id=context.principal_id))


@router.get("/operator-center", response_model=OperatorCenterOut)
def get_operator_center(
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
    _operator_guard: None = Depends(require_operator_context),
) -> OperatorCenterOut:
    service = build_product_service(container)
    payload = service.operator_center(
        principal_id=context.principal_id,
        operator_id=str(context.operator_id or "").strip(),
    )
    return OperatorCenterOut(
        generated_at=str(payload.get("generated_at") or ""),
        workspace=dict(payload.get("workspace") or {}),
        operators=dict(payload.get("operators") or {}),
        queue_health=dict(payload.get("queue_health") or {}),
        providers=dict(payload.get("providers") or {}),
        readiness=dict(payload.get("readiness") or {}),
        delivery=dict(payload.get("delivery") or {}),
        access=dict(payload.get("access") or {}),
        sync=dict(payload.get("sync") or {}),
        usage={str(key): int(value or 0) for key, value in dict(payload.get("usage") or {}).items()},
        lanes=[OperatorCenterLaneOut(**dict(value)) for value in list(payload.get("lanes") or [])],
        next_actions=[OperatorCenterActionOut(**dict(value)) for value in list(payload.get("next_actions") or [])],
        recent_runtime=[dict(value) for value in list(payload.get("recent_runtime") or [])],
        snapshot={str(key): int(value or 0) for key, value in dict(payload.get("snapshot") or {}).items()},
        operator_memo_grounding=dict(payload.get("operator_memo_grounding") or {}) or None,
    )


@router.get("/plan", response_model=WorkspacePlanDetailOut)
def get_workspace_plan_detail(
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> WorkspacePlanDetailOut:
    service = build_product_service(container)
    diagnostics = service.workspace_diagnostics(principal_id=context.principal_id)
    service.record_surface_event(
        principal_id=context.principal_id,
        event_type="plan_opened",
        surface="plan_api",
        actor=str(context.operator_id or context.access_email or context.principal_id or "browser").strip(),
    )
    return WorkspacePlanDetailOut(
        workspace=dict(diagnostics.get("workspace") or {}),
        selected_channels=[str(value) for value in (diagnostics.get("selected_channels") or []) if str(value).strip()],
        plan=dict(diagnostics.get("plan") or {}),
        billing=dict(diagnostics.get("billing") or {}),
        entitlements=dict(diagnostics.get("entitlements") or {}),
        commercial=dict(diagnostics.get("commercial") or {}),
        operators=dict(diagnostics.get("operators") or {}),
    )


@router.get("/usage", response_model=WorkspaceUsageDetailOut)
def get_workspace_usage_detail(
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> WorkspaceUsageDetailOut:
    service = build_product_service(container)
    service.record_surface_event(
        principal_id=context.principal_id,
        event_type="usage_opened",
        surface="usage_api",
        actor=str(context.operator_id or context.access_email or context.principal_id or "browser").strip(),
    )
    diagnostics = service.workspace_diagnostics(principal_id=context.principal_id)
    return WorkspaceUsageDetailOut(
        workspace=dict(diagnostics.get("workspace") or {}),
        selected_channels=[str(value) for value in (diagnostics.get("selected_channels") or []) if str(value).strip()],
        usage={str(key): int(value or 0) for key, value in dict(diagnostics.get("usage") or {}).items()},
        analytics=dict(diagnostics.get("analytics") or {}),
        readiness=dict(diagnostics.get("readiness") or {}),
        operators=dict(diagnostics.get("operators") or {}),
    )


@router.get("/outcomes", response_model=WorkspaceOutcomesOut)
def get_workspace_outcomes(
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> WorkspaceOutcomesOut:
    service = build_product_service(container)
    service.record_surface_event(
        principal_id=context.principal_id,
        event_type="outcomes_opened",
        surface="outcomes_api",
        actor=str(context.operator_id or context.access_email or context.principal_id or "browser").strip(),
    )
    return WorkspaceOutcomesOut(**service.workspace_outcomes(principal_id=context.principal_id))


@router.get("/trust", response_model=WorkspaceTrustOut)
def get_workspace_trust(
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> WorkspaceTrustOut:
    service = build_product_service(container)
    service.record_surface_event(
        principal_id=context.principal_id,
        event_type="trust_opened",
        surface="trust_api",
        actor=str(context.operator_id or context.access_email or context.principal_id or "browser").strip(),
    )
    return WorkspaceTrustOut(**service.workspace_trust_summary(principal_id=context.principal_id))


@router.get("/diagnostics/export", response_model=WorkspaceSupportBundleOut)
def export_workspace_support_bundle(
    download: bool = Query(False),
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
    _operator_guard: None = Depends(require_operator_context),
) -> WorkspaceSupportBundleOut | JSONResponse:
    service = build_product_service(container)
    actor = str(context.operator_id or context.access_email or context.principal_id or "browser").strip()
    service.record_surface_event(
        principal_id=context.principal_id,
        event_type="support_bundle_downloaded" if download else "support_bundle_opened",
        surface="diagnostics_export",
        actor=actor,
    )
    bundle = service.workspace_support_bundle(principal_id=context.principal_id)
    if download:
        return JSONResponse(
            content=bundle,
            headers={
                "Content-Disposition": f'attachment; filename="{_support_bundle_download_filename(bundle)}"',
                "Cache-Control": "no-store",
            },
        )
    return WorkspaceSupportBundleOut(**bundle)


@router.get("/support", response_model=WorkspaceSupportBundleOut)
def get_workspace_support_detail(
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
    _operator_guard: None = Depends(require_operator_context),
) -> WorkspaceSupportBundleOut:
    service = build_product_service(container)
    service.record_surface_event(
        principal_id=context.principal_id,
        event_type="support_opened",
        surface="support_api",
        actor=str(context.operator_id or context.access_email or context.principal_id or "browser").strip(),
    )
    return WorkspaceSupportBundleOut(**service.workspace_support_bundle(principal_id=context.principal_id))


@router.post("/support/fix-verification/request", response_model=WorkspaceSupportBundleOut)
def request_support_fix_verification(
    request: Request,
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
    _operator_guard: None = Depends(require_operator_context),
) -> WorkspaceSupportBundleOut:
    service = build_product_service(container)
    actor = str(context.operator_id or context.access_email or context.principal_id or "support").strip()
    try:
        service.request_support_fix_verification(
            principal_id=context.principal_id,
            actor=actor,
            base_url=str(request.base_url),
        )
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return WorkspaceSupportBundleOut(**service.workspace_support_bundle(principal_id=context.principal_id))

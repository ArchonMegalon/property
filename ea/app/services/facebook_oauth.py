from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from app.domain.models import ConnectorBinding, ProviderBindingRecord

if TYPE_CHECKING:
    from app.container import AppContainer

FACEBOOK_PROVIDER_KEY = "facebook_login"
FACEBOOK_CONNECTOR_NAME = "facebook_login"
FACEBOOK_AUTH_HOST = "https://www.facebook.com"
FACEBOOK_GRAPH_HOST = "https://graph.facebook.com"
FACEBOOK_SCOPE_IDENTITY = ("public_profile",)
_FACEBOOK_USED_STATE_KEYS: dict[str, float] = {}
_FACEBOOK_USED_STATE_CACHE_LIMIT = 5000


@dataclass(frozen=True)
class FacebookOAuthConfig:
    app_id: str
    app_secret: str
    redirect_uri: str
    state_secret: str
    graph_version: str


@dataclass(frozen=True)
class FacebookOAuthStartPacket:
    principal_id: str
    requested_scopes: tuple[str, ...]
    state: str
    auth_url: str
    redirect_uri: str
    graph_version: str


@dataclass(frozen=True)
class FacebookOAuthAccount:
    binding: ProviderBindingRecord
    connector_binding: ConnectorBinding | None
    facebook_subject: str
    facebook_email: str
    facebook_name: str
    granted_scopes: tuple[str, ...]
    token_status: str
    last_refresh_at: str


def load_facebook_oauth_config() -> FacebookOAuthConfig:
    app_id = str(os.environ.get("EA_FACEBOOK_OAUTH_APP_ID") or os.environ.get("EA_FACEBOOK_OAUTH_CLIENT_ID") or "").strip()
    app_secret = str(
        os.environ.get("EA_FACEBOOK_OAUTH_APP_SECRET") or os.environ.get("EA_FACEBOOK_OAUTH_CLIENT_SECRET") or ""
    ).strip()
    redirect_uri = str(os.environ.get("EA_FACEBOOK_OAUTH_REDIRECT_URI") or "").strip()
    state_secret = str(
        os.environ.get("EA_FACEBOOK_OAUTH_STATE_SECRET")
        or os.environ.get("EA_GOOGLE_OAUTH_STATE_SECRET")
        or os.environ.get("EA_PROVIDER_SECRET_KEY")
        or os.environ.get("EA_SIGNING_SECRET")
        or ""
    ).strip()
    graph_version = _normalize_graph_version(os.environ.get("EA_FACEBOOK_OAUTH_GRAPH_VERSION") or "v21.0")
    if not app_id:
        raise RuntimeError("facebook_oauth_app_id_missing")
    if not app_secret:
        raise RuntimeError("facebook_oauth_app_secret_missing")
    if not redirect_uri:
        raise RuntimeError("facebook_oauth_redirect_uri_missing")
    if not state_secret:
        raise RuntimeError("facebook_oauth_state_secret_missing")
    return FacebookOAuthConfig(
        app_id=app_id,
        app_secret=app_secret,
        redirect_uri=redirect_uri,
        state_secret=state_secret,
        graph_version=graph_version,
    )


def build_facebook_oauth_start(
    *,
    principal_id: str,
    redirect_uri_override: str | None = None,
    return_to: str | None = None,
    browser_source: str | None = None,
) -> FacebookOAuthStartPacket:
    config = load_facebook_oauth_config()
    requested_scopes = _facebook_identity_scopes()
    redirect_uri = _validated_facebook_redirect_uri(
        str(redirect_uri_override or config.redirect_uri).strip() or config.redirect_uri,
        config=config,
    )
    state_payload: dict[str, Any] = {
        "principal_id": str(principal_id or "").strip(),
        "redirect_uri": redirect_uri,
        "nonce": secrets.token_urlsafe(12),
        "issued_at": int(time.time()),
    }
    normalized_return_to = str(return_to or "").strip()
    if normalized_return_to:
        state_payload["return_to"] = normalized_return_to
    normalized_browser_source = str(browser_source or "").strip()
    if normalized_browser_source:
        state_payload["browser_source"] = normalized_browser_source
    state = _encode_signed_state(state_payload, secret=config.state_secret)
    query = urllib.parse.urlencode(
        {
            "client_id": config.app_id,
            "redirect_uri": redirect_uri,
            "state": state,
            "scope": ",".join(requested_scopes),
            "response_type": "code",
            "auth_type": "rerequest",
        }
    )
    return FacebookOAuthStartPacket(
        principal_id=str(principal_id or "").strip(),
        requested_scopes=requested_scopes,
        state=state,
        auth_url=f"{FACEBOOK_AUTH_HOST}/{config.graph_version}/dialog/oauth?{query}",
        redirect_uri=redirect_uri,
        graph_version=config.graph_version,
    )


def read_facebook_oauth_state(state: str) -> dict[str, Any]:
    config = load_facebook_oauth_config()
    return _decode_signed_state(state, secret=config.state_secret)


def read_facebook_oauth_state_unchecked(state: str) -> dict[str, Any]:
    config = load_facebook_oauth_config()
    return _decode_signed_state(state, secret=config.state_secret, verify_age=False)


def complete_facebook_oauth_callback(
    *,
    container: AppContainer,
    code: str,
    state: str,
) -> FacebookOAuthAccount:
    config = load_facebook_oauth_config()
    state_payload = _decode_signed_state(state, secret=config.state_secret)
    principal_id = str(state_payload.get("principal_id") or "").strip()
    browser_source = str(state_payload.get("browser_source") or "").strip()
    redirect_uri = _validated_facebook_redirect_uri(
        str(state_payload.get("redirect_uri") or config.redirect_uri).strip() or config.redirect_uri,
        config=config,
    )
    _consume_facebook_oauth_state(state_payload)
    token_payload = _exchange_facebook_code_for_token(
        code=code,
        app_id=config.app_id,
        app_secret=config.app_secret,
        redirect_uri=redirect_uri,
        graph_version=config.graph_version,
    )
    access_token = str(token_payload.get("access_token") or "").strip()
    userinfo = _fetch_facebook_userinfo(
        access_token=access_token,
        app_secret=config.app_secret,
        graph_version=config.graph_version,
    )
    requested_scopes = _facebook_identity_scopes()
    facebook_subject = str(userinfo.get("id") or "").strip()
    facebook_email = str(userinfo.get("email") or "").strip().lower()
    facebook_name = str(userinfo.get("name") or "").strip()
    if not facebook_subject:
        raise RuntimeError("facebook_oauth_userinfo_incomplete")
    returned_scope_text = str(token_payload.get("scope") or "").strip()
    returned_scopes = _split_scope_text(returned_scope_text)
    if not returned_scopes:
        raise RuntimeError("facebook_oauth_granted_scopes_missing")
    if not principal_id:
        if browser_source == "sign_in":
            principal_id = _find_facebook_principal(
                container=container,
                facebook_subject=facebook_subject,
                facebook_email=facebook_email,
            )
            if not principal_id:
                raise RuntimeError("facebook_sign_in_not_found")
        else:
            raise RuntimeError("facebook_oauth_principal_missing")
    granted_scopes = returned_scopes
    granted_scopes_source = "facebook_token_response"
    expires_in = _safe_int(token_payload.get("expires_in"), default=0)
    access_token_expires_at = _utc_iso_after_seconds(expires_in) if expires_in > 0 else ""
    binding_id = _primary_facebook_binding_id(principal_id)
    auth_metadata_json = {
        "facebook_subject": facebook_subject,
        "facebook_email": facebook_email,
        "facebook_name": facebook_name,
        "requested_scopes": list(requested_scopes),
        "granted_scopes": list(granted_scopes),
        "granted_scopes_source": granted_scopes_source,
        "returned_scope_text": returned_scope_text,
        "access_token_expires_at": access_token_expires_at,
        "token_status": "active",
        "workspace_mode": "user_oauth",
        "last_successful_api_call_at": _utc_iso_now(),
        "last_refresh_at": _utc_iso_now(),
        "reauth_required_reason": "",
    }
    scope_json = {
        "bundle": "identity",
        "requested_scopes": list(requested_scopes),
        "scopes": list(granted_scopes),
        "granted_scopes": list(granted_scopes),
        "granted_scopes_source": granted_scopes_source,
    }
    probe_details_json = {
        "facebook_email": facebook_email,
        "facebook_subject": facebook_subject,
        "workspace_mode": "user_oauth",
    }
    binding = container.provider_registry.upsert_binding_record(
        binding_id=binding_id,
        principal_id=principal_id,
        provider_key=FACEBOOK_PROVIDER_KEY,
        status="enabled",
        priority=75,
        scope_json=scope_json,
        auth_metadata_json=auth_metadata_json,
        probe_state="ready",
        probe_details_json=probe_details_json,
    )
    connector_binding = container.tool_runtime.upsert_connector_binding(
        principal_id=principal_id,
        connector_name=FACEBOOK_CONNECTOR_NAME,
        external_account_ref=facebook_email or facebook_subject,
        scope_json=scope_json,
        auth_metadata_json=auth_metadata_json,
        status="enabled",
    )
    return FacebookOAuthAccount(
        binding=binding,
        connector_binding=connector_binding,
        facebook_subject=facebook_subject,
        facebook_email=facebook_email,
        facebook_name=facebook_name,
        granted_scopes=granted_scopes,
        token_status="active",
        last_refresh_at=auth_metadata_json["last_refresh_at"],
    )


def _primary_facebook_binding_id(principal_id: str) -> str:
    return f"{str(principal_id or '').strip()}:{FACEBOOK_PROVIDER_KEY}"


def _find_facebook_principal(*, container: AppContainer, facebook_subject: str, facebook_email: str = "") -> str:
    normalized_subject = str(facebook_subject or "").strip()
    normalized_email = str(facebook_email or "").strip().lower()
    if not normalized_subject and not normalized_email:
        return ""
    for binding in container.tool_runtime.list_connector_bindings_for_connector(FACEBOOK_CONNECTOR_NAME, limit=5000):
        if str(binding.status or "").strip().lower() != "enabled":
            continue
        metadata = dict(binding.auth_metadata_json or {})
        candidates = {
            str(binding.external_account_ref or "").strip(),
            str(metadata.get("facebook_subject") or "").strip(),
            str(metadata.get("facebook_email") or "").strip().lower(),
        }
        candidates.discard("")
        if normalized_subject and normalized_subject in candidates:
            return str(binding.principal_id or "").strip()
        if normalized_email and normalized_email in candidates:
            return str(binding.principal_id or "").strip()
    return ""


def _exchange_facebook_code_for_token(
    *,
    code: str,
    app_id: str,
    app_secret: str,
    redirect_uri: str,
    graph_version: str,
) -> dict[str, Any]:
    query = urllib.parse.urlencode(
        {
            "client_id": app_id,
            "client_secret": app_secret,
            "redirect_uri": redirect_uri,
            "code": code,
        }
    )
    request = urllib.request.Request(
        f"{FACEBOOK_GRAPH_HOST}/{_normalize_graph_version(graph_version)}/oauth/access_token?{query}",
        method="GET",
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def _validated_facebook_redirect_uri(raw: str, *, config: FacebookOAuthConfig) -> str:
    candidate = str(raw or "").strip() or str(config.redirect_uri or "").strip()
    parsed = urllib.parse.urlparse(candidate)
    if not parsed.scheme or not parsed.netloc:
        raise RuntimeError("facebook_oauth_redirect_uri_invalid")
    allowed = _facebook_redirect_uri_allowlist(config)
    if candidate.rstrip("/") not in allowed:
        raise RuntimeError("facebook_oauth_redirect_uri_invalid")
    return candidate


def _facebook_redirect_uri_allowlist(config: FacebookOAuthConfig) -> set[str]:
    allowed: set[str] = set()

    def add(raw: str, *, browser_callback: bool = False) -> None:
        value = str(raw or "").strip()
        if not value:
            return
        parsed = urllib.parse.urlparse(value)
        if not parsed.scheme or not parsed.netloc:
            return
        origin = f"{parsed.scheme}://{parsed.netloc}".rstrip("/")
        if browser_callback:
            allowed.add(f"{origin}/facebook/callback")
        else:
            allowed.add(value.rstrip("/"))

    add(config.redirect_uri)
    add(config.redirect_uri, browser_callback=True)
    add(os.environ.get("EA_PUBLIC_APP_BASE_URL") or "", browser_callback=True)
    add(os.environ.get("PROPERTYQUARRY_PUBLIC_BASE_URL") or "", browser_callback=True)
    return allowed


def _fetch_facebook_userinfo(*, access_token: str, app_secret: str, graph_version: str) -> dict[str, Any]:
    if not access_token:
        raise RuntimeError("facebook_oauth_access_token_missing")
    appsecret_proof = hmac.new(app_secret.encode("utf-8"), access_token.encode("utf-8"), hashlib.sha256).hexdigest()
    fields = ["id", "name"]
    if "email" in _facebook_identity_scopes():
        fields.append("email")
    query = urllib.parse.urlencode(
        {
            "fields": ",".join(fields),
            "access_token": access_token,
            "appsecret_proof": appsecret_proof,
        }
    )
    request = urllib.request.Request(
        f"{FACEBOOK_GRAPH_HOST}/{_normalize_graph_version(graph_version)}/me?{query}",
        method="GET",
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def _split_scope_text(raw: str) -> tuple[str, ...]:
    normalized = str(raw or "").replace(",", " ")
    return tuple(sorted({part.strip() for part in normalized.split() if part.strip()}))


def _facebook_identity_scopes() -> tuple[str, ...]:
    raw = str(os.environ.get("PROPERTYQUARRY_FACEBOOK_OAUTH_SCOPES") or os.environ.get("EA_FACEBOOK_OAUTH_SCOPES") or "").strip()
    if not raw:
        return FACEBOOK_SCOPE_IDENTITY
    scopes = _split_scope_text(raw)
    if "public_profile" not in scopes:
        scopes = tuple(sorted((*scopes, "public_profile")))
    return scopes


def _normalize_graph_version(raw: str | None) -> str:
    normalized = str(raw or "").strip().lower().lstrip("/") or "v21.0"
    if not normalized.startswith("v"):
        normalized = f"v{normalized}"
    return normalized


def _encode_signed_state(payload: dict[str, Any], *, secret: str) -> str:
    body = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    body_b64 = _b64url_encode(body)
    signature = hmac.new(secret.encode("utf-8"), body_b64.encode("ascii"), hashlib.sha256).digest()
    return f"{body_b64}.{_b64url_encode(signature)}"


def _decode_signed_state(state: str, *, secret: str, verify_age: bool = True) -> dict[str, Any]:
    raw = str(state or "").strip()
    if "." not in raw:
        raise RuntimeError("facebook_oauth_state_invalid")
    body_b64, signature_b64 = raw.split(".", 1)
    expected = hmac.new(secret.encode("utf-8"), body_b64.encode("ascii"), hashlib.sha256).digest()
    provided = _b64url_decode(signature_b64)
    if not hmac.compare_digest(expected, provided):
        raise RuntimeError("facebook_oauth_state_signature_invalid")
    payload = json.loads(_b64url_decode(body_b64).decode("utf-8"))
    issued_at = _safe_int(payload.get("issued_at"), default=0)
    max_age_seconds = max(_safe_int(os.environ.get("EA_FACEBOOK_OAUTH_STATE_MAX_AGE_SECONDS"), default=21600), 300)
    if verify_age and (issued_at <= 0 or time.time() - issued_at > max_age_seconds):
        raise RuntimeError("facebook_oauth_state_expired")
    return payload


def _consume_facebook_oauth_state(payload: dict[str, Any]) -> None:
    nonce = str(payload.get("nonce") or "").strip()
    issued_at = _safe_int(payload.get("issued_at"), default=0)
    if not nonce or issued_at <= 0:
        raise RuntimeError("facebook_oauth_state_nonce_missing")
    now = time.time()
    max_age_seconds = max(_safe_int(os.environ.get("EA_FACEBOOK_OAUTH_STATE_MAX_AGE_SECONDS"), default=21600), 300)
    cutoff = now - max_age_seconds
    for key, used_at in list(_FACEBOOK_USED_STATE_KEYS.items()):
        if used_at < cutoff:
            _FACEBOOK_USED_STATE_KEYS.pop(key, None)
    if len(_FACEBOOK_USED_STATE_KEYS) > _FACEBOOK_USED_STATE_CACHE_LIMIT:
        for key, _used_at in sorted(_FACEBOOK_USED_STATE_KEYS.items(), key=lambda item: item[1])[
            : max(1, len(_FACEBOOK_USED_STATE_KEYS) - _FACEBOOK_USED_STATE_CACHE_LIMIT)
        ]:
            _FACEBOOK_USED_STATE_KEYS.pop(key, None)
    replay_key = _facebook_oauth_state_replay_key(payload)
    if replay_key in _FACEBOOK_USED_STATE_KEYS:
        raise RuntimeError("facebook_oauth_state_replayed")
    _FACEBOOK_USED_STATE_KEYS[replay_key] = now


def _facebook_oauth_state_replay_key(payload: dict[str, Any]) -> str:
    replay_material = {
        "principal_id": str(payload.get("principal_id") or "").strip(),
        "redirect_uri": str(payload.get("redirect_uri") or "").strip(),
        "browser_source": str(payload.get("browser_source") or "").strip(),
        "nonce": str(payload.get("nonce") or "").strip(),
        "issued_at": _safe_int(payload.get("issued_at"), default=0),
    }
    body = json.dumps(replay_material, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def _safe_int(value: Any, *, default: int) -> int:
    try:
        return int(value)
    except Exception:
        return default


def _utc_iso_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _utc_iso_after_seconds(seconds: int) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() + max(0, int(seconds))))


def _b64url_encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _b64url_decode(raw: str) -> bytes:
    padding = "=" * ((4 - len(raw) % 4) % 4)
    return base64.urlsafe_b64decode(raw + padding)

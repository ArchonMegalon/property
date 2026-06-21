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

import jwt

from app.domain.models import ConnectorBinding, ProviderBindingRecord

if TYPE_CHECKING:
    from app.container import AppContainer

ID_AUSTRIA_PROVIDER_KEY = "id_austria"
ID_AUSTRIA_CONNECTOR_NAME = "id_austria"
ID_AUSTRIA_BPK_CLAIM = "urn:pvpgvat:oidc.bpk"
ID_AUSTRIA_SCOPES = ("openid", "profile")
ID_AUSTRIA_PRODUCTION_ISSUER = "https://idp.id-austria.gv.at"
ID_AUSTRIA_REFERENCE_ISSUER = "https://idp.ref.id-austria.gv.at"
ID_AUSTRIA_ALLOWED_ALGORITHMS = ("RS256", "RS384", "RS512", "ES256", "ES384", "ES512")
_ID_AUSTRIA_USED_STATE_KEYS: dict[str, float] = {}
_ID_AUSTRIA_USED_STATE_CACHE_LIMIT = 5000


@dataclass(frozen=True)
class IdAustriaOidcConfig:
    client_id: str
    client_secret: str
    redirect_uri: str
    state_secret: str
    issuer: str
    authorization_endpoint: str
    token_endpoint: str
    jwks_uri: str


@dataclass(frozen=True)
class IdAustriaStartPacket:
    principal_id: str
    requested_scopes: tuple[str, ...]
    state: str
    auth_url: str
    redirect_uri: str
    issuer: str


@dataclass(frozen=True)
class IdAustriaAccount:
    binding: ProviderBindingRecord
    connector_binding: ConnectorBinding | None
    bpk: str
    subject: str
    given_name: str
    family_name: str
    issuer: str
    token_status: str
    last_refresh_at: str


def load_id_austria_oidc_config() -> IdAustriaOidcConfig:
    client_id = str(os.environ.get("PROPERTYQUARRY_ID_AUSTRIA_CLIENT_ID") or "").strip()
    client_secret = str(os.environ.get("PROPERTYQUARRY_ID_AUSTRIA_CLIENT_SECRET") or "").strip()
    redirect_uri = str(os.environ.get("PROPERTYQUARRY_ID_AUSTRIA_REDIRECT_URI") or "").strip()
    state_secret = str(
        os.environ.get("PROPERTYQUARRY_ID_AUSTRIA_STATE_SECRET")
        or os.environ.get("EA_GOOGLE_OAUTH_STATE_SECRET")
        or os.environ.get("EA_PROVIDER_SECRET_KEY")
        or os.environ.get("EA_SIGNING_SECRET")
        or ""
    ).strip()
    environment = str(os.environ.get("PROPERTYQUARRY_ID_AUSTRIA_ENVIRONMENT") or "production").strip().lower()
    default_issuer = ID_AUSTRIA_REFERENCE_ISSUER if environment in {"reference", "ref", "test"} else ID_AUSTRIA_PRODUCTION_ISSUER
    issuer = str(os.environ.get("PROPERTYQUARRY_ID_AUSTRIA_ISSUER") or default_issuer).strip().rstrip("/")
    authorization_endpoint = str(
        os.environ.get("PROPERTYQUARRY_ID_AUSTRIA_AUTHORIZATION_ENDPOINT")
        or f"{issuer}/auth/idp/profile/oidc/authorize"
    ).strip()
    token_endpoint = str(
        os.environ.get("PROPERTYQUARRY_ID_AUSTRIA_TOKEN_ENDPOINT")
        or f"{issuer}/auth/idp/profile/oidc/token"
    ).strip()
    jwks_uri = str(
        os.environ.get("PROPERTYQUARRY_ID_AUSTRIA_JWKS_URI")
        or f"{issuer}/auth/idp/profile/oidc/keyset"
    ).strip()
    if not client_id:
        raise RuntimeError("id_austria_client_id_missing")
    if not _is_absolute_url(client_id):
        raise RuntimeError("id_austria_client_id_invalid")
    if not client_secret:
        raise RuntimeError("id_austria_client_secret_missing")
    if not redirect_uri:
        raise RuntimeError("id_austria_redirect_uri_missing")
    if not state_secret:
        raise RuntimeError("id_austria_state_secret_missing")
    if not _is_absolute_url(redirect_uri):
        raise RuntimeError("id_austria_redirect_uri_invalid")
    for endpoint_name, endpoint in (
        ("issuer", issuer),
        ("authorization_endpoint", authorization_endpoint),
        ("token_endpoint", token_endpoint),
        ("jwks_uri", jwks_uri),
    ):
        if not _is_absolute_url(endpoint):
            raise RuntimeError(f"id_austria_{endpoint_name}_invalid")
    return IdAustriaOidcConfig(
        client_id=client_id,
        client_secret=client_secret,
        redirect_uri=redirect_uri,
        state_secret=state_secret,
        issuer=issuer,
        authorization_endpoint=authorization_endpoint,
        token_endpoint=token_endpoint,
        jwks_uri=jwks_uri,
    )


def id_austria_sign_in_configured() -> bool:
    try:
        load_id_austria_oidc_config()
    except RuntimeError:
        return False
    return True


def build_id_austria_oidc_start(
    *,
    principal_id: str,
    redirect_uri_override: str | None = None,
    return_to: str | None = None,
    browser_source: str | None = None,
) -> IdAustriaStartPacket:
    config = load_id_austria_oidc_config()
    redirect_uri = _validated_id_austria_redirect_uri(
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
            "response_type": "code",
            "client_id": config.client_id,
            "redirect_uri": redirect_uri,
            "scope": " ".join(ID_AUSTRIA_SCOPES),
            "state": state,
            "nonce": str(state_payload["nonce"]),
        }
    )
    return IdAustriaStartPacket(
        principal_id=str(principal_id or "").strip(),
        requested_scopes=ID_AUSTRIA_SCOPES,
        state=state,
        auth_url=f"{config.authorization_endpoint}?{query}",
        redirect_uri=redirect_uri,
        issuer=config.issuer,
    )


def read_id_austria_oidc_state(state: str) -> dict[str, Any]:
    config = load_id_austria_oidc_config()
    return _decode_signed_state(state, secret=config.state_secret)


def read_id_austria_oidc_state_unchecked(state: str) -> dict[str, Any]:
    config = load_id_austria_oidc_config()
    return _decode_signed_state(state, secret=config.state_secret, verify_age=False)


def complete_id_austria_oidc_callback(
    *,
    container: AppContainer,
    code: str,
    state: str,
) -> IdAustriaAccount:
    config = load_id_austria_oidc_config()
    state_payload = _decode_signed_state(state, secret=config.state_secret)
    principal_id = str(state_payload.get("principal_id") or "").strip()
    browser_source = str(state_payload.get("browser_source") or "").strip()
    redirect_uri = _validated_id_austria_redirect_uri(
        str(state_payload.get("redirect_uri") or config.redirect_uri).strip() or config.redirect_uri,
        config=config,
    )
    _consume_id_austria_oidc_state(state_payload)
    token_payload = _exchange_id_austria_code_for_tokens(
        code=code,
        client_id=config.client_id,
        client_secret=config.client_secret,
        redirect_uri=redirect_uri,
        token_endpoint=config.token_endpoint,
    )
    id_token = str(token_payload.get("id_token") or "").strip()
    claims = _decode_id_austria_id_token(id_token=id_token, config=config)
    bpk = str(claims.get(ID_AUSTRIA_BPK_CLAIM) or claims.get("bpk") or "").strip()
    subject = str(claims.get("sub") or "").strip()
    if not bpk:
        raise RuntimeError("id_austria_bpk_missing")
    if not principal_id:
        if browser_source == "sign_in":
            principal_id = _find_id_austria_principal(container=container, bpk=bpk)
            if not principal_id:
                raise RuntimeError("id_austria_sign_in_not_found")
        else:
            raise RuntimeError("id_austria_principal_missing")
    binding_id = _primary_id_austria_binding_id(principal_id)
    bpk_hash = _stable_hash(bpk)
    token_expires_in = _safe_int(token_payload.get("expires_in"), default=0)
    auth_metadata_json = {
        "id_austria_bpk_hash": bpk_hash,
        "id_austria_subject": subject,
        "given_name": str(claims.get("given_name") or "").strip(),
        "family_name": str(claims.get("family_name") or "").strip(),
        "issuer": str(claims.get("iss") or config.issuer).strip(),
        "requested_scopes": list(ID_AUSTRIA_SCOPES),
        "token_status": "active",
        "workspace_mode": "identity_oidc",
        "access_token_expires_at": _utc_iso_after_seconds(token_expires_in) if token_expires_in > 0 else "",
        "last_successful_api_call_at": _utc_iso_now(),
        "last_refresh_at": _utc_iso_now(),
        "reauth_required_reason": "",
    }
    scope_json = {
        "bundle": "identity",
        "requested_scopes": list(ID_AUSTRIA_SCOPES),
        "scopes": list(ID_AUSTRIA_SCOPES),
        "granted_scopes": list(ID_AUSTRIA_SCOPES),
        "granted_scopes_source": "id_austria_id_token",
    }
    probe_details_json = {
        "id_austria_bpk_hash": bpk_hash,
        "id_austria_subject": subject,
        "workspace_mode": "identity_oidc",
    }
    binding = container.provider_registry.upsert_binding_record(
        binding_id=binding_id,
        principal_id=principal_id,
        provider_key=ID_AUSTRIA_PROVIDER_KEY,
        status="enabled",
        priority=85,
        scope_json=scope_json,
        auth_metadata_json=auth_metadata_json,
        probe_state="ready",
        probe_details_json=probe_details_json,
    )
    connector_binding = container.tool_runtime.upsert_connector_binding(
        principal_id=principal_id,
        connector_name=ID_AUSTRIA_CONNECTOR_NAME,
        external_account_ref=bpk_hash,
        scope_json=scope_json,
        auth_metadata_json=auth_metadata_json,
        status="enabled",
    )
    return IdAustriaAccount(
        binding=binding,
        connector_binding=connector_binding,
        bpk=bpk,
        subject=subject,
        given_name=str(claims.get("given_name") or "").strip(),
        family_name=str(claims.get("family_name") or "").strip(),
        issuer=str(claims.get("iss") or config.issuer).strip(),
        token_status="active",
        last_refresh_at=auth_metadata_json["last_refresh_at"],
    )


def list_id_austria_accounts(*, container: AppContainer, principal_id: str) -> list[IdAustriaAccount]:
    accounts: list[IdAustriaAccount] = []
    for binding in container.provider_registry.list_persisted_binding_records(principal_id=principal_id, limit=100):
        if str(binding.provider_key or "").strip() != ID_AUSTRIA_PROVIDER_KEY:
            continue
        metadata = dict(binding.auth_metadata_json or {})
        accounts.append(
            IdAustriaAccount(
                binding=binding,
                connector_binding=None,
                bpk="",
                subject=str(metadata.get("id_austria_subject") or "").strip(),
                given_name=str(metadata.get("given_name") or "").strip(),
                family_name=str(metadata.get("family_name") or "").strip(),
                issuer=str(metadata.get("issuer") or "").strip(),
                token_status=str(metadata.get("token_status") or "").strip() or "unknown",
                last_refresh_at=str(metadata.get("last_refresh_at") or "").strip(),
            )
        )
    return accounts


def _find_id_austria_principal(*, container: AppContainer, bpk: str) -> str:
    normalized_bpk = str(bpk or "").strip()
    if not normalized_bpk:
        return ""
    bpk_hash = _stable_hash(normalized_bpk)
    for binding in container.tool_runtime.list_connector_bindings_for_connector(ID_AUSTRIA_CONNECTOR_NAME, limit=5000):
        if str(binding.status or "").strip().lower() != "enabled":
            continue
        metadata = dict(binding.auth_metadata_json or {})
        candidates = {
            str(binding.external_account_ref or "").strip(),
            str(metadata.get("id_austria_bpk_hash") or "").strip(),
        }
        if bpk_hash in candidates:
            return str(binding.principal_id or "").strip()
    return ""


def _primary_id_austria_binding_id(principal_id: str) -> str:
    return f"{str(principal_id or '').strip()}:{ID_AUSTRIA_PROVIDER_KEY}"


def _exchange_id_austria_code_for_tokens(
    *,
    code: str,
    client_id: str,
    client_secret: str,
    redirect_uri: str,
    token_endpoint: str,
) -> dict[str, Any]:
    data = urllib.parse.urlencode(
        {
            "code": code,
            "grant_type": "authorization_code",
            "client_secret": client_secret,
            "redirect_uri": redirect_uri,
            "client_id": client_id,
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        token_endpoint,
        data=data,
        method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        raw = response.read(1024 * 1024 + 1)
        if len(raw) > 1024 * 1024:
            raise RuntimeError("id_austria_token_response_too_large")
        return json.loads(raw.decode("utf-8"))


def _decode_id_austria_id_token(*, id_token: str, config: IdAustriaOidcConfig) -> dict[str, Any]:
    token = str(id_token or "").strip()
    if not token:
        raise RuntimeError("id_austria_id_token_missing")
    if token.count(".") != 2:
        raise RuntimeError("id_austria_encrypted_id_token_unsupported")
    signing_key = jwt.PyJWKClient(config.jwks_uri).get_signing_key_from_jwt(token)
    return dict(
        jwt.decode(
            token,
            signing_key.key,
            algorithms=list(ID_AUSTRIA_ALLOWED_ALGORITHMS),
            audience=config.client_id,
            issuer=config.issuer,
            options={"require": ["exp", "iat", "iss", "aud"]},
        )
    )


def _validated_id_austria_redirect_uri(raw: str, *, config: IdAustriaOidcConfig) -> str:
    candidate = str(raw or "").strip() or str(config.redirect_uri or "").strip()
    if not _is_absolute_url(candidate):
        raise RuntimeError("id_austria_redirect_uri_invalid")
    allowed = _id_austria_redirect_uri_allowlist(config)
    if candidate.rstrip("/") not in allowed:
        raise RuntimeError("id_austria_redirect_uri_invalid")
    return candidate


def _id_austria_redirect_uri_allowlist(config: IdAustriaOidcConfig) -> set[str]:
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
            allowed.add(f"{origin}/id-austria/callback")
        else:
            allowed.add(value.rstrip("/"))

    add(config.redirect_uri)
    add(config.redirect_uri, browser_callback=True)
    add(os.environ.get("EA_PUBLIC_APP_BASE_URL") or "", browser_callback=True)
    add(os.environ.get("PROPERTYQUARRY_PUBLIC_BASE_URL") or "", browser_callback=True)
    return allowed


def _is_absolute_url(value: str) -> bool:
    parsed = urllib.parse.urlparse(str(value or "").strip())
    return parsed.scheme in {"https", "http"} and bool(parsed.netloc)


def _encode_signed_state(payload: dict[str, Any], *, secret: str) -> str:
    body = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    body_b64 = _b64url_encode(body)
    signature = hmac.new(secret.encode("utf-8"), body_b64.encode("ascii"), hashlib.sha256).digest()
    return f"{body_b64}.{_b64url_encode(signature)}"


def _decode_signed_state(state: str, *, secret: str, verify_age: bool = True) -> dict[str, Any]:
    raw = str(state or "").strip()
    if "." not in raw:
        raise RuntimeError("id_austria_state_invalid")
    body_b64, signature_b64 = raw.split(".", 1)
    expected = hmac.new(secret.encode("utf-8"), body_b64.encode("ascii"), hashlib.sha256).digest()
    provided = _b64url_decode(signature_b64)
    if not hmac.compare_digest(expected, provided):
        raise RuntimeError("id_austria_state_signature_invalid")
    payload = json.loads(_b64url_decode(body_b64).decode("utf-8"))
    issued_at = _safe_int(payload.get("issued_at"), default=0)
    max_age_seconds = max(_safe_int(os.environ.get("PROPERTYQUARRY_ID_AUSTRIA_STATE_MAX_AGE_SECONDS"), default=21600), 300)
    if verify_age and (issued_at <= 0 or time.time() - issued_at > max_age_seconds):
        raise RuntimeError("id_austria_state_expired")
    return payload


def _id_austria_oidc_state_replay_key(payload: dict[str, Any]) -> str:
    nonce = str(payload.get("nonce") or "").strip()
    issued_at = _safe_int(payload.get("issued_at"), default=0)
    if not nonce or issued_at <= 0:
        raise RuntimeError("id_austria_state_nonce_missing")
    material = json.dumps(
        {
            "browser_source": str(payload.get("browser_source") or "").strip(),
            "issued_at": issued_at,
            "nonce": nonce,
            "principal_id": str(payload.get("principal_id") or "").strip(),
            "redirect_uri": str(payload.get("redirect_uri") or "").strip(),
        },
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def _consume_id_austria_oidc_state(payload: dict[str, Any]) -> None:
    replay_key = _id_austria_oidc_state_replay_key(payload)
    now = time.time()
    max_age_seconds = max(_safe_int(os.environ.get("PROPERTYQUARRY_ID_AUSTRIA_STATE_MAX_AGE_SECONDS"), default=21600), 300)
    expired_before = now - max_age_seconds
    for key, consumed_at in list(_ID_AUSTRIA_USED_STATE_KEYS.items()):
        if consumed_at < expired_before:
            _ID_AUSTRIA_USED_STATE_KEYS.pop(key, None)
    if replay_key in _ID_AUSTRIA_USED_STATE_KEYS:
        raise RuntimeError("id_austria_state_replayed")
    if len(_ID_AUSTRIA_USED_STATE_KEYS) >= _ID_AUSTRIA_USED_STATE_CACHE_LIMIT:
        oldest_key = min(_ID_AUSTRIA_USED_STATE_KEYS, key=_ID_AUSTRIA_USED_STATE_KEYS.get)
        _ID_AUSTRIA_USED_STATE_KEYS.pop(oldest_key, None)
    _ID_AUSTRIA_USED_STATE_KEYS[replay_key] = now


def _safe_int(value: Any, *, default: int) -> int:
    try:
        return int(value)
    except Exception:
        return default


def _utc_iso_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _utc_iso_after_seconds(seconds: int) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() + max(0, int(seconds))))


def _stable_hash(value: str) -> str:
    return hashlib.sha256(str(value or "").encode("utf-8")).hexdigest()[:16]


def _b64url_encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _b64url_decode(raw: str) -> bytes:
    padding = "=" * ((4 - len(raw) % 4) % 4)
    return base64.urlsafe_b64decode(raw + padding)

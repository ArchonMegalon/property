from __future__ import annotations

import hashlib
import json
import os
import urllib.parse
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Iterable


BRILLIANT_DIRECTORIES_PROVIDER_KEY = "brilliant_directories"
BRILLIANT_DIRECTORIES_CONTRACT_NAME = "propertyquarry.brilliant_directories_projection.v1"
BRILLIANT_DIRECTORIES_VERIFICATION_CONTRACT_NAME = "propertyquarry.brilliant_directories_provider_verification.v1"

BRILLIANT_DIRECTORIES_PUBLIC_PROFILE_FIELDS = frozenset(
    {
        "profile_id",
        "display_name",
        "category",
        "public_url",
        "city",
        "region",
        "country_code",
        "summary",
        "tags",
    }
)

BRILLIANT_DIRECTORIES_FORBIDDEN_KEY_MARKERS = (
    "password",
    "secret",
    "token",
    "api_key",
    "email",
    "phone",
    "mobile",
    "whatsapp",
    "telegram",
    "street",
    "address",
    "lat",
    "lng",
    "geo",
    "payment",
    "billing",
    "invoice",
    "property_fact",
    "listing_truth",
    "ranking",
    "fit_score",
    "search_run",
    "preference",
    "medical",
    "family",
    "child",
    "commute",
)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _env_flag(name: str, *, default: bool = False) -> bool:
    raw = str(os.getenv(name) or "").strip().lower()
    if not raw:
        return default
    return raw in {"1", "true", "yes", "on"}


def brilliant_directories_enabled() -> bool:
    return (
        _env_flag("PROPERTYQUARRY_BRILLIANT_DIRECTORIES_ENABLED")
        and _env_flag("PROPERTYQUARRY_BRILLIANT_DIRECTORIES_API_ENABLED")
        and not _env_flag("PROPERTYQUARRY_BRILLIANT_DIRECTORIES_DISABLED")
    )


def _split_csv(raw: str) -> tuple[str, ...]:
    return tuple(item.strip().lower() for item in str(raw or "").split(",") if item.strip())


def _sha256_short(value: str) -> str:
    if not value:
        return ""
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


@dataclass(frozen=True)
class BrilliantDirectoriesApiError(RuntimeError):
    status_code: int
    detail: str

    def __str__(self) -> str:
        return self.detail


@dataclass(frozen=True)
class BrilliantDirectoriesConfig:
    enabled: bool
    base_url: str
    host: str
    allowed_hosts: tuple[str, ...]
    api_key_header: str
    api_key: str = field(default="", repr=False)

    @property
    def configured(self) -> bool:
        return bool(self.enabled and self.base_url and self.api_key and self.host)

    @property
    def api_key_fingerprint(self) -> str:
        return _sha256_short(self.api_key)

    def as_receipt(self) -> dict[str, object]:
        return {
            "enabled": self.enabled,
            "configured": self.configured,
            "base_url": self.base_url,
            "host": self.host,
            "allowed_hosts": list(self.allowed_hosts),
            "api_key_header": self.api_key_header,
            "api_key_fingerprint": self.api_key_fingerprint,
        }


@dataclass(frozen=True)
class BrilliantDirectoriesDirectoryProfile:
    profile_id: str
    display_name: str
    category: str = ""
    public_url: str = ""
    city: str = ""
    region: str = ""
    country_code: str = ""
    summary: str = ""
    tags: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "profile_id": self.profile_id,
            "display_name": self.display_name,
        }
        for key in ("category", "public_url", "city", "region", "country_code", "summary"):
            value = getattr(self, key)
            if value:
                payload[key] = value
        if self.tags:
            payload["tags"] = list(self.tags)
        return payload


@dataclass(frozen=True)
class BrilliantDirectoriesProjectionPacket:
    purpose: str
    projection_mode: str
    profiles: tuple[BrilliantDirectoriesDirectoryProfile, ...]
    generated_at: str = field(default_factory=_utc_now_iso)

    def as_dict(self) -> dict[str, object]:
        return {
            "contract_name": BRILLIANT_DIRECTORIES_CONTRACT_NAME,
            "provider": BRILLIANT_DIRECTORIES_PROVIDER_KEY,
            "purpose": self.purpose,
            "projection_mode": self.projection_mode,
            "generated_at": self.generated_at,
            "profile_count": len(self.profiles),
            "profiles": [profile.as_dict() for profile in self.profiles],
            "allowed_profile_fields": sorted(BRILLIANT_DIRECTORIES_PUBLIC_PROFILE_FIELDS),
            "forbidden_key_markers": list(BRILLIANT_DIRECTORIES_FORBIDDEN_KEY_MARKERS),
            "propertyquarry_source_of_truth": True,
            "publication_allowed": False,
            "direct_property_truth_mutation_allowed": False,
        }


@dataclass(frozen=True)
class BrilliantDirectoriesApiRequest:
    method: str
    url: str
    headers: dict[str, str]
    body: bytes | None = None

    def redacted_receipt(self) -> dict[str, object]:
        redacted_headers = dict(self.headers)
        for key in tuple(redacted_headers):
            if key.lower() in {"authorization", "x-api-key", "api-key"} or "key" in key.lower():
                redacted_headers[key] = "[redacted]"
        return {
            "method": self.method,
            "url": self.url,
            "headers": redacted_headers,
            "body_sha256": hashlib.sha256(self.body or b"").hexdigest() if self.body is not None else "",
        }


def load_brilliant_directories_config() -> BrilliantDirectoriesConfig:
    enabled = brilliant_directories_enabled()
    api_key_header = str(os.getenv("PROPERTYQUARRY_BRILLIANT_DIRECTORIES_API_KEY_HEADER") or "X-Api-Key").strip()
    if not api_key_header:
        api_key_header = "X-Api-Key"
    if not enabled:
        return BrilliantDirectoriesConfig(
            enabled=False,
            base_url="",
            host="",
            allowed_hosts=_split_csv(os.getenv("PROPERTYQUARRY_BRILLIANT_DIRECTORIES_ALLOWED_HOSTS") or ""),
            api_key_header=api_key_header,
            api_key="",
        )

    base_url = str(os.getenv("PROPERTYQUARRY_BRILLIANT_DIRECTORIES_BASE_URL") or "").strip().rstrip("/")
    api_key = str(
        os.getenv("PROPERTYQUARRY_BRILLIANT_DIRECTORIES_API_KEY")
        or os.getenv("BRILLIANT_DIRECTORIES_API_KEY")
        or ""
    ).strip()
    allowed_hosts = _split_csv(os.getenv("PROPERTYQUARRY_BRILLIANT_DIRECTORIES_ALLOWED_HOSTS") or "")
    if not base_url:
        raise BrilliantDirectoriesApiError(400, "brilliant_directories_base_url_missing")
    if not api_key:
        raise BrilliantDirectoriesApiError(503, "brilliant_directories_api_key_missing")
    if not allowed_hosts:
        raise BrilliantDirectoriesApiError(400, "brilliant_directories_allowed_hosts_missing")
    parsed = urllib.parse.urlparse(base_url)
    host = str(parsed.hostname or "").strip().lower()
    if parsed.scheme != "https":
        raise BrilliantDirectoriesApiError(400, "brilliant_directories_https_required")
    if parsed.username or parsed.password:
        raise BrilliantDirectoriesApiError(400, "brilliant_directories_base_url_credentials_forbidden")
    if not host or host not in allowed_hosts:
        raise BrilliantDirectoriesApiError(400, "brilliant_directories_host_not_allowed")
    normalized = urllib.parse.urlunparse(("https", parsed.netloc, parsed.path.rstrip("/"), "", "", "")).rstrip("/")
    return BrilliantDirectoriesConfig(
        enabled=True,
        base_url=normalized,
        host=host,
        allowed_hosts=allowed_hosts,
        api_key_header=api_key_header,
        api_key=api_key,
    )


def _assert_no_forbidden_keys(value: Any, *, path: str = "$") -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            normalized_key = str(key or "").strip().lower()
            if any(marker in normalized_key for marker in BRILLIANT_DIRECTORIES_FORBIDDEN_KEY_MARKERS):
                raise BrilliantDirectoriesApiError(422, f"brilliant_directories_private_field_blocked:{path}.{key}")
            _assert_no_forbidden_keys(child, path=f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _assert_no_forbidden_keys(child, path=f"{path}[{index}]")


def _string(value: object, *, max_length: int = 500) -> str:
    text = " ".join(str(value or "").strip().split())
    return text[:max_length]


def _tags(value: object) -> tuple[str, ...]:
    if isinstance(value, (list, tuple, set)):
        return tuple(_string(item, max_length=48) for item in value if _string(item, max_length=48))[:12]
    if isinstance(value, str):
        return tuple(_string(item, max_length=48) for item in value.split(",") if _string(item, max_length=48))[:12]
    return ()


def build_directory_profile_projection(raw_profile: dict[str, object]) -> BrilliantDirectoriesDirectoryProfile:
    _assert_no_forbidden_keys(raw_profile)
    profile_id = _string(
        raw_profile.get("profile_id")
        or raw_profile.get("member_id")
        or raw_profile.get("id")
        or raw_profile.get("user_id"),
        max_length=96,
    )
    display_name = _string(
        raw_profile.get("display_name")
        or raw_profile.get("name")
        or raw_profile.get("company_name")
        or raw_profile.get("title"),
        max_length=140,
    )
    if not profile_id or not display_name:
        raise BrilliantDirectoriesApiError(422, "brilliant_directories_profile_identity_missing")
    public_url = _string(raw_profile.get("public_url") or raw_profile.get("url") or raw_profile.get("profile_url"), max_length=500)
    if public_url:
        parsed = urllib.parse.urlparse(public_url)
        if parsed.scheme not in {"https", ""}:
            raise BrilliantDirectoriesApiError(422, "brilliant_directories_profile_url_not_https")
    return BrilliantDirectoriesDirectoryProfile(
        profile_id=profile_id,
        display_name=display_name,
        category=_string(raw_profile.get("category") or raw_profile.get("profession") or raw_profile.get("service"), max_length=96),
        public_url=public_url,
        city=_string(raw_profile.get("city"), max_length=96),
        region=_string(raw_profile.get("region") or raw_profile.get("state") or raw_profile.get("province"), max_length=96),
        country_code=_string(raw_profile.get("country_code") or raw_profile.get("country"), max_length=12).upper(),
        summary=_string(raw_profile.get("summary") or raw_profile.get("description") or raw_profile.get("bio"), max_length=500),
        tags=_tags(raw_profile.get("tags") or raw_profile.get("specialties")),
    )


def build_brilliant_directories_projection_packet(
    profiles: Iterable[BrilliantDirectoriesDirectoryProfile],
    *,
    purpose: str,
    projection_mode: str = "public_directory_profile",
) -> BrilliantDirectoriesProjectionPacket:
    normalized_profiles = tuple(profiles)
    if not normalized_profiles:
        raise BrilliantDirectoriesApiError(422, "brilliant_directories_projection_profiles_missing")
    purpose_text = _string(purpose, max_length=140)
    if not purpose_text:
        raise BrilliantDirectoriesApiError(422, "brilliant_directories_projection_purpose_missing")
    return BrilliantDirectoriesProjectionPacket(
        purpose=purpose_text,
        projection_mode=_string(projection_mode, max_length=96) or "public_directory_profile",
        profiles=normalized_profiles,
    )


def build_brilliant_directories_api_request(
    config: BrilliantDirectoriesConfig,
    method: str,
    path: str,
    *,
    payload: dict[str, object] | None = None,
    query: dict[str, object] | None = None,
) -> BrilliantDirectoriesApiRequest:
    if not config.configured:
        raise BrilliantDirectoriesApiError(503, "brilliant_directories_not_configured")
    normalized_method = str(method or "").strip().upper()
    if normalized_method not in {"GET", "POST", "PUT", "PATCH", "DELETE"}:
        raise BrilliantDirectoriesApiError(400, "brilliant_directories_method_not_allowed")
    normalized_path = "/" + str(path or "").strip().lstrip("/")
    parsed_path = urllib.parse.urlparse(normalized_path)
    if parsed_path.scheme or parsed_path.netloc or ".." in normalized_path.split("/"):
        raise BrilliantDirectoriesApiError(400, "brilliant_directories_path_not_allowed")
    url = f"{config.base_url}{urllib.parse.quote(parsed_path.path, safe='/')}"
    if query:
        safe_query = {key: value for key, value in query.items() if value not in {None, ""}}
        if safe_query:
            url = f"{url}?{urllib.parse.urlencode(safe_query)}"
    body = None
    if payload is not None:
        _assert_no_forbidden_keys(payload)
        body = json.dumps(payload, ensure_ascii=True, sort_keys=True).encode("utf-8")
    return BrilliantDirectoriesApiRequest(
        method=normalized_method,
        url=url,
        headers={
            "Accept": "application/json",
            "Content-Type": "application/json",
            config.api_key_header: config.api_key,
            "User-Agent": "PropertyQuarry-BrilliantDirectories/1.0",
        },
        body=body,
    )


def build_brilliant_directories_verification_receipt() -> dict[str, object]:
    try:
        config = load_brilliant_directories_config()
        status = "dry_verified_configured" if config.configured else "disabled"
        error = ""
    except BrilliantDirectoriesApiError as exc:
        config = BrilliantDirectoriesConfig(False, "", "", (), "X-Api-Key")
        status = "blocked"
        error = str(exc)
    return {
        "contract_name": BRILLIANT_DIRECTORIES_VERIFICATION_CONTRACT_NAME,
        "generated_at": _utc_now_iso(),
        "provider": BRILLIANT_DIRECTORIES_PROVIDER_KEY,
        "status": status,
        "error": error,
        "config": config.as_receipt(),
        "live_network_called": False,
        "verified_capabilities": {
            "api_key_config_contract": True,
            "https_base_url_required": True,
            "allowed_host_required": True,
            "public_profile_projection_contract": True,
            "private_property_truth_blocked": True,
            "direct_publication_disabled": True,
        },
        "sources": [
            "https://bootstrap.brilliantdirectories.com/support/solutions/articles/12000101842-brilliant-directories-api-endpoints-technical-reference",
            "https://bootstrap.brilliantdirectories.com/support/solutions/articles/12000088768-developer-hub-generate-api-key-overview",
            "https://bootstrap.brilliantdirectories.com/support/solutions/articles/12000083005-developer-hub-webhooks",
        ],
    }

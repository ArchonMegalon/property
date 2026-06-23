from __future__ import annotations

import hashlib
import json
import os
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping


BRILLIANT_DIRECTORIES_PROVIDER_KEY = "brilliant_directories"
BRILLIANT_DIRECTORIES_CONTRACT_NAME = "propertyquarry.brilliant_directories_projection.v1"
BRILLIANT_DIRECTORIES_VERIFICATION_CONTRACT_NAME = "propertyquarry.brilliant_directories_provider_verification.v1"
BRILLIANT_DIRECTORIES_MAX_RESPONSE_BYTES = 2 * 1024 * 1024
BRILLIANT_DIRECTORIES_WHITE_LABEL_BLOCKLIST = ("brilliantdirectories", "brilliant-directories")

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


def _safe_public_url(raw_url: str, *, allowed_hosts: tuple[str, ...]) -> str:
    raw = str(raw_url or "").strip()
    if not raw:
        return ""
    parsed = urllib.parse.urlparse(raw)
    if parsed.scheme != "https":
        return ""
    host = str(parsed.hostname or "").strip().lower()
    if not host or parsed.username or parsed.password:
        return ""
    if allowed_hosts and host not in allowed_hosts:
        return ""
    return urllib.parse.urlunparse(("https", parsed.netloc, parsed.path.rstrip("/") or "/", "", parsed.query, "")).strip()


def _safe_white_label_handoff_url(raw_url: str, *, allowed_hosts: tuple[str, ...]) -> str:
    normalized = _safe_public_url(raw_url, allowed_hosts=allowed_hosts)
    if not normalized:
        return ""
    parsed = urllib.parse.urlparse(normalized)
    host = str(parsed.hostname or "").strip().lower()
    if any(marker in host for marker in BRILLIANT_DIRECTORIES_WHITE_LABEL_BLOCKLIST):
        return ""
    return normalized


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


class _BrilliantDirectoriesNoRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        raise urllib.error.HTTPError(req.full_url, code, "brilliant_directories_redirect_blocked", headers, fp)


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


def brilliant_directories_billing_handoff_url(config: BrilliantDirectoriesConfig | None = None) -> str:
    resolved_config = config
    if resolved_config is None:
        resolved_config = load_brilliant_directories_config()
    if not resolved_config.configured:
        return ""
    return _safe_white_label_handoff_url(
        str(os.getenv("PROPERTYQUARRY_BRILLIANT_DIRECTORIES_BILLING_URL") or "").strip(),
        allowed_hosts=resolved_config.allowed_hosts,
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


def _safe_directory_public_url(value: object, *, allowed_hosts: tuple[str, ...] = ()) -> str:
    raw = _string(value, max_length=500)
    if not raw:
        return ""
    parsed = urllib.parse.urlparse(raw)
    if parsed.scheme or parsed.netloc:
        host = str(parsed.hostname or "").strip().lower()
        if parsed.scheme != "https" or not host or host not in allowed_hosts:
            return ""
        return urllib.parse.urlunparse(("https", parsed.netloc, parsed.path, "", parsed.query, "")).strip()
    if raw.startswith("//") or "\\" in raw or ".." in raw.split("/"):
        return ""
    return raw.lstrip("/")


def _public_profile_dict(
    raw_profile: Mapping[str, object],
    *,
    include_summary: bool = True,
    allowed_url_hosts: tuple[str, ...] = (),
) -> dict[str, object]:
    first_name = _string(raw_profile.get("first_name"), max_length=70)
    last_name = _string(raw_profile.get("last_name"), max_length=70)
    full_name = " ".join(item for item in (first_name, last_name) if item)
    profile: dict[str, object] = {
        "profile_id": raw_profile.get("profile_id")
        or raw_profile.get("member_id")
        or raw_profile.get("id")
        or raw_profile.get("user_id"),
        "display_name": raw_profile.get("display_name")
        or raw_profile.get("name")
        or raw_profile.get("company_name")
        or raw_profile.get("company")
        or raw_profile.get("title")
        or full_name,
        "category": raw_profile.get("category")
        or raw_profile.get("profession")
        or raw_profile.get("service")
        or raw_profile.get("profession_name"),
        "public_url": _safe_directory_public_url(
            raw_profile.get("public_url")
            or raw_profile.get("url")
            or raw_profile.get("profile_url")
            or raw_profile.get("filename"),
            allowed_hosts=allowed_url_hosts,
        ),
        "city": raw_profile.get("city"),
        "region": raw_profile.get("region") or raw_profile.get("state") or raw_profile.get("province") or raw_profile.get("state_ln"),
        "country_code": raw_profile.get("country_code") or raw_profile.get("country"),
        "tags": raw_profile.get("tags") or raw_profile.get("specialties"),
    }
    if include_summary:
        profile["summary"] = raw_profile.get("summary") or raw_profile.get("description") or raw_profile.get("bio")
    return profile


def build_directory_profile_projection(
    raw_profile: dict[str, object],
    *,
    strict_private_keys: bool = True,
    include_summary: bool = True,
    allowed_url_hosts: tuple[str, ...] = (),
) -> BrilliantDirectoriesDirectoryProfile:
    if strict_private_keys:
        _assert_no_forbidden_keys(raw_profile)
        projected_profile: Mapping[str, object] = raw_profile
    else:
        projected_profile = _public_profile_dict(
            raw_profile,
            include_summary=include_summary,
            allowed_url_hosts=allowed_url_hosts,
        )
    profile_id = _string(
        projected_profile.get("profile_id")
        or projected_profile.get("member_id")
        or projected_profile.get("id")
        or projected_profile.get("user_id"),
        max_length=96,
    )
    display_name = _string(
        projected_profile.get("display_name")
        or projected_profile.get("name")
        or projected_profile.get("company_name")
        or projected_profile.get("title"),
        max_length=140,
    )
    if not profile_id or not display_name:
        raise BrilliantDirectoriesApiError(422, "brilliant_directories_profile_identity_missing")
    public_url = _string(
        projected_profile.get("public_url") or projected_profile.get("url") or projected_profile.get("profile_url"),
        max_length=500,
    )
    if public_url:
        parsed = urllib.parse.urlparse(public_url)
        if parsed.scheme not in {"https", ""}:
            raise BrilliantDirectoriesApiError(422, "brilliant_directories_profile_url_not_https")
    return BrilliantDirectoriesDirectoryProfile(
        profile_id=profile_id,
        display_name=display_name,
        category=_string(
            projected_profile.get("category") or projected_profile.get("profession") or projected_profile.get("service"),
            max_length=96,
        ),
        public_url=public_url,
        city=_string(projected_profile.get("city"), max_length=96),
        region=_string(projected_profile.get("region") or projected_profile.get("state") or projected_profile.get("province"), max_length=96),
        country_code=_string(projected_profile.get("country_code") or projected_profile.get("country"), max_length=12).upper(),
        summary=_string(projected_profile.get("summary") or projected_profile.get("description") or projected_profile.get("bio"), max_length=500),
        tags=_tags(projected_profile.get("tags") or projected_profile.get("specialties")),
    )


def build_directory_profile_projection_from_provider(raw_profile: dict[str, object]) -> BrilliantDirectoriesDirectoryProfile:
    return build_directory_profile_projection(raw_profile, strict_private_keys=False, include_summary=False)


def build_directory_profile_projection_from_configured_provider(
    raw_profile: dict[str, object],
    *,
    allowed_url_hosts: tuple[str, ...],
    include_summary: bool = False,
) -> BrilliantDirectoriesDirectoryProfile:
    return build_directory_profile_projection(
        raw_profile,
        strict_private_keys=False,
        include_summary=include_summary,
        allowed_url_hosts=allowed_url_hosts,
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


def _flatten_form_payload(payload: dict[str, object]) -> dict[str, object]:
    flattened: dict[str, object] = {}
    for key, value in payload.items():
        if isinstance(value, dict):
            raise BrilliantDirectoriesApiError(400, "brilliant_directories_nested_form_payload_not_allowed")
        if isinstance(value, (list, tuple, set)):
            safe_values: list[str] = []
            for item in value:
                if isinstance(item, (dict, list, tuple, set)):
                    raise BrilliantDirectoriesApiError(400, "brilliant_directories_nested_form_payload_not_allowed")
                safe_values.append(_string(item, max_length=500))
            flattened[str(key)] = safe_values
        else:
            flattened[str(key)] = _string(value, max_length=500)
    return flattened


def build_brilliant_directories_api_request(
    config: BrilliantDirectoriesConfig,
    method: str,
    path: str,
    *,
    payload: dict[str, object] | None = None,
    query: dict[str, object] | None = None,
    body_format: str = "form",
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
    content_type = ""
    if payload is not None:
        _assert_no_forbidden_keys(payload)
        normalized_body_format = str(body_format or "").strip().lower()
        if normalized_body_format == "form":
            body = urllib.parse.urlencode(_flatten_form_payload(payload), doseq=True).encode("utf-8")
            content_type = "application/x-www-form-urlencoded"
        elif normalized_body_format == "json":
            body = json.dumps(payload, ensure_ascii=True, sort_keys=True).encode("utf-8")
            content_type = "application/json"
        else:
            raise BrilliantDirectoriesApiError(400, "brilliant_directories_body_format_not_allowed")
    headers = {
        "Accept": "application/json",
        config.api_key_header: config.api_key,
        "User-Agent": "PropertyQuarry-BrilliantDirectories/1.0",
    }
    if content_type:
        headers["Content-Type"] = content_type
    return BrilliantDirectoriesApiRequest(
        method=normalized_method,
        url=url,
        headers=headers,
        body=body,
    )


def execute_brilliant_directories_api_request(
    request: BrilliantDirectoriesApiRequest,
    *,
    timeout_seconds: float = 30.0,
    opener: object | None = None,
) -> dict[str, object]:
    normalized_url = str(request.url or "").strip()
    parsed = urllib.parse.urlparse(normalized_url)
    if parsed.scheme != "https":
        raise BrilliantDirectoriesApiError(400, "brilliant_directories_https_required")
    opener = opener or urllib.request.build_opener(_BrilliantDirectoriesNoRedirectHandler())
    urllib_request = urllib.request.Request(
        normalized_url,
        data=request.body,
        headers=dict(request.headers or {}),
        method=str(request.method or "GET").upper(),
    )
    try:
        response = opener.open(urllib_request, timeout=float(timeout_seconds or 30.0))  # type: ignore[attr-defined]
    except urllib.error.HTTPError as exc:
        reason = str(getattr(exc, "reason", "") or getattr(exc, "msg", "") or exc or "")
        detail = (
            "brilliant_directories_redirect_blocked"
            if int(exc.code) in {301, 302, 303, 307, 308} and "brilliant_directories_redirect_blocked" in reason
            else f"brilliant_directories_http_{int(exc.code)}"
        )
        raise BrilliantDirectoriesApiError(int(exc.code), detail) from exc
    except urllib.error.URLError as exc:
        raise BrilliantDirectoriesApiError(502, "brilliant_directories_unreachable") from exc

    content_type = ""
    try:
        content_type = str(response.getheader("Content-Type", "") or "").lower()
    except Exception:
        content_type = "application/json"
    if content_type and "json" not in content_type:
        raise BrilliantDirectoriesApiError(502, "brilliant_directories_unexpected_content_type")
    try:
        body = response.read(BRILLIANT_DIRECTORIES_MAX_RESPONSE_BYTES + 1)
    except TypeError:
        body = response.read()
    if len(body) > BRILLIANT_DIRECTORIES_MAX_RESPONSE_BYTES:
        raise BrilliantDirectoriesApiError(502, "brilliant_directories_response_too_large")
    if not body:
        return {}
    try:
        parsed_body = json.loads(body.decode("utf-8"))
    except Exception as exc:
        raise BrilliantDirectoriesApiError(502, "brilliant_directories_invalid_json") from exc
    if isinstance(parsed_body, dict):
        return parsed_body
    if isinstance(parsed_body, list):
        return {"message": parsed_body}
    return {"value": parsed_body}


def _brilliant_directories_api_v2_path(config: BrilliantDirectoriesConfig, suffix: str) -> str:
    parsed = urllib.parse.urlparse(config.base_url)
    normalized_path = "/" + str(parsed.path or "").strip("/")
    if normalized_path.rstrip("/").endswith("/api/v2"):
        return "/" + str(suffix or "").strip().lstrip("/")
    return "/api/v2/" + str(suffix or "").strip().lstrip("/")


def build_brilliant_directories_member_search_request(
    config: BrilliantDirectoriesConfig,
    *,
    keyword: str = "",
    category: str = "",
    city: str = "",
    country_code: str = "",
    page: int = 1,
    limit: int = 25,
) -> BrilliantDirectoriesApiRequest:
    payload: dict[str, object] = {
        "q": _string(keyword, max_length=140),
        "category": _string(category, max_length=96),
        "city": _string(city, max_length=96),
        "country_code": _string(country_code, max_length=12).upper(),
        "page": max(1, int(page or 1)),
        "limit": min(100, max(1, int(limit or 25))),
    }
    payload = {key: value for key, value in payload.items() if value not in {"", None}}
    return build_brilliant_directories_api_request(
        config,
        "POST",
        _brilliant_directories_api_v2_path(config, "user/search"),
        payload=payload,
        body_format="form",
    )


def build_brilliant_directories_member_profile_request(
    config: BrilliantDirectoriesConfig,
    *,
    profile_id: str,
) -> BrilliantDirectoriesApiRequest:
    normalized_profile_id = _string(profile_id, max_length=96)
    if not normalized_profile_id or not all(char.isalnum() or char in {"-", "_", ".", ":"} for char in normalized_profile_id):
        raise BrilliantDirectoriesApiError(400, "brilliant_directories_profile_id_invalid")
    return build_brilliant_directories_api_request(
        config,
        "GET",
        _brilliant_directories_api_v2_path(config, f"user/get/{normalized_profile_id}"),
    )


def fetch_brilliant_directories_member_projection_packet(
    config: BrilliantDirectoriesConfig,
    *,
    purpose: str,
    keyword: str = "",
    category: str = "",
    city: str = "",
    country_code: str = "",
    page: int = 1,
    limit: int = 25,
    timeout_seconds: float = 30.0,
    opener: object | None = None,
) -> BrilliantDirectoriesProjectionPacket:
    request = build_brilliant_directories_member_search_request(
        config,
        keyword=keyword,
        category=category,
        city=city,
        country_code=country_code,
        page=page,
        limit=limit,
    )
    response_payload = execute_brilliant_directories_api_request(
        request,
        timeout_seconds=timeout_seconds,
        opener=opener,
    )
    return build_brilliant_directories_projection_packet_from_search_response(
        response_payload,
        purpose=purpose,
        allowed_url_hosts=config.allowed_hosts,
    )


def fetch_brilliant_directories_member_profile_projection_packet(
    config: BrilliantDirectoriesConfig,
    *,
    profile_id: str,
    purpose: str,
    timeout_seconds: float = 30.0,
    opener: object | None = None,
) -> BrilliantDirectoriesProjectionPacket:
    request = build_brilliant_directories_member_profile_request(config, profile_id=profile_id)
    response_payload = execute_brilliant_directories_api_request(
        request,
        timeout_seconds=timeout_seconds,
        opener=opener,
    )
    return build_brilliant_directories_projection_packet_from_profile_response(
        response_payload,
        purpose=purpose,
        allowed_url_hosts=config.allowed_hosts,
    )


def build_brilliant_directories_projection_packet_from_search_response(
    response_payload: dict[str, object],
    *,
    purpose: str,
    allowed_url_hosts: tuple[str, ...] = (),
) -> BrilliantDirectoriesProjectionPacket:
    rows = response_payload.get("message")
    if rows is None and isinstance(response_payload.get("data"), list):
        rows = response_payload.get("data")
    if not isinstance(rows, list):
        raise BrilliantDirectoriesApiError(502, "brilliant_directories_search_response_rows_missing")
    profiles = tuple(
        build_directory_profile_projection_from_configured_provider(row, allowed_url_hosts=allowed_url_hosts)
        for row in rows
        if isinstance(row, dict)
    )
    return build_brilliant_directories_projection_packet(profiles, purpose=purpose)


def build_brilliant_directories_projection_packet_from_profile_response(
    response_payload: dict[str, object],
    *,
    purpose: str,
    allowed_url_hosts: tuple[str, ...] = (),
) -> BrilliantDirectoriesProjectionPacket:
    row = response_payload.get("message")
    if row is None:
        row = response_payload.get("data")
    if isinstance(row, list):
        row = row[0] if row and isinstance(row[0], dict) else None
    if not isinstance(row, dict):
        raise BrilliantDirectoriesApiError(502, "brilliant_directories_profile_response_row_missing")
    profile = build_directory_profile_projection_from_configured_provider(
        row,
        allowed_url_hosts=allowed_url_hosts,
        include_summary=True,
    )
    return build_brilliant_directories_projection_packet((profile,), purpose=purpose, projection_mode="public_directory_profile_detail")


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
            "json_response_executor_contract": True,
            "response_byte_limit": BRILLIANT_DIRECTORIES_MAX_RESPONSE_BYTES,
            "redirects_blocked": True,
            "form_encoded_request_contract": True,
            "public_member_search_projection_contract": True,
            "public_member_profile_projection_contract": True,
            "public_profile_projection_contract": True,
            "public_profile_url_host_allowlist": True,
            "private_property_truth_blocked": True,
            "private_provider_contact_fields_stripped": True,
            "direct_publication_disabled": True,
        },
        "sources": [
            "https://bootstrap.brilliantdirectories.com/support/solutions/articles/12000101842-brilliant-directories-api-endpoints-technical-reference",
            "https://bootstrap.brilliantdirectories.com/support/solutions/articles/12000088768-developer-hub-generate-api-key-overview",
            "https://bootstrap.brilliantdirectories.com/support/solutions/articles/12000083005-developer-hub-webhooks",
        ],
    }

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any


SUBSCRIBR_DEFAULT_BASE_URL = "https://subscribr.ai/api/v1"


def env_flag(name: str, *, default: bool = False) -> bool:
    raw = str(os.getenv(name) or "").strip().lower()
    if not raw:
        return default
    return raw in {"1", "true", "yes", "on"}


def subscribr_enabled() -> bool:
    return env_flag("PROPERTYQUARRY_SUBSCRIBR_ENABLED") and env_flag("PROPERTYQUARRY_SUBSCRIBR_API_ENABLED")


@dataclass(frozen=True)
class SubscribrApiError(RuntimeError):
    status_code: int
    detail: str
    retry_after_seconds: float = 0.0

    def __str__(self) -> str:
        return self.detail


class SubscribrClient:
    def __init__(
        self,
        *,
        token: str = "",
        base_url: str = "",
        timeout_seconds: float = 30.0,
        opener: object | None = None,
    ) -> None:
        self._token = str(token or os.getenv("SUBSCRIBR_PROPERTY_SCRIPT_API_TOKEN") or "").strip()
        self._base_url = str(base_url or os.getenv("PROPERTYQUARRY_SUBSCRIBR_BASE_URL") or SUBSCRIBR_DEFAULT_BASE_URL).rstrip("/")
        self._timeout_seconds = float(timeout_seconds or 30.0)
        self._opener = opener or urllib.request.build_opener()

    @property
    def configured(self) -> bool:
        return bool(self._token)

    @property
    def base_url(self) -> str:
        return self._base_url

    def _headers(self) -> dict[str, str]:
        if not self._token:
            raise SubscribrApiError(503, "subscribr_token_not_configured")
        return {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self._token}",
            "User-Agent": "PropertyQuarry-ContentStudio/1.0",
        }

    def _request(
        self,
        method: str,
        path: str,
        *,
        payload: dict[str, object] | None = None,
        query: dict[str, object] | None = None,
    ) -> dict[str, object]:
        normalized_path = "/" + str(path or "").lstrip("/")
        url = f"{self._base_url}{normalized_path}"
        if query:
            url = f"{url}?{urllib.parse.urlencode({key: value for key, value in query.items() if value not in {None, ''}})}"
        data = None
        if payload is not None:
            data = json.dumps(payload, ensure_ascii=True, sort_keys=True).encode("utf-8")
        request = urllib.request.Request(url, data=data, headers=self._headers(), method=method.upper())
        try:
            response = self._opener.open(request, timeout=self._timeout_seconds)  # type: ignore[attr-defined]
        except urllib.error.HTTPError as exc:
            retry_after = 0.0
            try:
                retry_after = float(exc.headers.get("Retry-After") or 0)
            except Exception:
                retry_after = 0.0
            detail = f"subscribr_http_{int(exc.code)}"
            raise SubscribrApiError(int(exc.code), detail, retry_after_seconds=retry_after) from exc
        except urllib.error.URLError as exc:
            raise SubscribrApiError(502, "subscribr_unreachable") from exc
        body = response.read()
        if not body:
            return {}
        try:
            parsed = json.loads(body.decode("utf-8"))
        except Exception as exc:
            raise SubscribrApiError(502, "subscribr_invalid_json") from exc
        return parsed if isinstance(parsed, dict) else {"items": parsed}

    def get_team(self) -> dict[str, object]:
        return self._request("GET", "/team")

    def get_credits(self) -> dict[str, object]:
        return self._request("GET", "/team/credits")

    def list_channels(self) -> dict[str, object]:
        return self._request("GET", "/channels")

    def create_idea(self, *, channel_id: str | int, payload: dict[str, object]) -> dict[str, object]:
        return self._request("POST", f"/channels/{channel_id}/ideas", payload=payload)

    def create_script(self, *, channel_id: str | int, payload: dict[str, object]) -> dict[str, object]:
        return self._request("POST", f"/channels/{channel_id}/scripts", payload=payload)

    def generate_script(self, *, script_id: str | int, payload: dict[str, object] | None = None) -> dict[str, object]:
        return self._request("POST", f"/scripts/{script_id}/script/generate", payload=payload or {})

    def export_script(self, *, script_id: str | int, export_format: str = "markdown") -> dict[str, object]:
        return self._request("GET", f"/scripts/{script_id}/export", query={"format": export_format})

    def poll_script_export(
        self,
        *,
        script_id: str | int,
        export_format: str = "markdown",
        attempts: int = 6,
        initial_delay_seconds: float = 1.0,
    ) -> dict[str, object]:
        delay = max(0.1, float(initial_delay_seconds or 1.0))
        last_error: SubscribrApiError | None = None
        for attempt in range(max(1, int(attempts or 1))):
            try:
                return self.export_script(script_id=script_id, export_format=export_format)
            except SubscribrApiError as exc:
                last_error = exc
                if exc.status_code not in {202, 404, 409, 429}:
                    raise
                sleep_for = exc.retry_after_seconds or delay
                if attempt < attempts - 1:
                    time.sleep(min(30.0, sleep_for))
                    delay *= 1.5
        raise last_error or SubscribrApiError(504, "subscribr_export_timeout")


def redacted_subscribr_error(error: BaseException) -> dict[str, object]:
    if isinstance(error, SubscribrApiError):
        return {
            "status_code": error.status_code,
            "detail": error.detail,
            "retry_after_seconds": error.retry_after_seconds,
        }
    return {"status_code": 500, "detail": error.__class__.__name__}


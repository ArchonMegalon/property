from __future__ import annotations

import os
from typing import Protocol
from uuid import uuid4

import requests

from app.services.dadan.models import DadanRecordingRequest, DadanRecordingRequestStatus


class DadanAdapter(Protocol):
    def create_recording_request(
        self,
        *,
        title: str,
        instructions: str,
        request_password: str = "",
        metadata: dict[str, object] | None = None,
    ) -> DadanRecordingRequest:
        ...

    def get_recording_request(self, *, request_code: str) -> DadanRecordingRequestStatus:
        ...


def _env_flag(name: str, default: str = "0") -> bool:
    return str(os.getenv(name) or default).strip().lower() in {"1", "true", "yes", "on"}


def _dadan_mode() -> str:
    if not _env_flag("PROPERTYQUARRY_DADAN_ENABLED"):
        return "disabled"
    return str(os.getenv("PROPERTYQUARRY_DADAN_MODE") or "manual").strip().lower() or "manual"


def _base_url() -> str:
    return str(os.getenv("DADAN_BASE_URL") or "https://app.dadan.io/api/v1").strip().rstrip("/")


class EnvDadanAdapter:
    def __init__(self, *, mode: str | None = None, api_key: str | None = None, base_url: str | None = None) -> None:
        self.mode = str(mode or _dadan_mode()).strip().lower() or "disabled"
        self.api_key = str(api_key if api_key is not None else os.getenv("DADAN_API_KEY") or "").strip()
        self.base_url = str(base_url or _base_url()).strip().rstrip("/")

    def create_recording_request(
        self,
        *,
        title: str,
        instructions: str,
        request_password: str = "",
        metadata: dict[str, object] | None = None,
    ) -> DadanRecordingRequest:
        normalized_title = str(title or "PropertyQuarry video request").strip()[:240]
        normalized_instructions = str(instructions or "").strip()[:4000]
        if self.mode in {"disabled", "off"}:
            raise RuntimeError("dadan_disabled")
        if self.mode in {"manual", "api_dry_run", "dry_run"}:
            code = f"dry_{uuid4().hex[:16]}"
            return DadanRecordingRequest(
                request_code=code,
                request_url=f"https://app.dadan.io/request/{code}",
                title=normalized_title,
                status="dry_run",
                raw_response_json={"mode": self.mode, "metadata_keys": sorted(str(key) for key in dict(metadata or {}).keys())},
            )
        if not self.api_key:
            raise RuntimeError("dadan_api_key_required")
        response = requests.post(
            f"{self.base_url}/usedadan/requestrecording",
            headers={"X-Dadan-API-Key": self.api_key, "Content-Type": "application/json"},
            json={
                "title": normalized_title,
                "instructions": normalized_instructions,
                **({"requestPassword": request_password} if str(request_password or "").strip() else {}),
                **({"metadata": dict(metadata or {})} if metadata else {}),
            },
            timeout=30,
        )
        response.raise_for_status()
        payload = response.json() if response.content else {}
        if not isinstance(payload, dict):
            payload = {}
        code = str(payload.get("requestCode") or payload.get("code") or payload.get("request_code") or "").strip()
        url = str(payload.get("requestUrl") or payload.get("url") or payload.get("request_url") or "").strip()
        if not code or not url:
            raise RuntimeError("dadan_create_response_missing_request")
        return DadanRecordingRequest(request_code=code, request_url=url, title=normalized_title, status="created", raw_response_json=payload)

    def get_recording_request(self, *, request_code: str) -> DadanRecordingRequestStatus:
        code = str(request_code or "").strip()
        if not code:
            raise RuntimeError("dadan_request_code_required")
        if self.mode in {"disabled", "off"}:
            raise RuntimeError("dadan_disabled")
        if self.mode in {"manual", "api_dry_run", "dry_run"}:
            return DadanRecordingRequestStatus(request_code=code, status="dry_run", raw_response_json={"mode": self.mode})
        if not self.api_key:
            raise RuntimeError("dadan_api_key_required")
        response = requests.get(
            f"{self.base_url}/usedadan/requestrecording/{code}",
            headers={"X-Dadan-API-Key": self.api_key},
            timeout=30,
        )
        response.raise_for_status()
        payload = response.json() if response.content else {}
        if not isinstance(payload, dict):
            payload = {}
        return DadanRecordingRequestStatus(
            request_code=code,
            status=str(payload.get("status") or "unknown").strip(),
            recording_url=str(payload.get("recordingUrl") or payload.get("recording_url") or "").strip(),
            submitted_at=str(payload.get("submittedAt") or payload.get("submitted_at") or "").strip(),
            raw_response_json=payload,
        )

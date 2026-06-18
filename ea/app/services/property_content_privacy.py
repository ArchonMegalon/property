from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable


EMAIL_RE = re.compile(r"[A-Z0-9._%+\-]{1,120}@[A-Z0-9.\-]{1,160}\.[A-Z]{2,24}", re.IGNORECASE)
PAYMENT_RE = re.compile(r"\b(?:\d[ -]*?){13,19}\b")
PRIVATE_KEY_MARKERS = (
    "api_key",
    "authorization",
    "bearer",
    "billing",
    "card",
    "commute_destination",
    "cookie",
    "credential",
    "customer_email",
    "email",
    "family_member",
    "medical",
    "password",
    "payment",
    "paypal",
    "portal_credential",
    "private_feedback",
    "private_profile",
    "raw_provider_payload",
    "saved_search_name",
    "seller_contact",
    "session",
    "stripe",
    "token",
    "user_email",
    "user_name",
    "work_address",
)
ALLOWED_PRIVATE_CONTEXT_KEYS = frozenset(
    {
        "approved_preferences",
        "approved_fit_context",
        "classification",
        "private_profile_included",
        "user_identity_included",
    }
)


@dataclass(frozen=True)
class PropertyContentPrivacyFinding:
    code: str
    path: str
    detail: str

    def as_dict(self) -> dict[str, str]:
        return {"code": self.code, "path": self.path, "detail": self.detail}


def _key_is_private(key: object) -> bool:
    normalized = re.sub(r"[^a-z0-9]+", "_", str(key or "").strip().lower()).strip("_")
    if normalized in ALLOWED_PRIVATE_CONTEXT_KEYS:
        return False
    return any(marker in normalized for marker in PRIVATE_KEY_MARKERS)


def _walk(value: object, *, path: str = "$") -> Iterable[tuple[str, object, object]]:
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = f"{path}.{key}"
            yield child_path, key, child
            yield from _walk(child, path=child_path)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            child_path = f"{path}[{index}]"
            yield child_path, index, child
            yield from _walk(child, path=child_path)


def property_content_privacy_findings(payload: dict[str, object] | str) -> list[PropertyContentPrivacyFinding]:
    findings: list[PropertyContentPrivacyFinding] = []
    if isinstance(payload, str):
        if EMAIL_RE.search(payload):
            findings.append(PropertyContentPrivacyFinding("email_value_blocked", "$", "email-like value is not allowed"))
        if PAYMENT_RE.search(payload):
            findings.append(PropertyContentPrivacyFinding("payment_value_blocked", "$", "payment-like value is not allowed"))
        return findings
    if not isinstance(payload, dict):
        return findings
    privacy = payload.get("privacy") if isinstance(payload.get("privacy"), dict) else {}
    if isinstance(privacy, dict):
        if bool(privacy.get("user_identity_included")):
            findings.append(PropertyContentPrivacyFinding("user_identity_included", "$.privacy.user_identity_included", "user identity must be excluded"))
        if bool(privacy.get("private_profile_included")):
            findings.append(PropertyContentPrivacyFinding("private_profile_included", "$.privacy.private_profile_included", "private profile must be excluded"))
    for path, key, child in _walk(payload):
        if not isinstance(key, int) and _key_is_private(key):
            findings.append(PropertyContentPrivacyFinding("private_key_blocked", path, f"{key} is not allowed in Subscribr packets"))
        if isinstance(child, str):
            if EMAIL_RE.search(child):
                findings.append(PropertyContentPrivacyFinding("email_value_blocked", path, "email-like value is not allowed"))
            if PAYMENT_RE.search(child):
                findings.append(PropertyContentPrivacyFinding("payment_value_blocked", path, "payment-like value is not allowed"))
    return findings


def validate_property_content_privacy(payload: dict[str, object] | str) -> dict[str, object]:
    findings = property_content_privacy_findings(payload)
    return {
        "status": "fail" if findings else "pass",
        "findings": [finding.as_dict() for finding in findings],
    }


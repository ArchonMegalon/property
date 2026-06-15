from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_property_search_stage_receipts() -> dict[str, object]:
    return {
        "run_started_at": _now_iso(),
        "sources_resolved_at": "",
        "first_shortlist_ready_at": "",
        "deep_research_ready_at": "",
        "results_compiled_at": "",
        "results_delivery_ready_at": "",
        "completed_at": "",
    }


def mark_property_search_stage_receipt(
    receipts: dict[str, object] | None,
    key: str,
    *,
    value: str | None = None,
    overwrite: bool = False,
) -> dict[str, object]:
    packet = dict(receipts or {})
    normalized_key = str(key or "").strip()
    if not normalized_key:
        return packet
    if not overwrite and str(packet.get(normalized_key) or "").strip():
        return packet
    packet[normalized_key] = str(value or "").strip() or _now_iso()
    return packet


def property_search_stage_receipt_summary(
    receipts: dict[str, object] | None,
    *,
    timing_ms: dict[str, object] | None = None,
) -> dict[str, object]:
    packet = dict(receipts or {})
    if timing_ms:
        packet["timing_ms"] = {
            key: value
            for key, value in dict(timing_ms or {}).items()
            if value not in (None, "")
        }
    return packet


def property_search_stage_receipts_ready(receipts: dict[str, object] | None) -> dict[str, bool]:
    packet = dict(receipts or {})
    return {
        "sources_resolved": bool(str(packet.get("sources_resolved_at") or "").strip()),
        "first_shortlist_ready": bool(str(packet.get("first_shortlist_ready_at") or "").strip()),
        "deep_research_ready": bool(str(packet.get("deep_research_ready_at") or "").strip()),
        "results_compiled": bool(str(packet.get("results_compiled_at") or "").strip()),
        "results_delivery_ready": bool(str(packet.get("results_delivery_ready_at") or "").strip()),
        "completed": bool(str(packet.get("completed_at") or "").strip()),
    }

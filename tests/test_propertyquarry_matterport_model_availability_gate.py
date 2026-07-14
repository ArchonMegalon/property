from __future__ import annotations

from scripts.propertyquarry_matterport_model_availability_gate import (
    build_model_availability_receipt,
)


def _probe(status: int = 200) -> dict[str, object]:
    return {
        "http_status": status,
        "final_url": "https://my.matterport.com/show/?m=MODEL123456",
        "content_type": "application/json",
        "transport_error": "",
    }


def test_availability_gate_passes_public_matching_model() -> None:
    receipt = build_model_availability_receipt(
        model_sid="MODEL123456",
        show_probe=_probe(),
        graph_probe=_probe(),
        graph_payload={"data": {"model": {"id": "MODEL123456"}, "view": {}}},
        checked_at="2026-07-11T00:00:00Z",
    )

    assert receipt["status"] == "pass"
    assert receipt["model_available"] is True
    assert receipt["blockers"] == []


def test_availability_gate_fails_closed_for_provider_not_found() -> None:
    receipt = build_model_availability_receipt(
        model_sid="MODEL123456",
        show_probe=_probe(status=404),
        graph_probe=_probe(),
        graph_payload={
            "data": {"model": None, "view": None},
            "errors": [
                {
                    "path": ["model"],
                    "extensions": {"code": "not.found", "httpCode": 404},
                },
                {
                    "path": ["view"],
                    "extensions": {"code": "not.found", "httpCode": 404},
                },
            ],
        },
        checked_at="2026-07-11T00:00:00Z",
    )

    assert receipt["status"] == "blocked"
    assert receipt["model_available"] is False
    assert receipt["show_http_status"] == 404
    assert receipt["blockers"] == [
        "matterport_show_page_unavailable",
        "matterport_model_not_found",
        "matterport_default_view_not_found",
    ]


def test_availability_gate_fails_closed_for_mismatched_model() -> None:
    receipt = build_model_availability_receipt(
        model_sid="MODEL123456",
        show_probe=_probe(),
        graph_probe=_probe(),
        graph_payload={"data": {"model": {"id": "OTHERMODEL1"}, "view": {}}},
        checked_at="2026-07-11T00:00:00Z",
    )

    assert receipt["status"] == "blocked"
    assert receipt["model_available"] is False
    assert receipt["blockers"] == ["matterport_model_sid_mismatch"]

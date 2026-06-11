from __future__ import annotations

from pathlib import Path

from app.product.models import HandoffNote
from app.product.service import ProductService
from tests.product_test_helpers import build_property_client, start_workspace


def reset_packet_repo() -> None:
    from app.repositories import property_packet_publications

    repo = property_packet_publications._MEMORY_REPO
    repo._publications.clear()
    repo._publication_order.clear()
    repo._events.clear()
    repo._event_order.clear()


def seed_packet(
    client,
    *,
    packet_kind: str = "family_review",
    privacy_mode: str = "family_review",
    fliplink_format: str = "flipbook_3d",
    property_ref: str = "listing-123",
    payload: dict[str, object] | None = None,
) -> str:
    import os

    os.environ["PROPERTYQUARRY_LEGACY_PDF_RENDERER_ALLOW"] = "1"
    property_payload = payload or {
        "title": "Family flat near Augarten",
        "property_url": "https://www.willhaben.at/iad/immobilien/d/demo",
        "match_reasons": ["Floorplan and family fit."],
        "floorplan_refs": ["https://packets.propertyquarry.com/assets/floorplan.pdf"],
        "photo_refs": ["https://packets.propertyquarry.com/assets/photo.jpg"],
        "property_facts": {
            "rooms": 3,
            "area_m2": 84,
            "street_address": "Private Street 4",
            "map_lat": 48.2,
            "map_lng": 16.3,
            "has_floorplan": True,
            "postal_name": "1020 Wien",
        },
        "public_preference_snapshot": {"prefer_balcony": True},
    }
    response = client.post(
        f"/app/api/properties/{property_ref}/packets/render",
        json={
            "packet_kind": packet_kind,
            "privacy_mode": privacy_mode,
            "fliplink_format": fliplink_format,
            "property_payload": property_payload,
        },
    )
    assert response.status_code == 200, response.text
    return response.json()["publication"]["publication_id"]


def property_client_with_workspace(*, principal_id: str, tmp_path: Path):
    import os

    os.environ["EA_STORAGE_BACKEND"] = "memory"
    os.environ["EA_ARTIFACTS_DIR"] = str(tmp_path)
    os.environ["PROPERTYQUARRY_LEGACY_PDF_RENDERER_ALLOW"] = "1"
    client = build_property_client(principal_id=principal_id)
    start_workspace(client, mode="personal", workspace_name="PropertyQuarry")
    return client


def seed_property_search_preferences(client) -> None:
    stored = client.post(
        "/v1/onboarding/property-search/preferences",
        json={
            "country_code": "AT",
            "language_code": "de",
            "listing_mode": "buy",
            "property_type": "apartment",
            "location_query": "Wien",
            "keywords": "lift family balcony",
            "investment_research_mode": "auto",
            "selected_platforms": ["willhaben"],
            "preference_person_id": "self",
            "max_results_per_source": 4,
        },
    )
    assert stored.status_code == 200, stored.text


def install_property_run(monkeypatch, *, property_url: str, title: str = "Augarten flat") -> None:
    top_candidate = {
        "title": title,
        "property_url": property_url,
        "fit_summary": "Personal fit 92/100 · shortlist · Lift and transit fit.",
        "recommendation": "shortlist",
        "review_url": "https://propertyquarry.com/review/augarten",
        "tour_url": "https://propertyquarry.com/tours/augarten",
        "match_reasons": ["Lift and transit fit."],
        "mismatch_reasons": [],
        "property_facts": {
            "price_eur": 420000.0,
            "price_display": "EUR 420,000",
            "area_m2": 78,
            "address": "Wien",
            "postal_name": "Wien",
        },
    }

    def _fake_run_status(self, *, principal_id: str, run_id: str):
        return {
            "generated_at": "2026-06-07T10:00:00+00:00",
            "run_id": run_id,
            "principal_id": principal_id,
            "status_url": f"/app/api/signals/property/search/run/{run_id}",
            "status": "processed",
            "selected_platforms": ["willhaben"],
            "progress": 100,
            "current_step": "completed",
            "message": "Property scouting run completed.",
            "stages_total": 8,
            "steps_completed": 8,
            "summary": {
                "sources_total": 1,
                "listing_total": 3,
                "tour_created_total": 1,
                "tour_existing_total": 0,
                "sources": [
                    {
                        "source_label": "Willhaben",
                        "listing_total": 3,
                        "high_fit_total": 1,
                        "tour_created_total": 1,
                        "notified_total": 1,
                        "top_fit_score": 0.92,
                        "top_candidates": [top_candidate],
                    }
                ],
            },
            "events": [
                {"step": "sources_resolved", "message": "Resolved 1 source for scanning.", "status": "in_progress"},
                {"step": "completed", "message": "Property scouting run completed.", "status": "processed"},
            ],
        }

    def _fake_handoffs(self, *, principal_id: str, limit: int = 20, operator_id: str = "", status: str | None = "pending"):
        return (
            HandoffNote(
                id="human_task:tour-1",
                queue_item_ref="queue:tour-1",
                summary="Hosted 3D page for shortlist",
                owner="office",
                due_time=None,
                escalation_status="high",
                task_type="property_tour_followup",
                delivery_reason="Lift, playground and subway fit the profile.",
                property_url=property_url,
                tour_url="https://propertyquarry.com/tours/augarten",
            ),
        )

    monkeypatch.setattr(ProductService, "get_property_search_run_status", _fake_run_status)
    monkeypatch.setattr(ProductService, "list_handoffs", _fake_handoffs)

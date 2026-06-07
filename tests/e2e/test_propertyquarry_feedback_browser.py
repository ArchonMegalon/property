from __future__ import annotations

from pathlib import Path

import pytest

from tests.propertyquarry_phase_helpers import (
    install_property_run,
    property_client_with_workspace,
    reset_packet_repo,
    seed_packet,
    seed_property_search_preferences,
)


@pytest.fixture(autouse=True)
def _reset_repo() -> None:
    reset_packet_repo()


def test_packet_dashboard_and_workbench_show_feedback_language(monkeypatch, tmp_path: Path) -> None:
    client = property_client_with_workspace(principal_id="pq-phase2-browser", tmp_path=tmp_path)
    publication_id = seed_packet(client, property_ref="listing-phase2-browser")
    response = client.post(
        "/app/api/property-feedback",
        json={
            "stakeholder_id": "family-bob",
            "stakeholder_label": "Bob",
            "property_ref": "listing-phase2-browser",
            "publication_id": publication_id,
            "category": "concern",
            "text": "Noise on the street side.",
        },
    )
    assert response.status_code == 200

    page = client.get("/app/properties/packets")
    assert page.status_code == 200
    assert "Structured feedback" in page.text
    assert "No structured feedback yet." not in page.text

    seed_property_search_preferences(client)
    install_property_run(monkeypatch, property_url="https://example.com/listing-phase2")
    workbench = client.get("/app/properties", params={"run_id": "run-phase2"})
    assert workbench.status_code == 200
    assert "Top objections" in workbench.text
    assert "Stakeholder timeline" in workbench.text

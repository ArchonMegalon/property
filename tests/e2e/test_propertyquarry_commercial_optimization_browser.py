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


def test_workspace_and_packet_dashboard_show_commercial_and_optimization_language(monkeypatch, tmp_path: Path) -> None:
    client = property_client_with_workspace(principal_id="pq-phase6-browser", tmp_path=tmp_path)
    publication_id = seed_packet(client, property_ref="listing-phase6-browser")
    client.post(
        f"/app/api/properties/packets/{publication_id}/fliplink/analytics-snapshot",
        json={"views": 8, "unique_visitors": 2, "average_time_seconds": 55},
    )
    seed_property_search_preferences(client)
    install_property_run(monkeypatch, property_url="https://example.com/listing-phase6")
    workspace = client.get("/app/properties", params={"run_id": "run-phase6"})
    assert workspace.status_code == 200
    assert "View plan tiers" in workspace.text
    assert "Open billing controls" in workspace.text

    packets = client.get("/app/properties/packets")
    assert packets.status_code == 200
    assert "Optimization recommendations" in packets.text

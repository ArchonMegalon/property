from __future__ import annotations

from pathlib import Path

import pytest

from tests.propertyquarry_phase_helpers import install_property_run, property_client_with_workspace, reset_packet_repo, seed_property_search_preferences


@pytest.fixture(autouse=True)
def _reset_repo() -> None:
    reset_packet_repo()


def test_workbench_surface_timeline_language(monkeypatch, tmp_path: Path) -> None:
    client = property_client_with_workspace(principal_id="pq-phase5-browser", tmp_path=tmp_path)
    seed_property_search_preferences(client)
    install_property_run(monkeypatch, property_url="https://example.com/listing-phase5")
    workbench = client.get("/app/properties", params={"run_id": "run-phase5"})
    assert workbench.status_code == 200
    assert "Timeline" in workbench.text
    assert "More context" in workbench.text

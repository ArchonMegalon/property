from __future__ import annotations

from tests.product_test_helpers import build_property_operator_client


def test_property_content_studio_workflow_is_local_first_and_review_gated(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("PROPERTYQUARRY_CONTENT_JOB_LEDGER", str(tmp_path / "ledger.json"))
    monkeypatch.setenv("PROPERTYQUARRY_SUBSCRIBR_COMPLETION_DIR", str(tmp_path / "completion"))
    client = build_property_operator_client(principal_id="content-e2e")

    created = client.post("/app/api/property/content/source-packets/synthetic-dossier")
    packet = created.json()["packet"]
    requested = client.post("/app/api/property/content/subscribr/request-script", json={"packet": packet})
    receipt = client.post(
        "/app/api/property/content/subscribr/script-receipt",
        json={
            "packet": packet,
            "markdown": (
                "# Why this listing matched\n\n"
                "Generated from the reviewed dossier and source packet. "
                "Heating system remains unknown and should be verified before the viewing.\n"
            ),
            "provider_channel_id": "212",
            "provider_idea_id": "idea-1",
            "provider_script_id": "script-1",
        },
    )
    studio = client.get("/admin/property/content-studio")

    assert created.status_code == 200
    assert created.json()["validation"]["status"] == "pass"
    assert requested.status_code == 200
    assert requested.json()["job"]["provider_status"] == "disabled"
    assert receipt.status_code == 200, receipt.text
    assert receipt.json()["status"] == "review_required"
    assert receipt.json()["publication_allowed"] is False
    assert studio.status_code == 200
    assert "pq-synthetic-dossier-demo" in studio.text


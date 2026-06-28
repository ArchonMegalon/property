from __future__ import annotations

import html
import json
import re

from app.product.service import ProductService
from tests.product_test_helpers import build_property_client, start_workspace


def test_propertyquarry_results_surface_omits_empty_outcome_when_ranked_results_exist(monkeypatch) -> None:
    client = build_property_client(principal_id="pq-results-no-empty-outcome")
    start_workspace(client, mode="personal", workspace_name="Property Office")

    def _fake_run_status(self, *, principal_id: str, run_id: str):
        return {
            "run_id": run_id,
            "principal_id": principal_id,
            "status_url": f"/app/api/signals/property/search/run/{run_id}",
            "status": "completed_partial",
            "progress": 100,
            "message": "Property scouting run completed.",
            "property_search_preferences": {
                "country_code": "AT",
                "listing_mode": "rent",
                "location_query": "1010 Vienna, 1020 Vienna",
                "selected_location_values": ["1010 Vienna", "1020 Vienna"],
                "property_type": ["any"],
                "min_match_score": 0,
            },
            "summary": {
                "status": "completed_partial",
                "listing_total": 3,
                "reviewed_listing_total": 336,
                "filtered_total": 171,
                "held_back_total": 171,
                "filtered_area_total": 104,
                "filtered_generic_page_total": 66,
                "score_demoted_total": 0,
                "high_match_min_score": 0,
                "ranked_candidates": [
                    {
                        "candidate_ref": "cand-1010",
                        "title": "Moderne Wohn&Bürofläche mit Balkon im Herzen Wiens",
                        "property_url": "https://example.test/1010-home",
                        "source_label": "Willhaben",
                        "fit_score": 53,
                        "fit_summary": "Currently leads the run.",
                        "property_facts": {"postal_name": "1010 Wien", "rooms": 4},
                    },
                    {
                        "candidate_ref": "cand-1020",
                        "title": "2 TERRASSEN!! 4 ZIMMER, ZENTRALE LAGE mit FERNBLICK!!",
                        "property_url": "https://example.test/1020-home",
                        "source_label": "Willhaben",
                        "fit_score": 53,
                        "fit_summary": "Currently leads the run.",
                        "property_facts": {"postal_name": "1020 Wien", "rooms": 4},
                    },
                    {
                        "candidate_ref": "cand-1020-b",
                        "title": "Viertel 2: Trabrennbahnausblick; Tischler-Meisterwerk!",
                        "property_url": "https://example.test/1020-home-b",
                        "source_label": "Willhaben",
                        "fit_score": 48,
                        "fit_summary": "Still worth reviewing.",
                        "property_facts": {"postal_name": "1020 Wien", "rooms": 1},
                    },
                ],
                "sources": [],
            },
            "events": [{"step": "completed", "message": "Property scouting run completed.", "status": "processed"}],
        }

    monkeypatch.setattr(ProductService, "get_property_search_run_status", _fake_run_status)

    response = client.get("/app/properties", params={"run_id": "run-ranked-live"}, headers={"host": "propertyquarry.com"})
    assert response.status_code == 200
    workbench_match = re.search(
        r'<script type="application/json" data-property-workbench-json>(.*?)</script>',
        response.text,
        re.S,
    )
    assert workbench_match
    workbench_payload = json.loads(html.unescape(workbench_match.group(1)))
    assert len(workbench_payload["results"]) >= 1
    assert workbench_payload["empty_outcome"] == {}

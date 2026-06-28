from __future__ import annotations

from scripts.propertyquarry_live_empty_recovery_canary import (
    _extract_counterfactual_buttons,
    _extract_empty_state_copy,
    _extract_filtered_dialog_slider_fields,
    build_live_empty_recovery_canary_receipt,
)


def test_live_empty_recovery_canary_extracts_counterfactual_buttons_and_slider() -> None:
    html = """
    <section class="pqx-stage pqx-running pqx-empty-results">
      <aside>
        <h1>No shortlist yet.</h1>
        <p class="pqx-note pqx-empty-outcome-line">10 listings matched the provider sweep.</p>
      </aside>
      <div data-pqx-counterfactuals>
        <div class="pqx-suppression-grid">
          <div class="pqx-suppression-item pqx-suppression-item-adjustable">
            <strong>Let score rank every home</strong>
            <span class="pqx-note">Lower the current ranking bar.</span>
            <label class="pqx-filter-radius-control pqx-suppression-slider">
              <span>Ranking bar <b data-pqx-filter-slider-value>15 /100</b></span>
              <input
                type="range"
                min="0"
                max="35"
                step="5"
                value="15"
                data-pqx-filter-slider
                data-pqx-filter-field="min_match_score"
                data-pqx-filter-kind="ranking_bar"
                data-pqx-filter-unit="/100"
              >
            </label>
            <button class="pqx-suppression-action" type="button" data-pqx-counterfactual='{"min_match_score": 15}' aria-label="Relax rule">Use 15/100</button>
          </div>
        </div>
      </div>
      <dialog class="pqx-filtered-dialog" data-pqx-filtered-dialog>
        <div class="pqx-filtered-dialog-rule">
          <strong>Let score rank every home</strong>
          <label class="pqx-filter-radius-control">
            <span>Ranking bar <b data-pqx-filter-slider-value>15 /100</b></span>
            <input
              type="range"
              min="0"
              max="35"
              step="5"
              value="15"
              data-pqx-filter-slider
              data-pqx-filter-field="min_match_score"
              data-pqx-filter-kind="ranking_bar"
              data-pqx-filter-unit="/100"
            >
          </label>
        </div>
      </dialog>
      <section class="pqx-card pqx-empty-results-note" data-pqx-ranked-candidates></section>
    </section>
    """

    assert _extract_empty_state_copy(html)["heading"] == "No shortlist yet."
    assert _extract_counterfactual_buttons(html) == [
        {
            "title": "Let score rank every home",
            "action": "Use 15/100",
            "adjustments": {"min_match_score": 15},
            "payload_text": '{"min_match_score": 15}',
        }
    ]
    assert _extract_filtered_dialog_slider_fields(html) == [
        {
            "field": "min_match_score",
            "kind": "ranking_bar",
            "unit": "/100",
            "min": "0",
            "max": "35",
            "value": "15",
        }
    ]


def test_live_empty_recovery_canary_receipt_passes_for_terminal_empty_run() -> None:
    def _workspace_starter(**_kwargs):
        return {"ok": True, "_http": {"status_code": 200}}

    def _run_starter(**_kwargs):
        return {"run_id": "run-empty-canary", "status": "queued", "_http": {"status_code": 200}}

    def _status_fetcher(**_kwargs):
        return {
            "run_id": "run-empty-canary",
            "status": "processed",
            "message": "The completed result desk is ready.",
            "summary": {
                "listing_total": 10,
                "filtered_total": 6,
                "raw_listing_total": 10,
            },
        }

    def _page_fetcher(**_kwargs):
        return {
            "status_code": 200,
            "final_url": "http://127.0.0.1:8097/app/properties?run_id=run-empty-canary",
            "text": """
            <section class="pqx-stage pqx-running pqx-empty-results">
              <aside>
                <h1>No shortlist yet.</h1>
                <p class="pqx-note pqx-empty-outcome-line">10 listings matched the provider sweep.</p>
              </aside>
              <div data-pqx-counterfactuals>
                <div class="pqx-suppression-grid">
                  <div class="pqx-suppression-item pqx-suppression-item-adjustable">
                    <strong>Let score rank every home</strong>
                    <span class="pqx-note">Lower the current ranking bar.</span>
                    <label class="pqx-filter-radius-control pqx-suppression-slider">
                      <span>Ranking bar <b data-pqx-filter-slider-value>15 /100</b></span>
                      <input
                        type="range"
                        min="0"
                        max="35"
                        step="5"
                        value="15"
                        data-pqx-filter-slider
                        data-pqx-filter-field="min_match_score"
                        data-pqx-filter-kind="ranking_bar"
                        data-pqx-filter-unit="/100"
                      >
                    </label>
                    <button class="pqx-suppression-action" type="button" data-pqx-counterfactual='{"min_match_score": 15}' aria-label="Relax rule">Use 15/100</button>
                  </div>
                </div>
              </div>
              <dialog class="pqx-filtered-dialog" data-pqx-filtered-dialog>
                <div class="pqx-filtered-dialog-rule">
                  <strong>Let score rank every home</strong>
                  <label class="pqx-filter-radius-control">
                    <span>Ranking bar <b data-pqx-filter-slider-value>15 /100</b></span>
                    <input
                      type="range"
                      min="0"
                      max="35"
                      step="5"
                      value="15"
                      data-pqx-filter-slider
                      data-pqx-filter-field="min_match_score"
                      data-pqx-filter-kind="ranking_bar"
                      data-pqx-filter-unit="/100"
                    >
                  </label>
                </div>
              </dialog>
              <section class="pqx-card pqx-empty-results-note" data-pqx-ranked-candidates></section>
            </section>
            """,
        }

    def _run_deleter(**_kwargs):
        return {"deleted": True}

    receipt = build_live_empty_recovery_canary_receipt(
        base_url="http://127.0.0.1:8097",
        token="test-token",
        principal_id="pq-live-empty-canary-test",
        timeout_seconds=30.0,
        poll_seconds=0.01,
        workspace_starter=_workspace_starter,
        run_starter=_run_starter,
        status_fetcher=_status_fetcher,
        page_fetcher=_page_fetcher,
        run_deleter=_run_deleter,
    )

    assert receipt["status"] == "pass"
    assert receipt["failed_checks"] == []
    assert receipt["counterfactual_buttons"][0]["title"] == "Let score rank every home"


def test_live_empty_recovery_canary_receipt_fails_when_ranking_recovery_is_missing() -> None:
    def _workspace_starter(**_kwargs):
        return {"ok": True, "_http": {"status_code": 200}}

    def _run_starter(**_kwargs):
        return {"run_id": "run-empty-canary", "status": "queued", "_http": {"status_code": 200}}

    def _status_fetcher(**_kwargs):
        return {
            "run_id": "run-empty-canary",
            "status": "processed",
            "message": "The completed result desk is ready.",
            "summary": {
                "listing_total": 10,
                "filtered_total": 6,
                "raw_listing_total": 10,
            },
        }

    def _page_fetcher(**_kwargs):
        return {
            "status_code": 200,
            "final_url": "http://127.0.0.1:8097/app/properties?run_id=run-empty-canary",
            "text": """
            <section class="pqx-stage pqx-running pqx-empty-results">
              <aside><h1>No shortlist yet.</h1></aside>
              <div data-pqx-counterfactuals></div>
              <section class="pqx-card pqx-empty-results-note" data-pqx-ranked-candidates></section>
            </section>
            """,
        }

    def _run_deleter(**_kwargs):
        return {"deleted": True}

    receipt = build_live_empty_recovery_canary_receipt(
        base_url="http://127.0.0.1:8097",
        token="test-token",
        principal_id="pq-live-empty-canary-test",
        timeout_seconds=30.0,
        poll_seconds=0.01,
        workspace_starter=_workspace_starter,
        run_starter=_run_starter,
        status_fetcher=_status_fetcher,
        page_fetcher=_page_fetcher,
        run_deleter=_run_deleter,
    )

    assert receipt["status"] == "fail"
    assert "ranking_recovery_button_present" in receipt["failed_checks"]
    assert "ranking_slider_present" in receipt["failed_checks"]

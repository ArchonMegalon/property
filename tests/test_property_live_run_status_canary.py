from __future__ import annotations

from scripts.propertyquarry_live_run_status_canary import (
    CUSTOMER_EVENT_LABELS,
    _contains_noise,
    _extract_event_cards,
    _extract_run_message,
    build_live_run_status_canary_receipt,
)


def test_live_run_status_canary_extracts_run_message_and_event_cards() -> None:
    html = """
    <div class="pqx-note" data-pqx-run-message>Willhaben · 3 / 10 · 179 homes reviewed</div>
    <div class="pqx-event-list" data-pqx-run-events>
      <div class="pqx-event-card"><strong>Checking listings</strong><span class="pqx-note">Willhaben · 3 / 10 · 179 homes reviewed</span></div>
      <div class="pqx-event-card"><strong>Ranking homes</strong><span class="pqx-note">Shortlist ready · 1 home · Willhaben · 179 homes reviewed</span></div>
    </div>
    """

    assert _extract_run_message(html) == "Willhaben · 3 / 10 · 179 homes reviewed"
    assert _extract_event_cards(html) == [
        {"label": "Checking listings", "message": "Willhaben · 3 / 10 · 179 homes reviewed"},
        {"label": "Ranking homes", "message": "Shortlist ready · 1 home · Willhaben · 179 homes reviewed"},
    ]


def test_live_run_status_canary_ignores_script_template_event_cards() -> None:
    html = """
    <details class="pqx-card">
      <div class="pqx-event-list" data-pqx-run-events>
        <div class="pqx-event-card"><strong>Checking listings</strong><span class="pqx-note">Willhaben · 3 / 10 · 179 homes reviewed</span></div>
      </div>
    </details>
    <script>
      const renderTimeline = (rows) => (Array.isArray(rows) ? rows : []).map((row) => `
        <div class="pqx-event-card"><strong>${escapeHtml(row.title || 'Update')}</strong><span class="pqx-note">${escapeHtml(row.detail || '')}</span></div>
      `).join('');
    </script>
    """

    assert _extract_event_cards(html) == [
        {"label": "Checking listings", "message": "Willhaben · 3 / 10 · 179 homes reviewed"},
    ]


def test_live_run_status_canary_noise_detector_catches_internal_status_copy() -> None:
    assert _contains_noise("Could not load property search status.")
    assert _contains_noise("Starting property search run.")
    assert _contains_noise("Willhaben · 1 / 10 · 24 homes reviewed")
    assert not _contains_noise("Preparing provider checks.")


def test_live_run_status_canary_receipt_passes_for_active_run() -> None:
    def _workspace_starter(**_kwargs):
        return {"ok": True, "_http": {"status_code": 200}}

    def _run_starter(**_kwargs):
        return {
            "run_id": "run-live-canary",
            "status": "queued",
            "_http": {"status_code": 200},
        }

    poll_count = {"value": 0}

    def _status_fetcher(**_kwargs):
        poll_count["value"] += 1
        if poll_count["value"] == 1:
            return {
                "run_id": "run-live-canary",
                "status": "in_progress",
                "current_step": "source_fetching",
                "message": "Fetching source page for Willhaben.",
                "events": [
                    {
                        "step": "source_fetching",
                        "status": "in_progress",
                        "message": "Willhaben · 1 / 10 · 24 homes found · details caught up",
                    }
                ],
            }
        return {
            "run_id": "run-live-canary",
            "status": "in_progress",
            "current_step": "source_shortlist",
            "message": "Built shortlist of 1 listing(s) for Willhaben.",
            "events": [
                {
                    "step": "source_shortlist",
                    "status": "in_progress",
                    "message": "Shortlist ready · 1 home · Willhaben · 24 homes found · details caught up",
                }
            ],
        }

    def _page_fetcher(**_kwargs):
        return {
            "status_code": 200,
            "text": """
            <div class="pqx-note" data-pqx-run-message>Willhaben · 1 / 10 · 24 homes found · details caught up</div>
            <div class="pqx-event-list" data-pqx-run-events>
              <div class="pqx-event-card"><strong>Checking listings</strong><span class="pqx-note">Willhaben · 1 / 10 · 24 homes found · details caught up</span></div>
            </div>
            """,
        }

    def _run_deleter(**_kwargs):
        return {"deleted": True}

    receipt = build_live_run_status_canary_receipt(
        base_url="http://127.0.0.1:8097",
        token="test-token",
        principal_id="pq-live-run-status-canary-test",
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
    assert receipt["run_id"] == "run-live-canary"
    assert receipt["page_run_message"] == "Willhaben · 1 / 10 · 24 homes found · details caught up"
    assert receipt["page_event_cards"][0]["label"] in CUSTOMER_EVENT_LABELS


def test_live_run_status_canary_receipt_fails_for_noisy_page_events() -> None:
    def _workspace_starter(**_kwargs):
        return {"ok": True, "_http": {"status_code": 200}}

    def _run_starter(**_kwargs):
        return {
            "run_id": "run-live-canary",
            "status": "queued",
            "_http": {"status_code": 200},
        }

    def _status_fetcher(**_kwargs):
        return {
            "run_id": "run-live-canary",
            "status": "in_progress",
            "current_step": "source_fetching",
            "message": "Fetching source page for Willhaben.",
            "events": [
                {
                    "step": "source_fetching",
                    "status": "in_progress",
                    "message": "Willhaben · 1 / 10 · 24 homes found · details caught up",
                }
            ],
        }

    def _page_fetcher(**_kwargs):
        return {
            "status_code": 200,
            "text": """
            <div class="pqx-note" data-pqx-run-message>Checking run status.</div>
            <div class="pqx-event-list" data-pqx-run-events>
              <div class="pqx-event-card"><strong>Source Fetching</strong><span class="pqx-note">Could not load property search status.</span></div>
            </div>
            """,
        }

    def _run_deleter(**_kwargs):
        return {"deleted": True}

    receipt = build_live_run_status_canary_receipt(
        base_url="http://127.0.0.1:8097",
        token="test-token",
        principal_id="pq-live-run-status-canary-test",
        timeout_seconds=30.0,
        poll_seconds=0.01,
        workspace_starter=_workspace_starter,
        run_starter=_run_starter,
        status_fetcher=_status_fetcher,
        page_fetcher=_page_fetcher,
        run_deleter=_run_deleter,
    )

    assert receipt["status"] == "fail"
    assert "page_run_message_noise_free" in receipt["failed_checks"]
    assert "page_event_labels_customer_facing" in receipt["failed_checks"]
    assert "page_event_messages_noise_free" in receipt["failed_checks"]


def test_live_run_status_canary_retries_page_until_customer_trail_appears() -> None:
    def _workspace_starter(**_kwargs):
        return {"ok": True, "_http": {"status_code": 200}}

    def _run_starter(**_kwargs):
        return {
            "run_id": "run-live-canary",
            "status": "queued",
            "_http": {"status_code": 200},
        }

    def _status_fetcher(**_kwargs):
        return {
            "run_id": "run-live-canary",
            "status": "in_progress",
            "current_step": "source_fetching",
            "message": "Fetching source page for Willhaben.",
            "events": [
                {
                    "step": "source_fetching",
                    "status": "in_progress",
                    "message": "Willhaben · 1 / 10 · 24 homes found · details caught up",
                }
            ],
        }

    page_fetch_count = {"value": 0}

    def _page_fetcher(**_kwargs):
        page_fetch_count["value"] += 1
        if page_fetch_count["value"] == 1:
            return {"status_code": 200, "text": "<div>loading</div>"}
        return {
            "status_code": 200,
            "text": """
            <div class="pqx-note" data-pqx-run-message>Willhaben · 1 / 10 · 24 homes found · details caught up</div>
            <div class="pqx-event-list" data-pqx-run-events>
              <div class="pqx-event-card"><strong>Checking listings</strong><span class="pqx-note">Willhaben · 1 / 10 · 24 homes found · details caught up</span></div>
            </div>
            """,
        }

    def _run_deleter(**_kwargs):
        return {"deleted": True}

    receipt = build_live_run_status_canary_receipt(
        base_url="http://127.0.0.1:8097",
        token="test-token",
        principal_id="pq-live-run-status-canary-test",
        timeout_seconds=30.0,
        poll_seconds=0.01,
        workspace_starter=_workspace_starter,
        run_starter=_run_starter,
        status_fetcher=_status_fetcher,
        page_fetcher=_page_fetcher,
        run_deleter=_run_deleter,
    )

    assert receipt["status"] == "pass"
    assert page_fetch_count["value"] >= 2

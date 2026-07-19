from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
WORKBENCH_SCRIPT = REPO_ROOT / "ea/app/templates/app/_property_workbench_script.html"
FEEDBACK_SCRIPT = REPO_ROOT / "ea/app/templates/app/_property_workbench_feedback_script.html"


def test_workbench_network_mutations_and_pollers_are_bounded_and_cancellable() -> None:
    source = WORKBENCH_SCRIPT.read_text(encoding="utf-8")

    assert "const fetchWithTimeout = async" in source
    assert "new AbortController()" in source
    assert "activeRequestControllers" in source
    assert "RUN_POLL_WINDOW_MS" in source
    assert "RUN_POLL_MAX_FAILURES" in source
    assert "VISUAL_POLL_WINDOW_MS" in source
    assert "VISUAL_POLL_MAX_FAILURES" in source
    assert "REPAIR_POLL_WINDOW_MS" in source
    assert "REPAIR_POLL_MAX_FAILURES" in source
    assert "while (true)" not in source
    assert "while (!pageRequestLifecycleEnded && Date.now() < deadline)" in source
    assert "data-pqx-poll-resume" in source
    assert "pauseVisualStatusPolling" in source
    assert "data-pw-visual-poll-paused" in source
    assert source.count("document.hidden || navigator.onLine === false") >= 3


def test_search_launch_reuses_a_payload_bound_idempotency_key_until_acknowledged() -> None:
    source = WORKBENCH_SCRIPT.read_text(encoding="utf-8")

    assert "const stableSearchLaunchIdempotencyKey = async (bodyText) =>" in source
    assert "payload_sha256: digest" in source
    assert "window.sessionStorage.setItem(SEARCH_LAUNCH_IDEMPOTENCY_STORAGE_KEY" in source
    assert "'Idempotency-Key': idempotencyKey" in source
    assert source.count("const launch = await postSearchLaunch(") == 2
    assert source.count("clearSearchLaunchIdempotencyKey(launch.bodyText, launch.idempotencyKey);") == 2

    feedback = FEEDBACK_SCRIPT.read_text(encoding="utf-8")
    assert "button.getAttribute('data-pw-visual-poll-paused') === 'true'" in feedback
    assert "updateVisualButtonFromStatus(button, { firstPollDelaySeconds: 0.1, resetDeadline: true });" in feedback

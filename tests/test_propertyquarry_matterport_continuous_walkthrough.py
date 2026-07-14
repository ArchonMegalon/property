from __future__ import annotations

import json
import math

from scripts import propertyquarry_matterport_continuous_walkthrough as walkthrough


class _FakeCanvas:
    @property
    def first(self) -> "_FakeCanvas":
        return self

    def bounding_box(self) -> dict[str, float]:
        return {"x": 0.0, "y": 0.0, "width": 1920.0, "height": 1080.0}


class _FakeMouse:
    def __init__(self) -> None:
        self.moves: list[tuple[float, float, int | None]] = []
        self.down_count = 0
        self.up_count = 0

    def move(self, x: float, y: float, *, steps: int | None = None) -> None:
        self.moves.append((x, y, steps))

    def down(self) -> None:
        self.down_count += 1

    def up(self) -> None:
        self.up_count += 1


class _FakePage:
    def __init__(self) -> None:
        self.canvas = _FakeCanvas()
        self.mouse = _FakeMouse()
        self.waits: list[int] = []

    def locator(self, selector: str) -> _FakeCanvas:
        assert selector == "canvas"
        return self.canvas

    def wait_for_timeout(self, milliseconds: int) -> None:
        self.waits.append(milliseconds)


def test_route_url_defaults_to_explicit_interactive_play_mode() -> None:
    route = {
        "model_sid": "model-123",
        "route": [{"id": "scan-id", "index": 0, "sweep_uuid": "scan-uuid"}],
    }

    url = walkthrough._route_url(
        route,
        play_mode="0",
        start_selector="index",
        start_rotation="3.14159,0",
        start_value="0",
    )

    assert "m=model-123" in url
    assert "play=0" in url
    assert "qs=1" in url
    assert "ss=1" in url


def test_turn_math_uses_shortest_signed_angle_and_calibrated_hold() -> None:
    assert math.isclose(walkthrough._signed_angle(-math.pi / 2, 0), -math.pi / 2)
    assert math.isclose(walkthrough._signed_angle(math.pi, -math.pi / 2), -math.pi / 2)
    assert walkthrough._turn_hold_ms(math.pi / 2, slope=0.359, intercept=0.111) == 4066


def test_mouse_turn_splits_wide_rotation_into_bounded_smooth_drags() -> None:
    page = _FakePage()

    pixels, duration_ms, segments = walkthrough._drag_canvas_by_angle(
        page,
        math.pi,
        pixels_per_radian=1081.081,
        duration_ms_per_radian=1200,
    )

    assert math.isclose(pixels, -3396.316, abs_tol=0.01)
    assert duration_ms == 3770
    assert segments == 3
    assert page.mouse.down_count == 3
    assert page.mouse.up_count == 3
    assert page.waits == [50, 50]


def test_watchdog_timeout_preserves_checkpoint_and_fails_closed(tmp_path) -> None:
    receipt_path = tmp_path / "route-receipt.json"
    receipt_path.write_text(
        json.dumps(
            {
                "contract_name": "propertyquarry.matterport_continuous_walkthrough_probe.v1",
                "status": "incomplete",
                "phase": "route_action_completed",
                "route_steps": [{"ordinal": 1, "status": "pass"}],
            }
        ),
        encoding="utf-8",
    )

    receipt = walkthrough._watchdog_failure_receipt(
        receipt_path=receipt_path,
        timeout_seconds=90,
        stderr="browser close stalled",
    )

    assert receipt["status"] == "fail"
    assert receipt["phase"] == "worker_timeout"
    assert receipt["route_steps"] == [{"ordinal": 1, "status": "pass"}]
    assert receipt["checks"]["browser_shutdown_cleanly"] is False
    assert receipt["checks"]["worker_completed"] is False
    assert json.loads(receipt_path.read_text(encoding="utf-8")) == receipt

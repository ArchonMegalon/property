import pytest

from scripts.property_walkthrough_motion_smoothness_gate import evaluate_window, parse_window


def test_motion_smoothness_evaluation_accepts_buttery_60fps_metrics() -> None:
    evaluation = evaluate_window(
        {
            "frame_count": 150,
            "duplicate_ratio": 0.16,
            "p95_frame_delta": 26.2,
            "mean_motion_step": 1.03,
            "p95_motion_jerk": 2.51,
        },
        {
            "frame_count": 300,
            "duplicate_ratio": 0.16,
            "p95_frame_delta": 15.0,
            "mean_motion_step": 0.52,
            "p95_motion_jerk": 1.04,
        },
        max_jerk_ratio=0.65,
        max_frame_delta_ratio=0.75,
    )

    assert evaluation["status"] == "pass"
    assert evaluation["p95_motion_jerk_ratio"] == 0.4143
    assert evaluation["p95_frame_delta_ratio"] == 0.5725


def test_motion_smoothness_evaluation_rejects_frame_duplication_only() -> None:
    evaluation = evaluate_window(
        {
            "frame_count": 150,
            "duplicate_ratio": 0.05,
            "p95_frame_delta": 20.0,
            "mean_motion_step": 1.0,
            "p95_motion_jerk": 2.0,
        },
        {
            "frame_count": 300,
            "duplicate_ratio": 0.55,
            "p95_frame_delta": 20.0,
            "mean_motion_step": 1.0,
            "p95_motion_jerk": 2.0,
        },
        max_jerk_ratio=0.65,
        max_frame_delta_ratio=0.75,
    )

    assert evaluation["status"] == "fail"
    assert evaluation["checks"]["duplicate_ratio_not_increased"] is False
    assert evaluation["checks"]["per_frame_motion_step_near_half"] is False


@pytest.mark.parametrize(
    "value,expected",
    [("7:5", (7.0, 5.0)), ("29.5:3.25", (29.5, 3.25))],
)
def test_parse_motion_window(value: str, expected: tuple[float, float]) -> None:
    assert parse_window(value) == expected

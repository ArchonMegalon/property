import pytest

from scripts.repair_magicfit_property_walkthrough_continuity import (
    build_repair_filter,
    remap_transition_offsets,
)


def test_build_repair_filter_replaces_hard_cut_with_one_second_crossfade() -> None:
    filter_graph, final_label, duration, repair_offsets = build_repair_filter(
        duration_seconds=71.465,
        cut_seconds=[11.7],
        transition_seconds=1.0,
        output_fps=24.0,
    )

    assert final_label == "x1"
    assert duration == 70.465
    assert repair_offsets == [10.7]
    assert "trim=start=0.000:end=11.700" in filter_graph
    assert "trim=start=11.700:end=71.465" in filter_graph
    assert "fps=24" in filter_graph
    assert "xfade=transition=fade:duration=1.000:offset=10.700" in filter_graph


def test_remap_transition_offsets_accounts_for_prior_repairs() -> None:
    offsets = remap_transition_offsets(
        source_offsets=[14.093, 28.186, 42.279, 56.372],
        cut_seconds=[11.7],
        transition_seconds=1.0,
        repair_offsets=[10.7],
    )

    assert offsets == [10.7, 13.093, 27.186, 41.279, 55.372]


def test_build_repair_filter_rejects_cuts_without_crossfade_room() -> None:
    with pytest.raises(ValueError, match="continuity_repair_cut_spacing_too_short"):
        build_repair_filter(
            duration_seconds=10.0,
            cut_seconds=[0.5],
            transition_seconds=1.0,
        )

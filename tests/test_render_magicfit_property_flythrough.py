from pathlib import Path

from scripts.render_magicfit_property_flythrough import (
    ASPECT_CURRENT_OPTIONS,
    extension_output_contract_matches,
    option_label_candidates,
    output_contract_matches,
    persist_storage_state,
    provider_asset_path,
    wait_for_submit_ready,
)


def test_persist_storage_state_keeps_provider_session_private(tmp_path: Path) -> None:
    target = tmp_path / "runtime" / "magicfit-storage.json"

    class FakeContext:
        def storage_state(self, *, path: str) -> None:
            Path(path).write_text('{"cookies": []}', encoding="utf-8")

    class FakePage:
        context = FakeContext()

    persist_storage_state(FakePage(), target)

    assert target.is_file()
    assert target.stat().st_mode & 0o777 == 0o600


def test_option_label_candidates_include_magicfit_ratio_shorthand() -> None:
    assert option_label_candidates("Landscape (16:9)") == ["Landscape (16:9)", "16:9"]
    assert option_label_candidates("Portrait (9:16)") == ["Portrait (9:16)", "9:16"]


def test_option_label_candidates_keep_non_ratio_labels_exact() -> None:
    assert option_label_candidates("Seedance 2.0 Fast") == ["Seedance 2.0 Fast"]
    assert option_label_candidates("15s") == ["15s"]


def test_aspect_selector_prefers_full_current_control_labels() -> None:
    assert ASPECT_CURRENT_OPTIONS.index("Portrait (9:16)") < ASPECT_CURRENT_OPTIONS.index("9:16")
    assert ASPECT_CURRENT_OPTIONS.index("Landscape (16:9)") < ASPECT_CURRENT_OPTIONS.index("16:9")


def test_output_contract_matches_requested_landscape_duration() -> None:
    assert output_contract_matches(
        metadata={"ok": True, "duration_seconds": 15.04, "width": 1920, "height": 1080},
        duration_seconds=15,
        aspect_label="Landscape (16:9)",
    )


def test_output_contract_rejects_short_portrait_result_for_landscape_request() -> None:
    assert not output_contract_matches(
        metadata={"ok": True, "duration_seconds": 4.04, "width": 1080, "height": 1920},
        duration_seconds=15,
        aspect_label="Landscape (16:9)",
    )


def test_output_contract_rejects_missing_probe_metadata() -> None:
    assert not output_contract_matches(
        metadata={"ok": False},
        duration_seconds=15,
        aspect_label="Landscape (16:9)",
    )


def test_provider_asset_path_strips_query_without_weakening_identity() -> None:
    assert provider_asset_path(
        "https://media.powlcdn.com/magicfit/123-provider.mp4?token=private"
    ) == "/magicfit/123-provider.mp4"


def test_extension_output_contract_requires_cumulative_source_duration() -> None:
    source = {
        "ok": True,
        "duration_seconds": 15.1,
        "width": 1920,
        "height": 1080,
    }

    assert extension_output_contract_matches(
        metadata={
            "ok": True,
            "duration_seconds": 30.15,
            "width": 1920,
            "height": 1080,
        },
        source_metadata=source,
        extension_seconds=15,
    )
    assert not extension_output_contract_matches(
        metadata={
            "ok": True,
            "duration_seconds": 15.05,
            "width": 1920,
            "height": 1080,
        },
        source_metadata=source,
        extension_seconds=15,
    )


def test_wait_for_submit_ready_returns_only_enabled_submit() -> None:
    class FakeSubmit:
        def is_visible(self, *, timeout: int) -> bool:
            return timeout == 1_000

        def is_enabled(self, *, timeout: int) -> bool:
            return timeout == 1_000

    submit = FakeSubmit()

    class FakeLocator:
        last = submit

    class FakePage:
        def locator(self, selector: str) -> FakeLocator:
            assert selector == "form button[type=submit]"
            return FakeLocator()

    assert wait_for_submit_ready(FakePage()) is submit

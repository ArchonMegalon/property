from __future__ import annotations

from types import SimpleNamespace

import pytest

from scripts import propertyquarry_playwright_runtime as runtime


def test_playwright_runtime_normalizes_only_supported_engines() -> None:
    assert runtime.normalize_playwright_engine("") == "chromium"
    assert runtime.normalize_playwright_engine(" Firefox ") == "firefox"
    assert runtime.normalize_playwright_engine("WEBKIT") == "webkit"
    with pytest.raises(ValueError, match="unsupported_playwright_browser_engine:edge"):
        runtime.normalize_playwright_engine("edge")


def test_playwright_runtime_selects_requested_engine_without_chromium_arg_leakage(tmp_path) -> None:
    executable = tmp_path / "browser"
    executable.write_text("test", encoding="utf-8")
    browser_type = SimpleNamespace(executable_path=str(executable), launch=lambda **_kwargs: None)
    playwright = SimpleNamespace(chromium=browser_type, firefox=browser_type, webkit=browser_type)

    assert runtime.playwright_browser_type(playwright, engine="firefox") is browser_type
    assert runtime.playwright_engine_launch_kwargs(
        playwright,
        engine="chromium",
        args=["--no-sandbox"],
    ) == {
        "headless": True,
        "executable_path": str(executable),
        "args": ["--no-sandbox"],
    }
    assert runtime.playwright_engine_launch_kwargs(
        playwright,
        engine="firefox",
        args=["--chromium-only"],
    ) == {
        "headless": True,
        "executable_path": str(executable),
    }


def test_playwright_runtime_fails_clearly_when_required_engine_is_missing() -> None:
    with pytest.raises(RuntimeError, match="playwright_browser_engine_unavailable:webkit"):
        runtime.playwright_browser_type(SimpleNamespace(chromium=object()), engine="webkit")


def test_playwright_runtime_does_not_fallback_from_invalid_configured_executable(monkeypatch) -> None:
    monkeypatch.setenv("PROPERTYQUARRY_PLAYWRIGHT_FIREFOX_EXECUTABLE", "/missing/firefox")
    with pytest.raises(FileNotFoundError, match="PROPERTYQUARRY_PLAYWRIGHT_FIREFOX_EXECUTABLE"):
        runtime.playwright_engine_executable(SimpleNamespace(), engine="firefox")

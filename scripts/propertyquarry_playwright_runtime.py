from __future__ import annotations

import os
from pathlib import Path
from typing import Callable


CHROMIUM_EXECUTABLE_ENV = "PROPERTYQUARRY_PLAYWRIGHT_CHROMIUM_EXECUTABLE"
SUPPORTED_PLAYWRIGHT_ENGINES = ("chromium", "firefox", "webkit")
PLAYWRIGHT_EXECUTABLE_ENV_BY_ENGINE = {
    "chromium": CHROMIUM_EXECUTABLE_ENV,
    "firefox": "PROPERTYQUARRY_PLAYWRIGHT_FIREFOX_EXECUTABLE",
    "webkit": "PROPERTYQUARRY_PLAYWRIGHT_WEBKIT_EXECUTABLE",
}


def normalize_playwright_engine(value: object) -> str:
    engine = str(value or "chromium").strip().lower()
    if engine not in SUPPORTED_PLAYWRIGHT_ENGINES:
        raise ValueError(f"unsupported_playwright_browser_engine:{engine}")
    return engine


def playwright_browser_type(playwright: object, *, engine: str = "chromium") -> object:
    normalized_engine = normalize_playwright_engine(engine)
    browser_type = getattr(playwright, normalized_engine, None)
    if browser_type is None or not callable(getattr(browser_type, "launch", None)):
        raise RuntimeError(f"playwright_browser_engine_unavailable:{normalized_engine}")
    return browser_type


def playwright_engine_executable(
    playwright: object | None = None,
    *,
    engine: str = "chromium",
) -> str:
    normalized_engine = normalize_playwright_engine(engine)
    executable_env = PLAYWRIGHT_EXECUTABLE_ENV_BY_ENGINE[normalized_engine]
    configured = str(os.getenv(executable_env) or "").strip()
    if configured:
        if not Path(configured).is_file():
            raise FileNotFoundError(f"{executable_env} does not point to a file: {configured}")
        return configured
    try:
        browser_type = getattr(playwright, normalized_engine) if playwright is not None else None
        candidate = str(getattr(browser_type, "executable_path", "") or "").strip()
    except Exception:
        candidate = ""
    return candidate if candidate and Path(candidate).is_file() else ""


def playwright_engine_launch_kwargs(
    playwright: object,
    *,
    engine: str = "chromium",
    args: list[str] | None = None,
) -> dict[str, object]:
    normalized_engine = normalize_playwright_engine(engine)
    launch_kwargs: dict[str, object] = {"headless": True}
    executable = playwright_engine_executable(playwright, engine=normalized_engine)
    if executable:
        launch_kwargs["executable_path"] = executable
    if args and normalized_engine == "chromium":
        launch_kwargs["args"] = list(args)
    return launch_kwargs


def playwright_engine_capture_available(
    *,
    engine: str = "chromium",
    sync_playwright_factory: Callable[[], object] | None = None,
) -> bool:
    normalized_engine = normalize_playwright_engine(engine)
    if sync_playwright_factory is None:
        try:
            from playwright.sync_api import sync_playwright as sync_playwright_factory
        except Exception:
            return False
    try:
        with sync_playwright_factory() as playwright:  # type: ignore[attr-defined]
            playwright_browser_type(playwright, engine=normalized_engine)
            return bool(playwright_engine_executable(playwright, engine=normalized_engine))
    except Exception:
        return False


def playwright_chromium_executable(playwright: object | None = None) -> str:
    return playwright_engine_executable(playwright, engine="chromium")


def playwright_chromium_launch_kwargs(
    playwright: object,
    *,
    args: list[str] | None = None,
) -> dict[str, object]:
    return playwright_engine_launch_kwargs(playwright, engine="chromium", args=args)


def playwright_chromium_capture_available(
    sync_playwright_factory: Callable[[], object] | None = None,
) -> bool:
    return playwright_engine_capture_available(
        engine="chromium",
        sync_playwright_factory=sync_playwright_factory,
    )

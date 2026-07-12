from __future__ import annotations

import os
from pathlib import Path
from typing import Callable


CHROMIUM_EXECUTABLE_ENV = "PROPERTYQUARRY_PLAYWRIGHT_CHROMIUM_EXECUTABLE"


def playwright_chromium_executable(playwright: object | None = None) -> str:
    configured = str(os.getenv(CHROMIUM_EXECUTABLE_ENV) or "").strip()
    if configured:
        if not Path(configured).is_file():
            raise FileNotFoundError(f"{CHROMIUM_EXECUTABLE_ENV} does not point to a file: {configured}")
        return configured
    try:
        chromium = getattr(playwright, "chromium") if playwright is not None else None
        candidate = str(getattr(chromium, "executable_path", "") or "").strip()
    except Exception:
        candidate = ""
    return candidate if candidate and Path(candidate).is_file() else ""


def playwright_chromium_launch_kwargs(
    playwright: object,
    *,
    args: list[str] | None = None,
) -> dict[str, object]:
    launch_kwargs: dict[str, object] = {"headless": True}
    executable = playwright_chromium_executable(playwright)
    if executable:
        launch_kwargs["executable_path"] = executable
    if args:
        launch_kwargs["args"] = list(args)
    return launch_kwargs


def playwright_chromium_capture_available(
    sync_playwright_factory: Callable[[], object] | None = None,
) -> bool:
    if sync_playwright_factory is None:
        try:
            from playwright.sync_api import sync_playwright as sync_playwright_factory
        except Exception:
            return False
    try:
        with sync_playwright_factory() as playwright:  # type: ignore[attr-defined]
            return bool(playwright_chromium_executable(playwright))
    except Exception:
        return False

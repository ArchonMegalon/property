"""Lazy public service exports for security-bounded runtimes.

Package initialization must not pull optional provider adapters into a runtime
that only needs one service module.  The historical public names remain
available and are loaded on first access, while ``app.services`` itself stays
safe to import in the bounded render image.
"""

from importlib import import_module
from typing import Any


_LAZY_EXPORTS = {
    "ComfyUIToolAdapter": (
        "tool_execution_comfyui_adapter",
        "ComfyUIToolAdapter",
    ),
    "ComfyUIToolExecutionModule": (
        "tool_execution_comfyui_module",
        "ComfyUIToolExecutionModule",
    ),
    "register_builtin_comfyui_image_generate": (
        "tool_execution_comfyui_registry",
        "register_builtin_comfyui_image_generate",
    ),
}

__all__ = list(_LAZY_EXPORTS)


def __getattr__(name: str) -> Any:
    target = _LAZY_EXPORTS.get(name)
    if target is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module_name, attribute_name = target
    value = getattr(import_module(f"{__name__}.{module_name}"), attribute_name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted({*globals(), *__all__})

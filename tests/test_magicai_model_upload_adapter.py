from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType


ROOT = Path(__file__).resolve().parents[1]


def _load_script() -> ModuleType:
    path = ROOT / "scripts" / "render_magicai_model_upload_adapter.py"
    spec = importlib.util.spec_from_file_location("render_magicai_model_upload_adapter", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _FakeResponse:
    def __init__(self, payload: dict[str, object]) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, object]:
        return self._payload


class _FakeSession:
    def __init__(self, payload: dict[str, object]) -> None:
        self.payload = payload
        self.calls: list[tuple[str, dict[str, object]]] = []

    def get(self, url: str, **kwargs: object) -> _FakeResponse:
        self.calls.append((url, dict(kwargs)))
        return _FakeResponse(self.payload)


def test_magicai_model_upload_adapter_normalizes_platform_host_to_api_host() -> None:
    module = _load_script()

    assert module._normalize_api_base_url("https://app.omagic.ai") == "https://api.omagic.ai"
    assert module._normalize_api_base_url("https://platform.omagic.ai") == "https://api.omagic.ai"
    assert module._normalize_api_base_url("https://api.omagic.ai") == "https://api.omagic.ai"


def test_magicai_model_upload_adapter_prefers_showroom_like_3d_template(monkeypatch) -> None:
    module = _load_script()
    payload = {
        "hits": 2,
        "templates": [
            {
                "id": 111,
                "title": "Times Square 3D objects",
                "slug": "times-square-3d-objects",
                "description": "Billboard crowd city scene.",
                "category_names": ["Trending"],
                "variants": [
                    {
                        "id": "229",
                        "template_args": {
                            "UserObject": {"type": "d3", "required": True},
                        },
                    }
                ],
            },
            {
                "id": 64,
                "title": "Large Showroom",
                "slug": "large-showroom",
                "description": "Showroom architecture scene with a clean product stage.",
                "category_names": ["Trending"],
                "variants": [
                    {
                        "id": "299",
                        "template_args": {
                            "UserObject": {"type": "d3", "required": True},
                        },
                    }
                ],
            },
        ],
    }
    session = _FakeSession(payload)
    for name in (
        "PROPERTYQUARRY_OMAGIC_TEMPLATE_VARIANT_ID",
        "PROPERTYQUARRY_OMAGIC_TEMPLATE_ARGUMENT_NAME",
        "PROPERTYQUARRY_OMAGIC_TEMPLATE_TEXT_ARGUMENT_NAME",
        "PROPERTYQUARRY_OMAGIC_TEMPLATE_ASPECT_RATIO_ARGUMENT_NAME",
    ):
        monkeypatch.delenv(name, raising=False)

    selection = module._discover_template(session, api_base_url="https://api.omagic.ai")

    assert selection["template_variant_id"] == "299"
    assert selection["d3_argument_name"] == "UserObject"
    assert selection["template_title"] == "Large Showroom"
    assert selection["selection_source"] == "catalog_discovery"

from __future__ import annotations

from app.services.public_rybbit import rybbit_head_snippet


def test_propertyquarry_rybbit_snippet_is_disabled_by_default(monkeypatch) -> None:
    monkeypatch.delenv("PROPERTYQUARRY_RYBBIT_ENABLED", raising=False)
    monkeypatch.delenv("RYBBIT_ENABLED", raising=False)
    monkeypatch.delenv("PROPERTYQUARRY_RYBBIT_SITE_ID", raising=False)
    monkeypatch.delenv("RYBBIT_SITE_ID", raising=False)

    assert rybbit_head_snippet() == ""


def test_propertyquarry_rybbit_snippet_masks_private_property_paths(monkeypatch) -> None:
    monkeypatch.setenv("PROPERTYQUARRY_RYBBIT_ENABLED", "1")
    monkeypatch.setenv("PROPERTYQUARRY_RYBBIT_SITE_ID", "propertyquarry-site")
    monkeypatch.setenv("PROPERTYQUARRY_RYBBIT_BASE_URL", "https://analytics.propertyquarry.com")

    snippet = rybbit_head_snippet()

    assert 'src="https://analytics.propertyquarry.com/api/script.js"' in snippet
    assert 'data-site-id="propertyquarry-site"' in snippet
    assert "/workspace-access/**" in snippet
    assert "/app/api/**" in snippet
    assert "/tours/**" in snippet
    assert "/app/properties/**" in snippet


def test_propertyquarry_rybbit_snippet_rejects_invalid_base_url(monkeypatch) -> None:
    monkeypatch.setenv("PROPERTYQUARRY_RYBBIT_ENABLED", "1")
    monkeypatch.setenv("PROPERTYQUARRY_RYBBIT_SITE_ID", "propertyquarry-site")
    monkeypatch.setenv("PROPERTYQUARRY_RYBBIT_BASE_URL", "javascript:alert(1)")

    assert rybbit_head_snippet() == ""

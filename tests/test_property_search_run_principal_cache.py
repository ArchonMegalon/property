from __future__ import annotations

from app.product import service
from app.product.service import ProductService


def test_property_search_run_principal_ids_cache_workspace_discovery(monkeypatch) -> None:
    service._PROPERTY_SEARCH_RUN_PRINCIPAL_CACHE.clear()
    product = ProductService.__new__(ProductService)
    calls: list[str] = []

    def _fake_workspace_sign_in_candidates(**kwargs):
        calls.append(str(kwargs.get("email") or ""))
        return ({"principal_id": "workspace:tibor"},)

    monkeypatch.setattr(product, "_workspace_sign_in_candidates", _fake_workspace_sign_in_candidates)

    first = product._property_search_run_principal_ids(
        principal_id="cf-email:tibor.girschele@gmail.com",
        account_email="tibor.girschele@gmail.com",
    )
    second = product._property_search_run_principal_ids(
        principal_id="cf-email:tibor.girschele@gmail.com",
        account_email="tibor.girschele@gmail.com",
    )

    assert first == second
    assert "workspace:tibor" in first
    assert calls == ["tibor.girschele@gmail.com"]

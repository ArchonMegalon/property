from __future__ import annotations

from scripts import check_property_furniture_style_contract as gate


def test_furniture_style_contract_binds_runtime_plan_model_and_pricing() -> None:
    receipt = gate.build_furniture_style_contract_receipt()

    assert receipt["status"] == "pass"
    assert receipt["schema"] == "propertyquarry.furniture_style_contract_receipt.v2"
    assert receipt["availability_mode"] == "per_visual_request"
    assert receipt["plan_caps"] == {"free": 5, "plus": 5, "agent": 5}
    assert receipt["helper_plan_caps"] == receipt["plan_caps"]
    assert receipt["pricing_surface_bound"] is True


def test_furniture_style_contract_fails_closed_on_runtime_cap_drift(monkeypatch) -> None:
    original = gate.property_furniture_style_cap
    monkeypatch.setattr(
        gate,
        "property_furniture_style_cap",
        lambda plan_key: 1 if plan_key == "free" else original(plan_key),
    )

    receipt = gate.build_furniture_style_contract_receipt()

    assert receipt["status"] == "fail"
    assert receipt["helper_plan_caps"]["free"] == 1
    assert any("all five request-time styles" in failure for failure in receipt["failures"])


def test_furniture_style_contract_fails_closed_when_pricing_is_unbound(monkeypatch) -> None:
    original = gate._read

    def _read_without_plan_binding(path: str) -> str:
        body = original(path)
        if path == "ea/app/templates/pricing_page.html":
            return body.replace("{{ plan.furniture_style_limit }}", "5")
        return body

    monkeypatch.setattr(gate, "_read", _read_without_plan_binding)

    receipt = gate.build_furniture_style_contract_receipt()

    assert receipt["status"] == "fail"
    assert receipt["pricing_surface_bound"] is False
    assert any("pricing surface missing" in failure for failure in receipt["failures"])

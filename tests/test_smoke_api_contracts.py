from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_smoke_api_feature_detects_optional_legacy_surfaces() -> None:
    smoke_api = (ROOT / "scripts/smoke_api.sh").read_text(encoding="utf-8")

    assert 'route_available "/v1/human/tasks?limit=1"' in smoke_api
    assert 'route_available "/v1/observations/recent?limit=1"' in smoke_api
    assert 'route_available "/v1/delivery/outbox/pending?limit=1"' in smoke_api
    assert 'route_available "/v1/connectors/bindings?limit=1"' in smoke_api
    assert 'route_available "/v1/tasks/contracts"' in smoke_api
    assert 'route_available "/v1/skills?limit=1"' in smoke_api
    assert 'route_available "/v1/responses"' in smoke_api
    assert 'skipped: /v1/human/tasks routes are not published on this runtime' in smoke_api
    assert 'skipped: /v1/responses routes are not published on this runtime' in smoke_api


def test_smoke_api_normalizes_registration_email_token() -> None:
    smoke_api = (ROOT / "scripts/smoke_api.sh").read_text(encoding="utf-8")

    assert 'REGISTER_EMAIL="smoke-register-${SMOKE_RUN_TOKEN,,}@example.com"' in smoke_api

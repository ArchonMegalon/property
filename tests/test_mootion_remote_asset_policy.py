from __future__ import annotations

import json
import socket
import time

import pytest

from app import mootion_remote_asset_policy as policy


def _addresses(*values: str) -> list[tuple[object, ...]]:
    rows: list[tuple[object, ...]] = []
    for value in values:
        family = socket.AF_INET6 if ":" in value else socket.AF_INET
        rows.append((family, socket.SOCK_STREAM, 6, "", (value, 443)))
    return rows


def test_mootion_remote_asset_host_policy_accepts_only_resolved_exact_hosts(monkeypatch) -> None:
    monkeypatch.setattr(policy.socket, "getaddrinfo", lambda host, port, type=0: _addresses("8.8.8.8"))

    status = policy.mootion_remote_asset_host_policy_readiness("CDN.EXAMPLE.,cdn.example")

    assert status == {
        "configured": True,
        "valid": True,
        "reason": "",
        "validation_error": "",
        "host_count": 1,
    }
    assert "cdn.example" not in json.dumps(status).lower()


@pytest.mark.parametrize(
    "raw_value",
    (
        "https://cdn.example",
        "cdn.example:443",
        "*.example",
        "2130706433",
        "cdn..example",
        "cdn_example.com",
    ),
)
def test_mootion_remote_asset_host_policy_rejects_malformed_values(raw_value: str) -> None:
    status = policy.mootion_remote_asset_host_policy_readiness(raw_value)

    assert status["configured"] is True
    assert status["valid"] is False
    assert status["reason"] == "mootion_remote_asset_host_allowlist_invalid"


@pytest.mark.parametrize(
    "addresses",
    (
        ("127.0.0.1",),
        ("8.8.8.8", "10.0.0.1"),
        ("::1",),
    ),
)
def test_mootion_remote_asset_host_policy_rejects_any_non_global_resolution(
    addresses: tuple[str, ...],
    monkeypatch,
) -> None:
    monkeypatch.setattr(policy.socket, "getaddrinfo", lambda host, port, type=0: _addresses(*addresses))

    status = policy.mootion_remote_asset_host_policy_readiness("cdn.example")

    assert status["valid"] is False
    assert status["reason"] == "mootion_remote_asset_host_allowlist_invalid"
    assert status["validation_error"] == "mootion_remote_asset_host_blocked"


def test_mootion_remote_asset_host_policy_rejects_unresolvable_hosts(monkeypatch) -> None:
    def _unresolvable(*args, **kwargs):
        raise socket.gaierror("not found")

    monkeypatch.setattr(policy.socket, "getaddrinfo", _unresolvable)

    status = policy.mootion_remote_asset_host_policy_readiness("missing.example")

    assert status["valid"] is False
    assert status["reason"] == "mootion_remote_asset_host_allowlist_invalid"
    assert status["validation_error"] == "mootion_remote_asset_dns_failed"


def test_mootion_remote_asset_dns_resolution_obeys_the_wall_deadline() -> None:
    def _blocked_resolver(*args, **kwargs):
        time.sleep(1.0)
        return _addresses("8.8.8.8")

    started_at = time.monotonic()
    with pytest.raises(policy.MootionRemoteAssetPolicyError, match="mootion_remote_asset_deadline_exceeded"):
        policy.mootion_remote_asset_global_addresses(
            "cdn.example",
            deadline=started_at + 0.05,
            resolver=_blocked_resolver,
        )
    assert time.monotonic() - started_at < 0.5

from __future__ import annotations

import ipaddress
import os
import queue
import re
import socket
import threading
import time
from collections.abc import Callable


MOOTION_REMOTE_VIDEO_ALLOWED_HOSTS_ENV = "PROPERTYQUARRY_MOOTION_REMOTE_VIDEO_ALLOWED_HOSTS"
_DNS_READINESS_TIMEOUT_SECONDS = 5.0
_HOST_LABEL_RE = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\Z")


class MootionRemoteAssetPolicyError(RuntimeError):
    """A secret-safe, fail-closed remote asset policy failure."""


def _configured_host_tokens(raw_value: object | None = None) -> list[str]:
    value = os.getenv(MOOTION_REMOTE_VIDEO_ALLOWED_HOSTS_ENV) if raw_value is None else raw_value
    return [token.strip() for token in str(value or "").split(",") if token.strip()]


def normalize_mootion_remote_asset_hostname(value: object) -> str:
    hostname = str(value or "").strip().lower()
    if hostname.endswith("."):
        hostname = hostname[:-1]
    if not hostname or len(hostname) > 253 or "." not in hostname:
        raise MootionRemoteAssetPolicyError("mootion_remote_asset_host_allowlist_invalid")
    try:
        hostname.encode("ascii")
    except UnicodeEncodeError as exc:
        raise MootionRemoteAssetPolicyError("mootion_remote_asset_host_allowlist_invalid") from exc
    if any(character in hostname for character in (":", "/", "@", "*", "?", "#")):
        raise MootionRemoteAssetPolicyError("mootion_remote_asset_host_allowlist_invalid")
    try:
        ipaddress.ip_address(hostname)
    except ValueError:
        pass
    else:
        raise MootionRemoteAssetPolicyError("mootion_remote_asset_host_allowlist_invalid")
    labels = hostname.split(".")
    if any(not _HOST_LABEL_RE.fullmatch(label) for label in labels) or labels[-1].isdigit():
        raise MootionRemoteAssetPolicyError("mootion_remote_asset_host_allowlist_invalid")
    return hostname


def _getaddrinfo_before_deadline(
    hostname: str,
    *,
    deadline: float,
    resolver: Callable[..., list[tuple[object, ...]]] | None = None,
) -> list[tuple[object, ...]]:
    remaining_seconds = deadline - time.monotonic()
    if remaining_seconds <= 0:
        raise MootionRemoteAssetPolicyError("mootion_remote_asset_deadline_exceeded")
    result_queue: queue.Queue[tuple[bool, object]] = queue.Queue(maxsize=1)

    def _resolve() -> None:
        try:
            effective_resolver = resolver or socket.getaddrinfo
            result_queue.put((True, effective_resolver(hostname, 443, type=socket.SOCK_STREAM)))
        except Exception as exc:  # noqa: BLE001
            result_queue.put((False, exc))

    threading.Thread(
        target=_resolve,
        name="mootion-remote-asset-dns",
        daemon=True,
    ).start()
    try:
        succeeded, value = result_queue.get(timeout=remaining_seconds)
    except queue.Empty as exc:
        raise MootionRemoteAssetPolicyError("mootion_remote_asset_deadline_exceeded") from exc
    if not succeeded:
        if isinstance(value, BaseException):
            raise MootionRemoteAssetPolicyError("mootion_remote_asset_dns_failed") from value
        raise MootionRemoteAssetPolicyError("mootion_remote_asset_dns_failed")
    return list(value)  # type: ignore[arg-type]


def mootion_remote_asset_global_addresses(
    hostname: str,
    *,
    deadline: float | None = None,
    resolver: Callable[..., list[tuple[object, ...]]] | None = None,
) -> tuple[str, ...]:
    normalized_hostname = normalize_mootion_remote_asset_hostname(hostname)
    effective_deadline = deadline if deadline is not None else time.monotonic() + _DNS_READINESS_TIMEOUT_SECONDS
    rows = _getaddrinfo_before_deadline(
        normalized_hostname,
        deadline=effective_deadline,
        resolver=resolver,
    )
    if time.monotonic() >= effective_deadline:
        raise MootionRemoteAssetPolicyError("mootion_remote_asset_deadline_exceeded")
    addresses = tuple(
        sorted(
            {
                str(row[4][0] or "").split("%", 1)[0]
                for row in rows
                if len(row) > 4 and row[4]
            }
        )
    )
    if not addresses:
        raise MootionRemoteAssetPolicyError("mootion_remote_asset_dns_failed")
    for address_text in addresses:
        try:
            address = ipaddress.ip_address(address_text)
        except ValueError as exc:
            raise MootionRemoteAssetPolicyError("mootion_remote_asset_dns_invalid") from exc
        if not address.is_global:
            raise MootionRemoteAssetPolicyError("mootion_remote_asset_host_blocked")
    return addresses


def validated_mootion_remote_asset_allowed_hosts(
    raw_value: object | None = None,
    *,
    deadline: float | None = None,
) -> tuple[str, ...]:
    tokens = _configured_host_tokens(raw_value)
    if not tokens:
        raise MootionRemoteAssetPolicyError("mootion_remote_asset_host_allowlist_missing")
    effective_deadline = deadline if deadline is not None else time.monotonic() + _DNS_READINESS_TIMEOUT_SECONDS
    hosts: list[str] = []
    for token in tokens:
        host = normalize_mootion_remote_asset_hostname(token)
        if host not in hosts:
            hosts.append(host)
    for host in hosts:
        mootion_remote_asset_global_addresses(host, deadline=effective_deadline)
    if time.monotonic() >= effective_deadline:
        raise MootionRemoteAssetPolicyError("mootion_remote_asset_deadline_exceeded")
    return tuple(hosts)


def mootion_remote_asset_host_policy_readiness(raw_value: object | None = None) -> dict[str, object]:
    configured = bool(_configured_host_tokens(raw_value))
    try:
        hosts = validated_mootion_remote_asset_allowed_hosts(raw_value)
    except MootionRemoteAssetPolicyError as exc:
        code = str(exc or "mootion_remote_asset_host_allowlist_invalid")
        reason = (
            "mootion_remote_asset_host_allowlist_missing"
            if code == "mootion_remote_asset_host_allowlist_missing"
            else "mootion_remote_asset_host_allowlist_invalid"
        )
        return {
            "configured": configured,
            "valid": False,
            "reason": reason,
            "validation_error": code,
            "host_count": 0,
        }
    return {
        "configured": True,
        "valid": True,
        "reason": "",
        "validation_error": "",
        "host_count": len(hosts),
    }

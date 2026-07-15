from __future__ import annotations

import contextlib
import math
import os
import socket
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from app.mootion_remote_asset_policy import (
    MootionRemoteAssetPolicyError,
    mootion_remote_asset_global_addresses,
    normalize_mootion_remote_asset_hostname,
    validated_mootion_remote_asset_allowed_hosts,
)


class _MootionNoRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[no-untyped-def]
        return None


def _mootion_remote_asset_opener():  # type: ignore[no-untyped-def]
    return urllib.request.build_opener(urllib.request.ProxyHandler({}), _MootionNoRedirectHandler())


def _mootion_remote_asset_global_addresses(hostname: str, *, deadline: float | None = None) -> tuple[str, ...]:
    return mootion_remote_asset_global_addresses(hostname, deadline=deadline)


def _mootion_remote_asset_response_socket(response: object) -> object:
    fp = getattr(response, "fp", None)
    raw = getattr(fp, "raw", None)
    for candidate in (
        getattr(raw, "_sock", None),
        getattr(fp, "_sock", None),
        getattr(response, "_sock", None),
    ):
        if callable(getattr(candidate, "settimeout", None)):
            return candidate
    raise RuntimeError("mootion_remote_asset_stream_unbounded")


def _stream_mootion_remote_asset_response(
    response: object,
    *,
    output: object,
    max_bytes: int,
    deadline: float,
) -> int:
    read_once = getattr(response, "read1", None)
    if not callable(read_once):
        raise RuntimeError("mootion_remote_asset_stream_unbounded")
    response_socket = _mootion_remote_asset_response_socket(response)
    total_bytes = 0
    while True:
        remaining_seconds = deadline - time.monotonic()
        if remaining_seconds <= 0:
            raise RuntimeError("mootion_remote_asset_deadline_exceeded")
        response_socket.settimeout(max(0.001, min(1.0, remaining_seconds)))
        try:
            chunk = read_once(64 * 1024)
        except (TimeoutError, socket.timeout) as exc:
            if time.monotonic() >= deadline:
                raise RuntimeError("mootion_remote_asset_deadline_exceeded") from exc
            continue
        if time.monotonic() >= deadline:
            raise RuntimeError("mootion_remote_asset_deadline_exceeded")
        if not chunk:
            break
        total_bytes += len(chunk)
        if total_bytes > max_bytes:
            raise RuntimeError("mootion_remote_asset_too_large")
        output.write(chunk)
        if time.monotonic() >= deadline:
            raise RuntimeError("mootion_remote_asset_deadline_exceeded")
    return total_bytes


def _mootion_remote_asset_timeout_seconds() -> float:
    try:
        configured = float(os.getenv("PROPERTYQUARRY_MOOTION_REMOTE_VIDEO_TIMEOUT_SECONDS") or "180")
    except ValueError as exc:
        raise RuntimeError("mootion_remote_asset_timeout_invalid") from exc
    if not math.isfinite(configured):
        raise RuntimeError("mootion_remote_asset_timeout_invalid")
    return max(5.0, min(300.0, configured))


def _mootion_remote_asset_max_bytes() -> int:
    try:
        configured = int(os.getenv("PROPERTYQUARRY_MOOTION_REMOTE_VIDEO_MAX_BYTES") or str(512 * 1024 * 1024))
    except ValueError as exc:
        raise RuntimeError("mootion_remote_asset_max_bytes_invalid") from exc
    return max(1_048_576, min(1_073_741_824, configured))


def _mootion_remote_asset_target_path(asset_url: object, *, target_dir: Path) -> Path:
    parsed = urllib.parse.urlparse(str(asset_url or "").strip())
    suffix = Path(parsed.path).suffix.lower()
    if suffix not in {".mp4", ".webm", ".mov", ".m4v", ".mkv"}:
        suffix = ".mp4"
    target_path = (target_dir / f"mootion-browseract-remote{suffix}").resolve()
    if target_dir.resolve() not in target_path.parents:
        raise RuntimeError("mootion_remote_asset_target_invalid")
    return target_path


def _materialize_mootion_remote_video_asset_in_process(asset_url: object, *, target_dir: Path) -> Path:
    deadline = time.monotonic() + _mootion_remote_asset_timeout_seconds()
    allowed_hosts = set(validated_mootion_remote_asset_allowed_hosts(deadline=deadline))

    def _validated_url(value: object) -> tuple[str, urllib.parse.ParseResult]:
        normalized_value = str(value or "").strip()
        parsed_value = urllib.parse.urlparse(normalized_value)
        try:
            parsed_hostname = normalize_mootion_remote_asset_hostname(parsed_value.hostname)
        except MootionRemoteAssetPolicyError as exc:
            raise RuntimeError("mootion_remote_asset_url_invalid") from exc
        try:
            parsed_port = parsed_value.port
        except ValueError as exc:
            raise RuntimeError("mootion_remote_asset_url_invalid") from exc
        if (
            parsed_value.scheme.lower() != "https"
            or not parsed_hostname
            or parsed_value.username is not None
            or parsed_value.password is not None
            or parsed_port not in {None, 443}
        ):
            raise RuntimeError("mootion_remote_asset_url_invalid")
        if parsed_hostname not in allowed_hosts:
            raise RuntimeError("mootion_remote_asset_host_blocked")
        _mootion_remote_asset_global_addresses(parsed_hostname, deadline=deadline)
        return normalized_value, parsed_value

    normalized_url, _parsed = _validated_url(asset_url)
    target_path = _mootion_remote_asset_target_path(normalized_url, target_dir=target_dir)
    if target_path.exists():
        raise RuntimeError("mootion_remote_asset_target_exists")
    max_bytes = _mootion_remote_asset_max_bytes()
    opener = _mootion_remote_asset_opener()
    current_url = normalized_url
    total_bytes = 0
    redirect_count = 0
    try:
        while True:
            current_url, _current_parsed = _validated_url(current_url)
            remaining_seconds = deadline - time.monotonic()
            if remaining_seconds <= 0:
                raise RuntimeError("mootion_remote_asset_deadline_exceeded")
            request = urllib.request.Request(
                current_url,
                headers={"User-Agent": "PropertyQuarry-Mootion/1.0", "Accept-Encoding": "identity"},
            )
            try:
                response = opener.open(request, timeout=max(0.05, min(15.0, remaining_seconds)))
            except urllib.error.HTTPError as exc:
                try:
                    if int(exc.code or 0) not in {301, 302, 303, 307, 308}:
                        raise
                    redirect_count += 1
                    if redirect_count > 3:
                        raise RuntimeError("mootion_remote_asset_redirect_limit") from exc
                    location = str(exc.headers.get("Location") or "").strip()
                    if not location:
                        raise RuntimeError("mootion_remote_asset_redirect_invalid") from exc
                    current_url, _redirect_parsed = _validated_url(urllib.parse.urljoin(current_url, location))
                finally:
                    with contextlib.suppress(Exception):
                        exc.close()
                continue
            with response:
                response_url = str(getattr(response, "geturl", lambda: current_url)() or current_url).strip()
                _validated_url(response_url)
                content_length_text = str(response.headers.get("Content-Length") or "").strip()
                if content_length_text and int(content_length_text) > max_bytes:
                    raise RuntimeError("mootion_remote_asset_too_large")
                with target_path.open("wb") as output:
                    total_bytes = _stream_mootion_remote_asset_response(
                        response,
                        output=output,
                        max_bytes=max_bytes,
                        deadline=deadline,
                    )
            break
    except Exception:
        with contextlib.suppress(OSError):
            target_path.unlink()
        raise
    if total_bytes <= 0:
        with contextlib.suppress(OSError):
            target_path.unlink()
        raise RuntimeError("mootion_remote_asset_empty")
    return target_path

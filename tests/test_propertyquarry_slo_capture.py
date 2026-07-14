from __future__ import annotations

import json
import stat
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import pytest

from scripts.propertyquarry_slo_capture import (
    CaptureConfig,
    CaptureError,
    capture_metrics,
)


RELEASE_SHA = "a" * 40
IMAGE_DIGEST = "sha256:" + "b" * 64
CONTAINER_IMAGE_ID = "sha256:" + "c" * 64
CONTAINER_IDS = ("1" * 64, "2" * 64)
REPLICA_IDS = ("propertyquarry-api-1", "propertyquarry-api-2")


class _Response:
    def __init__(
        self,
        payload: bytes,
        *,
        status: int = 200,
        content_type: str = "text/plain; version=0.0.4; charset=utf-8",
        cache_control: str = "private, no-store",
        peer_ip: str = "127.0.0.1",
        reflected_header: str = "",
    ) -> None:
        self._payload = payload
        self._status = status
        self.peer_ip = peer_ip
        self.tls_verified = False
        self.headers = {
            "Content-Type": content_type,
            "Cache-Control": cache_control,
        }
        if reflected_header:
            self.headers["X-Debug"] = reflected_header

    def getcode(self) -> int:
        return self._status

    def read(self, amount: int = -1) -> bytes:
        return self._payload if amount < 0 else self._payload[:amount]

    def __enter__(self) -> "_Response":
        return self

    def __exit__(self, *args: object) -> None:
        return None


@dataclass
class _Completed:
    stdout: bytes
    returncode: int = 0


def _inspect_row(container_id: str, replica_id: str, port: int) -> dict[str, object]:
    return {
        "Id": container_id,
        "Image": CONTAINER_IMAGE_ID,
        "State": {"Running": True},
        "Config": {
            "Hostname": replica_id,
            "Image": f"registry.example/propertyquarry@{IMAGE_DIGEST}",
            "Labels": {
                "com.docker.compose.service": "propertyquarry-api",
                "org.opencontainers.image.revision": RELEASE_SHA,
            },
            "Env": [
                "EA_ROLE=api",
                f"PROPERTYQUARRY_RELEASE_COMMIT_SHA={RELEASE_SHA}",
                f"PROPERTYQUARRY_RELEASE_IMAGE_DIGEST={IMAGE_DIGEST}",
            ],
        },
        "NetworkSettings": {
            "Ports": {"8090/tcp": [{"HostIp": "127.0.0.1", "HostPort": str(port)}]}
        },
    }


class _Docker:
    def __init__(self, *, replicas: int = 2, change_inventory: bool = False) -> None:
        self.rows = [
            _inspect_row(CONTAINER_IDS[index], REPLICA_IDS[index], 8090 + index)
            for index in range(replicas)
        ]
        self.change_inventory = change_inventory
        self.discovery_count = 0

    def __call__(self, argv: list[str], **_kwargs: object) -> _Completed:
        if argv[:2] == ["docker", "ps"]:
            self.discovery_count += 1
            rows = self.rows
            if self.change_inventory and self.discovery_count > 1:
                rows = self.rows[:-1]
            return _Completed(
                ("\n".join(str(row["Id"])[:12] for row in rows) + "\n").encode()
            )
        assert argv[:2] == ["docker", "inspect"]
        requested = argv[2:]
        rows = [
            row
            for row in self.rows
            if any(str(row["Id"]).startswith(prefix) for prefix in requested)
        ]
        return _Completed(json.dumps(rows).encode())


def _config(tmp_path: Path, **overrides: object) -> CaptureConfig:
    values: dict[str, object] = {
        "base_url": "http://127.0.0.1:8090",
        "release_commit_sha": RELEASE_SHA,
        "release_image_digest": IMAGE_DIGEST,
        "metrics_snapshot_path": tmp_path / "metrics.json",
        "metrics_probe_path": tmp_path / "probe.json",
        "host_header": "propertyquarry.com",
        "snapshot_interval_seconds": 5,
    }
    values.update(overrides)
    return CaptureConfig(**values)  # type: ignore[arg-type]


def _replica_for_url(url: str) -> str:
    return REPLICA_IDS[1] if ":8091/" in url else REPLICA_IDS[0]


def _metrics(replica_id: str, value: int = 1) -> bytes:
    return (
        "# TYPE propertyquarry_runtime_build_info gauge\n"
        "propertyquarry_runtime_build_info{"
        f'release_commit_sha="{RELEASE_SHA}",'
        f'release_image_digest="{IMAGE_DIGEST}",'
        f'replica_id="{replica_id}"'
        f"}} {value}\n"
    ).encode()


def _valid_open(calls: list[dict[str, object]]):
    def open_url(request: urllib.request.Request, *, timeout: int) -> _Response:
        calls.append(
            {
                "url": request.full_url,
                "authorization": request.get_header("Authorization"),
                "principal": request.get_header("X-ea-principal-id"),
                "host": request.get_header("Host"),
                "timeout": timeout,
            }
        )
        replica_id = _replica_for_url(request.full_url)
        if request.full_url.endswith("/version"):
            return _Response(
                json.dumps(
                    {
                        "release_commit_sha": RELEASE_SHA,
                        "release_image_digest": IMAGE_DIGEST,
                        "replica_id": replica_id,
                        "role": "api",
                    }
                ).encode(),
                content_type="application/json",
            )
        return _Response(_metrics(replica_id))

    return open_url


def _assert_no_output(tmp_path: Path) -> None:
    assert list(tmp_path.iterdir()) == []


def test_capture_derives_replica_count_and_writes_distinct_docker_bound_artifacts(
    tmp_path: Path,
) -> None:
    calls: list[dict[str, object]] = []
    config = _config(tmp_path)
    receipt = capture_metrics(
        config,
        open_url=_valid_open(calls),
        docker_runner=_Docker(),
        environ={"EA_API_TOKEN": "super-secret-token"},
        now=datetime(2026, 7, 14, 12, 30, tzinfo=timezone.utc),
        sleeper=lambda _seconds: None,
    )

    assert receipt["schema"] == "propertyquarry.metrics_probe_bundle.v2"
    assert receipt["replica_count"] == 2
    assert receipt["captured_at"] == "2026-07-14T12:30:05Z"
    assert receipt["credential_persisted"] is False
    assert {row["container_id"] for row in receipt["replicas"]} == set(CONTAINER_IDS)
    assert len({row["path"] for row in receipt["replicas"]}) == 2
    manifest = json.loads(config.metrics_snapshot_path.read_text(encoding="utf-8"))
    assert manifest["replica_count"] == 2
    assert manifest["window_seconds"] == 5.0
    assert len({row["start"]["path"] for row in manifest["replicas"]}) == 2
    assert len({row["end"]["path"] for row in manifest["replicas"]}) == 2
    assert all(row["container_image_id"] == CONTAINER_IMAGE_ID for row in manifest["replicas"])
    assert len(calls) == 8
    assert all(call["authorization"] is None for call in calls if str(call["url"]).endswith("/version"))
    assert all(
        call["authorization"] == "Bearer super-secret-token"
        for call in calls
        if str(call["url"]).endswith("/internal/metrics")
    )
    for artifact in tmp_path.iterdir():
        assert stat.S_IMODE(artifact.stat().st_mode) == 0o600
        assert "super-secret-token" not in artifact.read_text(encoding="utf-8")


@pytest.mark.parametrize(
    "target_url",
    (
        "https://propertyquarry.com",
        "https://metrics.example.test",
        "http://10.0.0.8:8090",
        "http://169.254.169.254",
        "http://127.0.0.1:8090/internal/metrics",
        "http://token@127.0.0.1:8090",
    ),
)
def test_capture_rejects_hostnames_unresolved_targets_and_plain_private_http(
    tmp_path: Path,
    target_url: str,
) -> None:
    called = False

    def open_url(*_args: object, **_kwargs: object) -> _Response:
        nonlocal called
        called = True
        return _Response(b"not reached")

    with pytest.raises(CaptureError):
        capture_metrics(
            _config(tmp_path, base_url=target_url),
            open_url=open_url,
            docker_runner=_Docker(),
            environ={"EA_API_TOKEN": "secret"},
            sleeper=lambda _seconds: None,
        )

    assert called is False
    _assert_no_output(tmp_path)


def test_capture_rejects_operator_asserted_replica_identity(tmp_path: Path) -> None:
    with pytest.raises(CaptureError, match="deprecated replica ID diverges"):
        capture_metrics(
            _config(tmp_path, replica_id="self-asserted", replica_count=1),
            open_url=_valid_open([]),
            docker_runner=_Docker(replicas=1),
            environ={"EA_API_TOKEN": "secret"},
            sleeper=lambda _seconds: None,
        )
    _assert_no_output(tmp_path)


def test_capture_rejects_version_identity_mismatch_before_any_write(tmp_path: Path) -> None:
    def open_url(request: urllib.request.Request, *, timeout: int) -> _Response:
        del timeout
        if request.full_url.endswith("/version"):
            return _Response(
                json.dumps(
                    {
                        "release_commit_sha": "d" * 40,
                        "release_image_digest": IMAGE_DIGEST,
                        "replica_id": REPLICA_IDS[0],
                        "role": "api",
                    }
                ).encode(),
                content_type="application/json",
            )
        return _Response(_metrics(REPLICA_IDS[0]))

    with pytest.raises(CaptureError, match="/version identity diverges"):
        capture_metrics(
            _config(tmp_path),
            open_url=open_url,
            docker_runner=_Docker(replicas=1),
            environ={"EA_API_TOKEN": "secret"},
            sleeper=lambda _seconds: None,
        )
    _assert_no_output(tmp_path)


@pytest.mark.parametrize("reflection", ("body", "header"))
def test_capture_rejects_bearer_reflection_before_any_write(
    tmp_path: Path, reflection: str
) -> None:
    token = "never-persist-this-token"

    def open_url(request: urllib.request.Request, *, timeout: int) -> _Response:
        del timeout
        replica_id = _replica_for_url(request.full_url)
        if request.full_url.endswith("/version"):
            return _Response(
                json.dumps(
                    {
                        "release_commit_sha": RELEASE_SHA,
                        "release_image_digest": IMAGE_DIGEST,
                        "replica_id": replica_id,
                        "role": "api",
                    }
                ).encode(),
                content_type="application/json",
            )
        return _Response(
            _metrics(replica_id) + (token.encode() if reflection == "body" else b""),
            reflected_header=token if reflection == "header" else "",
        )

    with pytest.raises(CaptureError, match="reflected the bearer"):
        capture_metrics(
            _config(tmp_path),
            open_url=open_url,
            docker_runner=_Docker(replicas=1),
            environ={"EA_API_TOKEN": token},
            sleeper=lambda _seconds: None,
        )
    _assert_no_output(tmp_path)


def test_capture_verifies_connected_peer_before_any_write(tmp_path: Path) -> None:
    def open_url(request: urllib.request.Request, *, timeout: int) -> _Response:
        del timeout
        replica_id = _replica_for_url(request.full_url)
        if request.full_url.endswith("/version"):
            payload = json.dumps(
                {
                    "release_commit_sha": RELEASE_SHA,
                    "release_image_digest": IMAGE_DIGEST,
                    "replica_id": replica_id,
                    "role": "api",
                }
            ).encode()
            return _Response(payload, content_type="application/json", peer_ip="127.0.0.2")
        return _Response(_metrics(replica_id))

    with pytest.raises(CaptureError, match="connected peer"):
        capture_metrics(
            _config(tmp_path),
            open_url=open_url,
            docker_runner=_Docker(replicas=1),
            environ={"EA_API_TOKEN": "secret"},
            sleeper=lambda _seconds: None,
        )
    _assert_no_output(tmp_path)


def test_capture_rejects_inventory_changes_during_window_without_writing(tmp_path: Path) -> None:
    with pytest.raises(CaptureError, match="inventory changed"):
        capture_metrics(
            _config(tmp_path),
            open_url=_valid_open([]),
            docker_runner=_Docker(change_inventory=True),
            environ={"EA_API_TOKEN": "secret"},
            sleeper=lambda _seconds: None,
        )
    _assert_no_output(tmp_path)


def test_capture_refuses_to_replace_existing_bundle(tmp_path: Path) -> None:
    bundle = tmp_path / "metrics.json"
    bundle.write_text("existing", encoding="utf-8")

    with pytest.raises(CaptureError, match="already exists"):
        capture_metrics(
            _config(tmp_path),
            open_url=_valid_open([]),
            docker_runner=_Docker(replicas=1),
            environ={"EA_API_TOKEN": "secret"},
            sleeper=lambda _seconds: None,
        )

    assert bundle.read_text(encoding="utf-8") == "existing"
    assert not (tmp_path / "probe.json").exists()

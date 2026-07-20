from __future__ import annotations

import contextlib
import copy
import json
import subprocess
import sys
import threading
import types
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from scripts import propertyquarry_capacity_evidence as capacity


COMMIT_SHA = "a" * 40
SOURCE_SHA = "b" * 64


def _source_identity(*, clean: bool = True) -> dict[str, object]:
    return {
        "commit_sha": COMMIT_SHA,
        "source_tree_sha256": SOURCE_SHA,
        "source_tree_method": "git_tracked_and_nonignored_untracked_current_content_manifest_v1",
        "source_file_count": 12,
        "source_total_bytes": 4096,
        "working_tree_clean": clean,
    }


def _sample(start: datetime, seconds: float) -> dict[str, object]:
    return {
        "started_at": capacity._iso(start),
        "completed_at": capacity._iso(start + timedelta(seconds=seconds)),
        "window_seconds": seconds,
    }


def _host_measurement(*, generated_at: datetime) -> dict[str, object]:
    memory_current = 256 * 1024 * 1024
    memory_maximum = 2 * 1024 * 1024 * 1024
    pids_current = 8
    pids_maximum = 512
    return {
        "state": "measured",
        "reason": "",
        "workload": copy.deepcopy(capacity.PROFILE["host_sampler"]),
        "sample": _sample(generated_at, 1.0),
        "cpu": {
            "logical_cpu_count": 4,
            "process_cpu_seconds": 0.2,
            "normalized_cpu_percent": 5.0,
            "normalization": "process_cpu_seconds_per_wall_second_divided_by_logical_cpu_count",
        },
        "memory": {
            "rss_before_bytes": 64 * 1024 * 1024,
            "rss_peak_bytes": 72 * 1024 * 1024,
            "rss_after_bytes": 68 * 1024 * 1024,
            "rss_growth_bytes": 4 * 1024 * 1024,
            "cgroup_current_peak_bytes": memory_current,
            "cgroup_maximum_bytes": memory_maximum,
            "cgroup_maximum_state": "measured",
            "cgroup_headroom_bytes": memory_maximum - memory_current,
        },
        "processes": {
            "producer_pid_count": 1,
            "thread_count_before": 2,
            "thread_count_peak": 8,
            "thread_count_after": 2,
            "cgroup_pids_current_peak": pids_current,
            "cgroup_pids_maximum": pids_maximum,
            "cgroup_pids_maximum_state": "measured",
            "cgroup_pids_headroom": pids_maximum - pids_current,
        },
        "disk": {
            "filesystem_scope": "repository_filesystem",
            "total_bytes": 10_000_000_000,
            "free_bytes_before": 5_100_000_000,
            "free_bytes_after": 5_000_000_000,
            "free_percent_after": 50.0,
            "process_read_bytes_delta": 4096,
            "process_write_bytes_delta": 0,
            "io_scope": "producer_process_proc_io_when_available",
        },
    }


def _queue_measurement(*, generated_at: datetime) -> dict[str, object]:
    workload = copy.deepcopy(capacity.PROFILE["queue_scheduler_worker"])
    thresholds = capacity.THRESHOLDS["queue_scheduler_worker"]
    job_count = int(workload["job_count"])
    sample_window_seconds = 1.0
    throughput = round(job_count / sample_window_seconds, 3)
    assert throughput >= float(thresholds["scheduler_items_per_second_minimum"])
    assert throughput >= float(thresholds["worker_items_per_second_minimum"])
    return {
        "state": "measured",
        "reason": "",
        "workload": workload,
        "scheduler_sample": _sample(generated_at, sample_window_seconds),
        "worker_sample": _sample(generated_at, sample_window_seconds),
        "observations": {
            "initial_depth": 0,
            "scheduled": job_count,
            "peak_depth": job_count,
            "completed": job_count,
            "final_depth": 0,
            "error_count": 0,
            "scheduler_items_per_second": throughput,
            "worker_items_per_second": throughput,
        },
        "cleanup": {"active_jobs_after": 0, "fixture_released": True},
    }


def _postgres_measurement(*, generated_at: datetime) -> dict[str, object]:
    connect_samples = [5.0, 6.0, 7.0, 8.0]
    query_samples = [2.0] * int(capacity.PROFILE["postgres"]["query_count"])
    return {
        "state": "measured",
        "reason": "",
        "target": {
            "transport": "loopback_tcp",
            "port": 55432,
            "database_name_sha256": "c" * 64,
            "server_version_num": "160006",
        },
        "workload": copy.deepcopy(capacity.PROFILE["postgres"]),
        "sample": _sample(generated_at, 1.0),
        "observations": {
            "connection_attempts": 4,
            "connected": 4,
            "connection_error_count": 0,
            "connect_latency_samples_ms": connect_samples,
            "connect_p95_ms": capacity._percentile(connect_samples, 0.95),
            "query_attempts": 40,
            "query_successes": 40,
            "query_error_count": 0,
            "pool_acquire_latency_samples_ms": [0.1] * 40,
            "query_latency_samples_ms": query_samples,
            "query_p95_ms": capacity._percentile(query_samples, 0.95),
            "queries_per_second": 40.0,
            "peak_checked_out": 4,
        },
        "cleanup": {"connections_closed": 4, "open_connections_after": 0},
    }


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.0"
    hit_count = 0

    def do_GET(self) -> None:  # noqa: N802
        type(self).hit_count += 1
        body = b'{"status":"ready"}'
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:
        del format, args


@contextlib.contextmanager
def _loopback_server():
    _Handler.hit_count = 0
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/readyz"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def _complete_receipt() -> dict[str, object]:
    with _loopback_server() as url:
        api = capacity.measure_api(url)
    queue_measurement = capacity.measure_queue_scheduler_worker()
    generated_at = datetime.now(timezone.utc)
    return capacity.build_capacity_receipt(
        source_identity=_source_identity(),
        api=api,
        postgres=_postgres_measurement(generated_at=generated_at),
        queue_scheduler_worker=queue_measurement,
        host=_host_measurement(generated_at=generated_at),
        generated_at=generated_at,
    )


def _receipt_time(receipt: dict[str, object]) -> datetime:
    return capacity._parse_timestamp(receipt["generated_at"], field="generated_at")


def _rehash(payload: dict[str, object]) -> None:
    payload["payload_sha256"] = capacity._payload_sha256(payload)


def test_loopback_api_queue_host_and_strict_receipt_verify() -> None:
    receipt = _complete_receipt()

    assert _Handler.hit_count == capacity.PROFILE["api"]["request_count"]
    assert receipt["summary"]["local_status"] == "local_thresholds_passed"
    assert receipt["summary"]["production_capacity_established"] is False
    verification = capacity.validate_capacity_receipt(
        receipt,
        expected_commit_sha=COMMIT_SHA,
        expected_source_tree_sha256=SOURCE_SHA,
        now=_receipt_time(receipt) + timedelta(minutes=1),
    )
    assert verification["status"] == "verified_local_measurement"
    assert verification["production_capacity_established"] is False


def test_missing_api_and_postgres_are_explicit_partial_states() -> None:
    generated_at = datetime.now(timezone.utc)
    receipt = capacity.build_capacity_receipt(
        source_identity=_source_identity(clean=False),
        api=capacity.measure_api(None),
        postgres=capacity.measure_postgres(None),
        queue_scheduler_worker=_queue_measurement(generated_at=generated_at),
        host=_host_measurement(generated_at=generated_at),
        generated_at=generated_at,
    )

    assert receipt["summary"]["local_status"] == "partial_local_measurement"
    assert receipt["summary"]["required_not_measured_count"] == 10
    assert receipt["measurements"]["api"]["state"] == "not_measured"
    assert receipt["measurements"]["postgres"]["state"] == "not_measured"
    capacity.validate_capacity_receipt(
        receipt,
        expected_commit_sha=COMMIT_SHA,
        expected_source_tree_sha256=SOURCE_SHA,
        now=generated_at,
    )


def test_host_measurement_helpers_and_sampler_lifecycle_are_covered_deterministically(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(capacity, "_proc_status", lambda: (64 * 1024 * 1024, 3))
    monkeypatch.setattr(capacity, "_proc_io", lambda: (100, 200))
    monkeypatch.setattr(
        capacity.shutil,
        "disk_usage",
        lambda _path: types.SimpleNamespace(total=1_000, free=600),
    )
    cgroup_values = {
        "memory.current": (256, "measured"),
        "memory.max": (1_024, "measured"),
        "pids.current": (8, "measured"),
        "pids.max": (64, "measured"),
    }
    monkeypatch.setattr(capacity, "_read_cgroup_number", cgroup_values.__getitem__)
    monkeypatch.setattr(capacity.time, "perf_counter", lambda: 10.0)
    monkeypatch.setattr(capacity.time, "process_time", lambda: 2.0)
    monkeypatch.setattr(capacity.os, "cpu_count", lambda: 4)

    captured = capacity._host_baseline(tmp_path)
    assert captured.rss_bytes == 64 * 1024 * 1024
    assert captured.threads == 3
    assert captured.disk_total == 1_000
    assert captured.disk_free == 600
    assert captured.read_bytes == 100
    assert captured.write_bytes == 200
    assert captured.cgroup_memory_current == 256
    assert captured.cgroup_memory_maximum == 1_024
    assert captured.cgroup_pids_current == 8
    assert captured.cgroup_pids_maximum == 64
    assert captured.monotonic == 10.0
    assert captured.process_cpu_seconds == 2.0

    started_at = datetime(2026, 7, 20, 12, 0, tzinfo=timezone.utc)
    before = capacity._HostBaseline(
        captured_at=started_at,
        monotonic=10.0,
        process_cpu_seconds=2.0,
        rss_bytes=64,
        threads=2,
        disk_total=1_000,
        disk_free=600,
        read_bytes=100,
        write_bytes=200,
        cgroup_memory_current=256,
        cgroup_memory_maximum=1_024,
        cgroup_memory_maximum_state="measured",
        cgroup_pids_current=8,
        cgroup_pids_maximum=64,
        cgroup_pids_maximum_state="measured",
    )
    after = capacity._HostBaseline(
        captured_at=started_at + timedelta(seconds=2),
        monotonic=12.0,
        process_cpu_seconds=2.4,
        rss_bytes=80,
        threads=3,
        disk_total=1_000,
        disk_free=500,
        read_bytes=160,
        write_bytes=260,
        cgroup_memory_current=280,
        cgroup_memory_maximum=1_024,
        cgroup_memory_maximum_state="measured",
        cgroup_pids_current=9,
        cgroup_pids_maximum=64,
        cgroup_pids_maximum_state="measured",
    )
    sampler = capacity.HostSampler()
    sampler.max_rss_bytes = 90
    sampler.max_threads = 5
    sampler.max_cgroup_memory_current = 300
    sampler.max_cgroup_pids_current = 12

    measured = capacity.build_host_measurement(before, after, sampler)
    assert measured["sample"]["window_seconds"] == 2.0
    assert measured["cpu"]["normalized_cpu_percent"] == 5.0
    assert measured["memory"]["rss_peak_bytes"] == 90
    assert measured["memory"]["cgroup_current_peak_bytes"] == 300
    assert measured["memory"]["cgroup_headroom_bytes"] == 724
    assert measured["processes"]["thread_count_peak"] == 5
    assert measured["processes"]["cgroup_pids_current_peak"] == 12
    assert measured["processes"]["cgroup_pids_headroom"] == 52
    assert measured["disk"]["free_percent_after"] == 50.0
    assert measured["disk"]["process_read_bytes_delta"] == 60
    assert measured["disk"]["process_write_bytes_delta"] == 60

    lifecycle_sampler = capacity.HostSampler()
    monkeypatch.setattr(lifecycle_sampler, "_sample_loop", lambda: None)
    lifecycle_sampler.start()
    lifecycle_sampler.stop()
    assert lifecycle_sampler._thread is not None
    assert lifecycle_sampler._thread.is_alive() is False
    with pytest.raises(capacity.CapacityEvidenceError, match="started twice"):
        lifecycle_sampler.start()


def test_api_rejects_external_query_and_credential_targets() -> None:
    for url in (
        "https://example.com/readyz",
        "http://localhost:8090/readyz",
        "http://127.0.0.1:8090/readyz?token=secret",
        "http://user:password@127.0.0.1:8090/readyz",
    ):
        with pytest.raises(capacity.CapacityEvidenceError):
            capacity.measure_api(url)


def test_postgres_probe_uses_read_only_transactions_bounded_pool_and_cleanup(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    commands: list[str] = []
    connections: list[FakeConnection] = []

    class FakeCursor:
        def __init__(self) -> None:
            self.last = ""

        def __enter__(self):
            return self

        def __exit__(self, *args: object) -> None:
            del args

        def execute(self, command: str, parameters: object = None) -> None:
            del parameters
            self.last = command
            commands.append(command)

        def fetchone(self) -> tuple[object, ...]:
            if self.last == "SHOW default_transaction_read_only":
                return ("on",)
            if self.last == "SHOW server_version_num":
                return ("160006",)
            if self.last == "SHOW transaction_read_only":
                return ("on",)
            if self.last == "SELECT 1":
                return (1,)
            return (None,)

    class FakeTransaction:
        def __enter__(self):
            return self

        def __exit__(self, *args: object) -> None:
            del args

    class FakeConnection:
        def __init__(self) -> None:
            self.closed = False

        def cursor(self) -> FakeCursor:
            return FakeCursor()

        def transaction(self) -> FakeTransaction:
            return FakeTransaction()

        def close(self) -> None:
            self.closed = True

    fake_psycopg = types.ModuleType("psycopg")

    def connect(*args: object, **kwargs: object) -> FakeConnection:
        del args
        assert kwargs["autocommit"] is True
        assert "default_transaction_read_only=on" in str(kwargs["options"])
        connection = FakeConnection()
        connections.append(connection)
        return connection

    fake_psycopg.connect = connect  # type: ignore[attr-defined]
    fake_conninfo = types.ModuleType("psycopg.conninfo")
    fake_conninfo.conninfo_to_dict = lambda dsn: {  # type: ignore[attr-defined]
        "host": "127.0.0.1",
        "port": "55432",
        "dbname": "propertyquarry_capacity_fixture",
    }
    monkeypatch.setitem(sys.modules, "psycopg", fake_psycopg)
    monkeypatch.setitem(sys.modules, "psycopg.conninfo", fake_conninfo)
    dsn_file = tmp_path / "postgres.dsn"
    dsn_file.write_text("postgresql://capacity@127.0.0.1:55432/propertyquarry_capacity_fixture", encoding="utf-8")
    dsn_file.chmod(0o600)

    measured = capacity.measure_postgres(dsn_file)

    assert measured["state"] == "measured"
    assert measured["observations"]["query_successes"] == 40
    assert measured["observations"]["peak_checked_out"] <= 4
    assert measured["cleanup"] == {"connections_closed": 4, "open_connections_after": 0}
    assert all(connection.closed for connection in connections)
    assert "SET TRANSACTION READ ONLY" in commands
    assert "SHOW transaction_read_only" in commands
    assert not any(command.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE", "CREATE", "ALTER", "DROP")) for command in commands)


def test_postgres_connection_failure_is_valid_failed_evidence_not_a_false_pass(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    fake_psycopg = types.ModuleType("psycopg")

    def fail_connect(*args: object, **kwargs: object) -> object:
        del args, kwargs
        raise OSError("fixture refused")

    fake_psycopg.connect = fail_connect  # type: ignore[attr-defined]
    fake_conninfo = types.ModuleType("psycopg.conninfo")
    fake_conninfo.conninfo_to_dict = lambda dsn: {  # type: ignore[attr-defined]
        "host": "127.0.0.1",
        "port": "55432",
        "dbname": "propertyquarry_capacity_fixture",
    }
    monkeypatch.setitem(sys.modules, "psycopg", fake_psycopg)
    monkeypatch.setitem(sys.modules, "psycopg.conninfo", fake_conninfo)
    dsn_file = tmp_path / "postgres.dsn"
    dsn_file.write_text("postgresql://capacity@127.0.0.1:55432/propertyquarry_capacity_fixture", encoding="utf-8")
    dsn_file.chmod(0o600)

    measured = capacity.measure_postgres(dsn_file)
    generated_at = datetime.now(timezone.utc)
    receipt = capacity.build_capacity_receipt(
        source_identity=_source_identity(),
        api=capacity._empty_api("loopback_api_url_not_supplied"),
        postgres=measured,
        queue_scheduler_worker=capacity.measure_queue_scheduler_worker(),
        host=_host_measurement(generated_at=generated_at),
        generated_at=generated_at,
    )

    assert measured["state"] == "measured"
    assert measured["observations"]["connection_error_count"] == 4
    assert measured["observations"]["query_error_count"] == 40
    assert receipt["summary"]["local_status"] == "local_thresholds_failed"
    capacity.validate_capacity_receipt(
        receipt,
        expected_commit_sha=COMMIT_SHA,
        expected_source_tree_sha256=SOURCE_SHA,
        now=generated_at,
    )


def test_postgres_dsn_must_be_private_and_loopback(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    fake_conninfo = types.ModuleType("psycopg.conninfo")
    fake_conninfo.conninfo_to_dict = lambda dsn: {  # type: ignore[attr-defined]
        "host": "203.0.113.10", "port": "5432", "dbname": "property"
    }
    monkeypatch.setitem(sys.modules, "psycopg.conninfo", fake_conninfo)
    with pytest.raises(capacity.CapacityEvidenceError, match="loopback"):
        capacity._postgres_target("postgresql://example")

    fake_conninfo.conninfo_to_dict = lambda dsn: {  # type: ignore[attr-defined]
        "host": "127.0.0.1",
        "hostaddr": "203.0.113.11",
        "port": "5432",
        "dbname": "property",
    }
    with pytest.raises(capacity.CapacityEvidenceError, match="hostaddr"):
        capacity._postgres_target("postgresql://example")

    dsn_file = tmp_path / "postgres.dsn"
    dsn_file.write_text("postgresql://local", encoding="utf-8")
    dsn_file.chmod(0o644)
    with pytest.raises(capacity.CapacityEvidenceError, match="0600"):
        capacity._read_private_dsn(dsn_file)

    private_dsn = tmp_path / "private.dsn"
    private_dsn.write_text("postgresql://local", encoding="utf-8")
    private_dsn.chmod(0o600)
    symlink = tmp_path / "linked.dsn"
    symlink.symlink_to(private_dsn)
    with pytest.raises(capacity.CapacityEvidenceError, match="safely"):
        capacity._read_private_dsn(symlink)


def test_validator_rejects_rehashed_measurement_aggregate_tampering() -> None:
    receipt = _complete_receipt()
    receipt["measurements"]["api"]["observations"]["p95_latency_ms"] = 0.0
    _rehash(receipt)

    with pytest.raises(capacity.CapacityEvidenceError, match="aggregates"):
        capacity.validate_capacity_receipt(
            receipt,
            expected_commit_sha=COMMIT_SHA,
            expected_source_tree_sha256=SOURCE_SHA,
            now=_receipt_time(receipt),
        )


def test_validator_rejects_rehashed_stored_check_and_summary_tampering() -> None:
    receipt = _complete_receipt()
    receipt["checks"][0]["status"] = "pass"
    receipt["checks"][0]["observed"] = 0
    _rehash(receipt)

    with pytest.raises(capacity.CapacityEvidenceError, match="stored checks"):
        capacity.validate_capacity_receipt(
            receipt,
            expected_commit_sha=COMMIT_SHA,
            expected_source_tree_sha256=SOURCE_SHA,
            now=_receipt_time(receipt),
        )


def test_validator_rejects_any_production_capacity_claim_even_when_rehashed() -> None:
    receipt = _complete_receipt()
    receipt["scope"]["production_capacity_established"] = True
    receipt["summary"]["production_capacity_established"] = True
    _rehash(receipt)

    with pytest.raises(capacity.CapacityEvidenceError, match="local-only contract"):
        capacity.validate_capacity_receipt(
            receipt,
            expected_commit_sha=COMMIT_SHA,
            expected_source_tree_sha256=SOURCE_SHA,
            now=_receipt_time(receipt),
        )


def test_validator_rejects_wrong_candidate_stale_receipt_and_bool_as_count() -> None:
    receipt = _complete_receipt()
    with pytest.raises(capacity.CapacityEvidenceError, match="different source candidate"):
        capacity.validate_capacity_receipt(
            receipt,
            expected_commit_sha="d" * 40,
            expected_source_tree_sha256=SOURCE_SHA,
            now=_receipt_time(receipt),
        )
    with pytest.raises(capacity.CapacityEvidenceError, match="stale"):
        capacity.validate_capacity_receipt(
            receipt,
            expected_commit_sha=COMMIT_SHA,
            expected_source_tree_sha256=SOURCE_SHA,
            now=_receipt_time(receipt) + timedelta(days=2),
        )
    receipt["measurements"]["api"]["observations"]["response_bytes"] = True
    receipt["measurements"]["network"]["response_bytes"] = True
    _rehash(receipt)
    with pytest.raises(capacity.CapacityEvidenceError, match="bounded integer"):
        capacity.validate_capacity_receipt(
            receipt,
            expected_commit_sha=COMMIT_SHA,
            expected_source_tree_sha256=SOURCE_SHA,
            now=_receipt_time(receipt),
        )


def test_validator_rejects_rehashed_old_measurement_under_fresh_receipt() -> None:
    receipt = _complete_receipt()
    receipt_time = _receipt_time(receipt)
    old_start = receipt_time - timedelta(hours=2)
    receipt["measurements"]["api"]["sample"]["started_at"] = capacity._iso(old_start)
    receipt["measurements"]["api"]["sample"]["completed_at"] = capacity._iso(
        old_start
        + timedelta(seconds=receipt["measurements"]["api"]["sample"]["window_seconds"])
    )
    _rehash(receipt)

    with pytest.raises(capacity.CapacityEvidenceError, match="not contemporaneous"):
        capacity.validate_capacity_receipt(
            receipt,
            expected_commit_sha=COMMIT_SHA,
            expected_source_tree_sha256=SOURCE_SHA,
            now=receipt_time,
        )


def test_cgroup_v2_reader_uses_current_boundary_and_handles_unbounded(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(capacity, "_current_cgroup_v2_directory", lambda: tmp_path)
    (tmp_path / "pids.current").write_text("17\n", encoding="ascii")
    (tmp_path / "pids.max").write_text("max\n", encoding="ascii")

    assert capacity._read_cgroup_number("pids.current") == (17, "measured")
    assert capacity._read_cgroup_number("pids.max") == (None, "unbounded")
    assert capacity._read_cgroup_number("not.allowed") == (None, "invalid")


def test_source_identity_hashes_current_tracked_and_untracked_content(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["/usr/bin/git", "init", "-q", str(repo)], check=True)
    subprocess.run(["/usr/bin/git", "-C", str(repo), "config", "user.email", "capacity@example.invalid"], check=True)
    subprocess.run(["/usr/bin/git", "-C", str(repo), "config", "user.name", "Capacity Fixture"], check=True)
    tracked = repo / "tracked.txt"
    tracked.write_text("one\n", encoding="utf-8")
    subprocess.run(["/usr/bin/git", "-C", str(repo), "add", "tracked.txt"], check=True)
    subprocess.run(["/usr/bin/git", "-C", str(repo), "commit", "-qm", "fixture"], check=True)

    clean = capacity.collect_source_identity(repo)
    assert clean["working_tree_clean"] is True
    untracked = repo / "new.txt"
    untracked.write_text("two\n", encoding="utf-8")
    dirty = capacity.collect_source_identity(repo)
    assert dirty["working_tree_clean"] is False
    assert dirty["source_file_count"] == 2
    assert dirty["source_tree_sha256"] != clean["source_tree_sha256"]
    tracked.write_text("changed\n", encoding="utf-8")
    changed = capacity.collect_source_identity(repo)
    assert changed["source_tree_sha256"] != dirty["source_tree_sha256"]


def test_receipt_loader_rejects_duplicate_keys_and_private_writer_uses_mode_0600(tmp_path: Path) -> None:
    duplicate = tmp_path / "duplicate.json"
    duplicate.write_text('{"schema_version":"one","schema_version":"two"}', encoding="utf-8")
    with pytest.raises(capacity.CapacityEvidenceError, match="duplicate JSON key"):
        capacity.load_receipt(duplicate)

    output = tmp_path / "capacity.json"
    capacity._atomic_write_private_json(output, {"ok": True})
    assert output.stat().st_mode & 0o777 == 0o600
    assert json.loads(output.read_text(encoding="utf-8")) == {"ok": True}

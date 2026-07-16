from __future__ import annotations

import hashlib
import json
import re
import stat
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Mapping, Sequence

import pytest

from scripts import propertyquarry_release_security_gate as gate


RELEASE_SHA = "a" * 40
WEB_IMAGE = f"registry.example/propertyquarry-web@sha256:{'b' * 64}"
RENDER_IMAGE = f"registry.example/propertyquarry-render@sha256:{'c' * 64}"
NOW = datetime(2026, 7, 13, 12, 0, tzinfo=timezone.utc)


def _pip_payload(*, vulnerable: bool = False) -> list[dict[str, object]]:
    vulns: list[dict[str, object]] = []
    if vulnerable:
        vulns.append(
            {
                "id": "PYSEC-2026-001",
                "fix_versions": ["9.9.9"],
                "aliases": ["CVE-2026-1001"],
            }
        )
    return [{"name": "fastapi", "version": "0.135.1", "vulns": vulns}]


def _sbom_payload(name: str, *, components: bool = True) -> dict[str, object]:
    return {
        "bomFormat": "CycloneDX",
        "specVersion": "1.6",
        "version": 1,
        "metadata": {"component": {"type": "container", "name": name}},
        "components": (
            [{"type": "library", "name": "openssl", "version": "3.0.0"}]
            if components
            else []
        ),
    }


def _trivy_payload(
    *, severity: str | None = None, vulnerability_id: str = "CVE-2026-2001"
) -> dict[str, object]:
    vulnerabilities: list[dict[str, str]] = []
    if severity:
        vulnerabilities.append(
            {
                "VulnerabilityID": vulnerability_id,
                "PkgName": "openssl",
                "InstalledVersion": "3.0.0",
                "FixedVersion": "3.0.1",
                "Severity": severity,
            }
        )
    return {
        "SchemaVersion": 2,
        "Results": [{"Target": "sbom", "Vulnerabilities": vulnerabilities}],
    }


class FakeRunner:
    def __init__(
        self,
        *,
        available: set[str] | None = None,
        pip_payload: object | None = None,
        web_sbom: Mapping[str, object] | None = None,
        render_sbom: Mapping[str, object] | None = None,
        web_trivy: Mapping[str, object] | None = None,
        render_trivy: Mapping[str, object] | None = None,
        pip_scan_returncode: int = 0,
        failures: Mapping[str, gate.CommandResult] | None = None,
    ) -> None:
        self.available_tools = available if available is not None else set(gate.REQUIRED_TOOLS)
        self.pip_payload = pip_payload if pip_payload is not None else _pip_payload()
        self.web_sbom = dict(web_sbom or _sbom_payload("web"))
        self.render_sbom = dict(render_sbom or _sbom_payload("render"))
        self.web_trivy = dict(web_trivy or _trivy_payload())
        self.render_trivy = dict(render_trivy or _trivy_payload())
        self.pip_scan_returncode = pip_scan_returncode
        self.failures = dict(failures or {})
        self.calls: list[tuple[str, ...]] = []

    def available(self, executable: str) -> bool:
        return executable in self.available_tools

    def run(self, argv: Sequence[str], *, timeout_seconds: int) -> gate.CommandResult:
        command = tuple(argv)
        self.calls.append(command)
        executable = command[0]
        failure_key = executable
        if executable == "syft" and command[1].startswith("docker:"):
            failure_key = "syft-scan"
        elif executable == "trivy" and command[1] == "sbom":
            failure_key = "trivy-scan"
        elif executable == "pip-audit" and "--requirement" in command:
            failure_key = "pip-scan"
        if failure_key in self.failures:
            return self.failures[failure_key]
        if executable == "pip-audit" and "--version" in command:
            return gate.CommandResult(0, stdout="pip-audit 2.9.0")
        if executable == "syft" and command[1] == "--version":
            return gate.CommandResult(0, stdout="syft 1.30.0")
        if executable == "trivy" and command[1] == "--version":
            return gate.CommandResult(0, stdout="Version: 0.60.0")
        if executable == "pip-audit":
            return gate.CommandResult(
                self.pip_scan_returncode, stdout=json.dumps(self.pip_payload)
            )
        if executable == "syft":
            payload = self.render_sbom if "propertyquarry-render" in command[1] else self.web_sbom
            return gate.CommandResult(0, stdout=json.dumps(payload))
        if executable == "trivy":
            payload = self.render_trivy if "render.sbom" in command[-1] else self.web_trivy
            return gate.CommandResult(0, stdout=json.dumps(payload))
        raise AssertionError(f"unexpected command: {command}")


def _write_waivers(path: Path, waivers: list[dict[str, object]] | None = None) -> Path:
    path.write_text(
        json.dumps({"schema": gate.WAIVER_SCHEMA, "waivers": waivers or []}),
        encoding="utf-8",
    )
    return path


def _config(
    tmp_path: Path,
    *,
    flagship: bool = True,
    threshold: str = "HIGH",
    waivers: list[dict[str, object]] | None = None,
    **overrides: object,
) -> gate.GateConfig:
    values: dict[str, object] = {
        "release_commit_sha": RELEASE_SHA,
        "web_image": WEB_IMAGE,
        "render_image": RENDER_IMAGE,
        "severity_threshold": threshold,
        "flagship": flagship,
        "waivers_path": _write_waivers(tmp_path / "waivers.json", waivers),
        "artifacts_dir": tmp_path / "artifacts",
        "receipt_path": tmp_path / "receipt.json",
        "timeout_seconds": 30,
    }
    values.update(overrides)
    return gate.GateConfig(**values)  # type: ignore[arg-type]


def _waiver(
    *,
    waiver_id: str,
    source: str,
    target: str,
    vulnerability_id: str,
    package: str,
    severity: str,
    created_at: datetime = NOW - timedelta(days=1),
    expires_at: datetime = NOW + timedelta(days=7),
) -> dict[str, object]:
    return {
        "id": waiver_id,
        "source": source,
        "target": target,
        "vulnerability_id": vulnerability_id,
        "package": package,
        "severity": severity,
        "release_commit_sha": RELEASE_SHA,
        "owner": "security-owner",
        "approved_by": "release-approver",
        "reason": "Temporary mitigation is deployed and monitored.",
        "created_at": created_at.isoformat(),
        "expires_at": expires_at.isoformat(),
    }


def test_full_release_and_image_identities_are_required_before_scanning(tmp_path: Path) -> None:
    runner = FakeRunner()
    config = _config(tmp_path, web_image="propertyquarry-web:latest")
    receipt, exit_code = gate.run_security_gate(config=config, runner=runner, now=NOW)

    assert exit_code == 2
    assert receipt["status"] == "failed"
    assert "immutable image reference" in receipt["error"]["message"]
    assert runner.calls == []
    assert stat.S_IMODE(config.receipt_path.stat().st_mode) == 0o600


def test_missing_scanners_fail_closed_for_flagship(tmp_path: Path) -> None:
    runner = FakeRunner(available={"pip-audit"})
    receipt, exit_code = gate.run_security_gate(
        config=_config(tmp_path), runner=runner, now=NOW
    )

    assert exit_code == 2
    assert receipt["status"] == "failed"
    assert receipt["gate_passed"] is False
    assert "syft" in receipt["error"]["message"]
    assert "trivy" in receipt["error"]["message"]
    assert runner.calls == []


def test_missing_scanners_are_advisory_for_ordinary_local_use(tmp_path: Path) -> None:
    runner = FakeRunner(available=set())
    receipt, exit_code = gate.run_security_gate(
        config=_config(tmp_path, flagship=False), runner=runner, now=NOW
    )

    assert exit_code == 0
    assert receipt["status"] == "advisory_unavailable"
    assert receipt["gate_passed"] is False
    assert runner.calls == []


def test_clean_flagship_scan_writes_sboms_scans_and_private_receipt(tmp_path: Path) -> None:
    runner = FakeRunner()
    config = _config(tmp_path)
    receipt, exit_code = gate.run_security_gate(config=config, runner=runner, now=NOW)

    assert exit_code == 0
    assert receipt["status"] == "pass"
    assert receipt["gate_passed"] is True
    assert receipt["summary"]["blocking"] == 0
    assert receipt["artifacts"]["web"]["component_count"] == 1
    assert receipt["artifacts"]["render"]["component_count"] == 1
    assert (config.artifacts_dir / "web.sbom.cdx.json").is_file()
    assert (config.artifacts_dir / "render.sbom.cdx.json").is_file()
    assert (config.artifacts_dir / "dependencies.pip-audit.json").is_file()
    assert stat.S_IMODE(config.receipt_path.stat().st_mode) == 0o600
    assert all(stat.S_IMODE(path.stat().st_mode) == 0o600 for path in config.artifacts_dir.iterdir())

    command_text = "\n".join(" ".join(call) for call in runner.calls)
    assert "docker:" + WEB_IMAGE in command_text
    assert "docker:" + RENDER_IMAGE in command_text
    assert "--skip-db-update" in command_text
    assert "--skip-java-db-update" in command_text
    assert "--skip-vex-repo-update" in command_text
    assert "--skip-version-check" in command_text
    assert "--offline-scan" in command_text
    assert "--scanners vuln" in command_text
    assert "--disable-pip" in command_text
    assert "--vulnerability-service osv" in command_text
    assert "docker pull" not in command_text
    assert "syft registry:" not in command_text
    assert "pip install" not in command_text


def test_high_and_unknown_findings_block_flagship_at_high_threshold(tmp_path: Path) -> None:
    runner = FakeRunner(
        pip_payload=_pip_payload(vulnerable=True),
        pip_scan_returncode=1,
        web_trivy=_trivy_payload(severity="LOW"),
        render_trivy=_trivy_payload(severity="HIGH", vulnerability_id="CVE-2026-3001"),
    )
    receipt, exit_code = gate.run_security_gate(
        config=_config(tmp_path), runner=runner, now=NOW
    )

    assert exit_code == 1
    assert receipt["status"] == "failed"
    assert receipt["summary"] == {
        "total": 3,
        "at_or_above_threshold": 2,
        "waived": 0,
        "blocking": 2,
        "by_effective_severity": {
            "CRITICAL": 1,
            "HIGH": 1,
            "MEDIUM": 0,
            "LOW": 1,
        },
    }
    pip_finding = next(item for item in receipt["findings"] if item["source"] == "pip-audit")
    assert pip_finding["severity"] == "UNKNOWN"
    assert pip_finding["effective_severity"] == "CRITICAL"


def test_vulnerabilities_remain_advisory_outside_flagship_mode(tmp_path: Path) -> None:
    runner = FakeRunner(render_trivy=_trivy_payload(severity="CRITICAL"))
    receipt, exit_code = gate.run_security_gate(
        config=_config(tmp_path, flagship=False), runner=runner, now=NOW
    )

    assert exit_code == 0
    assert receipt["status"] == "advisory_findings"
    assert receipt["gate_passed"] is False
    assert receipt["summary"]["blocking"] == 1


def test_exact_release_bound_time_limited_waivers_clear_findings(tmp_path: Path) -> None:
    dependency_hash = hashlib.sha256(gate.LOCK_PATH.read_bytes()).hexdigest()
    waivers = [
        _waiver(
            waiver_id="PQSEC-2026-001",
            source="pip-audit",
            target=f"sha256:{dependency_hash}",
            vulnerability_id="PYSEC-2026-001",
            package="fastapi",
            severity="UNKNOWN",
        ),
        _waiver(
            waiver_id="PQSEC-2026-002",
            source="trivy:render",
            target=RENDER_IMAGE,
            vulnerability_id="CVE-2026-3001",
            package="openssl",
            severity="HIGH",
        ),
    ]
    runner = FakeRunner(
        pip_payload=_pip_payload(vulnerable=True),
        render_trivy=_trivy_payload(severity="HIGH", vulnerability_id="CVE-2026-3001"),
    )
    receipt, exit_code = gate.run_security_gate(
        config=_config(tmp_path, waivers=waivers), runner=runner, now=NOW
    )

    assert exit_code == 0
    assert receipt["status"] == "pass"
    assert receipt["summary"]["at_or_above_threshold"] == 2
    assert receipt["summary"]["waived"] == 2
    assert receipt["summary"]["blocking"] == 0
    assert [item["id"] for item in receipt["waivers"]["applied"]] == [
        "PQSEC-2026-001",
        "PQSEC-2026-002",
    ]


@pytest.mark.parametrize(
    ("created_at", "expires_at", "message"),
    [
        (NOW - timedelta(days=10), NOW - timedelta(seconds=1), "expired"),
        (NOW - timedelta(days=1), NOW + timedelta(days=31), "within 30 days"),
        (NOW + timedelta(seconds=1), NOW + timedelta(days=1), "cannot be in the future"),
    ],
)
def test_expired_future_or_overlong_waivers_fail_before_scanning(
    tmp_path: Path,
    created_at: datetime,
    expires_at: datetime,
    message: str,
) -> None:
    dependency_hash = hashlib.sha256(gate.LOCK_PATH.read_bytes()).hexdigest()
    waiver = _waiver(
        waiver_id="PQSEC-2026-099",
        source="pip-audit",
        target=f"sha256:{dependency_hash}",
        vulnerability_id="PYSEC-2026-001",
        package="fastapi",
        severity="UNKNOWN",
        created_at=created_at,
        expires_at=expires_at,
    )
    runner = FakeRunner()
    receipt, exit_code = gate.run_security_gate(
        config=_config(tmp_path, waivers=[waiver]), runner=runner, now=NOW
    )

    assert exit_code == 2
    assert message in receipt["error"]["message"]
    assert runner.calls == []


def test_waiver_requires_independent_approver(tmp_path: Path) -> None:
    dependency_hash = hashlib.sha256(gate.LOCK_PATH.read_bytes()).hexdigest()
    waiver = _waiver(
        waiver_id="PQSEC-2026-100",
        source="pip-audit",
        target=f"sha256:{dependency_hash}",
        vulnerability_id="PYSEC-2026-001",
        package="fastapi",
        severity="UNKNOWN",
    )
    waiver["approved_by"] = waiver["owner"]
    runner = FakeRunner()
    receipt, exit_code = gate.run_security_gate(
        config=_config(tmp_path, waivers=[waiver]), runner=runner, now=NOW
    )

    assert exit_code == 2
    assert "independent from the waiver owner" in receipt["error"]["message"]
    assert runner.calls == []


def test_missing_or_empty_sbom_fails_flagship_closed(tmp_path: Path) -> None:
    runner = FakeRunner(web_sbom=_sbom_payload("web", components=False))
    receipt, exit_code = gate.run_security_gate(
        config=_config(tmp_path), runner=runner, now=NOW
    )

    assert exit_code == 2
    assert receipt["status"] == "failed"
    assert "at least one component" in receipt["error"]["message"]
    assert receipt["artifacts"].get("web") is None


def test_scanner_failure_with_secret_output_is_withheld_from_receipt(tmp_path: Path) -> None:
    secret = "registry-token-super-secret"
    runner = FakeRunner(
        failures={
            "trivy-scan": gate.CommandResult(
                7, stdout=secret, stderr=f"authorization={secret}"
            )
        }
    )
    receipt, exit_code = gate.run_security_gate(
        config=_config(tmp_path), runner=runner, now=NOW
    )

    assert exit_code == 2
    serialized = json.dumps(receipt)
    assert secret not in serialized
    assert "raw output was withheld" in receipt["error"]["message"]


def test_subprocess_runner_disables_syft_and_trivy_update_checks(monkeypatch: pytest.MonkeyPatch) -> None:
    observed_environments: list[dict[str, str]] = []

    class Completed:
        returncode = 0
        stdout = "{}"
        stderr = ""

    def fake_run(*args: object, **kwargs: object) -> Completed:
        observed_environments.append(dict(kwargs["env"]))  # type: ignore[arg-type]
        return Completed()

    monkeypatch.setattr(gate.subprocess, "run", fake_run)
    runner = gate.SubprocessScannerRunner()
    runner.run(("syft", "--version"), timeout_seconds=10)
    runner.run(("trivy", "--version"), timeout_seconds=10)

    assert observed_environments[0]["SYFT_CHECK_FOR_APP_UPDATE"] == "false"
    assert observed_environments[1]["TRIVY_SKIP_VERSION_CHECK"] == "true"


def _workflow_job(workflow: str, job_name: str) -> str:
    marker = f"  {job_name}:\n"
    start = workflow.index(marker)
    body_start = start + len(marker)
    next_job = re.search(r"^  [a-zA-Z0-9_-]+:\n", workflow[body_start:], flags=re.MULTILINE)
    end = body_start + next_job.start() if next_job else len(workflow)
    return workflow[start:end]


def test_ci_flagship_security_job_is_focused_protected_and_blocks_live_gate() -> None:
    workflow = (gate.APP_ROOT / ".github/workflows/smoke-runtime.yml").read_text(
        encoding="utf-8"
    )
    job = _workflow_job(workflow, "propertyquarry-flagship-security")
    live_job = _workflow_job(workflow, "propertyquarry-live-release-gates")

    assert "workflow_dispatch" in job
    assert "github.ref == 'refs/heads/main'" in job
    assert "environment:\n      name: propertyquarry-production" in job
    assert "permissions:\n      contents: read" in job
    assert "runs-on: [self-hosted, propertyquarry-security]" in job
    assert "persist-credentials: false" in job
    assert "command -v pip-audit" not in job
    assert "command -v syft" not in job
    assert "command -v trivy" not in job
    assert "PROPERTYQUARRY_WEB_IMAGE: ${{ vars.PROPERTYQUARRY_WEB_IMAGE }}" in job
    assert "PROPERTYQUARRY_RENDER_IMAGE: ${{ vars.PROPERTYQUARRY_RENDER_IMAGE }}" in job
    assert "--severity-threshold HIGH" in job
    assert "--flagship" in job
    assert "propertyquarry_security_waivers.json" in job
    assert (
        "actions/upload-artifact@ea165f8d65b6e75b540449e92b4886f43607fa02 # v4"
        in job
    )
    assert "pip install" not in job
    assert "apt-get" not in job
    assert "docker pull" not in job
    assert "docker compose" not in job
    assert "ea-api" not in job
    assert (
        "needs:\n"
        "      - propertyquarry-ordinary-ci-success\n"
        "      - propertyquarry-flagship-security\n"
        "      - propertyquarry-continuous-ux"
        in live_job
    )
    assert "needs['propertyquarry-ordinary-ci-success'].result == 'success'" in live_job
    assert "needs['propertyquarry-flagship-security'].result == 'success'" in live_job
    assert "needs['propertyquarry-continuous-ux'].result == 'success'" in live_job
    assert "PROPERTYQUARRY_WORKFLOW_HEAD_SHA: ${{ github.sha }}" in job
    assert "release_manifest_runtime_sha" in job
    assert "workflow-binding.json" in job

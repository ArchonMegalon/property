#!/usr/bin/env python3
"""Reproducible dependency, image, and SBOM gate for PropertyQuarry releases.

The controller never installs scanners, pulls images, or updates vulnerability
databases. Flagship mode requires preinstalled pip-audit, Syft, and Trivy plus
already-local digest-pinned PropertyQuarry images and a pre-provisioned Trivy
database. Non-flagship mode records unavailable/advisory results without
breaking ordinary local development.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Mapping, Protocol, Sequence


APP_ROOT = Path(__file__).resolve().parents[1]
LOCK_PATH = APP_ROOT / "ea" / "requirements.lock"
DEFAULT_WAIVERS_PATH = APP_ROOT / "config" / "propertyquarry_security_waivers.json"
RECEIPT_SCHEMA = "propertyquarry.release_security_receipt.v1"
WAIVER_SCHEMA = "propertyquarry.security_waivers.v1"
GIT_SHA_RE = re.compile(r"^[0-9a-fA-F]{40}$")
IMAGE_REF_RE = re.compile(r"^[^\s@]+@sha256:[0-9a-fA-F]{64}$")
WAIVER_ID_RE = re.compile(r"^PQSEC-[0-9]{4}-[0-9]{3,}$")
SEVERITY_RANK = {"LOW": 1, "MEDIUM": 2, "HIGH": 3, "CRITICAL": 4}
MAX_WAIVER_LIFETIME = timedelta(days=30)
REQUIRED_TOOLS = ("pip-audit", "syft", "trivy")


class SecurityGateError(RuntimeError):
    """Base release-security gate failure."""


class SecurityValidationError(SecurityGateError):
    """Invalid immutable identity, threshold, waiver, or scanner document."""


class ScannerExecutionError(SecurityGateError):
    """A required fixed scanner command failed."""


@dataclass(frozen=True)
class CommandResult:
    returncode: int
    stdout: str = ""
    stderr: str = ""


class ScannerRunner(Protocol):
    def available(self, executable: str) -> bool: ...

    def run(self, argv: Sequence[str], *, timeout_seconds: int) -> CommandResult: ...


class SubprocessScannerRunner:
    def available(self, executable: str) -> bool:
        return shutil.which(executable) is not None

    def run(self, argv: Sequence[str], *, timeout_seconds: int) -> CommandResult:
        command_env = dict(os.environ)
        if argv and argv[0] == "syft":
            command_env["SYFT_CHECK_FOR_APP_UPDATE"] = "false"
        if argv and argv[0] == "trivy":
            command_env["TRIVY_SKIP_VERSION_CHECK"] = "true"
        try:
            completed = subprocess.run(
                list(argv),
                cwd=APP_ROOT,
                check=False,
                capture_output=True,
                text=True,
                env=command_env,
                timeout=timeout_seconds,
            )
        except subprocess.TimeoutExpired as exc:
            raise ScannerExecutionError(
                f"scanner command timed out after {timeout_seconds} seconds"
            ) from exc
        except OSError as exc:
            raise ScannerExecutionError("could not start a required scanner") from exc
        return CommandResult(completed.returncode, completed.stdout, completed.stderr)


@dataclass(frozen=True)
class GateConfig:
    release_commit_sha: str
    web_image: str
    render_image: str
    severity_threshold: str
    flagship: bool
    waivers_path: Path
    artifacts_dir: Path
    receipt_path: Path
    timeout_seconds: int
    overwrite_receipt: bool = False


@dataclass(frozen=True)
class Finding:
    source: str
    target: str
    vulnerability_id: str
    package: str
    installed_version: str
    fixed_version: str
    severity: str
    effective_severity: str

    @property
    def key(self) -> tuple[str, str, str, str]:
        return (self.source, self.target, self.vulnerability_id, self.package)

    def receipt_value(self) -> dict[str, str]:
        return {
            "source": self.source,
            "target": self.target,
            "vulnerability_id": self.vulnerability_id,
            "package": self.package,
            "installed_version": self.installed_version,
            "fixed_version": self.fixed_version,
            "severity": self.severity,
            "effective_severity": self.effective_severity,
        }


@dataclass(frozen=True)
class Waiver:
    waiver_id: str
    source: str
    target: str
    vulnerability_id: str
    package: str
    severity: str
    release_commit_sha: str
    owner: str
    approved_by: str
    reason: str
    created_at: datetime
    expires_at: datetime

    @property
    def finding_key(self) -> tuple[str, str, str, str]:
        return (self.source, self.target, self.vulnerability_id, self.package)

    def receipt_value(self) -> dict[str, str]:
        return {
            "id": self.waiver_id,
            "source": self.source,
            "target": self.target,
            "vulnerability_id": self.vulnerability_id,
            "package": self.package,
            "severity": self.severity,
            "owner": self.owner,
            "approved_by": self.approved_by,
            "created_at": isoformat(self.created_at),
            "expires_at": isoformat(self.expires_at),
        }


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def isoformat(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def parse_timestamp(raw: object, *, field_name: str) -> datetime:
    value = str(raw or "").strip()
    if not value:
        raise SecurityValidationError(f"{field_name} is required")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise SecurityValidationError(f"{field_name} must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise SecurityValidationError(f"{field_name} must include an explicit timezone")
    return parsed.astimezone(timezone.utc)


def positive_int(raw: object, *, field_name: str, default: int) -> int:
    value = str(raw or "").strip()
    if not value:
        return default
    if not value.isdigit() or int(value) <= 0:
        raise SecurityValidationError(f"{field_name} must be a positive integer")
    return int(value)


def normalize_release_sha(raw: str) -> str:
    value = str(raw or "").strip().lower()
    if not GIT_SHA_RE.fullmatch(value):
        raise SecurityValidationError("release commit must be a full 40-character Git SHA")
    return value


def normalize_image_ref(raw: str, *, field_name: str) -> str:
    value = str(raw or "").strip()
    if not IMAGE_REF_RE.fullmatch(value):
        raise SecurityValidationError(
            f"{field_name} must be an immutable image reference ending in @sha256:<64 hex>"
        )
    prefix, digest = value.rsplit("@", 1)
    return f"{prefix}@{digest.lower()}"


def normalize_threshold(raw: str) -> str:
    value = str(raw or "").strip().upper()
    if value not in SEVERITY_RANK:
        raise SecurityValidationError("severity threshold must be LOW, MEDIUM, HIGH, or CRITICAL")
    return value


def validate_config(config: GateConfig) -> GateConfig:
    release = normalize_release_sha(config.release_commit_sha)
    web_image = normalize_image_ref(config.web_image, field_name="web image")
    render_image = normalize_image_ref(config.render_image, field_name="render image")
    if web_image == render_image:
        raise SecurityValidationError("web and render images must have distinct immutable identities")
    threshold = normalize_threshold(config.severity_threshold)
    timeout = positive_int(config.timeout_seconds, field_name="scanner timeout", default=900)
    return GateConfig(
        release_commit_sha=release,
        web_image=web_image,
        render_image=render_image,
        severity_threshold=threshold,
        flagship=bool(config.flagship),
        waivers_path=config.waivers_path,
        artifacts_dir=config.artifacts_dir,
        receipt_path=config.receipt_path,
        timeout_seconds=timeout,
        overwrite_receipt=config.overwrite_receipt,
    )


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def file_identity(path: Path) -> dict[str, object]:
    payload = path.read_bytes()
    return {"path": str(path), "bytes": len(payload), "sha256": sha256_bytes(payload)}


def output_evidence(value: str) -> dict[str, object]:
    payload = str(value or "").encode("utf-8", errors="replace")
    return {"bytes": len(payload), "sha256": sha256_bytes(payload)}


def atomic_write_json(path: Path, payload: object, *, overwrite: bool = True) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if path.exists() and not overwrite:
        raise SecurityValidationError(
            f"receipt already exists: {path}; choose a new path or use --overwrite-receipt"
        )
    fd, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary_path = Path(temporary_name)
    try:
        os.fchmod(fd, stat.S_IRUSR | stat.S_IWUSR)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
        os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)
    finally:
        if temporary_path.exists():
            temporary_path.unlink()


def parse_json_document(raw: str, *, document_name: str) -> object:
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise SecurityValidationError(f"{document_name} is not valid JSON") from exc


def load_waivers(
    path: Path,
    *,
    release_commit_sha: str,
    source_targets: Mapping[str, str],
    now: datetime,
) -> list[Waiver]:
    if not path.is_file():
        raise SecurityValidationError(f"waiver file is missing: {path}")
    payload = parse_json_document(path.read_text(encoding="utf-8"), document_name="waiver file")
    if not isinstance(payload, dict) or payload.get("schema") != WAIVER_SCHEMA:
        raise SecurityValidationError(f"waiver file schema must be {WAIVER_SCHEMA}")
    raw_waivers = payload.get("waivers")
    if not isinstance(raw_waivers, list):
        raise SecurityValidationError("waiver file waivers must be a list")

    waivers: list[Waiver] = []
    seen_ids: set[str] = set()
    seen_findings: set[tuple[str, str, str, str]] = set()
    for index, raw_waiver in enumerate(raw_waivers):
        field = f"waivers[{index}]"
        if not isinstance(raw_waiver, dict):
            raise SecurityValidationError(f"{field} must be an object")
        waiver_id = str(raw_waiver.get("id") or "").strip()
        if not WAIVER_ID_RE.fullmatch(waiver_id):
            raise SecurityValidationError(f"{field}.id must match PQSEC-YYYY-NNN")
        if waiver_id in seen_ids:
            raise SecurityValidationError(f"duplicate waiver id: {waiver_id}")
        seen_ids.add(waiver_id)

        source = str(raw_waiver.get("source") or "").strip()
        if source not in source_targets:
            raise SecurityValidationError(f"{field}.source is not an allowed scanner target")
        target = str(raw_waiver.get("target") or "").strip()
        if target != source_targets[source]:
            raise SecurityValidationError(
                f"{field}.target does not match the immutable target for {source}"
            )
        vulnerability_id = str(raw_waiver.get("vulnerability_id") or "").strip()
        package = str(raw_waiver.get("package") or "").strip()
        severity = str(raw_waiver.get("severity") or "").strip().upper()
        bound_release = normalize_release_sha(str(raw_waiver.get("release_commit_sha") or ""))
        owner = str(raw_waiver.get("owner") or "").strip()
        approved_by = str(raw_waiver.get("approved_by") or "").strip()
        reason = str(raw_waiver.get("reason") or "").strip()
        if not vulnerability_id or not package:
            raise SecurityValidationError(f"{field} requires vulnerability_id and package")
        if severity not in {*SEVERITY_RANK, "UNKNOWN"}:
            raise SecurityValidationError(f"{field}.severity is invalid")
        if bound_release != release_commit_sha:
            raise SecurityValidationError(f"{field} is not bound to this release commit")
        if not owner or not approved_by or len(reason) < 12:
            raise SecurityValidationError(
                f"{field} requires owner, approved_by, and a reason of at least 12 characters"
            )
        if owner == approved_by:
            raise SecurityValidationError(
                f"{field}.approved_by must be independent from the waiver owner"
            )
        created_at = parse_timestamp(raw_waiver.get("created_at"), field_name=f"{field}.created_at")
        expires_at = parse_timestamp(raw_waiver.get("expires_at"), field_name=f"{field}.expires_at")
        if created_at > now:
            raise SecurityValidationError(f"{field}.created_at cannot be in the future")
        if expires_at <= now:
            raise SecurityValidationError(f"{field} is expired")
        if expires_at <= created_at or expires_at - created_at > MAX_WAIVER_LIFETIME:
            raise SecurityValidationError(f"{field} must expire within 30 days of creation")

        waiver = Waiver(
            waiver_id=waiver_id,
            source=source,
            target=target,
            vulnerability_id=vulnerability_id,
            package=package,
            severity=severity,
            release_commit_sha=bound_release,
            owner=owner,
            approved_by=approved_by,
            reason=reason,
            created_at=created_at,
            expires_at=expires_at,
        )
        if waiver.finding_key in seen_findings:
            raise SecurityValidationError(f"multiple waivers target the same exact finding: {field}")
        seen_findings.add(waiver.finding_key)
        waivers.append(waiver)
    return waivers


def parse_pip_audit(payload: object, *, target: str) -> list[Finding]:
    if isinstance(payload, list):
        dependencies = payload
    elif isinstance(payload, dict) and isinstance(payload.get("dependencies"), list):
        dependencies = payload["dependencies"]
    else:
        raise SecurityValidationError(
            "pip-audit output must be a dependency list or contain a dependencies list"
        )
    findings: list[Finding] = []
    for dependency in dependencies:
        if not isinstance(dependency, dict) or not isinstance(dependency.get("vulns"), list):
            raise SecurityValidationError("pip-audit dependency entries must contain a vulns list")
        package = str(dependency.get("name") or "").strip()
        installed = str(dependency.get("version") or "").strip()
        if not package or not installed:
            raise SecurityValidationError("pip-audit dependency entries require name and version")
        for vulnerability in dependency["vulns"]:
            if not isinstance(vulnerability, dict):
                raise SecurityValidationError("pip-audit vulnerability entries must be objects")
            vulnerability_id = str(vulnerability.get("id") or "").strip()
            if not vulnerability_id:
                raise SecurityValidationError("pip-audit vulnerability entries require id")
            fixes = vulnerability.get("fix_versions") or []
            if not isinstance(fixes, list):
                raise SecurityValidationError("pip-audit fix_versions must be a list")
            findings.append(
                Finding(
                    source="pip-audit",
                    target=target,
                    vulnerability_id=vulnerability_id,
                    package=package,
                    installed_version=installed,
                    fixed_version=", ".join(str(item) for item in fixes),
                    severity="UNKNOWN",
                    effective_severity="CRITICAL",
                )
            )
    return findings


def validate_cyclonedx_sbom(payload: object, *, target_name: str) -> int:
    if not isinstance(payload, dict) or payload.get("bomFormat") != "CycloneDX":
        raise SecurityValidationError(f"{target_name} SBOM must be a CycloneDX JSON document")
    if not str(payload.get("specVersion") or "").strip():
        raise SecurityValidationError(f"{target_name} SBOM is missing specVersion")
    components = payload.get("components")
    if not isinstance(components, list) or not components:
        raise SecurityValidationError(f"{target_name} SBOM must contain at least one component")
    return len(components)


def parse_trivy(payload: object, *, source: str, target: str) -> list[Finding]:
    if not isinstance(payload, dict) or not isinstance(payload.get("Results"), list):
        raise SecurityValidationError(f"{source} output must contain a Results list")
    findings: list[Finding] = []
    for result in payload["Results"]:
        if not isinstance(result, dict):
            raise SecurityValidationError(f"{source} result entries must be objects")
        vulnerabilities = result.get("Vulnerabilities") or []
        if not isinstance(vulnerabilities, list):
            raise SecurityValidationError(f"{source} Vulnerabilities must be a list")
        for vulnerability in vulnerabilities:
            if not isinstance(vulnerability, dict):
                raise SecurityValidationError(f"{source} vulnerability entries must be objects")
            vulnerability_id = str(vulnerability.get("VulnerabilityID") or "").strip()
            package = str(vulnerability.get("PkgName") or "").strip()
            raw_severity = str(vulnerability.get("Severity") or "UNKNOWN").strip().upper()
            if not vulnerability_id or not package:
                raise SecurityValidationError(
                    f"{source} vulnerability entries require VulnerabilityID and PkgName"
                )
            effective = raw_severity if raw_severity in SEVERITY_RANK else "CRITICAL"
            findings.append(
                Finding(
                    source=source,
                    target=target,
                    vulnerability_id=vulnerability_id,
                    package=package,
                    installed_version=str(vulnerability.get("InstalledVersion") or "").strip(),
                    fixed_version=str(vulnerability.get("FixedVersion") or "").strip(),
                    severity=raw_severity if raw_severity in SEVERITY_RANK else "UNKNOWN",
                    effective_severity=effective,
                )
            )
    return findings


def scanner_command(
    runner: ScannerRunner,
    argv: Sequence[str],
    *,
    timeout_seconds: int,
    accepted_returncodes: frozenset[int] = frozenset({0}),
) -> CommandResult:
    result = runner.run(tuple(argv), timeout_seconds=timeout_seconds)
    if result.returncode not in accepted_returncodes:
        raise ScannerExecutionError(
            f"{argv[0]} failed with exit code {result.returncode}; raw output was withheld"
        )
    return result


def scanner_version(tool: str, output: str) -> str:
    raw = str(output or "").strip()
    match = re.search(r"\b[0-9]+\.[0-9]+(?:\.[0-9]+)?(?:[-+._a-zA-Z0-9]*)?\b", raw)
    if not match:
        raise SecurityValidationError(f"{tool} version output is not recognizable")
    return match.group(0)


def blank_receipt(config: GateConfig) -> dict[str, object]:
    return {
        "schema": RECEIPT_SCHEMA,
        "generated_at": isoformat(utc_now()),
        "mode": "flagship" if config.flagship else "advisory",
        "status": "initializing",
        "gate_passed": False,
        "severity_threshold": config.severity_threshold,
        "identities": {
            "release_commit_sha": config.release_commit_sha,
            "web_image": config.web_image,
            "render_image": config.render_image,
        },
        "network_contract": {
            "scanner_install_allowed": False,
            "registry_access_allowed": False,
            "image_source": "local_docker_digest_only",
            "trivy_database_updates_allowed": False,
        },
        "tools": {tool: {"available": False} for tool in REQUIRED_TOOLS},
        "artifacts": {},
        "findings": [],
        "summary": {
            "total": 0,
            "at_or_above_threshold": 0,
            "waived": 0,
            "blocking": 0,
        },
        "waivers": {"configured": 0, "applied": [], "unused": []},
    }


def run_security_gate(
    *,
    config: GateConfig,
    runner: ScannerRunner | None = None,
    now: datetime | None = None,
) -> tuple[dict[str, object], int]:
    runner = runner or SubprocessScannerRunner()
    now = (now or utc_now()).astimezone(timezone.utc)
    receipt = blank_receipt(config)
    exit_code = 0
    try:
        config = validate_config(config)
        receipt = blank_receipt(config)
        if not LOCK_PATH.is_file():
            raise SecurityValidationError("ea/requirements.lock is missing")
        lock_identity = file_identity(LOCK_PATH)
        dependency_target = f"sha256:{lock_identity['sha256']}"
        source_targets = {
            "pip-audit": dependency_target,
            "trivy:web": config.web_image,
            "trivy:render": config.render_image,
        }
        waivers = load_waivers(
            config.waivers_path,
            release_commit_sha=config.release_commit_sha,
            source_targets=source_targets,
            now=now,
        )
        receipt["identities"]["dependency_lock"] = lock_identity
        receipt["waivers"]["configured"] = len(waivers)

        missing_tools = [tool for tool in REQUIRED_TOOLS if not runner.available(tool)]
        for tool in REQUIRED_TOOLS:
            receipt["tools"][tool]["available"] = tool not in missing_tools
        if missing_tools:
            message = f"required scanners are missing: {', '.join(missing_tools)}"
            if config.flagship:
                raise ScannerExecutionError(message)
            receipt["status"] = "advisory_unavailable"
            receipt["error"] = {"type": "ScannerUnavailable", "message": message}
            return receipt, 0

        version_commands = {
            "pip-audit": ("pip-audit", "--version"),
            "syft": ("syft", "--version"),
            "trivy": ("trivy", "--version"),
        }
        for tool, argv in version_commands.items():
            result = scanner_command(runner, argv, timeout_seconds=config.timeout_seconds)
            receipt["tools"][tool]["version"] = scanner_version(tool, result.stdout)
            receipt["tools"][tool]["version_output"] = output_evidence(result.stdout)

        pip_result = scanner_command(
            runner,
            (
                "pip-audit",
                "--requirement",
                str(LOCK_PATH),
                "--no-deps",
                "--disable-pip",
                "--vulnerability-service",
                "osv",
                "--progress-spinner",
                "off",
                "--format",
                "json",
            ),
            timeout_seconds=config.timeout_seconds,
            accepted_returncodes=frozenset({0, 1}),
        )
        pip_payload = parse_json_document(pip_result.stdout, document_name="pip-audit output")
        dependency_artifact = config.artifacts_dir / "dependencies.pip-audit.json"
        atomic_write_json(dependency_artifact, pip_payload)
        findings = parse_pip_audit(pip_payload, target=dependency_target)
        receipt["artifacts"]["dependencies"] = file_identity(dependency_artifact)

        for target_name, image, source in (
            ("web", config.web_image, "trivy:web"),
            ("render", config.render_image, "trivy:render"),
        ):
            syft_result = scanner_command(
                runner,
                ("syft", f"docker:{image}", "--output", "cyclonedx-json"),
                timeout_seconds=config.timeout_seconds,
            )
            sbom_payload = parse_json_document(
                syft_result.stdout, document_name=f"{target_name} Syft SBOM"
            )
            component_count = validate_cyclonedx_sbom(sbom_payload, target_name=target_name)
            sbom_path = config.artifacts_dir / f"{target_name}.sbom.cdx.json"
            atomic_write_json(sbom_path, sbom_payload)

            trivy_result = scanner_command(
                runner,
                (
                    "trivy",
                    "sbom",
                    "--skip-db-update",
                    "--skip-java-db-update",
                    "--skip-vex-repo-update",
                    "--skip-version-check",
                    "--offline-scan",
                    "--scanners",
                    "vuln",
                    "--format",
                    "json",
                    str(sbom_path),
                ),
                timeout_seconds=config.timeout_seconds,
            )
            trivy_payload = parse_json_document(
                trivy_result.stdout, document_name=f"{target_name} Trivy output"
            )
            trivy_path = config.artifacts_dir / f"{target_name}.trivy.json"
            atomic_write_json(trivy_path, trivy_payload)
            findings.extend(parse_trivy(trivy_payload, source=source, target=image))
            receipt["artifacts"][target_name] = {
                "image": image,
                "sbom": file_identity(sbom_path),
                "sbom_format": "CycloneDX",
                "component_count": component_count,
                "vulnerability_scan": file_identity(trivy_path),
            }

        findings = sorted(
            findings,
            key=lambda item: (
                -SEVERITY_RANK[item.effective_severity],
                item.source,
                item.vulnerability_id,
                item.package,
            ),
        )
        waiver_by_finding = {waiver.finding_key: waiver for waiver in waivers}
        threshold_rank = SEVERITY_RANK[config.severity_threshold]
        applicable = [
            finding
            for finding in findings
            if SEVERITY_RANK[finding.effective_severity] >= threshold_rank
        ]
        applied: list[Waiver] = []
        blocking: list[Finding] = []
        finding_rows: list[dict[str, object]] = []
        for finding in findings:
            waiver = waiver_by_finding.get(finding.key)
            waiver_applies = waiver is not None and waiver.severity == finding.severity
            if waiver_applies:
                applied.append(waiver)
            if finding in applicable and not waiver_applies:
                blocking.append(finding)
            row: dict[str, object] = finding.receipt_value()
            row["at_or_above_threshold"] = finding in applicable
            row["waiver_id"] = waiver.waiver_id if waiver_applies else None
            finding_rows.append(row)

        applied_ids = {waiver.waiver_id for waiver in applied}
        receipt["findings"] = finding_rows
        receipt["waivers"] = {
            "configured": len(waivers),
            "applied": [waiver.receipt_value() for waiver in applied],
            "unused": [
                waiver.receipt_value() for waiver in waivers if waiver.waiver_id not in applied_ids
            ],
        }
        receipt["summary"] = {
            "total": len(findings),
            "at_or_above_threshold": len(applicable),
            "waived": len(applied),
            "blocking": len(blocking),
            "by_effective_severity": {
                severity: sum(1 for item in findings if item.effective_severity == severity)
                for severity in ("CRITICAL", "HIGH", "MEDIUM", "LOW")
            },
        }
        if blocking:
            receipt["status"] = "failed" if config.flagship else "advisory_findings"
            receipt["gate_passed"] = False
            exit_code = 1 if config.flagship else 0
        else:
            receipt["status"] = "pass"
            receipt["gate_passed"] = True
    except SecurityValidationError as exc:
        exit_code = 2
        receipt["status"] = "failed"
        receipt["error"] = {"type": type(exc).__name__, "message": str(exc)}
    except ScannerExecutionError as exc:
        if config.flagship:
            exit_code = 2
            receipt["status"] = "failed"
        else:
            exit_code = 0
            receipt["status"] = "advisory_unavailable"
        receipt["error"] = {"type": type(exc).__name__, "message": str(exc)}
    except Exception:
        exit_code = 2 if config.flagship else 0
        receipt["status"] = "failed" if config.flagship else "advisory_unavailable"
        receipt["error"] = {
            "type": "UnexpectedSecurityGateError",
            "message": "unexpected security-gate failure; scanner output was withheld",
        }
    finally:
        receipt["completed_at"] = isoformat(utc_now())
        atomic_write_json(
            config.receipt_path,
            receipt,
            overwrite=config.overwrite_receipt,
        )
    return receipt, exit_code


def default_output_paths(release_sha: str) -> tuple[Path, Path]:
    identity = release_sha if GIT_SHA_RE.fullmatch(str(release_sha or "")) else "invalid-release"
    root = APP_ROOT / "_completion" / "propertyquarry_release_security" / identity
    return root / "artifacts", root / "receipt.json"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Gate a digest-pinned PropertyQuarry release with preinstalled scanners."
    )
    parser.add_argument("--release-sha", required=True)
    parser.add_argument("--web-image", required=True)
    parser.add_argument("--render-image", required=True)
    parser.add_argument(
        "--severity-threshold",
        required=True,
        choices=("LOW", "MEDIUM", "HIGH", "CRITICAL"),
    )
    parser.add_argument("--flagship", action="store_true")
    parser.add_argument("--waivers", type=Path, default=DEFAULT_WAIVERS_PATH)
    parser.add_argument("--artifacts-dir", type=Path, default=None)
    parser.add_argument("--receipt", type=Path, default=None)
    parser.add_argument("--timeout-seconds", type=int, default=900)
    parser.add_argument("--overwrite-receipt", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    default_artifacts, default_receipt = default_output_paths(args.release_sha)
    config = GateConfig(
        release_commit_sha=args.release_sha,
        web_image=args.web_image,
        render_image=args.render_image,
        severity_threshold=args.severity_threshold,
        flagship=args.flagship,
        waivers_path=args.waivers,
        artifacts_dir=args.artifacts_dir or default_artifacts,
        receipt_path=args.receipt or default_receipt,
        timeout_seconds=args.timeout_seconds,
        overwrite_receipt=args.overwrite_receipt,
    )
    try:
        receipt, exit_code = run_security_gate(config=config)
    except SecurityValidationError as exc:
        print(f"PropertyQuarry security receipt error: {exc}", file=sys.stderr)
        return 2
    print(
        json.dumps(
            {"status": receipt.get("status"), "receipt": str(config.receipt_path)},
            sort_keys=True,
        )
    )
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())

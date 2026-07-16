#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.propertyquarry_live_http_security import validated_live_base_origin  # noqa: E402
from scripts.verify_generated_release_artifacts_clean import (  # noqa: E402
    RELEASE_MANIFEST_FIELDS,
    RELEASE_MANIFEST_PATH,
    load_release_manifest,
    release_manifest_sha256,
)


_FULL_GIT_SHA_PATTERN = re.compile(r"[0-9a-f]{40}")
_SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")
_IMAGE_DIGEST_PATTERN = re.compile(r"sha256:[0-9a-f]{64}")
_IMAGE_REFERENCE_PATTERN = re.compile(r"[^\s@]+@sha256:[0-9a-fA-F]{64}")
_REPLICA_ID_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}")
_SECURITY_RECEIPT_SCHEMA = "propertyquarry.release_security_receipt.v1"
_SECURITY_WORKFLOW_BINDING_CONTRACT = "propertyquarry.workflow_runtime_binding"
_REQUIRED_SECURITY_TOOLS = frozenset({"pip-audit", "syft", "trivy"})
_MAX_VERSION_BYTES = 200_000
_MAX_SECURITY_DOCUMENT_BYTES = 2_000_000
_MAX_SECURITY_ARTIFACT_BYTES = 100_000_000


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        return None


def _strict_json_object(raw: bytes, *, error_code: str) -> dict[str, Any]:
    def reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"{error_code}_duplicate_key")
            result[key] = value
        return result

    try:
        payload = json.loads(raw.decode("utf-8"), object_pairs_hook=reject_duplicate_keys)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{error_code}_invalid_json") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"{error_code}_root_not_object")
    return payload


def _read_stable_regular_bytes(path: Path, *, max_bytes: int, error_code: str) -> bytes:
    try:
        before = os.stat(path, follow_symlinks=False)
    except OSError as exc:
        raise ValueError(f"{error_code}_missing") from exc
    if not stat.S_ISREG(before.st_mode):
        raise ValueError(f"{error_code}_not_regular")
    if before.st_size < 1 or before.st_size > max_bytes:
        raise ValueError(f"{error_code}_size_invalid")

    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise ValueError(f"{error_code}_open_failed") from exc
    try:
        opened = os.fstat(descriptor)
        if (
            not stat.S_ISREG(opened.st_mode)
            or opened.st_dev != before.st_dev
            or opened.st_ino != before.st_ino
        ):
            raise ValueError(f"{error_code}_identity_changed")
        chunks: list[bytes] = []
        total = 0
        while True:
            chunk = os.read(descriptor, min(1_048_576, max_bytes + 1 - total))
            if not chunk:
                break
            chunks.append(chunk)
            total += len(chunk)
            if total > max_bytes:
                raise ValueError(f"{error_code}_size_invalid")
        after = os.fstat(descriptor)
    finally:
        os.close(descriptor)
    if (
        after.st_dev != opened.st_dev
        or after.st_ino != opened.st_ino
        or after.st_size != opened.st_size
        or after.st_mtime_ns != opened.st_mtime_ns
        or total != after.st_size
    ):
        raise ValueError(f"{error_code}_changed_during_read")
    return b"".join(chunks)


def _parse_timestamp(value: object, *, error_code: str) -> datetime:
    raw = str(value or "").strip()
    if not raw:
        raise ValueError(f"{error_code}_missing")
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{error_code}_invalid") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{error_code}_timezone_missing")
    return parsed.astimezone(timezone.utc)


def _bounded_text(value: object, *, error_code: str, max_length: int = 256) -> str:
    normalized = str(value or "").strip()
    if not normalized or len(normalized) > max_length or any(ord(char) < 32 for char in normalized):
        raise ValueError(f"{error_code}_invalid")
    return normalized


def _normalize_image_reference(value: object, *, error_code: str) -> str:
    normalized = str(value or "").strip()
    if _IMAGE_REFERENCE_PATTERN.fullmatch(normalized) is None:
        raise ValueError(f"{error_code}_invalid")
    repository, digest = normalized.rsplit("@", 1)
    return f"{repository}@{digest.lower()}"


def _file_identity_matches(
    identity: object,
    *,
    local_path: Path,
    expected_name: str,
    error_code: str,
    max_bytes: int = _MAX_SECURITY_ARTIFACT_BYTES,
) -> bool:
    if not isinstance(identity, dict) or set(identity) != {"path", "bytes", "sha256"}:
        raise ValueError(f"{error_code}_identity_invalid")
    recorded_path = str(identity.get("path") or "").strip()
    if not recorded_path or Path(recorded_path).name != expected_name:
        raise ValueError(f"{error_code}_name_mismatch")
    recorded_bytes = identity.get("bytes")
    if type(recorded_bytes) is not int or recorded_bytes < 1:  # noqa: E721
        raise ValueError(f"{error_code}_bytes_invalid")
    recorded_sha = str(identity.get("sha256") or "").strip().lower()
    if _SHA256_PATTERN.fullmatch(recorded_sha) is None:
        raise ValueError(f"{error_code}_sha256_invalid")
    raw = _read_stable_regular_bytes(local_path, max_bytes=max_bytes, error_code=error_code)
    if len(raw) != recorded_bytes or hashlib.sha256(raw).hexdigest() != recorded_sha:
        raise ValueError(f"{error_code}_content_mismatch")
    return True


def _verify_security_bundle(
    *,
    security_receipt_path: Path,
    security_workflow_binding_path: Path,
    expected_commit_sha: str,
    expected_image_digest: str,
    expected_web_image: str,
    expected_render_image: str,
    expected_workflow_head_sha: str,
    expected_workflow_run_id: str,
    expected_workflow_run_attempt: str,
) -> dict[str, object]:
    receipt_path = security_receipt_path.expanduser().resolve(strict=False)
    binding_path = security_workflow_binding_path.expanduser().resolve(strict=False)
    if receipt_path.parent != binding_path.parent:
        raise ValueError("security_bundle_parent_mismatch")

    receipt_raw = _read_stable_regular_bytes(
        receipt_path,
        max_bytes=_MAX_SECURITY_DOCUMENT_BYTES,
        error_code="security_receipt",
    )
    binding_raw = _read_stable_regular_bytes(
        binding_path,
        max_bytes=_MAX_SECURITY_DOCUMENT_BYTES,
        error_code="security_workflow_binding",
    )
    receipt = _strict_json_object(receipt_raw, error_code="security_receipt")
    binding = _strict_json_object(binding_raw, error_code="security_workflow_binding")

    required_receipt_fields = {
        "schema",
        "generated_at",
        "completed_at",
        "mode",
        "status",
        "gate_passed",
        "severity_threshold",
        "identities",
        "network_contract",
        "tools",
        "artifacts",
        "findings",
        "summary",
        "waivers",
    }
    if not required_receipt_fields.issubset(receipt):
        raise ValueError("security_receipt_fields_incomplete")
    if receipt.get("schema") != _SECURITY_RECEIPT_SCHEMA:
        raise ValueError("security_receipt_schema_mismatch")
    if receipt.get("mode") != "flagship" or receipt.get("status") != "pass":
        raise ValueError("security_receipt_not_flagship_pass")
    if receipt.get("gate_passed") is not True or receipt.get("severity_threshold") != "HIGH":
        raise ValueError("security_receipt_gate_not_verified")
    generated_at = _parse_timestamp(receipt.get("generated_at"), error_code="security_generated_at")
    completed_at = _parse_timestamp(receipt.get("completed_at"), error_code="security_completed_at")
    if completed_at < generated_at:
        raise ValueError("security_receipt_time_order_invalid")
    if receipt.get("network_contract") != {
        "scanner_install_allowed": False,
        "registry_access_allowed": False,
        "image_source": "local_docker_digest_only",
        "trivy_database_updates_allowed": False,
    }:
        raise ValueError("security_receipt_network_contract_invalid")
    if not isinstance(receipt.get("findings"), list):
        raise ValueError("security_receipt_findings_invalid")
    waivers = receipt.get("waivers")
    if (
        not isinstance(waivers, dict)
        or not {"configured", "applied", "unused"}.issubset(waivers)
        or type(waivers.get("configured")) is not int  # noqa: E721
        or not isinstance(waivers.get("applied"), list)
        or not isinstance(waivers.get("unused"), list)
    ):
        raise ValueError("security_receipt_waivers_invalid")

    identities = receipt.get("identities")
    if not isinstance(identities, dict):
        raise ValueError("security_receipt_identities_invalid")
    if str(identities.get("release_commit_sha") or "").strip().lower() != expected_commit_sha:
        raise ValueError("security_receipt_commit_mismatch")
    if str(identities.get("web_image") or "").strip() != expected_web_image:
        raise ValueError("security_receipt_web_image_mismatch")
    if str(identities.get("render_image") or "").strip() != expected_render_image:
        raise ValueError("security_receipt_render_image_mismatch")
    if expected_web_image.rsplit("@", 1)[-1].lower() != expected_image_digest:
        raise ValueError("security_receipt_live_image_digest_mismatch")
    _file_identity_matches(
        identities.get("dependency_lock"),
        local_path=ROOT / "ea" / "requirements.lock",
        expected_name="requirements.lock",
        error_code="security_dependency_lock",
    )

    tools = receipt.get("tools")
    if not isinstance(tools, dict) or set(tools) != _REQUIRED_SECURITY_TOOLS:
        raise ValueError("security_receipt_tools_incomplete")
    for tool_name in sorted(_REQUIRED_SECURITY_TOOLS):
        tool = tools.get(tool_name)
        if not isinstance(tool, dict) or tool.get("available") is not True:
            raise ValueError("security_receipt_tool_unverified")
        _bounded_text(tool.get("version"), error_code="security_tool_version", max_length=80)
        output_identity = tool.get("version_output")
        if not isinstance(output_identity, dict) or set(output_identity) != {"bytes", "sha256"}:
            raise ValueError("security_tool_version_identity_invalid")
        if type(output_identity.get("bytes")) is not int or int(output_identity["bytes"]) < 1:  # noqa: E721
            raise ValueError("security_tool_version_identity_invalid")
        if _SHA256_PATTERN.fullmatch(str(output_identity.get("sha256") or "").lower()) is None:
            raise ValueError("security_tool_version_identity_invalid")

    summary = receipt.get("summary")
    if not isinstance(summary, dict) or summary.get("blocking") != 0:
        raise ValueError("security_receipt_blocking_findings")
    artifacts = receipt.get("artifacts")
    if not isinstance(artifacts, dict) or set(artifacts) != {"dependencies", "web", "render"}:
        raise ValueError("security_receipt_artifacts_incomplete")
    artifact_root = receipt_path.parent / "artifacts"
    _file_identity_matches(
        artifacts.get("dependencies"),
        local_path=artifact_root / "dependencies.pip-audit.json",
        expected_name="dependencies.pip-audit.json",
        error_code="security_dependencies_artifact",
    )
    for target, expected_image in (("web", expected_web_image), ("render", expected_render_image)):
        target_receipt = artifacts.get(target)
        expected_keys = {"image", "sbom", "sbom_format", "component_count", "vulnerability_scan"}
        if not isinstance(target_receipt, dict) or set(target_receipt) != expected_keys:
            raise ValueError(f"security_{target}_artifact_incomplete")
        if target_receipt.get("image") != expected_image or target_receipt.get("sbom_format") != "CycloneDX":
            raise ValueError(f"security_{target}_artifact_identity_mismatch")
        if type(target_receipt.get("component_count")) is not int or int(target_receipt["component_count"]) < 1:  # noqa: E721
            raise ValueError(f"security_{target}_component_count_invalid")
        _file_identity_matches(
            target_receipt.get("sbom"),
            local_path=artifact_root / f"{target}.sbom.cdx.json",
            expected_name=f"{target}.sbom.cdx.json",
            error_code=f"security_{target}_sbom",
        )
        _file_identity_matches(
            target_receipt.get("vulnerability_scan"),
            local_path=artifact_root / f"{target}.trivy.json",
            expected_name=f"{target}.trivy.json",
            error_code=f"security_{target}_scan",
        )

    expected_binding_keys = {
        "contract_name",
        "version",
        "product",
        "runtime_commit_sha",
        "workflow_head_sha",
        "run_id",
        "run_attempt",
    }
    if set(binding) != expected_binding_keys:
        raise ValueError("security_workflow_binding_incomplete")
    binding_expected = {
        "contract_name": _SECURITY_WORKFLOW_BINDING_CONTRACT,
        "version": 1,
        "product": "PropertyQuarry",
        "runtime_commit_sha": expected_commit_sha,
        "workflow_head_sha": expected_workflow_head_sha,
        "run_id": expected_workflow_run_id,
        "run_attempt": expected_workflow_run_attempt,
    }
    if binding != binding_expected:
        raise ValueError("security_workflow_binding_mismatch")

    return {
        "verified": True,
        "receipt_sha256": hashlib.sha256(receipt_raw).hexdigest(),
        "workflow_binding_sha256": hashlib.sha256(binding_raw).hexdigest(),
        "release_commit_sha": expected_commit_sha,
        "release_image_digest": expected_image_digest,
        "web_image": expected_web_image,
        "render_image": expected_render_image,
        "workflow_head_sha": expected_workflow_head_sha,
        "workflow_run_id": expected_workflow_run_id,
        "workflow_run_attempt": expected_workflow_run_attempt,
    }


def _base_receipt(
    *,
    generated_at: str,
    status: str,
    base_url: str,
    expected: dict[str, str],
    checks: list[dict[str, object]],
) -> dict[str, object]:
    return {
        "contract_name": "propertyquarry.live_release_provenance.v2",
        "generated_at": generated_at,
        "status": status,
        "base_url": base_url,
        "expected": expected,
        "failed_count": sum(1 for check in checks if not bool(check.get("ok"))),
        "checks": checks,
    }


def build_live_release_provenance_receipt(
    *,
    base_url: str,
    expected_commit_sha: str,
    expected_repository: str = "",
    expected_public_origin: str = "",
    expected_branch: str = "main",
    expected_deployment_id: str = "",
    expected_artifact_set: str = "",
    expected_release_label: str = "",
    expected_release_generated_at: str = "",
    expected_image_digest: str = "",
    expected_replica_id: str = "",
    expected_web_image: str = "",
    expected_render_image: str = "",
    security_receipt_path: Path | str = "",
    security_workflow_binding_path: Path | str = "",
    expected_workflow_head_sha: str = "",
    expected_workflow_run_id: str = "",
    expected_workflow_run_attempt: str = "",
    release_manifest_path: Path | str = ROOT / RELEASE_MANIFEST_PATH,
    timeout_seconds: float = 15.0,
) -> dict[str, object]:
    generated_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    checks: list[dict[str, object]] = []
    expected: dict[str, str] = {}
    try:
        manifest = load_release_manifest(Path(release_manifest_path))
        manifest_sha256 = release_manifest_sha256(manifest)
        origin = validated_live_base_origin(base_url)
        expected_origin = validated_live_base_origin(expected_public_origin)
        manifest_origin = validated_live_base_origin(manifest["release_public_origin"])
        expected_sha = str(expected_commit_sha or "").strip().lower()
        expected_head_sha = str(expected_workflow_head_sha or "").strip().lower()
        expected_image = str(expected_image_digest or "").strip().lower()
        supplied_manifest_values = {
            "release_repository": _bounded_text(expected_repository, error_code="expected_repository"),
            "release_public_origin": expected_origin,
            "release_branch": _bounded_text(expected_branch, error_code="expected_branch"),
            "release_commit_sha": expected_sha,
            "release_deployment_id": _bounded_text(expected_deployment_id, error_code="expected_deployment_id"),
            "release_artifact_set": _bounded_text(expected_artifact_set, error_code="expected_artifact_set"),
            "release_label": _bounded_text(expected_release_label, error_code="expected_release_label"),
            "release_generated_at": _bounded_text(
                expected_release_generated_at,
                error_code="expected_release_generated_at",
            ),
        }
        expected.update(manifest)
        expected["release_manifest_sha256"] = manifest_sha256
        expected["release_image_digest"] = expected_image
        expected["replica_id"] = _bounded_text(
            expected_replica_id,
            error_code="expected_replica_id",
            max_length=128,
        )
        manifest_mismatches = sorted(
            key
            for key, supplied_value in supplied_manifest_values.items()
            if supplied_value != manifest.get(key)
        )
        if manifest_mismatches:
            raise ValueError(
                "expected_release_manifest_mismatch:"
                + ",".join(manifest_mismatches)
            )
        if origin != expected_origin or origin != manifest_origin:
            raise ValueError("expected_public_origin_differs_from_probe_origin")
        if _FULL_GIT_SHA_PATTERN.fullmatch(expected_sha) is None:
            raise ValueError("expected_commit_sha_invalid")
        if _FULL_GIT_SHA_PATTERN.fullmatch(expected_head_sha) is None:
            raise ValueError("expected_workflow_head_sha_invalid")
        if _IMAGE_DIGEST_PATTERN.fullmatch(expected_image) is None:
            raise ValueError("expected_image_digest_invalid")
        if _REPLICA_ID_PATTERN.fullmatch(expected["replica_id"]) is None:
            raise ValueError("expected_replica_id_invalid")
        _parse_timestamp(
            manifest["release_generated_at"],
            error_code="expected_release_generated_at",
        )
        web_image = _normalize_image_reference(expected_web_image, error_code="expected_web_image")
        render_image = _normalize_image_reference(expected_render_image, error_code="expected_render_image")
        if render_image == web_image:
            raise ValueError("expected_render_image_invalid")
        run_id = _bounded_text(expected_workflow_run_id, error_code="expected_workflow_run_id", max_length=64)
        run_attempt = _bounded_text(
            expected_workflow_run_attempt,
            error_code="expected_workflow_run_attempt",
            max_length=32,
        )
        if not run_id.isdigit() or not run_attempt.isdigit():
            raise ValueError("expected_workflow_identity_invalid")
        checks.append({"name": "expected_release_identity_complete", "ok": True})
    except ValueError as exc:
        checks.append({"name": "expected_release_identity_complete", "ok": False, "reason": str(exc)})
        return _base_receipt(
            generated_at=generated_at,
            status="blocked",
            base_url=str(base_url or ""),
            expected=expected,
            checks=checks,
        )

    try:
        security_binding = _verify_security_bundle(
            security_receipt_path=Path(security_receipt_path),
            security_workflow_binding_path=Path(security_workflow_binding_path),
            expected_commit_sha=expected_sha,
            expected_image_digest=expected_image,
            expected_web_image=web_image,
            expected_render_image=render_image,
            expected_workflow_head_sha=expected_head_sha,
            expected_workflow_run_id=run_id,
            expected_workflow_run_attempt=run_attempt,
        )
        checks.append({"name": "security_receipt_binding_verified", "ok": True})
    except (OSError, ValueError) as exc:
        checks.append({"name": "security_receipt_binding_verified", "ok": False, "reason": str(exc)})
        return _base_receipt(
            generated_at=generated_at,
            status="blocked",
            base_url=origin,
            expected=expected,
            checks=checks,
        )

    request = urllib.request.Request(
        f"{origin}/version",
        headers={
            "Accept": "application/json",
            "User-Agent": "PropertyQuarry-live-release-provenance/2.0",
        },
        method="GET",
    )
    opener = urllib.request.build_opener(_NoRedirect)
    try:
        with opener.open(request, timeout=max(1.0, float(timeout_seconds))) as response:
            status_code = int(getattr(response, "status", 0) or 0)
            body = response.read(_MAX_VERSION_BYTES + 1)
    except urllib.error.HTTPError as exc:
        status_code = int(exc.code or 0)
        body = exc.read(_MAX_VERSION_BYTES + 1)
    except Exception as exc:
        checks.append({"name": "version_reachable", "ok": False, "reason": type(exc).__name__})
        receipt = _base_receipt(
            generated_at=generated_at,
            status="fail",
            base_url=origin,
            expected=expected,
            checks=checks,
        )
        receipt["security_receipt_binding"] = security_binding
        return receipt

    payload: dict[str, Any] = {}
    response_valid = len(body) <= _MAX_VERSION_BYTES
    if response_valid:
        try:
            payload = _strict_json_object(body, error_code="version_response")
        except ValueError:
            response_valid = False

    checks.extend(
        [
            {"name": "version_status_ok", "ok": status_code == 200, "status_code": status_code},
            {"name": "version_response_bounded_json_object", "ok": response_valid},
            {
                "name": "release_manifest_complete",
                "ok": payload.get("release_manifest_status") == "complete",
            },
        ]
    )
    actual: dict[str, str] = {}
    for key in (
        *RELEASE_MANIFEST_FIELDS,
        "release_manifest_sha256",
        "release_image_digest",
        "replica_id",
    ):
        value = str(payload.get(key) or "").strip()
        if key in {"release_commit_sha", "release_image_digest"}:
            value = value.lower()
        actual[key] = value
        checks.append({"name": f"{key}_matches", "ok": value == expected[key]})
    try:
        _parse_timestamp(actual["release_generated_at"], error_code="release_generated_at")
        actual_generated_at_valid = True
    except ValueError:
        actual_generated_at_valid = False
    checks.extend(
        [
            {
                "name": "release_commit_sha_full",
                "ok": _FULL_GIT_SHA_PATTERN.fullmatch(actual["release_commit_sha"]) is not None,
            },
            {
                "name": "release_image_digest_full",
                "ok": _IMAGE_DIGEST_PATTERN.fullmatch(actual["release_image_digest"]) is not None,
            },
            {
                "name": "replica_identity_valid",
                "ok": _REPLICA_ID_PATTERN.fullmatch(actual["replica_id"]) is not None,
            },
            {"name": "release_generated_at_valid", "ok": actual_generated_at_valid},
        ]
    )
    failed = [check for check in checks if not bool(check.get("ok"))]
    receipt = _base_receipt(
        generated_at=generated_at,
        status="pass" if not failed else "fail",
        base_url=origin,
        expected=expected,
        checks=checks,
    )
    receipt["actual"] = actual
    receipt["security_receipt_binding"] = security_binding
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Verify complete live PropertyQuarry provenance and its current-run security binding."
    )
    parser.add_argument(
        "--base-url",
        default=os.getenv("PROPERTYQUARRY_LIVE_MOBILE_BASE_URL")
        or os.getenv("PROPERTYQUARRY_LIVE_SMOKE_BASE_URL")
        or "",
    )
    parser.add_argument(
        "--expected-commit-sha",
        default=os.getenv("PROPERTYQUARRY_EXPECTED_RELEASE_COMMIT_SHA") or "",
    )
    parser.add_argument(
        "--expected-repository",
        default=os.getenv("PROPERTYQUARRY_EXPECTED_RELEASE_REPOSITORY") or "",
    )
    parser.add_argument(
        "--expected-public-origin",
        default=os.getenv("PROPERTYQUARRY_EXPECTED_RELEASE_PUBLIC_ORIGIN") or "",
    )
    parser.add_argument(
        "--expected-branch",
        default=os.getenv("PROPERTYQUARRY_EXPECTED_RELEASE_BRANCH") or "main",
    )
    parser.add_argument(
        "--expected-deployment-id",
        default=os.getenv("PROPERTYQUARRY_EXPECTED_RELEASE_DEPLOYMENT_ID") or "",
    )
    parser.add_argument(
        "--expected-artifact-set",
        default=os.getenv("PROPERTYQUARRY_EXPECTED_RELEASE_ARTIFACT_SET") or "",
    )
    parser.add_argument(
        "--expected-release-label",
        default=os.getenv("PROPERTYQUARRY_EXPECTED_RELEASE_LABEL") or "",
    )
    parser.add_argument(
        "--expected-release-generated-at",
        default=os.getenv("PROPERTYQUARRY_EXPECTED_RELEASE_GENERATED_AT") or "",
    )
    parser.add_argument(
        "--expected-image-digest",
        default=os.getenv("PROPERTYQUARRY_EXPECTED_RELEASE_IMAGE_DIGEST") or "",
    )
    parser.add_argument(
        "--expected-replica-id",
        default=os.getenv("PROPERTYQUARRY_EXPECTED_REPLICA_ID") or "",
    )
    parser.add_argument(
        "--expected-web-image",
        default=os.getenv("PROPERTYQUARRY_EXPECTED_WEB_IMAGE") or "",
    )
    parser.add_argument(
        "--expected-render-image",
        default=os.getenv("PROPERTYQUARRY_EXPECTED_RENDER_IMAGE") or "",
    )
    parser.add_argument(
        "--security-receipt",
        default=os.getenv("PROPERTYQUARRY_RELEASE_SECURITY_RECEIPT") or "",
    )
    parser.add_argument(
        "--security-workflow-binding",
        default=os.getenv("PROPERTYQUARRY_RELEASE_SECURITY_WORKFLOW_BINDING") or "",
    )
    parser.add_argument(
        "--expected-workflow-head-sha",
        default=os.getenv("PROPERTYQUARRY_WORKFLOW_HEAD_SHA") or "",
    )
    parser.add_argument(
        "--expected-workflow-run-id",
        default=os.getenv("PROPERTYQUARRY_WORKFLOW_RUN_ID") or "",
    )
    parser.add_argument(
        "--expected-workflow-run-attempt",
        default=os.getenv("PROPERTYQUARRY_WORKFLOW_RUN_ATTEMPT") or "",
    )
    parser.add_argument(
        "--release-manifest",
        default=str(ROOT / RELEASE_MANIFEST_PATH),
    )
    parser.add_argument("--timeout-seconds", type=float, default=15.0)
    parser.add_argument("--write", default="_completion/smoke/property-live-release-provenance.json")
    args = parser.parse_args()
    receipt = build_live_release_provenance_receipt(
        base_url=str(args.base_url or ""),
        expected_commit_sha=str(args.expected_commit_sha or ""),
        expected_repository=str(args.expected_repository or ""),
        expected_public_origin=str(args.expected_public_origin or ""),
        expected_branch=str(args.expected_branch or "main"),
        expected_deployment_id=str(args.expected_deployment_id or ""),
        expected_artifact_set=str(args.expected_artifact_set or ""),
        expected_release_label=str(args.expected_release_label or ""),
        expected_release_generated_at=str(args.expected_release_generated_at or ""),
        expected_image_digest=str(args.expected_image_digest or ""),
        expected_replica_id=str(args.expected_replica_id or ""),
        expected_web_image=str(args.expected_web_image or ""),
        expected_render_image=str(args.expected_render_image or ""),
        security_receipt_path=str(args.security_receipt or ""),
        security_workflow_binding_path=str(args.security_workflow_binding or ""),
        expected_workflow_head_sha=str(args.expected_workflow_head_sha or ""),
        expected_workflow_run_id=str(args.expected_workflow_run_id or ""),
        expected_workflow_run_attempt=str(args.expected_workflow_run_attempt or ""),
        release_manifest_path=str(args.release_manifest or ""),
        timeout_seconds=float(args.timeout_seconds),
    )
    output = json.dumps(receipt, indent=2, sort_keys=True)
    if args.write:
        output_path = Path(args.write)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(output + "\n", encoding="utf-8")
    print(output)
    return 0 if receipt.get("status") == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())

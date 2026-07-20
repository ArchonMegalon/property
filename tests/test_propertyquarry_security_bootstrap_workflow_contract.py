from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]


def _workflow(path: str) -> tuple[str, dict[str, object]]:
    body = (ROOT / path).read_text(encoding="utf-8")
    payload = yaml.load(body, Loader=yaml.BaseLoader)
    assert isinstance(payload, dict)
    return body, payload


def test_bootstrap_artifact_is_exact_target_job_addressed() -> None:
    body, workflow = _workflow(
        ".github/workflows/propertyquarry-security-runner-bootstrap.yml"
    )
    triggers = workflow["on"]
    assert isinstance(triggers, dict)
    assert set(triggers) == {"workflow_dispatch"}
    bootstrap = workflow["jobs"]["bootstrap"]
    steps = bootstrap["steps"]
    target = next(step for step in steps if step.get("id") == "target")
    assert "security_run_attempt" in target["run"]
    assert "security_job_id" in target["run"]
    upload = next(
        step
        for step in steps
        if str(step.get("uses", "")).startswith("actions/upload-artifact@")
    )
    artifact_name = upload["with"]["name"]
    assert artifact_name == (
        "propertyquarry-security-runner-bootstrap-target-"
        "${{ steps.target.outputs.security_run_id }}-"
        "${{ steps.target.outputs.security_run_attempt }}-"
        "${{ steps.target.outputs.security_job_id }}"
    )
    assert "propertyquarry.security_runner_receipt_manifest.v1" in body
    assert "preflight-${PQ_SECURITY_RUN_ID}-${PQ_SECURITY_RUN_ATTEMPT}.json" in body
    assert "timeout --signal=TERM --kill-after=5s 30s" in body
    assert "gh api --method GET" in body
    assert "--paginate --slurp" in body
    assert "after three attempts" in body
    assert "workflow_run" not in triggers
    assert "workflow_call" not in triggers


def test_bootstrap_workflow_hash_binds_the_reviewed_script() -> None:
    body = (
        ROOT / ".github/workflows/propertyquarry-security-runner-bootstrap.yml"
    ).read_text(encoding="utf-8")
    digest = hashlib.sha256(
        (ROOT / "scripts/propertyquarry_security_runner_bootstrap.sh").read_bytes()
    ).hexdigest()
    assert f"'{digest}'" in body


def test_release_requires_least_privilege_github_hosted_attestation() -> None:
    body, workflow = _workflow(".github/workflows/smoke-runtime.yml")
    dispatch = workflow["on"]["workflow_dispatch"]
    inputs = dispatch["inputs"]
    expiry = inputs["security_runner_token_expires_at"]
    assert expiry["required"] == "true"
    protected = workflow["jobs"]["propertyquarry-protected-dispatch-inputs"]
    assert "security_runner_token_expires_at" in protected["outputs"]

    jobs = workflow["jobs"]
    attestation = jobs["propertyquarry-security-bootstrap-attestation"]
    assert attestation["runs-on"] == "ubuntu-24.04"
    assert attestation["permissions"] == {"actions": "read", "contents": "read"}
    assert set(attestation["needs"]) == {
        "propertyquarry-protected-dispatch-inputs",
        "propertyquarry-flagship-security",
    }
    assert "environment" not in attestation
    attestation_text = json.dumps(attestation, sort_keys=True)
    assert "id-token" not in attestation_text
    assert "secrets." not in attestation_text
    assert "self-hosted" not in str(attestation["runs-on"])
    assert "verify_propertyquarry_security_bootstrap_attestation.py" in attestation_text
    assert "actions/download-artifact@" not in attestation_text
    assert attestation["timeout-minutes"] == "15"
    run_steps = [step for step in attestation["steps"] if "run" in step]
    assert run_steps
    assert all(step["run"].lstrip().startswith("set -Eeuo pipefail") for step in run_steps)
    assert all(
        re.fullmatch(r"[^@]+@[0-9a-f]{40}", step["uses"])
        for step in attestation["steps"]
        if "uses" in step
    )
    resolve_run = next(
        step["run"] for step in attestation["steps"] if step.get("id") == "resolve"
    )
    assert "timeout --signal=TERM --kill-after=5s 30s" in resolve_run
    assert resolve_run.count("--paginate --slurp") >= 2
    assert "capture-json" in resolve_run
    assert 'capture_api_json "${target_jobs_path}" 8388608' in resolve_run
    assert 'deadline="$((SECONDS + 600))"' in resolve_run
    assert "selection_count > 1" in resolve_run
    assert "selection_count == 1" in resolve_run
    assert "artifact_id" in resolve_run
    download_run = next(
        step["run"]
        for step in attestation["steps"]
        if step.get("name")
        == "Download, authenticate, and safely extract the exact artifact ID"
    )
    assert (
        "repos/${GITHUB_REPOSITORY}/actions/artifacts/${ARTIFACT_ID}/zip"
        in download_run
    )
    assert "capture-archive" in download_run
    assert '--expected-digest "${EXPECTED_ARTIFACT_DIGEST}"' in download_run
    assert "extract-archive" in download_run
    assert "--max-entries 64" in download_run
    verify_run = next(
        step["run"] for step in attestation["steps"] if step.get("id") == "verify"
    )
    assert (
        "verify_propertyquarry_security_bootstrap_attestation.py verify"
        in verify_run
    )
    assert "set -x" not in attestation_text
    assert "printf 'GH_TOKEN" not in attestation_text

    flagship = jobs["propertyquarry-flagship-security"]
    assert "propertyquarry-security-bootstrap-attestation" not in flagship["needs"]
    release = jobs["propertyquarry-release-v2"]
    assert "propertyquarry-security-bootstrap-attestation" in release["needs"]
    assert (
        "needs['propertyquarry-security-bootstrap-attestation'].result == 'success'"
        in release["if"]
    )
    assert (
        "needs['propertyquarry-security-bootstrap-attestation'].outputs.attestation_sha256"
        in release["env"]["PROPERTYQUARRY_SECURITY_BOOTSTRAP_ATTESTATION_SHA256"]
    )
    requested = jobs["propertyquarry-requested-action-result"]
    assert "propertyquarry-security-bootstrap-attestation" in requested["needs"]
    assert "propertyquarry-security-bootstrap-attestation" in body
    triggers = workflow["on"]
    assert "workflow_run" not in triggers
    assert "workflow_call" not in triggers


def test_repository_authority_docs_describe_the_structural_bootstrap_gate() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")

    assert (
        "structurally gates `propertyquarry-release-v2` on the same-run "
        "`propertyquarry-security-bootstrap-attestation` job"
    ) in readme
    assert "binds its attestation SHA-256, bootstrap run ID, and artifact digest" in readme
    assert "bootstrap-consumption evidence is made an explicit" not in readme
    assert "standalone release authority" in readme


def test_run_blocks_never_interpolate_dispatch_inputs_or_event_payloads() -> None:
    unsafe_expression = re.compile(
        r"\$\{\{\s*(?:inputs(?:\.|\[)|github\.event(?:_name|\.|\[))"
    )
    for path in (
        ".github/workflows/propertyquarry-security-runner-bootstrap.yml",
        ".github/workflows/smoke-runtime.yml",
    ):
        _body, workflow = _workflow(path)
        for job_name, job in workflow["jobs"].items():
            for index, step in enumerate(job.get("steps", [])):
                run = step.get("run")
                if run is not None:
                    assert unsafe_expression.search(run) is None, (
                        f"unsafe direct expression in {path}:{job_name}:step-{index}"
                    )


def test_expiry_is_canonical_utc_before_use_or_output() -> None:
    bootstrap_body, _bootstrap = _workflow(
        ".github/workflows/propertyquarry-security-runner-bootstrap.yml"
    )
    smoke_body, _smoke = _workflow(".github/workflows/smoke-runtime.yml")

    assert "%Y-%m-%dT%H:%M:%SZ" in bootstrap_body
    assert "canonical_token_expires_at" in bootstrap_body
    assert "security_runner_token_expires_at" in bootstrap_body
    assert "datetime.strptime" in smoke_body
    assert "canonical_token_expires_at" in smoke_body
    assert "%Y-%m-%dT%H:%M:%SZ" in smoke_body


def test_attestation_selects_one_artifact_then_downloads_only_its_id() -> None:
    _body, workflow = _workflow(".github/workflows/smoke-runtime.yml")
    attestation = workflow["jobs"]["propertyquarry-security-bootstrap-attestation"]
    resolve_run = next(
        step["run"] for step in attestation["steps"] if step.get("id") == "resolve"
    )
    download_run = next(
        step["run"]
        for step in attestation["steps"]
        if step.get("name")
        == "Download, authenticate, and safely extract the exact artifact ID"
    )

    assert "selection_count > 1" in resolve_run
    assert "selection_count == 1" in resolve_run
    assert "workflow_run.id" in resolve_run
    assert resolve_run.count("actions/artifacts?per_page=100&name=") == 1
    assert download_run.count("actions/artifacts/${ARTIFACT_ID}/zip") == 1
    assert "artifact_name" not in download_run

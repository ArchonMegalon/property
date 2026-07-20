from __future__ import annotations

import base64
import hashlib
import json
import os
import shutil
import stat
import subprocess
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import pytest

from scripts import build_private_magicfit_review_evidence as private_review
from scripts import property_magicfit_secure_io as magicfit_secure_io
from scripts.accept_magicfit_delivery import (
    REVIEW_CHECKS,
    _validate_browser_receipt,
    _validate_evidence,
)
from scripts.build_private_magicfit_review_evidence import (
    BROWSER_RECEIPT_CONTRACT,
    EVIDENCE_CONTRACT,
    REVIEW_PAGE_ROUTE,
    VISUAL_REVIEW_CONTRACT,
    WORKER_MEMORY_MAX_BYTES,
    WORKER_TASKS_MAX,
    _capped_worker_command,
    _private_review_server,
    _require_worker_cgroup_limits,
    _visual_review,
    _write_private_file_exclusive,
)
from scripts.property_magicfit_delivery_contract import (
    REVIEW_RECEIPT_BUNDLE_CONTRACT,
)
from scripts.property_magicfit_secure_io import (
    MagicFitSecureIOError,
    load_magicfit_review_receipt_bundle,
    publish_magicfit_review_receipt_bundle,
)
from scripts.propertyquarry_playwright_runtime import (
    playwright_chromium_capture_available,
)


ROOT = Path(__file__).resolve().parents[1]
SLUG = "private-magicfit-review"
PNG_1X1 = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUB"
    "AScY42YAAAAASUVORK5CYII="
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _utc_now() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _write_video(path: Path) -> None:
    ffmpeg = shutil.which("ffmpeg")
    assert ffmpeg
    completed = subprocess.run(
        [
            ffmpeg,
            "-y",
            "-f",
            "lavfi",
            "-i",
            "color=c=black:s=64x36:d=1.2",
            "-pix_fmt",
            "yuv420p",
            "-movflags",
            "+faststart",
            str(path),
        ],
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr


def _fixture(root: Path) -> dict[str, Path]:
    private_root = root / "private"
    bundle = private_root / SLUG
    bundle.mkdir(parents=True)
    video = private_root / "magicfit-walkthrough.mp4"
    _write_video(video)
    source = private_root / "source-receipt.json"
    source.write_text(
        json.dumps(
            {
                "provider": "magicfit",
                "provider_key": "magicfit",
                "provider_backend_key": "magicfit",
                "render_status": "completed",
                "target_slug": SLUG,
                "output_file": str(video.resolve()),
                "hosted_walkthrough_video_url": (
                    "https://media.powlcdn.com/magicfit/private-review.mp4"
                ),
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    manifest = {
        "slug": SLUG,
        "display_title": "Private local review",
    }
    (bundle / "tour.json").write_text(json.dumps(manifest), encoding="utf-8")
    import_env = dict(os.environ)
    import_env["EA_PUBLIC_TOUR_DIR"] = str(private_root)
    import_env["PROPERTYQUARRY_TOUR_MIN_FREE_BYTES"] = "0"
    import_env["PROPERTYQUARRY_TOUR_LOCK_DIR"] = str(private_root / "import-locks")
    imported = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "import_magicfit_walkthrough.py"),
            "--slug",
            SLUG,
            "--video-path",
            str(video),
            "--source-receipt",
            str(source),
        ],
        cwd=ROOT,
        env=import_env,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert imported.returncode == 0, imported.stderr
    pending = json.loads(
        (bundle / "tour.magicfit.pending.json").read_text(encoding="utf-8")
    )
    generated_at = str(pending["generated_at"])
    delivery_digest = Path(pending["accepted_sidecar_relpath"]).stem
    contact = private_root / "contact-sheet.png"
    contact.write_bytes(PNG_1X1)
    visual = private_root / "visual-review.json"
    visual.write_text(
        json.dumps(
            {
                "schema": VISUAL_REVIEW_CONTRACT,
                "status": "pass",
                "provider": "magicfit",
                "target_slug": SLUG,
                "observed_at": generated_at,
                "video_sha256": _sha256(video),
                "base_manifest_sha256": pending["base_manifest_sha256"],
                "staged_manifest_sha256": pending["staged_manifest_sha256"],
                "delivery_digest": delivery_digest,
                "checklist": {key: True for key in sorted(REVIEW_CHECKS)},
            }
        ),
        encoding="utf-8",
    )
    review_bundle_root = private_root / "review-receipts"
    review_bundle_root.mkdir(mode=0o700)
    review_bundle = review_bundle_root / delivery_digest
    return {
        "private_root": private_root,
        "bundle": bundle,
        "video": video,
        "source": source,
        "contact": contact,
        "visual": visual,
        "review_bundle_root": review_bundle_root,
        "review_bundle": review_bundle,
        "browser": review_bundle / "browser-receipt.json",
        "evidence": review_bundle / "evidence-receipt.json",
        "bundle_manifest": review_bundle / "bundle-manifest.json",
        "browser_only": private_root / "browser-only.json",
        "public_root": root / "public-tours",
    }


def _command(
    paths: dict[str, Path],
    *,
    allow: bool = True,
    browser_only: bool = False,
) -> list[str]:
    command = [
        sys.executable,
        str(ROOT / "scripts" / "build_private_magicfit_review_evidence.py"),
    ]
    if allow:
        command.append("--allow-private-review")
    if browser_only:
        command.append("--browser-only")
    command.extend(
        [
            "--slug",
            SLUG,
            "--bundle-dir",
            str(paths["bundle"]),
            "--source-receipt",
            str(paths["source"]),
            "--timeout-seconds",
            "20",
        ]
    )
    if browser_only:
        command.extend(
            ("--browser-receipt-out", str(paths["browser_only"]))
        )
    else:
        command.extend(
            [
                "--contact-sheet",
                str(paths["contact"]),
                "--visual-review",
                str(paths["visual"]),
                "--review-bundle-root",
                str(paths["review_bundle_root"]),
            ]
        )
    return command


def _env(paths: dict[str, Path]) -> dict[str, str]:
    env = dict(os.environ)
    env["EA_PUBLIC_TOUR_DIR"] = str(paths["public_root"])
    env["PROPERTYQUARRY_TOUR_MIN_FREE_BYTES"] = "0"
    env["PROPERTYQUARRY_TOUR_LOCK_DIR"] = str(paths["private_root"] / "locks")
    return env


@pytest.mark.parametrize("failure_stage", ("chmod", "fsync", "close"))
def test_private_output_post_link_failure_is_removed_fsynced_and_retryable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure_stage: str,
) -> None:
    destination = tmp_path / "browser.json"
    original_chmod = Path.chmod
    original_fsync = private_review.os.fsync
    original_close = private_review.os.close
    failed = False
    synced: list[Path] = []
    original_fsync_directory = private_review._fsync_directory

    def fail_destination_chmod(path: Path, mode: int, *args: object, **kwargs: object) -> None:
        nonlocal failed
        if failure_stage == "chmod" and path == destination and not failed:
            failed = True
            raise OSError("injected post-link chmod failure")
        original_chmod(path, mode, *args, **kwargs)

    def fail_directory_fsync(descriptor: int) -> None:
        nonlocal failed
        if (
            failure_stage == "fsync"
            and stat.S_ISDIR(os.fstat(descriptor).st_mode)
            and not failed
        ):
            failed = True
            raise OSError("injected post-link fsync failure")
        original_fsync(descriptor)

    def fail_directory_close(descriptor: int) -> None:
        nonlocal failed
        if (
            failure_stage == "close"
            and stat.S_ISDIR(os.fstat(descriptor).st_mode)
            and not failed
        ):
            failed = True
            original_close(descriptor)
            raise OSError("injected post-link close failure")
        original_close(descriptor)

    def record_fsync(path: Path) -> None:
        synced.append(path)
        original_fsync_directory(path)

    monkeypatch.setattr(Path, "chmod", fail_destination_chmod)
    monkeypatch.setattr(private_review.os, "fsync", fail_directory_fsync)
    monkeypatch.setattr(private_review.os, "close", fail_directory_close)
    monkeypatch.setattr(private_review, "_fsync_directory", record_fsync)

    with pytest.raises(OSError, match=f"injected post-link {failure_stage} failure"):
        _write_private_file_exclusive(destination, b"first-attempt\n")

    assert not destination.exists()
    assert synced == [tmp_path] * (1 if failure_stage == "chmod" else 2)

    _write_private_file_exclusive(destination, b"retry-succeeded\n")
    assert destination.read_bytes() == b"retry-succeeded\n"
    assert destination.stat().st_mode & 0o777 == 0o600


def _receipt_bundle_publish_process(
    root: Path, digest: str, *, failpoint: str = ""
) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ)
    env.pop("PROPERTYQUARRY_MAGICFIT_REVIEW_BUNDLE_FAILPOINT", None)
    if failpoint:
        env["PROPERTYQUARRY_MAGICFIT_REVIEW_BUNDLE_FAILPOINT"] = failpoint
    program = (
        "import sys; from pathlib import Path; "
        "from scripts.property_magicfit_secure_io import "
        "publish_magicfit_review_receipt_bundle as publish; "
        "bundle=publish(Path(sys.argv[1]), delivery_digest=sys.argv[2], "
        "browser_receipt_bytes=b'{\"browser\":true}\\n', "
        "evidence_receipt_bytes=b'{\"evidence\":true}\\n'); "
        "print(bundle.delivery_digest)"
    )
    return subprocess.run(
        [sys.executable, "-c", program, str(root), digest],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )


@pytest.mark.parametrize(
    "failpoint",
    (
        "after_browser_receipt",
        "after_evidence_receipt",
        "after_bundle_manifest",
        "before_bundle_rename",
        "after_bundle_rename",
    ),
)
def test_review_receipt_bundle_crash_windows_are_atomic_and_retryable(
    tmp_path: Path, failpoint: str
) -> None:
    root = tmp_path / "receipts"
    root.mkdir(mode=0o700)
    digest = hashlib.sha256(failpoint.encode("utf-8")).hexdigest()

    interrupted = _receipt_bundle_publish_process(
        root, digest, failpoint=failpoint
    )

    assert interrupted.returncode == 86
    committed = root / digest
    temporary = root / ".magicfit-review-bundle.tmp"
    if failpoint == "after_bundle_rename":
        assert committed.is_dir()
        assert not temporary.exists()
    else:
        assert not committed.exists()
        assert temporary.is_dir()

    recovered = _receipt_bundle_publish_process(root, digest)
    assert recovered.returncode == 0, recovered.stderr
    assert recovered.stdout.strip() == digest
    loaded = load_magicfit_review_receipt_bundle(
        committed, expected_delivery_digest=digest
    )
    assert loaded.browser_receipt_bytes == b'{"browser":true}\n'
    assert loaded.evidence_receipt_bytes == b'{"evidence":true}\n'
    assert committed.stat().st_mode & 0o777 == 0o700
    assert not temporary.exists()
    assert {row.name for row in root.iterdir()} == {
        ".magicfit-review-bundles.lock",
        digest,
    }

    repeated = _receipt_bundle_publish_process(root, digest)
    assert repeated.returncode == 0, repeated.stderr
    assert repeated.stdout.strip() == digest
    assert {row.name for row in root.iterdir()} == {
        ".magicfit-review-bundles.lock",
        digest,
    }


def test_distinct_crashed_review_digests_keep_one_bounded_lock_and_temp(
    tmp_path: Path,
) -> None:
    root = tmp_path / "receipts"
    root.mkdir(mode=0o700)

    for index in range(12):
        digest = f"{index + 1:064x}"
        interrupted = _receipt_bundle_publish_process(
            root, digest, failpoint="after_browser_receipt"
        )
        assert interrupted.returncode == 86
        assert {row.name for row in root.iterdir()} == {
            ".magicfit-review-bundles.lock",
            ".magicfit-review-bundle.tmp",
        }

    final_digest = f"{12:064x}"
    recovered = _receipt_bundle_publish_process(root, final_digest)
    assert recovered.returncode == 0, recovered.stderr
    assert {row.name for row in root.iterdir()} == {
        ".magicfit-review-bundles.lock",
        final_digest,
    }


def test_review_receipt_bundle_concurrent_writers_commit_one_exact_directory(
    tmp_path: Path,
) -> None:
    root = tmp_path / "receipts"
    root.mkdir(mode=0o700)
    digest = "a" * 64
    env = dict(os.environ)
    env.pop("PROPERTYQUARRY_MAGICFIT_REVIEW_BUNDLE_FAILPOINT", None)
    program = (
        "import sys; from pathlib import Path; "
        "from scripts.property_magicfit_secure_io import "
        "publish_magicfit_review_receipt_bundle as publish; "
        "publish(Path(sys.argv[1]), delivery_digest=sys.argv[2], "
        "browser_receipt_bytes=b'browser\\n', "
        "evidence_receipt_bytes=b'evidence\\n')"
    )
    writers = [
        subprocess.Popen(
            [sys.executable, "-c", program, str(root), digest],
            cwd=ROOT,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        for _index in range(6)
    ]

    results = [writer.communicate(timeout=20) for writer in writers]

    assert [writer.returncode for writer in writers] == [0] * 6, results
    loaded = load_magicfit_review_receipt_bundle(
        root / digest, expected_delivery_digest=digest
    )
    assert loaded.browser_receipt_bytes == b"browser\n"
    assert loaded.evidence_receipt_bytes == b"evidence\n"
    assert {row.name for row in root.iterdir()} == {
        ".magicfit-review-bundles.lock",
        digest,
    }


def test_review_receipt_bundle_loader_rejects_missing_corrupt_symlink_and_wrong_digest(
    tmp_path: Path,
) -> None:
    root = tmp_path / "receipts"
    root.mkdir(mode=0o700)
    digest = "b" * 64
    with pytest.raises(MagicFitSecureIOError):
        load_magicfit_review_receipt_bundle(
            root / digest, expected_delivery_digest=digest
        )
    published = publish_magicfit_review_receipt_bundle(
        root,
        delivery_digest=digest,
        browser_receipt_bytes=b"browser\n",
        evidence_receipt_bytes=b"evidence\n",
    )

    with pytest.raises(MagicFitSecureIOError, match="path_digest_mismatch"):
        load_magicfit_review_receipt_bundle(
            published.path, expected_delivery_digest="c" * 64
        )

    evidence = published.path / "evidence-receipt.json"
    original_evidence = evidence.read_bytes()
    evidence.write_bytes(b"corrupt\n")
    evidence.chmod(0o600)
    with pytest.raises(MagicFitSecureIOError, match="artifact_digest_mismatch"):
        load_magicfit_review_receipt_bundle(
            published.path, expected_delivery_digest=digest
        )
    evidence.write_bytes(original_evidence)
    evidence.chmod(0o600)
    evidence.unlink()
    with pytest.raises(MagicFitSecureIOError):
        load_magicfit_review_receipt_bundle(
            published.path, expected_delivery_digest=digest
        )

    symlink_root = tmp_path / "symlink-receipts"
    symlink_root.mkdir(mode=0o700)
    (symlink_root / digest).symlink_to(published.path, target_is_directory=True)
    with pytest.raises(MagicFitSecureIOError):
        load_magicfit_review_receipt_bundle(
            symlink_root / digest, expected_delivery_digest=digest
        )


def test_review_receipt_bundle_recovery_never_deletes_unknown_temp_entries(
    tmp_path: Path,
) -> None:
    root = tmp_path / "receipts"
    root.mkdir(mode=0o700)
    temporary = root / ".magicfit-review-bundle.tmp"
    temporary.mkdir(mode=0o700)
    unknown = temporary / "operator-note.txt"
    unknown.write_text("preserve me", encoding="utf-8")
    unknown.chmod(0o600)

    with pytest.raises(MagicFitSecureIOError, match="temporary_layout_invalid"):
        publish_magicfit_review_receipt_bundle(
            root,
            delivery_digest="d" * 64,
            browser_receipt_bytes=b"browser\n",
            evidence_receipt_bytes=b"evidence\n",
        )

    assert unknown.read_text(encoding="utf-8") == "preserve me"


def test_magicfit_secure_reader_rejects_symlink_components_and_final_symlink(
    tmp_path: Path,
) -> None:
    real = tmp_path / "real"
    real.mkdir()
    subject = real / "subject.json"
    subject.write_bytes(b'{"status":"pass"}\n')
    linked_directory = tmp_path / "linked-directory"
    linked_directory.symlink_to(real, target_is_directory=True)
    linked_file = tmp_path / "linked-file.json"
    linked_file.symlink_to(subject)

    for path in (linked_directory / subject.name, linked_file):
        with pytest.raises(MagicFitSecureIOError):
            magicfit_secure_io.read_stable_bounded_bytes(
                path,
                reason="fixture_integrity_subject_invalid",
                maximum_bytes=1024,
            )


def test_magicfit_secure_reader_fails_closed_on_mid_read_path_replacement(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    subject = tmp_path / "subject.bin"
    original_body = b"a" * (1024 * 1024 + 31)
    replacement_body = b"b" * len(original_body)
    subject.write_bytes(original_body)
    original_read = magicfit_secure_io.os.read
    replaced = False

    def replace_after_first_read(descriptor: int, size: int) -> bytes:
        nonlocal replaced
        chunk = original_read(descriptor, size)
        if chunk and not replaced:
            replaced = True
            subject.unlink()
            subject.write_bytes(replacement_body)
        return chunk

    monkeypatch.setattr(magicfit_secure_io.os, "read", replace_after_first_read)

    with pytest.raises(MagicFitSecureIOError, match="changed_during_read"):
        magicfit_secure_io.read_stable_bounded_bytes(
            subject,
            reason="fixture_integrity_subject_changed",
            maximum_bytes=len(original_body),
        )


@pytest.mark.skipif(
    not shutil.which("ffmpeg") or not playwright_chromium_capture_available(),
    reason="ffmpeg and a real local Chromium are required",
)
def test_private_magicfit_review_runs_real_token_gated_playback_and_emits_exact_receipts(
    tmp_path: Path,
) -> None:
    paths = _fixture(tmp_path)
    completed = subprocess.run(
        _command(paths),
        cwd=ROOT,
        env=_env(paths),
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    result = json.loads(completed.stdout)
    assert result["status"] == "private_review_evidence_ready"
    assert result["acceptance_status"] == "pending"
    assert result["launch_eligible"] is False
    assert result["reviewer_authority_generated"] is False
    assert result["published"] is False
    assert result["proof_transport"] == "ephemeral_token_gated_loopback_review_server"
    assert result["public_route_proof"] is False
    assert result["visual_review_sha256"] == _sha256(paths["visual"])
    assert result["review_bundle"] == str(paths["review_bundle"])
    assert result["receipt_bundle_recovered"] is False
    assert result["execution_boundary"] == {
        "kind": "transient_user_systemd_scope",
        "memory_max_bytes": 1024 * 1024 * 1024,
        "memory_swap_max_bytes": 0,
        "tasks_max": 128,
        "cpu_quota_percent": 100.0,
        "runtime_max_seconds": 40,
    }
    assert not paths["public_root"].exists()

    pending = json.loads(
        (paths["bundle"] / "tour.magicfit.pending.json").read_text(encoding="utf-8")
    )
    browser = json.loads(paths["browser"].read_text(encoding="utf-8"))
    assert browser == {
        "schema": BROWSER_RECEIPT_CONTRACT,
        "status": "pass",
        "provider": "magicfit",
        "target_slug": SLUG,
        "observed_at": browser["observed_at"],
        "route": (
            f"operator-review://propertyquarry/magicfit/{SLUG}/{_sha256(paths['video'])}"
        ),
        "http_status": 200,
        "video_sha256": _sha256(paths["video"]),
        "base_manifest_sha256": pending["base_manifest_sha256"],
        "staged_manifest_sha256": pending["staged_manifest_sha256"],
        "delivery_digest": Path(pending["accepted_sidecar_relpath"]).stem,
        "duration_seconds": browser["duration_seconds"],
        "final_current_time": browser["final_current_time"],
        "playback_to_end": True,
        "video_error": None,
        "console_errors": [],
        "request_failures": [],
        "benign_request_aborts": browser["benign_request_aborts"],
        "bad_responses": [],
    }
    assert browser["duration_seconds"] > 1.0
    assert browser["final_current_time"] >= browser["duration_seconds"] - 0.25
    assert len(browser["benign_request_aborts"]) <= 1

    evidence = json.loads(paths["evidence"].read_text(encoding="utf-8"))
    assert evidence["schema"] == EVIDENCE_CONTRACT
    assert evidence["status"] == "pass"
    assert evidence["source_receipt_sha256"] == _sha256(paths["source"])
    assert evidence["base_manifest_sha256"] == pending["base_manifest_sha256"]
    assert evidence["staged_manifest_sha256"] == pending["staged_manifest_sha256"]
    assert evidence["delivery_digest"] == Path(
        pending["accepted_sidecar_relpath"]
    ).stem
    assert evidence["video"]["sha256"] == _sha256(paths["video"])
    assert evidence["artifacts"]["contact_sheet_sha256"] == _sha256(
        paths["contact"]
    )
    assert evidence["artifacts"]["browser_receipt_sha256"] == _sha256(
        paths["browser"]
    )
    assert evidence["artifacts"]["visual_review_sha256"] == _sha256(
        paths["visual"]
    )
    assert all(evidence["checklist"].values())
    assert paths["browser"].stat().st_mode & 0o777 == 0o600
    assert paths["evidence"].stat().st_mode & 0o777 == 0o600
    assert paths["bundle_manifest"].stat().st_mode & 0o777 == 0o600
    assert paths["review_bundle"].stat().st_mode & 0o777 == 0o700
    manifest = json.loads(paths["bundle_manifest"].read_text(encoding="utf-8"))
    assert manifest == {
        "contract_name": REVIEW_RECEIPT_BUNDLE_CONTRACT,
        "delivery_digest": paths["review_bundle"].name,
        "artifacts": {
            "browser_receipt": {
                "filename": "browser-receipt.json",
                "sha256": _sha256(paths["browser"]),
                "size_bytes": paths["browser"].stat().st_size,
            },
            "evidence_receipt": {
                "filename": "evidence-receipt.json",
                "sha256": _sha256(paths["evidence"]),
                "size_bytes": paths["evidence"].stat().st_size,
            },
        },
    }
    assert result["review_bundle_manifest_sha256"] == _sha256(
        paths["bundle_manifest"]
    )
    assert not (paths["review_bundle_root"] / ".magicfit-review-bundle.tmp").exists()
    exact_bodies = {
        path.name: path.read_bytes()
        for path in (
            paths["browser"],
            paths["evidence"],
            paths["bundle_manifest"],
        )
    }
    repeated = subprocess.run(
        _command(paths),
        cwd=ROOT,
        env=_env(paths),
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )
    assert repeated.returncode == 0, repeated.stderr
    assert json.loads(repeated.stdout)["receipt_bundle_recovered"] is True
    assert exact_bodies == {
        path.name: path.read_bytes()
        for path in (
            paths["browser"],
            paths["evidence"],
            paths["bundle_manifest"],
        )
    }
    assert not list(paths["private_root"].glob(".magicfit-private-review-*"))
    assert not list(paths["private_root"].glob("*authority*"))


@pytest.mark.skipif(
    not shutil.which("ffmpeg") or not playwright_chromium_capture_available(),
    reason="ffmpeg and a real local Chromium are required",
)
def test_private_magicfit_browser_only_writes_only_exact_technical_receipt(
    tmp_path: Path,
) -> None:
    paths = _fixture(tmp_path)
    paths["contact"].unlink()
    paths["visual"].unlink()
    completed = subprocess.run(
        _command(paths, browser_only=True),
        cwd=ROOT,
        env=_env(paths),
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    result = json.loads(completed.stdout)
    assert result["status"] == "private_browser_playback_ready"
    assert result["proof_scope"] == "private_technical_playback_only"
    assert result["proof_transport"] == "ephemeral_token_gated_loopback_review_server"
    assert result["public_route_proof"] is False
    assert result["acceptance_status"] == "pending"
    assert paths["browser_only"].is_file()
    assert paths["browser_only"].stat().st_mode & 0o777 == 0o600
    assert not paths["evidence"].exists()
    assert not paths["public_root"].exists()
    browser = json.loads(paths["browser_only"].read_text(encoding="utf-8"))
    assert browser["schema"] == BROWSER_RECEIPT_CONTRACT
    assert browser["status"] == "pass"
    assert browser["route"] == (
        f"operator-review://propertyquarry/magicfit/{SLUG}/{_sha256(paths['video'])}"
    )
    pending = json.loads(
        (paths["bundle"] / "tour.magicfit.pending.json").read_text(encoding="utf-8")
    )
    assert browser["base_manifest_sha256"] == pending["base_manifest_sha256"]
    assert browser["staged_manifest_sha256"] == pending["staged_manifest_sha256"]
    assert browser["delivery_digest"] == Path(
        pending["accepted_sidecar_relpath"]
    ).stem

    repeated = subprocess.run(
        _command(paths, browser_only=True),
        cwd=ROOT,
        env=_env(paths),
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )
    assert repeated.returncode == 0, repeated.stderr
    assert json.loads(repeated.stdout)["receipt_recovered"] is True


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg is required")
@pytest.mark.parametrize(
    "invalid_contact_sheet",
    (
        b"\x89PNG\r\n\x1a\n" + (b"\x00" * 64),
        PNG_1X1[:20],
    ),
    ids=("malformed-png-body", "truncated-png"),
)
def test_private_magicfit_full_review_rejects_signature_only_contact_sheet(
    tmp_path: Path,
    invalid_contact_sheet: bytes,
) -> None:
    paths = _fixture(tmp_path)
    paths["contact"].write_bytes(invalid_contact_sheet)

    completed = subprocess.run(
        _command(paths),
        cwd=ROOT,
        env=_env(paths),
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )

    assert completed.returncode != 0
    assert "magicfit_private_review_contact_sheet_invalid" in completed.stderr
    assert not paths["review_bundle"].exists()


def test_private_magicfit_review_defaults_denied_and_refuses_public_root(
    tmp_path: Path,
) -> None:
    paths = _fixture(tmp_path)
    denied = subprocess.run(
        _command(paths, allow=False),
        cwd=ROOT,
        env=_env(paths),
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )
    assert denied.returncode != 0
    assert "magicfit_private_review_not_authorized" in denied.stderr
    assert not paths["browser_only"].exists()
    assert not paths["evidence"].exists()

    denied_browser_only = subprocess.run(
        _command(paths, allow=False, browser_only=True),
        cwd=ROOT,
        env=_env(paths),
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )
    assert denied_browser_only.returncode != 0
    assert "magicfit_private_review_not_authorized" in denied_browser_only.stderr
    assert not paths["browser_only"].exists()

    collision = _command(paths, browser_only=True)
    collision.extend(("--evidence-receipt-out", str(paths["browser_only"])))
    collided = subprocess.run(
        collision,
        cwd=ROOT,
        env=_env(paths),
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )
    assert collided.returncode != 0
    assert (
        "magicfit_private_review_browser_only_pair_arguments_forbidden"
        in collided.stderr
    )
    assert not paths["browser_only"].exists()

    legacy = _command(paths)
    legacy.extend(("--browser-receipt-out", str(paths["browser_only"])))
    legacy_result = subprocess.run(
        legacy,
        cwd=ROOT,
        env=_env(paths),
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )
    assert legacy_result.returncode != 0
    assert (
        "magicfit_private_review_legacy_loose_outputs_forbidden"
        in legacy_result.stderr
    )

    public_env = _env(paths)
    public_env["EA_PUBLIC_TOUR_DIR"] = str(paths["private_root"])
    public = subprocess.run(
        _command(paths),
        cwd=ROOT,
        env=public_env,
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )
    assert public.returncode != 0
    assert "magicfit_private_review_public_root_forbidden" in public.stderr
    assert not paths["browser"].exists()
    assert not paths["evidence"].exists()


@pytest.mark.parametrize("invalid_slug", ([], {}))
def test_private_magicfit_review_rejects_non_scalar_manifest_slug_cleanly(
    tmp_path: Path,
    invalid_slug: object,
) -> None:
    paths = _fixture(tmp_path)
    manifest_path = paths["bundle"] / "tour.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["slug"] = invalid_slug
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    completed = subprocess.run(
        _command(paths),
        cwd=ROOT,
        env=_env(paths),
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )

    assert completed.returncode != 0
    assert "magicfit_private_review_manifest_binding_invalid" in completed.stderr
    assert "Traceback" not in completed.stderr
    assert not paths["browser"].exists()
    assert not paths["evidence"].exists()


def test_private_review_server_is_loopback_only_and_requires_ephemeral_token(
    tmp_path: Path,
) -> None:
    video = tmp_path / "video.mp4"
    video.write_bytes(b"not-needed-for-page-probe")
    token = tmp_path / "token"
    token.write_text("ephemeral-test-token", encoding="ascii")
    token.chmod(0o600)
    route = f"/tours/{SLUG}/walkthrough"

    with _private_review_server(
        video_path=video,
        route=route,
        token_path=token,
    ) as review_url:
        assert review_url.startswith("http://127.0.0.1:")
        with pytest.raises(urllib.error.HTTPError) as denied:
            urllib.request.urlopen(review_url, timeout=3)
        assert denied.value.code == 404
        request = urllib.request.Request(
            review_url,
            headers={"Authorization": "Bearer ephemeral-test-token"},
        )
        with urllib.request.urlopen(request, timeout=3) as response:
            assert response.status == 200
            assert REVIEW_PAGE_ROUTE in review_url
            assert b"tour-video" in response.read()


def test_worker_scope_wrapper_has_every_aggregate_limit_and_no_uncapped_fallback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    systemd_run = tmp_path / "systemd-run"
    systemd_run.write_text("fixture", encoding="utf-8")
    command = _capped_worker_command(
        ["python3", "worker.py"],
        runtime_max_seconds=47,
        systemd_run_path=str(systemd_run),
        unit_suffix="0123456789abcdef",
    )
    assert command[:6] == [
        str(systemd_run),
        "--user",
        "--scope",
        "--quiet",
        "--collect",
        "--unit=propertyquarry-magicfit-review-0123456789abcdef",
    ]
    assert f"--property=MemoryMax={WORKER_MEMORY_MAX_BYTES}" in command
    assert "--property=MemorySwapMax=0" in command
    assert f"--property=TasksMax={WORKER_TASKS_MAX}" in command
    assert "--property=CPUQuota=100%" in command
    assert "--property=RuntimeMaxSec=47s" in command
    assert command[-3:] == ["--", "python3", "worker.py"]

    monkeypatch.setattr(shutil, "which", lambda _name: None)
    with pytest.raises(SystemExit, match="cgroup_runner_missing"):
        _capped_worker_command(["python3", "worker.py"], runtime_max_seconds=47)


def test_worker_rejects_uncapped_cgroup_and_accepts_only_tighter_finite_limits(
    tmp_path: Path,
) -> None:
    cgroup_root = tmp_path / "cgroup"
    scope = cgroup_root / "review.scope"
    scope.mkdir(parents=True)
    proc_cgroup = tmp_path / "proc-self-cgroup"
    proc_cgroup.write_text("0::/review.scope\n", encoding="utf-8")
    (scope / "memory.max").write_text(str(512 * 1024 * 1024), encoding="ascii")
    (scope / "memory.swap.max").write_text("0", encoding="ascii")
    (scope / "pids.max").write_text("64", encoding="ascii")
    (scope / "cpu.max").write_text("50000 100000", encoding="ascii")

    assert _require_worker_cgroup_limits(
        proc_cgroup_path=proc_cgroup,
        cgroup_root=cgroup_root,
    ) == {
        "memory_max_bytes": 512 * 1024 * 1024,
        "memory_swap_max_bytes": 0,
        "tasks_max": 64,
        "cpu_quota_percent": 50.0,
    }

    (scope / "memory.max").write_text("max", encoding="ascii")
    with pytest.raises(SystemExit, match="cgroup_memory_uncapped"):
        _require_worker_cgroup_limits(
            proc_cgroup_path=proc_cgroup,
            cgroup_root=cgroup_root,
        )


def test_acceptance_validators_reject_finite_overflow_numbers() -> None:
    now = datetime.now(timezone.utc).replace(microsecond=0)
    observed_at = now.isoformat().replace("+00:00", "Z")
    sha = "a" * 64
    browser = {
        "schema": BROWSER_RECEIPT_CONTRACT,
        "status": "pass",
        "provider": "magicfit",
        "target_slug": SLUG,
        "observed_at": observed_at,
        "route": f"/tours/{SLUG}/walkthrough",
        "http_status": 200,
        "video_sha256": sha,
        "base_manifest_sha256": "e" * 64,
        "staged_manifest_sha256": "f" * 64,
        "delivery_digest": "1" * 64,
        "duration_seconds": float("inf"),
        "final_current_time": float("inf"),
        "playback_to_end": True,
        "video_error": None,
        "console_errors": [],
        "request_failures": [],
        "benign_request_aborts": [],
        "bad_responses": [],
    }
    with pytest.raises(SystemExit, match="browser_receipt_contract_invalid"):
        _validate_browser_receipt(
            browser,
            slug=SLUG,
            generated_at=now,
            video_sha256=sha,
            base_manifest_sha256="e" * 64,
            staged_manifest_sha256="f" * 64,
            delivery_digest="1" * 64,
            video_duration=1.0,
        )

    evidence = {
        "schema": EVIDENCE_CONTRACT,
        "status": "pass",
        "provider": "magicfit",
        "target_slug": SLUG,
        "observed_at": observed_at,
        "source_receipt_sha256": "b" * 64,
        "base_manifest_sha256": "e" * 64,
        "staged_manifest_sha256": "f" * 64,
        "delivery_digest": "1" * 64,
        "video": {
            "sha256": sha,
            "size_bytes": 1,
            "duration_seconds": float("inf"),
        },
        "checklist": {key: True for key in sorted(REVIEW_CHECKS)},
        "artifacts": {
            "contact_sheet_sha256": "c" * 64,
            "browser_receipt_sha256": "d" * 64,
            "visual_review_sha256": "2" * 64,
        },
    }
    with pytest.raises(SystemExit, match="evidence_video_invalid"):
        _validate_evidence(
            evidence,
            slug=SLUG,
            generated_at=now,
            video_sha256=sha,
            video_probe={"size_bytes": 1, "duration_seconds": 1.0},
            source_receipt_sha256="b" * 64,
            base_manifest_sha256="e" * 64,
            staged_manifest_sha256="f" * 64,
            delivery_digest="1" * 64,
            contact_sheet_sha256="c" * 64,
            browser_receipt_sha256="d" * 64,
            visual_review_sha256="2" * 64,
        )


def test_visual_review_contract_v3_binds_pending_subject_and_rejects_v1(
    tmp_path: Path,
) -> None:
    now = datetime.now(timezone.utc).replace(microsecond=0)
    observed_at = now.isoformat().replace("+00:00", "Z")
    review_path = tmp_path / "visual-review.json"
    payload = {
        "schema": VISUAL_REVIEW_CONTRACT,
        "status": "pass",
        "provider": "magicfit",
        "target_slug": SLUG,
        "observed_at": observed_at,
        "video_sha256": "a" * 64,
        "base_manifest_sha256": "b" * 64,
        "staged_manifest_sha256": "c" * 64,
        "delivery_digest": "d" * 64,
        "checklist": {key: True for key in sorted(REVIEW_CHECKS)},
    }
    review_path.write_text(json.dumps(payload), encoding="utf-8")
    assert all(
        _visual_review(
            path=review_path,
            slug=SLUG,
            generated_at=now,
            video_sha256="a" * 64,
            base_manifest_sha256="b" * 64,
            staged_manifest_sha256="c" * 64,
            delivery_digest="d" * 64,
        ).values()
    )
    with pytest.raises(SystemExit, match="visual_review_contract_invalid"):
        _visual_review(
            path=review_path,
            slug=SLUG,
            generated_at=now,
            video_sha256="a" * 64,
            base_manifest_sha256="b" * 64,
            staged_manifest_sha256="e" * 64,
            delivery_digest="d" * 64,
        )

    payload["schema"] = "propertyquarry.magicfit_private_visual_review.v1"
    for key in (
        "base_manifest_sha256",
        "staged_manifest_sha256",
        "delivery_digest",
    ):
        payload.pop(key)
    review_path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(SystemExit, match="visual_review_contract_invalid"):
        _visual_review(
            path=review_path,
            slug=SLUG,
            generated_at=now,
            video_sha256="a" * 64,
            base_manifest_sha256="b" * 64,
            staged_manifest_sha256="c" * 64,
            delivery_digest="d" * 64,
        )

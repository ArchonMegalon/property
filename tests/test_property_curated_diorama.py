from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

import pytest

from app.api.routes import landing as landing_routes
from app.services.property_curated_diorama import (
    build_curated_diorama_preview_index,
    curated_diorama_governance_subject_sha256,
)


def _approved_review(status: str, *, subject_sha256: str) -> dict[str, str]:
    return {
        "status": status,
        "basis": "Reviewed source permissions and release evidence.",
        "reviewed_by": "release-reviewer",
        "reviewed_at": "2026-07-12T20:00:00Z",
        "subject_sha256": subject_sha256,
        "evidence_sha256": hashlib.sha256(f"{status}-review-evidence".encode()).hexdigest(),
    }


def _manifest_for(asset: Path, *, asset_url: str = "/static/property/research/approved.png") -> dict[str, object]:
    asset_sha256 = hashlib.sha256(asset.read_bytes()).hexdigest()
    source_asset_sha256s = [hashlib.sha256(b"licensed-source-input").hexdigest()]
    governance_subject_sha256 = curated_diorama_governance_subject_sha256(
        asset_sha256=asset_sha256,
        source_asset_sha256s=source_asset_sha256s,
    )
    return {
        "contract_name": "propertyquarry.curated_diorama_previews.v2",
        "entries": [
            {
                "preview_kind": "rendered_diorama",
                "asset_url": asset_url,
                "asset_sha256": asset_sha256,
                "source_asset_sha256s": source_asset_sha256s,
                "candidate_refs": ["Candidate-A"],
                "listing_ids": ["123456"],
                "governance": {
                    "rights": _approved_review("approved", subject_sha256=governance_subject_sha256),
                    "privacy": _approved_review("approved", subject_sha256=governance_subject_sha256),
                    "provenance": _approved_review("verified", subject_sha256=governance_subject_sha256),
                },
            }
        ],
    }


def test_curated_diorama_v2_requires_complete_approved_governance(tmp_path: Path) -> None:
    static_root = tmp_path / "static"
    asset = static_root / "property" / "research" / "approved.png"
    asset.parent.mkdir(parents=True)
    asset.write_bytes(b"approved-render")

    assert build_curated_diorama_preview_index(_manifest_for(asset), static_root=static_root) == {
        "candidate:candidate-a": "/static/property/research/approved.png",
        "listing:123456": "/static/property/research/approved.png",
    }


@pytest.mark.parametrize(
    ("review_name", "field", "value"),
    [
        ("rights", "status", "pending"),
        ("privacy", "basis", ""),
        ("provenance", "reviewed_by", ""),
        ("rights", "reviewed_at", "2026-07-12"),
        ("privacy", "reviewed_at", "2099-01-01T00:00:00Z"),
        ("rights", "subject_sha256", "0" * 64),
        ("provenance", "evidence_sha256", ""),
    ],
)
def test_curated_diorama_rejects_incomplete_or_unapproved_review(
    tmp_path: Path,
    review_name: str,
    field: str,
    value: str,
) -> None:
    static_root = tmp_path / "static"
    asset = static_root / "property" / "research" / "approved.png"
    asset.parent.mkdir(parents=True)
    asset.write_bytes(b"approved-render")
    payload = _manifest_for(asset)
    payload["entries"][0]["governance"][review_name][field] = value

    assert build_curated_diorama_preview_index(payload, static_root=static_root) == {}


def test_curated_diorama_rejects_v1_hash_mismatch_and_path_escape(tmp_path: Path) -> None:
    static_root = tmp_path / "static"
    asset = static_root / "property" / "research" / "approved.png"
    asset.parent.mkdir(parents=True)
    asset.write_bytes(b"approved-render")
    payload = _manifest_for(asset)

    payload["contract_name"] = "propertyquarry.curated_diorama_previews.v1"
    assert build_curated_diorama_preview_index(payload, static_root=static_root) == {}

    payload = _manifest_for(asset)
    payload["entries"][0]["asset_sha256"] = "0" * 64
    assert build_curated_diorama_preview_index(payload, static_root=static_root) == {}

    payload = _manifest_for(asset, asset_url="/static/../outside.png")
    assert build_curated_diorama_preview_index(payload, static_root=static_root) == {}


def test_curated_diorama_rejects_string_identifiers_and_collisions(tmp_path: Path) -> None:
    static_root = tmp_path / "static"
    first_asset = static_root / "property" / "research" / "first.png"
    second_asset = static_root / "property" / "research" / "second.png"
    first_asset.parent.mkdir(parents=True)
    first_asset.write_bytes(b"first-approved-render")
    second_asset.write_bytes(b"second-approved-render")

    payload = _manifest_for(first_asset, asset_url="/static/property/research/first.png")
    payload["entries"][0]["candidate_refs"] = "candidate-a"
    assert build_curated_diorama_preview_index(payload, static_root=static_root) == {}

    first_entry = _manifest_for(first_asset, asset_url="/static/property/research/first.png")["entries"][0]
    second_entry = _manifest_for(second_asset, asset_url="/static/property/research/second.png")["entries"][0]
    second_entry["candidate_refs"] = ["candidate-a"]
    payload = {
        "contract_name": "propertyquarry.curated_diorama_previews.v2",
        "entries": [first_entry, second_entry],
    }
    assert build_curated_diorama_preview_index(payload, static_root=static_root) == {}


def test_curated_diorama_rejects_symlinked_asset(tmp_path: Path) -> None:
    static_root = tmp_path / "static"
    real_asset = tmp_path / "real.png"
    real_asset.write_bytes(b"approved-render")
    asset = static_root / "property" / "research" / "approved.png"
    asset.parent.mkdir(parents=True)
    try:
        asset.symlink_to(real_asset)
    except OSError:
        pytest.skip("symlinks unavailable")

    assert build_curated_diorama_preview_index(_manifest_for(asset), static_root=static_root) == {}


@pytest.mark.parametrize(
    "contract_name",
    [
        "propertyquarry.curated_diorama_previews.v1",
        "propertyquarry.curated_diorama_previews.v2",
    ],
)
def test_landing_curated_diorama_loader_rejects_legacy_or_unapproved_manifest(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    contract_name: str,
) -> None:
    static_root = tmp_path / "static"
    asset = static_root / "property" / "research" / "unapproved.png"
    asset.parent.mkdir(parents=True)
    asset.write_bytes(b"unapproved-render")
    manifest_path = tmp_path / "property_diorama_previews.json"
    manifest_path.write_text(
        json.dumps(
            {
                "contract_name": contract_name,
                "entries": [
                    {
                        "preview_kind": "rendered_diorama",
                        "asset_url": "/static/property/research/unapproved.png",
                        "asset_sha256": hashlib.sha256(asset.read_bytes()).hexdigest(),
                        "candidate_refs": ["candidate-unapproved"],
                        "listing_ids": ["123456"],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(landing_routes, "_PROPERTY_CURATED_DIORAMA_MANIFEST_PATH", manifest_path)
    monkeypatch.setattr(landing_routes, "_PROPERTY_CURATED_DIORAMA_STATIC_ROOT", static_root)
    landing_routes._property_curated_diorama_preview_index.cache_clear()
    try:
        assert landing_routes._property_curated_diorama_preview_index() == {}
    finally:
        landing_routes._property_curated_diorama_preview_index.cache_clear()


def test_tracked_curated_diorama_assets_are_not_orphaned() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    tracked_assets = {
        line.strip()
        for line in subprocess.check_output(
            ["git", "ls-files", "--", "ea/app/static/property/research"],
            cwd=repo_root,
            text=True,
        ).splitlines()
        if Path(line.strip()).suffix.lower() in {".avif", ".jpeg", ".jpg", ".png", ".webp"}
    }
    manifest_path = repo_root / "ea" / "app" / "data" / "property_diorama_previews.json"
    payload = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.is_file() else {}
    index = build_curated_diorama_preview_index(
        payload,
        static_root=repo_root / "ea" / "app" / "static",
    )
    approved_assets = {
        f"ea/app/static/{asset_url.removeprefix('/static/')}"
        for asset_url in index.values()
    }
    assert tracked_assets == approved_assets

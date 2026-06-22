#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
EA_ROOT = ROOT / "ea"
for candidate in (ROOT, EA_ROOT):
    if str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))

from app.product.property_score_methodology import (  # noqa: E402
    build_property_score_methodology,
    supported_property_score_methodology_languages,
)
from app.services.fliplink.models import FlipLinkFormat, PacketPrivacyMode, PropertyPacketKind  # noqa: E402
from app.services.fliplink.pdf_renderer import render_property_packet_pdf  # noqa: E402


def _synthetic_source(language_code: str) -> dict[str, object]:
    candidate = {
        "fit_score": 62,
        "match_reasons": [
            "Selected area is respected.",
            "Verified costs, floorplan, and 360 evidence raise confidence.",
            "Commute and daily-life preferences score well.",
        ],
        "mismatch_reasons": [
            "One soft preference is missing and lowers rank without excluding.",
            "Heating detail still needs confirmation before a final decision.",
        ],
    }
    methodology = build_property_score_methodology(language_code=language_code, candidate=candidate)
    return {
        "title": str(methodology.get("pdf_title") or "PropertyQuarry score methodology"),
        "summary": str(methodology.get("summary") or ""),
        "source_label": "PropertyQuarry scoring engine",
        "fit_score": candidate["fit_score"],
        "recommendation": "Strong fit",
        "match_reasons": candidate["match_reasons"],
        "mismatch_reasons": candidate["mismatch_reasons"],
        "viewing_questions": [
            "Verify the still-missing fact with the agent.",
            "Compare the route and noise evidence during an actual viewing.",
        ],
        "property_facts": {
            "language_code": language_code,
            "postal_name": "Demo market",
            "price_display": "Example budget",
            "area_m2": 82,
            "rooms": 3,
            "has_floorplan": True,
            "nearest_school_m": 430,
            "nearest_supermarket_m": 260,
        },
        "score_methodology": methodology,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Render PropertyQuarry scoring-methodology FlipLink PDFs for every provider language.")
    parser.add_argument("--output-dir", default=str(ROOT / "_completion" / "property_score_methodology"))
    parser.add_argument(
        "--strict-premium",
        action="store_true",
        help="Do not enable the emergency legacy renderer for local proof PDFs.",
    )
    args = parser.parse_args()
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    if not args.strict_premium:
        os.environ.setdefault("PROPERTYQUARRY_LEGACY_PDF_RENDERER_ALLOW", "1")
    manifest: dict[str, object] = {
        "contract_name": "propertyquarry.score_methodology_pdf_manifest.v1",
        "renderer": "FlipLink property packet renderer",
        "languages": [],
    }
    rows: list[dict[str, object]] = []
    for language_code in supported_property_score_methodology_languages():
        publication_id = f"score-methodology-{language_code}"
        rendered = render_property_packet_pdf(
            artifact_root=output_dir,
            publication_id=publication_id,
            principal_id="propertyquarry-score-methodology",
            source=_synthetic_source(language_code),
            packet_kind=PropertyPacketKind.FAMILY_REVIEW,
            privacy_mode=PacketPrivacyMode.ANONYMOUS_PUBLIC,
            fliplink_format=FlipLinkFormat.SMART_DOCUMENT,
            include_exact_address=False,
            include_floorplan=False,
            include_photos=False,
        )
        pdf_path = Path(str(rendered.get("pdf_path") or ""))
        if not pdf_path.exists():
            raise RuntimeError(f"PDF render failed for {language_code}: {json.dumps(rendered, ensure_ascii=True, sort_keys=True)}")
        pdf_bytes = pdf_path.read_bytes()
        rows.append(
            {
                "language_code": language_code,
                "pdf_path": str(pdf_path.relative_to(output_dir)),
                "pdf_sha256": hashlib.sha256(pdf_bytes).hexdigest(),
                "pdf_size_bytes": len(pdf_bytes),
                "receipt_path": str(Path(str(rendered.get("receipt_path") or "")).relative_to(output_dir)),
                "renderer_version": dict(rendered.get("receipt") or {}).get("renderer_version"),
            }
        )
    manifest["languages"] = rows
    manifest_path = output_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=True, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(manifest_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

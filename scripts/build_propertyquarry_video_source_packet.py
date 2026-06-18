#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
EA_ROOT = ROOT / "ea"
for candidate in (ROOT, EA_ROOT):
    if str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))

from app.domain.property.content_source_packet import build_property_content_source_packet, sha256_json  # noqa: E402
from app.services.property_content_packet_builder import (  # noqa: E402
    build_product_tutorial_source_packet,
    build_synthetic_dossier_source_packet,
)
from app.services.property_content_validation import validate_property_content_source_packet  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a PropertyQuarry Subscribr source packet.")
    parser.add_argument("--mode", default="PRODUCT_TUTORIAL")
    parser.add_argument("--title", default="How to Read a PropertyQuarry Dossier")
    parser.add_argument("--language", default="en")
    parser.add_argument("--jurisdiction", default="GLOBAL")
    parser.add_argument("--output", default="")
    args = parser.parse_args()
    mode = args.mode.strip().upper()
    if mode == "PRODUCT_TUTORIAL":
        packet = build_product_tutorial_source_packet(title=args.title, language=args.language, jurisdiction=args.jurisdiction)
    elif mode == "PROPERTY_DOSSIER":
        packet = build_synthetic_dossier_source_packet()
    else:
        packet = build_property_content_source_packet(
            packet_id=f"pq-{mode.lower().replace('_', '-')}-{sha256_json({'title': args.title})[:12]}",
            content_mode=mode,
            title=args.title,
            language=args.language,
            jurisdiction=args.jurisdiction,
            facts={"content_purpose": args.title},
            allowed_claims=["This is educational PropertyQuarry content."],
            sources=[{"source_type": "approved_operator_source", "sha256": sha256_json({"title": args.title})}],
        )
    report = validate_property_content_source_packet(packet)
    out_path = Path(args.output) if args.output else ROOT / "_completion" / "subscribr" / f"{packet['packet_id']}.source-packet.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps({"packet": packet, "validation": report}, ensure_ascii=True, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(out_path)
    return 0 if report["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())


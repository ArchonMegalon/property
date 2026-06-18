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

from app.services.property_content_studio import PropertyContentStudio  # noqa: E402


def _load_packet(path: Path) -> dict[str, object]:
    parsed = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(parsed, dict) and isinstance(parsed.get("packet"), dict):
        return dict(parsed["packet"])
    if isinstance(parsed, dict):
        return parsed
    raise SystemExit("packet file must contain an object")


def _default_markdown(packet: dict[str, object]) -> str:
    title = str(packet.get("title") or "PropertyQuarry source packet")
    mode = str(packet.get("content_mode") or "")
    if mode == "PROPERTY_DOSSIER":
        return (
            f"# {title}\n\n"
            "Generated from the reviewed dossier and source packet. "
            "This listing matched the supplied brief in this run. "
            "Heating system, reserve fund, and peak-hour noise remain unknown and should be verified before a viewing.\n"
        )
    return (
        f"# {title}\n\n"
        "This PropertyQuarry educational script explains the reviewed workflow using approved sources. "
        "Screenshots and current UI details must be checked before recording.\n"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Create a local Subscribr script receipt.")
    parser.add_argument("--packet", required=True)
    parser.add_argument("--markdown", default="")
    parser.add_argument("--provider-channel-id", default="")
    parser.add_argument("--provider-idea-id", default="")
    parser.add_argument("--provider-script-id", default="")
    args = parser.parse_args()
    packet = _load_packet(Path(args.packet))
    markdown = Path(args.markdown).read_text(encoding="utf-8") if args.markdown else _default_markdown(packet)
    receipt = PropertyContentStudio().materialize_script_receipt(
        packet=packet,
        markdown=markdown,
        provider_channel_id=args.provider_channel_id,
        provider_idea_id=args.provider_idea_id,
        provider_script_id=args.provider_script_id,
    )
    print(receipt["receipt_path"])
    return 0 if receipt["status"] == "review_required" else 1


if __name__ == "__main__":
    raise SystemExit(main())


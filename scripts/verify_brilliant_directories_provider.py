#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
EA_ROOT = ROOT / "ea"
for candidate in (ROOT, EA_ROOT):
    if str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))

from app.services.brilliant_directories import build_brilliant_directories_verification_receipt  # noqa: E402


def _billing_dns_handoff_markdown(payload: dict[str, object]) -> str:
    handoff = payload.get("billing_handoff") if isinstance(payload.get("billing_handoff"), dict) else {}
    record = handoff.get("required_dns_record") if isinstance(handoff.get("required_dns_record"), dict) else {}
    host = str(handoff.get("host") or record.get("name") or "billing.propertyquarry.com").strip()
    url = str(handoff.get("url") or "").strip()
    record_type = str(record.get("type") or "CNAME or A/AAAA").strip()
    target = str(record.get("target") or "the Brilliant Directories white-label billing host assigned to this account").strip()
    next_action = str(handoff.get("next_action") or f"create DNS for {host} before enabling the Brilliant Directories billing handoff").strip()
    host_resolves = "yes" if handoff.get("host_resolves") is True else "no"
    return "\n".join(
        [
            "# PropertyQuarry Billing DNS Handoff",
            "",
            "Gold remains blocked until the Brilliant Directories billing handoff host resolves.",
            "",
            f"- Host: `{host}`",
            f"- URL: `{url or 'not configured'}`",
            f"- Resolves now: `{host_resolves}`",
            f"- Required DNS record type: `{record_type}`",
            f"- Required DNS target: `{target}`",
            f"- Next action: {next_action}",
            "",
            "Do not enable `/app/billing` as an external redirect until this host resolves over HTTPS.",
            "PropertyQuarry must remain the source of truth for entitlements; Brilliant Directories billing events stay advisory until reconciled.",
            "",
        ]
    )


def _load_dotenv_defaults(path: Path) -> None:
    if os.getenv("PROPERTYQUARRY_SKIP_DOTENV"):
        return
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if not key or key in os.environ:
            continue
        os.environ[key] = value.strip().strip('"').strip("'")


def main() -> int:
    _load_dotenv_defaults(ROOT / ".env")
    out_dir = Path(
        os.getenv("PROPERTYQUARRY_BRILLIANT_DIRECTORIES_COMPLETION_DIR")
        or ROOT / "_completion" / "brilliant_directories"
    )
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "BRILLIANT_DIRECTORIES_PROVIDER_VERIFICATION.generated.json"
    payload = build_brilliant_directories_verification_receipt()
    out_path.write_text(json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (out_dir / "BRILLIANT_DIRECTORIES_BILLING_DNS_HANDOFF.md").write_text(
        _billing_dns_handoff_markdown(payload),
        encoding="utf-8",
    )
    print(out_path)
    return 0 if payload.get("status") in {"disabled", "dry_verified_configured"} else 1


if __name__ == "__main__":
    raise SystemExit(main())

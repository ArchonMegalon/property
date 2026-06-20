#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCOPE_DOC = ROOT / "docs" / "PROPERTYQUARRY_WHOLE_PROJECT_SCOPE.md"

REQUIRED_PHRASES = (
    "Public entry and SEO surfaces",
    "Authentication, logout, account, sessions, data export, deletion, and share-link revocation",
    "Search setup, district and postal-code filtering, hard versus soft filter behavior",
    "Search execution, source coverage, fleet repair, retry state, ETA state",
    "Results, filtered-breakdown actions, rank ordering",
    "Research detail, 360 tours, Matterport and 3DVista links",
    "Automation and saved searches, including map thumbnails",
    "Provider governance, market readiness, rights, rate limits",
    "Canonical property memory",
    "Ranking and learning",
    "Notifications, scout thresholds",
    "Billing, invoices, VAT, refunds",
    "Privacy, prompt-injection boundaries",
    "Accessibility, responsive layout",
    "Observability: SLOs",
    "Documentation, help center, legal pages",
    "Integration governance for LTD/provider lanes",
    "Audit prose alone is not done",
    "one canonical property identity",
)

FORBIDDEN_PHRASES = (
    "Executive Assistant",
    "Morning Memo",
    "office loop",
)


def main() -> int:
    failures: list[str] = []
    if not SCOPE_DOC.exists():
        failures.append("docs/PROPERTYQUARRY_WHOLE_PROJECT_SCOPE.md must define whole-product scope")
    else:
        body = SCOPE_DOC.read_text(encoding="utf-8")
        for phrase in REQUIRED_PHRASES:
            if phrase not in body:
                failures.append(f"whole-project scope is missing required phrase: {phrase}")
        for phrase in FORBIDDEN_PHRASES:
            if phrase in body:
                failures.append(f"whole-project scope uses inherited generic copy: {phrase}")

    release_gate = (ROOT / "scripts" / "property_release_gates.sh").read_text(encoding="utf-8")
    if "scripts/check_property_whole_project_scope.py" not in release_gate:
        failures.append("property_release_gates.sh must run check_property_whole_project_scope.py")

    if failures:
        print("property whole-project scope check failed:", file=sys.stderr)
        for failure in failures:
            print(f"- {failure}", file=sys.stderr)
        return 1

    print("ok: property whole-project scope")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

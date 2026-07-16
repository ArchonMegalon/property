from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_product_release_checklist_is_propertyquarry_scoped() -> None:
    checklist = (ROOT / "PRODUCT_RELEASE_CHECKLIST.md").read_text(encoding="utf-8")

    assert checklist.startswith("# PropertyQuarry Product Release Checklist\n")
    for required in (
        "search-to-decision loop",
        "Shortlist, compare, feedback, preference learning, and revisit",
        "Chromium, Firefox, and WebKit",
        "protected flagship-security job",
        "verified rollback path",
    ):
        assert required in checklist

    for stale_office_requirement in (
        "real executive-office work system",
        "`/app/today`",
        "`/app/briefing`",
        "`/app/inbox`",
        "`/app/follow-ups`",
        "`/app/people/{id}`",
    ):
        assert stale_office_requirement not in checklist


def test_release_checklist_requires_the_propertyquarry_product_loop() -> None:
    checklist = (ROOT / "RELEASE_CHECKLIST.md").read_text(encoding="utf-8")

    assert "`PRODUCT_RELEASE_CHECKLIST.md` is fully satisfied" in checklist
    assert "brief -> search dispatch -> ranked results -> property dossier" in checklist
    assert "memo -> queue -> draft/approval -> follow-up" not in checklist
    assert "`.codex-design/repo/IMPLEMENTATION_SCOPE.md`" in checklist

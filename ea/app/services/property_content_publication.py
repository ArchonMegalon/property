from __future__ import annotations


def property_content_publication_gate(
    *,
    source_validation: dict[str, object],
    script_validation: dict[str, object],
    human_review: dict[str, object] | None = None,
    direct_publish_enabled: bool = False,
) -> dict[str, object]:
    review = dict(human_review or {})
    approved = str(review.get("status") or "").strip().lower() == "approved" and bool(review.get("reviewer"))
    blocked_reasons: list[str] = []
    if str(source_validation.get("status") or "") != "pass":
        blocked_reasons.append("source_validation_failed")
    if str(script_validation.get("status") or "") != "pass":
        blocked_reasons.append("script_validation_failed")
    if not approved:
        blocked_reasons.append("human_review_required")
    if not direct_publish_enabled:
        blocked_reasons.append("direct_publish_disabled")
    return {
        "status": "allowed" if not blocked_reasons else "blocked",
        "blocked_reasons": blocked_reasons,
        "publication_allowed": not blocked_reasons,
    }


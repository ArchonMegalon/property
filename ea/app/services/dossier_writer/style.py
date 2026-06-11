from __future__ import annotations


FORBIDDEN_UNSUPPORTED_PHRASES = (
    "safe",
    "guaranteed",
    "legal certainty",
    "profitable",
    "risk-free",
    "best school",
    "crime-free",
)


def premium_sentence(text: str) -> str:
    normalized = " ".join(str(text or "").split()).strip()
    if not normalized:
        return ""
    return normalized if normalized.endswith((".", "?", "!")) else f"{normalized}."

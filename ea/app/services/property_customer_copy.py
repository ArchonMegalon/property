from __future__ import annotations

import re


def normalize_property_fit_note(value: object) -> str:
    text = " ".join(str(value or "").split()).strip()
    if not text:
        return ""

    text = re.sub(r"^\s*Chosen ahead of the next option because\s+", "", text, flags=re.IGNORECASE)
    text = re.sub(r"^\s*Ranked ahead of the next option because\s+", "", text, flags=re.IGNORECASE)
    text = re.sub(r"^\s*Chosen because\s+", "", text, flags=re.IGNORECASE)
    text = re.sub(
        r"\bit scored \d+(?:\.\d+)? points higher on the current brief\b",
        "it best matches your search",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(
        r"\bit scored \d+(?:\.\d+)? points higher\b",
        "it best matches your search",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(
        r"\bit stayed closest to the current brief on the available facts\b",
        "it best matches your search",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(
        r"[;,:]\s*it includes a floorplan while the next option does not\.?",
        ". A floorplan is already available.",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(
        r"\bit includes a floorplan while the next option does not\b",
        "a floorplan is already available",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(
        r"[;,:]?\s*and includes a floorplan\.?",
        ". A floorplan is already available.",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(
        r"\bit includes a floorplan\b",
        "a floorplan is already available",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(
        r"\bit stays meaningfully cheaper than the next option\b",
        "it is meaningfully cheaper",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(
        r"\bstays meaningfully cheaper than the next option\b",
        "is meaningfully cheaper",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(r"\bwhile the next option does not\b", "", text, flags=re.IGNORECASE)
    text = re.sub(r";\s*(it|a)\b", lambda match: f". {match.group(1).capitalize()}", text, flags=re.IGNORECASE)
    text = re.sub(r"\s+\.", ".", text)
    text = re.sub(r"\.\s*\.", ".", text)
    text = re.sub(r"\s{2,}", " ", text).strip(" ;,")
    if not text:
        return ""
    if text.lower().startswith("it "):
        text = "It " + text[3:]
    elif text[0].islower():
        text = text[0].upper() + text[1:]
    if not re.search(r"[.!?]$", text):
        text += "."
    return text

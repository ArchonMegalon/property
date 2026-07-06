from __future__ import annotations

import re

_PROPERTY_PROVIDER_SUFFIX_MARKERS = (
    "willhaben",
    "immoscout",
    "immobilienscout",
    "immowelt",
    "idealista",
    "remax",
    "immobilien",
)

_PROPERTY_PROVIDER_MARKETING_PATTERNS = (
    r"\.?\s*Wählen Sie aus\s+\d[\d.,\s]*(?:Angeboten|Immobilien|Wohnungen|Häusern|Objekten).*?$",
    r"\.?\s*Immobilien suchen und finden auf\s+.*?$",
    r"\.?\s*Choose from\s+\d[\d.,\s]*(?:listings|properties|homes|offers).*?$",
    r"\.?\s*(?:Search|Find)\s+(?:homes|properties|real estate)\s+(?:on|at)\s+.*?$",
)

_PROPERTY_SENTENCE_CASE_STOPWORDS = {
    "am",
    "an",
    "and",
    "at",
    "auf",
    "bei",
    "by",
    "das",
    "de",
    "der",
    "des",
    "die",
    "for",
    "from",
    "im",
    "in",
    "mit",
    "of",
    "on",
    "oder",
    "the",
    "to",
    "und",
    "von",
}


def _capitalize_first_alpha(value: str) -> str:
    for index, char in enumerate(value):
        if char.isalpha():
            return f"{value[:index]}{char.upper()}{value[index + 1:]}"
    return value


def _sentence_case_promotional_fragment(value: str) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    raw_letters = [char for char in raw if char.isalpha()]
    raw_upper_ratio = (sum(1 for char in raw_letters if char.isupper()) / len(raw_letters)) if raw_letters else 0.0
    if raw_upper_ratio >= 0.8:
        tokens = re.split(r"(\s+)", raw)
        normalized_tokens: list[str] = []
        alpha_token_index = 0
        for token in tokens:
            if not token or token.isspace():
                normalized_tokens.append(token)
                continue
            leading_match = re.match(r"^[^A-Za-zÄÖÜäöüß]*", token)
            trailing_match = re.search(r"[^A-Za-zÄÖÜäöüß]*$", token)
            leading = leading_match.group(0) if leading_match else ""
            trailing = trailing_match.group(0) if trailing_match else ""
            end_index = len(token) - len(trailing) if trailing else len(token)
            core = token[len(leading):end_index]
            letters = [char for char in core if char.isalpha()]
            if not letters:
                normalized_tokens.append(token)
                continue
            lowered = core.lower()
            lowered_key = lowered.casefold()
            if len(letters) <= 2 and core.upper() == core and lowered_key not in _PROPERTY_SENTENCE_CASE_STOPWORDS:
                normalized_core = core
            else:
                normalized_core = lowered
                if alpha_token_index == 0 or lowered_key not in _PROPERTY_SENTENCE_CASE_STOPWORDS:
                    normalized_core = _capitalize_first_alpha(normalized_core)
            normalized_tokens.append(f"{leading}{normalized_core}{trailing}")
            alpha_token_index += 1
        return "".join(normalized_tokens).strip()

    tokens = re.split(r"(\s+)", raw)
    normalized_tokens: list[str] = []
    for token in tokens:
        if not token or token.isspace():
            normalized_tokens.append(token)
            continue
        leading_match = re.match(r"^[^A-Za-zÄÖÜäöüß]*", token)
        trailing_match = re.search(r"[^A-Za-zÄÖÜäöüß]*$", token)
        leading = leading_match.group(0) if leading_match else ""
        trailing = trailing_match.group(0) if trailing_match else ""
        end_index = len(token) - len(trailing) if trailing else len(token)
        core = token[len(leading):end_index]
        letters = [char for char in core if char.isalpha()]
        if not letters:
            normalized_tokens.append(token)
            continue
        upper_ratio = (sum(1 for char in letters if char.isupper()) / len(letters)) if letters else 0.0
        if len(letters) >= 3 and upper_ratio >= 0.8:
            core = core.lower()
        normalized_tokens.append(f"{leading}{core}{trailing}")
    normalized = "".join(normalized_tokens).strip()
    return _capitalize_first_alpha(normalized)


def sanitize_property_marketing_copy(value: object) -> str:
    text = " ".join(str(value or "").split()).strip()
    if not text:
        return ""
    if " - " in text:
        head, tail = text.rsplit(" - ", 1)
        tail_normalized = tail.strip().lower()
        if tail_normalized and (
            "." in tail_normalized or any(marker in tail_normalized for marker in _PROPERTY_PROVIDER_SUFFIX_MARKERS)
        ):
            text = head.strip()
    for pattern in _PROPERTY_PROVIDER_MARKETING_PATTERNS:
        text = re.sub(pattern, "", text, flags=re.IGNORECASE).strip()
    had_promo_separators = bool(re.search(r"\s+\|\s+|\s+I\s+", text))
    text = re.sub(r"\s+\|\s+", " · ", text)
    text = re.sub(r"\s+I\s+", " · ", text)
    if " · " in text:
        text = " · ".join(
            fragment
            for fragment in (
                _sentence_case_promotional_fragment(part)
                for part in re.split(r"\s*·\s*", text)
            )
            if fragment
        )
    text = text.strip(" -·|")
    if had_promo_separators and text and not re.search(r"[.!?]$", text):
        text = f"{text}."
    return text


def _looks_like_compact_property_headline(text: str) -> bool:
    if " · " not in text:
        return False
    fragments = [fragment.strip(" ,.;:-") for fragment in re.split(r"\s*·\s*", text) if fragment.strip(" ,.;:-")]
    if len(fragments) < 2 or len(fragments) > 5:
        return False
    if any(len(fragment) > 48 for fragment in fragments):
        return False
    word_total = sum(len(re.findall(r"[A-Za-zÄÖÜäöüß0-9/+-]+", fragment)) for fragment in fragments)
    if word_total > 16:
        return False
    return not any(re.search(r"[.!?].+\S", fragment) for fragment in fragments)


def _description_sentence_case_fragment(fragment: str, *, first: bool) -> str:
    text = str(fragment or "").strip(" ,.;:-")
    if not text or first:
        return text
    match = re.match(r"^([A-Za-zÄÖÜäöüß]+)", text)
    if not match:
        return text
    word = match.group(1)
    if len(word) <= 1 or word.isupper():
        return text
    return f"{word[0].lower()}{word[1:]}{text[len(word):]}"


def summarize_property_description_copy(value: object) -> str:
    text = sanitize_property_marketing_copy(value)
    if not text or not _looks_like_compact_property_headline(text):
        return text
    fragments = [
        _description_sentence_case_fragment(fragment, first=index == 0)
        for index, fragment in enumerate(re.split(r"\s*·\s*", text))
    ]
    summary = ", ".join(fragment for fragment in fragments if fragment).strip(" ,;:-")
    if summary and not re.search(r"[.!?]$", summary):
        summary = f"{summary}."
    return summary


def normalize_property_fit_note(value: object) -> str:
    raw_text = " ".join(str(value or "").split()).strip()
    if not raw_text:
        return ""
    text = sanitize_property_marketing_copy(raw_text)
    if not text:
        return ""
    if _looks_like_compact_property_headline(text):
        summarized = summarize_property_description_copy(text)
        return summarized or text

    text = re.sub(r"^\s*Chosen ahead of the next option because\s+", "", text, flags=re.IGNORECASE)
    text = re.sub(r"^\s*Ranked ahead of the next option because\s+", "", text, flags=re.IGNORECASE)
    text = re.sub(r"^\s*Chosen because\s+", "", text, flags=re.IGNORECASE)
    text = re.sub(
        r"\bit scored \d+(?:\.\d+)? points higher for your search\b",
        "it best matches your search",
        text,
        flags=re.IGNORECASE,
    )
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
        r"\bit stayed closest to your search on the available facts\b",
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

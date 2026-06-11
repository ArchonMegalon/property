from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable


_POSITIVE_HINTS = (
    "like",
    "love",
    "great",
    "good",
    "nice",
    "bright",
    "light",
    "layout",
    "balcony",
    "kitchen",
    "living",
    "space",
    "ruhig",
    "gefällt",
    "gut",
    "hell",
    "schnitt",
    "balkon",
    "küche",
)
_NEGATIVE_HINTS = (
    "don't like",
    "do not like",
    "hate",
    "bad",
    "small",
    "dark",
    "noise",
    "noisy",
    "expensive",
    "bathroom",
    "worry",
    "concern",
    "gefällt nicht",
    "schlecht",
    "klein",
    "dunkel",
    "laut",
    "teuer",
    "bad",
    "sorge",
)
_QUESTION_HINTS = (
    "?",
    "question",
    "ask",
    "unclear",
    "confirm",
    "wissen",
    "frage",
    "unklar",
    "bestätigen",
)
_DEALBREAKER_HINTS = (
    "dealbreaker",
    "blocker",
    "reject",
    "no way",
    "not acceptable",
    "ausschluss",
    "k.o.",
    "ko-kriterium",
    "ablehnen",
)


@dataclass(frozen=True)
class DadanFeedbackSignal:
    stakeholder_id: str
    stakeholder_label: str
    category: str
    sentiment: str
    importance: int
    text: str
    source_event_id: str
    decision_state: str = ""
    followup_status: str = ""

    def as_dict(self) -> dict[str, object]:
        return {
            "stakeholder_id": self.stakeholder_id,
            "stakeholder_label": self.stakeholder_label,
            "category": self.category,
            "sentiment": self.sentiment,
            "importance": self.importance,
            "text": self.text,
            "source_event_id": self.source_event_id,
            "decision_state": self.decision_state,
            "followup_status": self.followup_status,
        }


def _clean(value: object, *, max_len: int = 2000) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip())[:max_len]


def _lower(value: object) -> str:
    return _clean(value).lower()


def _contains_any(text: str, hints: Iterable[str]) -> bool:
    return any(hint in text for hint in hints)


def _answer_rows(payload: dict[str, object]) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for key in ("answers", "responses", "questions", "survey_answers"):
        raw = payload.get(key)
        if not isinstance(raw, list):
            continue
        for item in raw:
            if isinstance(item, dict):
                rows.append(dict(item))
            elif str(item or "").strip():
                rows.append({"answer": str(item)})
    return rows


def _row_text(row: dict[str, object]) -> str:
    answer_parts = []
    for key in ("answer", "answer_text", "response", "text", "transcript"):
        value = _clean(row.get(key), max_len=500)
        if value:
            answer_parts.append(value)
    if answer_parts:
        return " - ".join(answer_parts)
    parts = []
    for key in ("question", "question_text", "label", "prompt"):
        value = _clean(row.get(key), max_len=500)
        if value:
            parts.append(value)
    return " - ".join(parts)


def _signal_from_text(
    text: str,
    *,
    stakeholder_id: str,
    stakeholder_label: str,
    source_event_id: str,
    fallback_index: int,
) -> DadanFeedbackSignal | None:
    cleaned = _clean(text)
    if not cleaned:
        return None
    lowered = cleaned.lower()
    category = "concern"
    sentiment = "neutral"
    importance = 3
    decision_state = ""
    followup_status = ""
    if _contains_any(lowered, _DEALBREAKER_HINTS):
        category = "dealbreaker"
        sentiment = "negative"
        importance = 5
        decision_state = "rejected"
    elif _contains_any(lowered, _QUESTION_HINTS):
        category = "question"
        sentiment = "neutral"
        importance = 4
        followup_status = "suggested"
    elif _contains_any(lowered, _POSITIVE_HINTS) and not _contains_any(lowered, _NEGATIVE_HINTS):
        category = "love"
        sentiment = "positive"
        importance = 4
        decision_state = "interested"
    elif _contains_any(lowered, _NEGATIVE_HINTS):
        category = "concern"
        sentiment = "negative"
        importance = 4
    elif "must" in lowered or "need" in lowered or "wichtig" in lowered or "brauche" in lowered:
        category = "priority"
        sentiment = "neutral"
        importance = 4
    return DadanFeedbackSignal(
        stakeholder_id=stakeholder_id,
        stakeholder_label=stakeholder_label,
        category=category,
        sentiment=sentiment,
        importance=importance,
        text=cleaned,
        source_event_id=f"{source_event_id}:{fallback_index}"[:160],
        decision_state=decision_state,
        followup_status=followup_status,
    )


def dadan_feedback_signals(payload: dict[str, object]) -> list[DadanFeedbackSignal]:
    """Normalize Dadan survey/video answers into PropertyQuarry feedback signals.

    Dadan remains a capture provider. The resulting records intentionally use the
    existing PropertyQuarry feedback categories so downstream ranking, dossiers,
    and household summaries do not depend on Dadan-specific payload shapes.
    """

    stakeholder_id = _clean(
        payload.get("stakeholder_id")
        or payload.get("viewer_id")
        or payload.get("respondent_id")
        or payload.get("email")
        or "dadan-viewer",
        max_len=160,
    )
    stakeholder_label = _clean(
        payload.get("stakeholder_label") or payload.get("viewer_name") or payload.get("name") or stakeholder_id,
        max_len=160,
    )
    source_event_id = _clean(
        payload.get("source_event_id") or payload.get("event_id") or payload.get("submission_id") or payload.get("video_id") or "dadan",
        max_len=120,
    )
    texts: list[str] = []
    for row in _answer_rows(payload):
        text = _row_text(row)
        if text:
            texts.append(text)
    transcript = _clean(payload.get("transcript") or payload.get("summary") or payload.get("comment") or payload.get("note"))
    if transcript:
        texts.append(transcript)
    signals: list[DadanFeedbackSignal] = []
    seen: set[str] = set()
    for index, text in enumerate(texts, start=1):
        signal = _signal_from_text(
            text,
            stakeholder_id=stakeholder_id,
            stakeholder_label=stakeholder_label,
            source_event_id=source_event_id,
            fallback_index=index,
        )
        if signal is None:
            continue
        dedupe = f"{signal.category}:{signal.text.lower()}"
        if dedupe in seen:
            continue
        seen.add(dedupe)
        signals.append(signal)
    return signals[:12]

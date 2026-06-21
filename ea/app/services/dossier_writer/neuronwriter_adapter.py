from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

from app.services.dossier_writer.models import DossierNarrativeDraft, DossierPacketKind, NeuronWriterRecommendation
from app.services.dossier_writer.redaction import public_safe_topic_text


NEURONWRITER_ENDPOINT = "https://app.neuronwriter.com/neuron-api/0.5/writer"
PUBLIC_PACKET_KINDS: set[DossierPacketKind] = {"paid_market_report", "public_city_guide"}


def neuronwriter_enabled() -> bool:
    explicit = str(os.getenv("PROPERTYQUARRY_NEURONWRITER_ENABLED") or "").strip().lower()
    if explicit in {"0", "false", "no", "off", "disabled"}:
        return False
    if explicit in {"1", "true", "yes", "on", "enabled", "always"}:
        return True
    return False


def neuronwriter_required() -> bool:
    value = str(os.getenv("PROPERTYQUARRY_NEURONWRITER_REQUIRED") or "").strip().lower()
    return value in {"1", "true", "yes", "on", "enabled", "always"}


def neuronwriter_api_key() -> str:
    return str(os.getenv("NEURONWRITER_API_KEY") or "").strip()


def neuronwriter_allowed_for_draft(draft: DossierNarrativeDraft) -> tuple[bool, str]:
    mode = str(os.getenv("PROPERTYQUARRY_NEURONWRITER_DOSSIER_MODE") or "public_only").strip().lower()
    if mode in {"0", "off", "disabled", "none", "no_external"}:
        return False, "neuronwriter_dossier_mode_disabled"
    if draft.packet_kind in PUBLIC_PACKET_KINDS:
        return True, ""
    return False, "neuronwriter_private_packet_blocked"


def _post(method: str, payload: dict[str, object], *, api_key: str) -> dict[str, object]:
    request = urllib.request.Request(
        f"{NEURONWRITER_ENDPOINT}/{method.lstrip('/')}",
        data=json.dumps(payload).encode("utf-8"),
        headers={"X-API-KEY": api_key, "Content-Type": "application/json", "Accept": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=90) as response:
            body = response.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")
        raise RuntimeError(f"neuronwriter_http_{exc.code}:{detail[:240]}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"neuronwriter_unreachable:{exc.reason}") from exc
    parsed = json.loads(body or "{}")
    return parsed if isinstance(parsed, dict) else {"items": parsed}


def create_neuronwriter_query(
    *,
    keyword: str,
    project_id: str,
    language: str,
    engine: str,
    api_key: str | None = None,
) -> NeuronWriterRecommendation:
    key = api_key or neuronwriter_api_key()
    if not key:
        return NeuronWriterRecommendation(status="blocked", mode="api_live", reason="neuronwriter_api_key_missing")
    payload = {"project": project_id, "keyword": keyword, "language": language, "engine": engine}
    result = _post("new-query", payload, api_key=key)
    return NeuronWriterRecommendation(
        status="pending",
        mode="api_live",
        query_id=str(result.get("query") or "").strip(),
        query_url=str(result.get("query_url") or "").strip(),
        share_url=str(result.get("share_url") or "").strip(),
        readonly_url=str(result.get("readonly_url") or "").strip(),
        raw=result,
    )


def get_neuronwriter_query(query_id: str, *, api_key: str | None = None) -> NeuronWriterRecommendation:
    key = api_key or neuronwriter_api_key()
    if not key:
        return NeuronWriterRecommendation(status="blocked", mode="api_live", reason="neuronwriter_api_key_missing")
    result = _post("get-query", {"query": query_id}, api_key=key)
    status = str(result.get("status") or "ready").strip().lower()
    terms: list[str] = []
    headings: list[str] = []
    questions: list[str] = []
    for key_name, target in (("terms", terms), ("content_terms", terms), ("title_terms", terms), ("h1_terms", headings), ("h2_terms", headings), ("questions", questions)):
        raw = result.get(key_name)
        if isinstance(raw, list):
            target.extend(str(item.get("term") if isinstance(item, dict) else item or "").strip() for item in raw)
    return NeuronWriterRecommendation(
        status="ready" if status in {"ready", "done", "completed", ""} else "pending",
        mode="api_live",
        query_id=query_id,
        headings=[item for item in dict.fromkeys(headings) if item],
        terms=[item for item in dict.fromkeys(terms) if item],
        questions=[item for item in dict.fromkeys(questions) if item],
        raw=result,
    )


def recommend_for_draft(draft: DossierNarrativeDraft, *, query_id: str = "") -> NeuronWriterRecommendation:
    allowed, reason = neuronwriter_allowed_for_draft(draft)
    if not allowed:
        return NeuronWriterRecommendation(status="blocked", mode="private_packet_guard", reason=reason)
    if not neuronwriter_enabled():
        if neuronwriter_required():
            return NeuronWriterRecommendation(
                status="blocked",
                mode="public_safe_required",
                reason="neuronwriter_required_but_not_configured",
            )
        return NeuronWriterRecommendation(status="disabled", mode="public_safe", reason="neuronwriter_disabled")
    if query_id:
        try:
            return get_neuronwriter_query(query_id)
        except Exception as exc:
            return NeuronWriterRecommendation(status="failed", mode="api_live", query_id=query_id, reason=str(exc)[:240])
    topic = public_safe_topic_text(
        " ".join(
            part
            for section in draft.sections
            for part in (
                section.title,
                section.subtitle,
                section.body_markdown,
                " ".join(str(item or "") for item in section.bullets),
                section.cta,
            )
            if str(part or "").strip()
        )
    )
    key = neuronwriter_api_key()
    if not key:
        return NeuronWriterRecommendation(status="blocked", mode="api_live", reason="neuronwriter_api_key_missing")
    project_id = str(os.getenv("PROPERTYQUARRY_NEURONWRITER_PROJECT_ID") or "propertyquarry-de").strip()
    engine = str(os.getenv("PROPERTYQUARRY_NEURONWRITER_ENGINE") or "google.at").strip()
    language = str(os.getenv("PROPERTYQUARRY_NEURONWRITER_LANGUAGE") or draft.language or "German").strip()
    keyword = str(os.getenv("PROPERTYQUARRY_NEURONWRITER_KEYWORD") or topic or "Property dossier review").strip()
    try:
        return create_neuronwriter_query(keyword=keyword[:180], project_id=project_id, language=language, engine=engine, api_key=key)
    except Exception as exc:
        return NeuronWriterRecommendation(status="failed", mode="api_live", reason=str(exc)[:240])

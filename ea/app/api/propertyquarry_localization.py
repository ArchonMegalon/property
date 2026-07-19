from __future__ import annotations

import html
import re
import urllib.parse
from dataclasses import dataclass
from http.cookies import CookieError, SimpleCookie
from typing import Awaitable, Callable

from starlette.types import Message, Receive, Scope, Send


PROPERTYQUARRY_LOCALE_COOKIE = "pq_locale"
PROPERTYQUARRY_PUBLIC_LOCALES = ("en", "de-AT", "de-DE", "es-CR")
PROPERTYQUARRY_PSEUDO_LOCALE = "qps-ploc"
PROPERTYQUARRY_MAX_LOCALIZED_HTML_BYTES = 2 * 1024 * 1024

_LOCALE_LABELS = {
    "en": "English",
    "de-AT": "Deutsch (Österreich)",
    "de-DE": "Deutsch (Deutschland)",
    "es-CR": "Español (Costa Rica)",
}

_LOCALE_ALIASES = {
    "en": "en",
    "en-gb": "en",
    "en-us": "en",
    "de": "de-DE",
    "de-at": "de-AT",
    "de-de": "de-DE",
    "es": "es-CR",
    "es-cr": "es-CR",
}

_DE_AT = {
    "PropertyQuarry Search": "PropertyQuarry Suche",
    "PropertyQuarry Shortlist": "PropertyQuarry Merkliste",
    "PropertyQuarry Research": "PropertyQuarry Recherche",
    "Skip to content": "Zum Inhalt springen",
    "Try again": "Erneut versuchen",
    "Search": "Suche",
    "Shortlist": "Merkliste",
    "Research": "Recherche",
    "Account": "Konto",
    "Research desk": "Recherchebereich",
    "PropertyQuarry sections": "PropertyQuarry Bereiche",
    "PropertyQuarry public home": "Öffentliche PropertyQuarry Startseite",
    "Dark mode": "Dunkelmodus",
    "Browser alerts": "Browser-Benachrichtigungen",
    "Saved defaults": "Gespeicherte Vorgaben",
    "Access": "Zugriff",
    "Billing": "Abrechnung",
    "Log out": "Abmelden",
    "Account navigation": "Kontonavigation",
    "Launch search": "Suche starten",
    "Search brief": "Suchprofil",
    "Adjust search": "Suche anpassen",
    "Back": "Zurück",
    "Next": "Weiter",
    "Save search": "Suche speichern",
    "Save changes": "Änderungen speichern",
    "Save as new": "Als neu speichern",
    "Reset": "Zurücksetzen",
    "Search flow": "Suchablauf",
    "Find a home": "Wohnung oder Haus finden",
    "Find an investment": "Anlageimmobilie finden",
    "What are you looking for?": "Wonach suchen Sie?",
    "Country": "Land",
    "Austria": "Österreich",
    "Germany": "Deutschland",
    "Costa Rica": "Costa Rica",
    "Rent": "Mieten",
    "Buy": "Kaufen",
    "Search mode": "Suchmodus",
    "Property type": "Immobilienart",
    "Off": "Aus",
    "Investment research": "Anlagerecherche",
    "Investment research on buy listings": "Anlagerecherche bei Kaufangeboten",
    "Investment strategy": "Anlagestrategie",
    "Best overall opportunity": "Beste Gesamtchance",
    "Cash flow": "Cashflow",
    "Appreciation": "Wertsteigerung",
    "Undervalued": "Unterbewertet",
    "Low risk": "Geringes Risiko",
    "State or metro area": "Bundesland oder Ballungsraum",
    "Target areas": "Zielgebiete",
    "Map": "Karte",
    "List": "Liste",
    "All areas": "Alle Gebiete",
    "Clear": "Leeren",
    "Done": "Fertig",
    "Zoom": "Zoom",
    "Meters": "Meter",
    "Kilometers": "Kilometer",
    "Unit": "Einheit",
    "Add areas manually": "Gebiete manuell hinzufügen",
    "Search sources": "Suchquellen",
    "All sites": "Alle Portale",
    "Result mode": "Ergebnismodus",
    "Strict shortlist": "Strenge Merkliste",
    "Discovery pass": "Breite Suche",
    "Load": "Laden",
    "Save": "Speichern",
    "Saved": "Gespeichert",
    "What matters": "Was wichtig ist",
    "Home": "Wohnen",
    "Daily life": "Alltag",
    "Checks": "Prüfpunkte",
    "Neutral": "Neutral",
    "Avoid": "Vermeiden",
    "Nice to have": "Wünschenswert",
    "Strong wish": "Starker Wunsch",
    "Must have": "Unverzichtbar",
    "saved homes": "gespeicherte Immobilien",
    "Open score guide": "Bewertungsleitfaden öffnen",
    "Start search": "Suche starten",
    "Property research": "Immobilienrecherche",
    "Research updated": "Recherche aktualisiert",
    "Research packet": "Recherchepaket",
    "Back to shortlist": "Zurück zur Merkliste",
    "Open property": "Immobilie öffnen",
    "Evidence": "Nachweise",
    "Decision": "Entscheidung",
    "Reactions": "Reaktionen",
    "What changed": "Was sich geändert hat",
    "Follow-up": "Nachfassen",
    "Yes": "Ja",
    "No": "Nein",
    "Maybe": "Vielleicht",
    "Request documents": "Unterlagen anfordern",
    "View shortlist": "Merkliste ansehen",
    "You’re offline.": "Sie sind offline.",
    "Keep this page open. Reconnect, then try again. Your saved work is unchanged.": (
        "Lassen Sie diese Seite geöffnet. Stellen Sie die Verbindung wieder her und versuchen Sie es erneut. "
        "Ihre gespeicherten Daten bleiben unverändert."
    ),
}

_DE_DE = {
    **_DE_AT,
    "Research desk": "Recherchebereich",
    "Find a home": "Wohnung oder Haus finden",
    "State or metro area": "Bundesland oder Metropolregion",
}

_ES_CR = {
    "PropertyQuarry Search": "Búsqueda de PropertyQuarry",
    "PropertyQuarry Shortlist": "Favoritos de PropertyQuarry",
    "PropertyQuarry Research": "Investigación de PropertyQuarry",
    "Skip to content": "Saltar al contenido",
    "Try again": "Intentar de nuevo",
    "Search": "Buscar",
    "Shortlist": "Favoritos",
    "Research": "Investigación",
    "Account": "Cuenta",
    "Research desk": "Mesa de investigación",
    "PropertyQuarry sections": "Secciones de PropertyQuarry",
    "PropertyQuarry public home": "Inicio público de PropertyQuarry",
    "Dark mode": "Modo oscuro",
    "Browser alerts": "Alertas del navegador",
    "Saved defaults": "Preferencias guardadas",
    "Access": "Acceso",
    "Billing": "Facturación",
    "Log out": "Cerrar sesión",
    "Account navigation": "Navegación de la cuenta",
    "Launch search": "Iniciar búsqueda",
    "Search brief": "Perfil de búsqueda",
    "Adjust search": "Ajustar búsqueda",
    "Back": "Atrás",
    "Next": "Siguiente",
    "Save search": "Guardar búsqueda",
    "Save changes": "Guardar cambios",
    "Save as new": "Guardar como nueva",
    "Reset": "Restablecer",
    "Search flow": "Flujo de búsqueda",
    "Find a home": "Buscar vivienda",
    "Find an investment": "Buscar inversión",
    "What are you looking for?": "¿Qué está buscando?",
    "Country": "País",
    "Austria": "Austria",
    "Germany": "Alemania",
    "Costa Rica": "Costa Rica",
    "Rent": "Alquilar",
    "Buy": "Comprar",
    "Search mode": "Modalidad de búsqueda",
    "Property type": "Tipo de propiedad",
    "Off": "Desactivado",
    "Investment research": "Investigación de inversión",
    "Investment research on buy listings": "Investigación de inversión en propiedades en venta",
    "Investment strategy": "Estrategia de inversión",
    "Best overall opportunity": "Mejor oportunidad general",
    "Cash flow": "Flujo de caja",
    "Appreciation": "Plusvalía",
    "Undervalued": "Subvalorada",
    "Low risk": "Riesgo bajo",
    "State or metro area": "Provincia o área metropolitana",
    "Target areas": "Zonas objetivo",
    "Map": "Mapa",
    "List": "Lista",
    "All areas": "Todas las zonas",
    "Clear": "Limpiar",
    "Done": "Listo",
    "Zoom": "Acercamiento",
    "Meters": "Metros",
    "Kilometers": "Kilómetros",
    "Unit": "Unidad",
    "Add areas manually": "Agregar zonas manualmente",
    "Search sources": "Fuentes de búsqueda",
    "All sites": "Todos los portales",
    "Result mode": "Modo de resultados",
    "Strict shortlist": "Favoritos estrictos",
    "Discovery pass": "Exploración amplia",
    "Load": "Cargar",
    "Save": "Guardar",
    "Saved": "Guardado",
    "What matters": "Lo que importa",
    "Home": "Vivienda",
    "Daily life": "Vida diaria",
    "Checks": "Verificaciones",
    "Neutral": "Neutral",
    "Avoid": "Evitar",
    "Nice to have": "Deseable",
    "Strong wish": "Muy deseable",
    "Must have": "Indispensable",
    "saved homes": "viviendas guardadas",
    "Open score guide": "Abrir guía de puntaje",
    "Start search": "Iniciar búsqueda",
    "Property research": "Investigación de la propiedad",
    "Research updated": "Investigación actualizada",
    "Research packet": "Paquete de investigación",
    "Back to shortlist": "Volver a favoritos",
    "Open property": "Abrir propiedad",
    "Evidence": "Evidencia",
    "Decision": "Decisión",
    "Reactions": "Reacciones",
    "What changed": "Qué cambió",
    "Follow-up": "Seguimiento",
    "Yes": "Sí",
    "No": "No",
    "Maybe": "Tal vez",
    "Request documents": "Solicitar documentos",
    "View shortlist": "Ver favoritos",
    "You’re offline.": "Está sin conexión.",
    "Keep this page open. Reconnect, then try again. Your saved work is unchanged.": (
        "Mantenga esta página abierta. Vuelva a conectarse e inténtelo de nuevo. "
        "Su trabajo guardado no cambia."
    ),
}

_TRANSLATIONS = {
    "de-AT": _DE_AT,
    "de-DE": _DE_DE,
    "es-CR": _ES_CR,
}

_STATUS_COPY = {
    "en": (
        "Language and translation status",
        "This route uses the English source interface. Legal terms and provider-specific copy remain in English.",
        "Localized interface copy has not been professionally reviewed.",
    ),
    "de-AT": (
        "Sprache und Übersetzungsstatus",
        "Die zentrale Benutzeroberfläche ist auf Deutsch verfügbar. Rechtliche Hinweise, Anbietertexte und noch nicht übersetzte Inhalte bleiben auf Englisch.",
        "Die Übersetzung wurde nicht professionell geprüft.",
    ),
    "de-DE": (
        "Sprache und Übersetzungsstatus",
        "Die zentrale Benutzeroberfläche ist auf Deutsch verfügbar. Rechtliche Hinweise, Anbietertexte und noch nicht übersetzte Inhalte bleiben auf Englisch.",
        "Die Übersetzung wurde nicht professionell geprüft.",
    ),
    "es-CR": (
        "Idioma y estado de traducción",
        "La interfaz principal está disponible en español. Los textos legales, de proveedores y aún no traducidos permanecen en inglés.",
        "La traducción no ha sido revisada profesionalmente.",
    ),
}

_PROTECTED_BLOCK_RE = re.compile(
    r"(<script\b[^>]*>.*?</script\s*>"
    r"|<style\b[^>]*>.*?</style\s*>"
    r"|<pre\b[^>]*>.*?</pre\s*>"
    r"|<code\b[^>]*>.*?</code\s*>"
    r"|<textarea\b[^>]*>.*?</textarea\s*>"
    r"|<template\b[^>]*>.*?</template\s*>"
    r"|<svg\b[^>]*>.*?</svg\s*>)",
    re.IGNORECASE | re.DOTALL,
)
_TEXT_NODE_RE = re.compile(r">(?P<text>[^<>]+)<")
_TRANSLATABLE_ATTRIBUTE_RE = re.compile(
    r"(?P<prefix>\b(?P<name>href|action|aria-label|title|placeholder)\s*=\s*)"
    r"(?P<quote>['\"])(?P<value>.*?)(?P=quote)",
    re.IGNORECASE | re.DOTALL,
)
_HTML_TAG_RE = re.compile(r"<html\b(?P<attrs>[^>]*)>", re.IGNORECASE)
_HTML_LANG_RE = re.compile(r"\s+lang\s*=\s*(['\"]).*?\1", re.IGNORECASE | re.DOTALL)
_HEAD_CONTENT_RE = re.compile(r"<head\b[^>]*>(?P<content>.*?)</head\s*>", re.IGNORECASE | re.DOTALL)
_META_TAG_RE = re.compile(r"<meta\b[^>]*>", re.IGNORECASE | re.DOTALL)
_TAG_ATTRIBUTE_RE = re.compile(
    r"\b(?P<name>[A-Za-z_:][A-Za-z0-9_.:-]*)\s*=\s*"
    r"(?P<quote>['\"])(?P<value>.*?)(?P=quote)",
    re.DOTALL,
)
_TRANSLATED_ROUTE_RE = re.compile(
    r"^/app/(?:search|properties|shortlist(?:/run/[^/]+)?|research(?:/[^/]+)?)/*$"
)
_LOCALIZATION_SLOT = '<span data-pq-localization-slot></span>'
_SAFE_QUERY_KEY_RE = re.compile(r"^[A-Za-z0-9_.-]{1,64}$")
_SENSITIVE_QUERY_KEY_PARTS = ("token", "secret", "password", "auth", "email", "code", "key")
_ACCEPT_LANGUAGE_Q_RE = re.compile(r"^(?:0(?:\.[0-9]{0,3})?|1(?:\.0{0,3})?)$")
_PSEUDO_ACCENTS = str.maketrans(
    {
        "a": "à",
        "b": "ƀ",
        "c": "ç",
        "d": "ď",
        "e": "ë",
        "f": "ƒ",
        "g": "ğ",
        "h": "ħ",
        "i": "ï",
        "j": "ĵ",
        "k": "ķ",
        "l": "ľ",
        "m": "ɱ",
        "n": "ñ",
        "o": "ô",
        "p": "þ",
        "q": "ɋ",
        "r": "ř",
        "s": "š",
        "t": "ŧ",
        "u": "ü",
        "v": "ṽ",
        "w": "ŵ",
        "x": "ẋ",
        "y": "ÿ",
        "z": "ž",
        "A": "À",
        "E": "Ë",
        "I": "Ï",
        "O": "Ô",
        "U": "Ü",
    }
)


@dataclass(frozen=True)
class PropertyQuarryLocaleDecision:
    locale: str
    source: str
    query_locale_valid: bool = False
    query_locale_rejected: bool = False


def normalize_propertyquarry_locale(value: object, *, allow_pseudo: bool = False) -> str | None:
    raw = str(value or "").strip().replace("_", "-")
    if not raw or len(raw) > 32 or any(ord(character) < 32 for character in raw):
        return None
    if allow_pseudo and raw.casefold() == PROPERTYQUARRY_PSEUDO_LOCALE:
        return PROPERTYQUARRY_PSEUDO_LOCALE
    return _LOCALE_ALIASES.get(raw.casefold())


def _parse_query_pairs(query_string: bytes | str) -> list[tuple[str, str]]:
    raw = query_string.decode("utf-8", errors="replace") if isinstance(query_string, bytes) else str(query_string or "")
    try:
        return urllib.parse.parse_qsl(raw[:8192], keep_blank_values=True, max_num_fields=64)
    except ValueError:
        return []


def _header_value(headers: list[tuple[bytes, bytes]], name: str) -> str:
    expected = name.lower().encode("ascii")
    values = [value.decode("latin-1") for key, value in headers if key.lower() == expected]
    return ",".join(values)


def _cookie_locale(raw_cookie: str) -> str | None:
    if not raw_cookie or len(raw_cookie) > 8192:
        return None
    cookie = SimpleCookie()
    try:
        cookie.load(raw_cookie)
    except CookieError:
        return None
    morsel = cookie.get(PROPERTYQUARRY_LOCALE_COOKIE)
    return normalize_propertyquarry_locale(morsel.value if morsel is not None else "")


def _accept_language_locale(raw_header: str) -> str | None:
    ranked: list[tuple[float, int, str]] = []
    for position, part in enumerate(str(raw_header or "")[:1024].split(",")[:16]):
        pieces = [piece.strip() for piece in part.split(";") if piece.strip()]
        if not pieces or pieces[0] == "*":
            continue
        quality = 1.0
        quality_seen = False
        quality_valid = True
        for parameter in pieces[1:]:
            name, separator, raw_quality = parameter.partition("=")
            if name.strip().casefold() != "q":
                continue
            if (
                quality_seen
                or not separator
                or not _ACCEPT_LANGUAGE_Q_RE.fullmatch(raw_quality.strip())
            ):
                quality_valid = False
                break
            quality_seen = True
            quality = float(raw_quality.strip())
        if not quality_valid:
            continue
        locale = normalize_propertyquarry_locale(pieces[0])
        if locale is not None and quality > 0:
            ranked.append((quality, -position, locale))
    return max(ranked)[2] if ranked else None


def resolve_propertyquarry_locale(
    *,
    query_string: bytes | str = b"",
    headers: list[tuple[bytes, bytes]] | tuple[tuple[bytes, bytes], ...] = (),
) -> PropertyQuarryLocaleDecision:
    header_list = list(headers)
    query_values = [value for key, value in _parse_query_pairs(query_string) if key == "lang"]
    if query_values:
        query_locale = normalize_propertyquarry_locale(query_values[-1])
        if query_locale is not None:
            return PropertyQuarryLocaleDecision(query_locale, "query", query_locale_valid=True)
    cookie_locale = _cookie_locale(_header_value(header_list, "cookie"))
    if cookie_locale is not None:
        return PropertyQuarryLocaleDecision(
            cookie_locale,
            "cookie",
            query_locale_rejected=bool(query_values),
        )
    accepted_locale = _accept_language_locale(_header_value(header_list, "accept-language"))
    if accepted_locale is not None:
        return PropertyQuarryLocaleDecision(
            accepted_locale,
            "accept-language",
            query_locale_rejected=bool(query_values),
        )
    return PropertyQuarryLocaleDecision("en", "default", query_locale_rejected=bool(query_values))


def propertyquarry_locale_cookie_header(locale: str, *, secure: bool) -> str:
    normalized = normalize_propertyquarry_locale(locale)
    if normalized is None:
        raise ValueError("unsupported_propertyquarry_locale")
    parts = [
        f"{PROPERTYQUARRY_LOCALE_COOKIE}={normalized}",
        "Path=/",
        "Max-Age=15552000",
        "HttpOnly",
        "SameSite=Lax",
    ]
    if secure:
        parts.append("Secure")
    return "; ".join(parts)


def propertyquarry_route_is_translated(path: str) -> bool:
    return bool(_TRANSLATED_ROUTE_RE.fullmatch(str(path or "")))


def _pseudo_localize(value: str) -> str:
    accented = value.translate(_PSEUDO_ACCENTS)
    expanded = re.sub(r"([àëïôüÀËÏÔÜ])", r"\1\1", accented)
    return f"[!! {expanded} — ẋẋ !!]"


def propertyquarry_translation(value: str, *, locale: str) -> str:
    normalized = normalize_propertyquarry_locale(locale, allow_pseudo=True)
    if normalized is None:
        raise ValueError("unsupported_propertyquarry_locale")
    if normalized == PROPERTYQUARRY_PSEUDO_LOCALE:
        return _pseudo_localize(str(value))
    if normalized == "en":
        return str(value)
    return _TRANSLATIONS[normalized].get(str(value), str(value))


def propertyquarry_translation_coverage(locale: str) -> dict[str, object]:
    normalized = normalize_propertyquarry_locale(locale, allow_pseudo=True)
    if normalized is None:
        raise ValueError("unsupported_propertyquarry_locale")
    source_messages = frozenset(_DE_AT)
    translated_messages = source_messages if normalized in {"en", PROPERTYQUARRY_PSEUDO_LOCALE} else frozenset(_TRANSLATIONS[normalized])
    return {
        "locale": normalized,
        "critical_source_messages": len(source_messages),
        "critical_translated_messages": len(source_messages.intersection(translated_messages)),
        "missing_critical_messages": sorted(source_messages.difference(translated_messages)),
        "coverage_scope": "critical_customer_ui_shell",
        "english_fallback_scopes": ["legal", "provider_specific", "incomplete"],
        "professional_review": False,
    }


def _safe_query_pairs(query_string: bytes | str) -> list[tuple[str, str]]:
    safe: list[tuple[str, str]] = []
    for key, value in _parse_query_pairs(query_string):
        lowered_key = key.casefold()
        if key == "lang" or not _SAFE_QUERY_KEY_RE.fullmatch(key):
            continue
        if any(part in lowered_key for part in _SENSITIVE_QUERY_KEY_PARTS):
            continue
        if len(value) > 512 or any(ord(character) < 32 for character in value):
            continue
        safe.append((key, value))
    return safe[:32]


def _route_url(
    *,
    path: str,
    query_string: bytes | str,
    locale: str,
) -> str:
    query = _safe_query_pairs(query_string)
    query.append(("lang", locale))
    return urllib.parse.urlunsplit(("", "", path, urllib.parse.urlencode(query), ""))


def _localized_internal_url(value: str, *, locale: str) -> str:
    raw = html.unescape(str(value or "").strip())
    if not raw or raw.startswith(("#", "//")):
        return raw
    parsed = urllib.parse.urlsplit(raw)
    if parsed.scheme or parsed.netloc:
        return raw
    path = parsed.path
    if (
        (path != "/app" and not path.startswith("/app/"))
        or path.startswith(("/app/api", "/app/assets", "/app/actions"))
    ):
        return raw
    query = [(key, item) for key, item in urllib.parse.parse_qsl(parsed.query, keep_blank_values=True) if key != "lang"]
    query.append(("lang", locale))
    return urllib.parse.urlunsplit(("", "", path, urllib.parse.urlencode(query), parsed.fragment))


def _translate_text_node(raw_text: str, *, locale: str) -> str:
    if not raw_text.strip():
        return raw_text
    leading = raw_text[: len(raw_text) - len(raw_text.lstrip())]
    trailing = raw_text[len(raw_text.rstrip()) :]
    normalized_text = " ".join(html.unescape(raw_text.strip()).split())
    translated = propertyquarry_translation(normalized_text, locale=locale)
    if translated == normalized_text and locale != PROPERTYQUARRY_PSEUDO_LOCALE:
        return raw_text
    return f"{leading}{html.escape(translated, quote=False)}{trailing}"


def _localize_unprotected_html(segment: str, *, locale: str, preserve_locale_in_urls: bool) -> str:
    def replace_attribute(match: re.Match[str]) -> str:
        name = match.group("name").lower()
        value = match.group("value")
        if name in {"href", "action"}:
            if not preserve_locale_in_urls:
                return match.group(0)
            translated_value = _localized_internal_url(value, locale=locale)
        else:
            normalized_value = " ".join(html.unescape(value).split())
            translated_value = propertyquarry_translation(normalized_value, locale=locale)
            if translated_value == normalized_value and locale != PROPERTYQUARRY_PSEUDO_LOCALE:
                return match.group(0)
        return f"{match.group('prefix')}{match.group('quote')}{html.escape(translated_value, quote=True)}{match.group('quote')}"

    with_attributes = _TRANSLATABLE_ATTRIBUTE_RE.sub(replace_attribute, segment)
    return _TEXT_NODE_RE.sub(
        lambda match: f">{_translate_text_node(match.group('text'), locale=locale)}<",
        with_attributes,
    )


def _set_html_lang(document: str, locale: str) -> str:
    def replace(match: re.Match[str]) -> str:
        attrs = _HTML_LANG_RE.sub("", match.group("attrs"))
        return f'<html{attrs} lang="{html.escape(locale, quote=True)}">'

    return _HTML_TAG_RE.sub(replace, document, count=1)


def _is_propertyquarry_document(document: str) -> bool:
    head_match = _HEAD_CONTENT_RE.search(str(document)[:131_072])
    if head_match is None:
        return False
    head_content = _PROTECTED_BLOCK_RE.sub("", head_match.group("content"))
    for meta_tag in _META_TAG_RE.findall(head_content):
        attributes = {
            match.group("name").casefold(): html.unescape(match.group("value")).strip()
            for match in _TAG_ATTRIBUTE_RE.finditer(meta_tag)
        }
        if (
            attributes.get("name", "").casefold() == "application-name"
            and attributes.get("content", "").casefold() == "propertyquarry"
        ):
            return True
    return False


def _status_copy(locale: str) -> tuple[str, str, str]:
    if locale == PROPERTYQUARRY_PSEUDO_LOCALE:
        return tuple(_pseudo_localize(item) for item in _STATUS_COPY["en"])  # type: ignore[return-value]
    return _STATUS_COPY[locale]


def _head_markup(
    *,
    locale: str,
) -> str:
    return (
        '<meta data-pq-localization-head name="propertyquarry:translation-status" '
        'content="critical-ui-shell; english-fallback-legal-provider-incomplete; not-professionally-reviewed">'
        '<link rel="stylesheet" href="/static/propertyquarry-localization.css">'
        f'<meta name="propertyquarry:locale" content="{html.escape(locale, quote=True)}">'
    )


def _selector_markup(
    *,
    path: str,
    query_string: bytes | str,
    locale: str,
    placement: str,
) -> str:
    heading, fallback_status, review_status = _status_copy(locale)
    current_label = _LOCALE_LABELS.get(locale, "Pseudo locale")
    options: list[str] = []
    for target_locale in PROPERTYQUARRY_PUBLIC_LOCALES:
        href = _route_url(path=path, query_string=query_string, locale=target_locale)
        current = ' aria-current="true"' if target_locale == locale else ""
        options.append(
            f'<a href="{html.escape(href, quote=True)}" hreflang="{target_locale}" lang="{target_locale}"{current}>'
            f'{html.escape(_LOCALE_LABELS[target_locale])}</a>'
        )
    return (
        f'<aside class="pq-locale-panel" data-pq-localization-status data-pq-locale="{html.escape(locale, quote=True)}" '
        f'data-pq-localization-placement="{html.escape(placement, quote=True)}" '
        'data-pq-localization-coverage="critical-customer-ui-shell" '
        'data-pq-english-fallback="legal provider-specific incomplete" '
        'data-pq-professional-review="false" role="note" '
        f'aria-label="{html.escape(heading, quote=True)}">'
        '<details class="pq-locale-disclosure">'
        f'<summary aria-label="{html.escape(f"{heading}: {current_label}", quote=True)}">'
        '<span class="pq-locale-glyph" aria-hidden="true">A/文</span>'
        f'<span class="pq-locale-current" lang="{html.escape(locale, quote=True)}">{html.escape(current_label)}</span>'
        '</summary>'
        '<div class="pq-locale-menu">'
        f'<strong>{html.escape(heading)}</strong>'
        f'<nav class="pq-locale-options" data-pq-locale-selector aria-label="{html.escape(heading, quote=True)}">'
        f'{"<span aria-hidden=\"true\"> · </span>".join(options)}</nav>'
        f'<p>{html.escape(fallback_status)} {html.escape(review_status)}</p>'
        '</div></details>'
        '</aside>'
    )


def localize_propertyquarry_html(
    document: str,
    *,
    locale: str,
    path: str,
    query_string: bytes | str = b"",
    preserve_locale_in_urls: bool = True,
) -> str:
    normalized_locale = normalize_propertyquarry_locale(locale, allow_pseudo=True)
    if normalized_locale is None:
        raise ValueError("unsupported_propertyquarry_locale")
    translated_path = propertyquarry_route_is_translated(path)
    if not translated_path:
        return document
    parts = _PROTECTED_BLOCK_RE.split(str(document))
    localized_parts = [
        part
        if index % 2
        else _localize_unprotected_html(
            part,
            locale=normalized_locale,
            preserve_locale_in_urls=preserve_locale_in_urls,
        )
        for index, part in enumerate(parts)
    ]
    localized = _set_html_lang("".join(localized_parts), normalized_locale)
    if "data-pq-localization-head" not in localized:
        localized = re.sub(
            r"</head\s*>",
            f"{_head_markup(locale=normalized_locale)}</head>",
            localized,
            count=1,
            flags=re.IGNORECASE,
        )
    if "data-pq-localization-status" not in localized:
        if _LOCALIZATION_SLOT in localized:
            localized = localized.replace(
                _LOCALIZATION_SLOT,
                _selector_markup(
                    path=path,
                    query_string=query_string,
                    locale=normalized_locale,
                    placement="integrated",
                ),
                1,
            )
        else:
            localized = re.sub(
                r"</body\s*>",
                f"{_selector_markup(path=path, query_string=query_string, locale=normalized_locale, placement='floating')}</body>",
                localized,
                count=1,
                flags=re.IGNORECASE,
            )
    return localized


def _replace_single_header(headers: list[tuple[bytes, bytes]], name: str, value: str) -> list[tuple[bytes, bytes]]:
    encoded_name = name.lower().encode("ascii")
    updated = [(key, item) for key, item in headers if key.lower() != encoded_name]
    updated.append((encoded_name, value.encode("latin-1")))
    return updated


def _drop_headers(headers: list[tuple[bytes, bytes]], *names: str) -> list[tuple[bytes, bytes]]:
    dropped = {name.lower().encode("ascii") for name in names}
    return [(key, value) for key, value in headers if key.lower() not in dropped]


def _append_vary(headers: list[tuple[bytes, bytes]], *names: str) -> list[tuple[bytes, bytes]]:
    existing = _header_value(headers, "vary")
    values = [item.strip() for item in existing.split(",") if item.strip()]
    lowered = {item.casefold() for item in values}
    for name in names:
        if name.casefold() not in lowered:
            values.append(name)
            lowered.add(name.casefold())
    return _replace_single_header(headers, "Vary", ", ".join(values))


def _scope_is_secure(scope: Scope) -> bool:
    return str(scope.get("scheme") or "").strip().casefold() == "https"


def _content_type_is_utf8_html(content_type: str) -> bool:
    parts = [part.strip() for part in str(content_type or "").split(";")]
    if not parts or parts[0].casefold() != "text/html":
        return False
    charsets: list[str] = []
    for parameter in parts[1:]:
        name, separator, value = parameter.partition("=")
        if name.strip().casefold() != "charset":
            continue
        if not separator:
            return False
        charset = value.strip().strip("\"'").casefold().replace("_", "-")
        charsets.append(charset)
    return not charsets or all(charset in {"utf-8", "utf8"} for charset in charsets)


def _content_length_within_limit(headers: list[tuple[bytes, bytes]], limit: int) -> bool:
    raw_length = _header_value(headers, "content-length").strip()
    if not raw_length:
        return True
    if not raw_length.isdecimal():
        return False
    return int(raw_length) <= limit


def _prepare_response_start(
    response_start: Message,
    *,
    decision: PropertyQuarryLocaleDecision,
    secure_cookie: bool,
    content_language: str | None = None,
    vary_by_locale: bool = False,
    localized_representation: bool = False,
) -> Message:
    prepared = dict(response_start)
    headers = list(prepared.get("headers") or [])
    if content_language is not None:
        headers = _replace_single_header(headers, "Content-Language", content_language)
    if vary_by_locale:
        headers = _append_vary(headers, "Cookie", "Accept-Language")
    if localized_representation:
        headers = _replace_single_header(
            headers,
            "X-PropertyQuarry-Translation-Status",
            "critical-ui-shell; english-fallback-legal-provider-incomplete; not-professionally-reviewed",
        )
    else:
        headers = _drop_headers(headers, "x-propertyquarry-translation-status")
    if decision.query_locale_valid:
        headers.append(
            (
                b"set-cookie",
                propertyquarry_locale_cookie_header(
                    decision.locale,
                    secure=secure_cookie,
                ).encode("latin-1"),
            )
        )
    prepared["headers"] = headers
    return prepared


class PropertyQuarryLocalizationMiddleware:
    def __init__(
        self,
        app: Callable[[Scope, Receive, Send], Awaitable[None]],
        *,
        max_html_bytes: int = PROPERTYQUARRY_MAX_LOCALIZED_HTML_BYTES,
    ) -> None:
        self.app = app
        configured_limit = int(max_html_bytes)
        if configured_limit < 1:
            raise ValueError("max_html_bytes_must_be_positive")
        self.max_html_bytes = min(configured_limit, PROPERTYQUARRY_MAX_LOCALIZED_HTML_BYTES)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope.get("type") != "http" or str(scope.get("method") or "GET").upper() not in {"GET", "HEAD"}:
            await self.app(scope, receive, send)
            return
        path = str(scope.get("path") or "")
        if not propertyquarry_route_is_translated(path):
            await self.app(scope, receive, send)
            return

        request_headers = list(scope.get("headers") or [])
        query_string = scope.get("query_string") or b""
        decision = resolve_propertyquarry_locale(query_string=query_string, headers=request_headers)
        preserve_locale = decision.source != "default" or decision.locale != "en"
        method = str(scope.get("method") or "GET").upper()
        secure_cookie = _scope_is_secure(scope)
        pending_start: Message | None = None
        buffered_body: list[Message] = []
        buffered_size = 0
        passthrough = False

        async def flush_source_response(*, propertyquarry_document: bool = False) -> None:
            nonlocal pending_start, buffered_body, buffered_size, passthrough
            if pending_start is None:
                return
            source_start = pending_start
            if propertyquarry_document:
                source_start = _prepare_response_start(
                    source_start,
                    decision=decision,
                    secure_cookie=secure_cookie,
                    content_language="en",
                )
            await send(source_start)
            for buffered_message in buffered_body:
                await send(buffered_message)
            pending_start = None
            buffered_body = []
            buffered_size = 0
            passthrough = True

        async def localized_send(message: Message) -> None:
            nonlocal pending_start, buffered_body, buffered_size, passthrough
            message_type = message.get("type")
            if message_type == "http.response.start":
                status = int(message.get("status") or 200)
                headers = list(message.get("headers") or [])
                content_type = _header_value(headers, "content-type")
                content_encoding = _header_value(headers, "content-encoding").strip()
                redirect_response = 300 <= status < 400

                if redirect_response:
                    await send(message)
                    passthrough = True
                    return

                inspectable_html = (
                    _content_type_is_utf8_html(content_type)
                    and not content_encoding
                    and _content_length_within_limit(headers, self.max_html_bytes)
                )
                if inspectable_html and method == "GET":
                    pending_start = dict(message)
                    return

                await send(message)
                passthrough = True
                return

            if passthrough or pending_start is None:
                await send(message)
                return

            if message_type != "http.response.body":
                await flush_source_response()
                await send(message)
                return

            buffered_message = dict(message)
            buffered_message["body"] = bytes(message.get("body") or b"")
            buffered_body.append(buffered_message)
            buffered_size += len(buffered_message["body"])
            if buffered_size > self.max_html_bytes:
                await flush_source_response()
                return
            if message.get("more_body"):
                return

            body = b"".join(
                bytes(buffered_message.get("body") or b"")
                for buffered_message in buffered_body
            )
            try:
                source = body.decode("utf-8")
            except UnicodeDecodeError:
                await flush_source_response()
                return

            propertyquarry_document = _is_propertyquarry_document(source)
            if not propertyquarry_document:
                await flush_source_response()
                return

            status = int(pending_start.get("status") or 200)
            if not 200 <= status < 300:
                await flush_source_response(propertyquarry_document=True)
                return

            localized_body = localize_propertyquarry_html(
                source,
                locale=decision.locale,
                path=path,
                query_string=query_string,
                preserve_locale_in_urls=preserve_locale,
            ).encode("utf-8")
            if len(localized_body) > self.max_html_bytes:
                await flush_source_response(propertyquarry_document=True)
                return

            localized_start = dict(pending_start)
            localized_headers = _drop_headers(
                list(localized_start.get("headers") or []),
                "content-length",
                "etag",
                "content-md5",
            )
            localized_headers = _replace_single_header(
                localized_headers,
                "Content-Length",
                str(len(localized_body)),
            )
            localized_start["headers"] = localized_headers
            await send(
                _prepare_response_start(
                    localized_start,
                    decision=decision,
                    secure_cookie=secure_cookie,
                    content_language=decision.locale,
                    vary_by_locale=True,
                    localized_representation=True,
                )
            )
            await send({"type": "http.response.body", "body": localized_body, "more_body": False})
            pending_start = None
            buffered_body = []
            buffered_size = 0
            passthrough = True

        await self.app(scope, receive, localized_send)
        if pending_start is not None:
            await flush_source_response()

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from app.services.premium_dossier.models import PremiumDossierCompileResult


@lru_cache(maxsize=1)
def _environment() -> Environment:
    template_root = Path(__file__).resolve().parent / "templates"
    env = Environment(
        loader=FileSystemLoader(str(template_root)),
        autoescape=select_autoescape(enabled_extensions=("html", "j2")),
        trim_blocks=True,
        lstrip_blocks=True,
    )
    return env


@lru_cache(maxsize=1)
def _premium_css() -> str:
    css_path = Path(__file__).resolve().parent / "static" / "premium_dossier.css"
    return css_path.read_text(encoding="utf-8")


def render_premium_dossier_html(compiled: PremiumDossierCompileResult) -> str:
    template = _environment().get_template("propertyquarry_dossier.html.j2")
    return template.render(
        dossier=compiled,
        css_text=_premium_css(),
        payload=compiled.redacted_payload,
    )


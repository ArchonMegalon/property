from __future__ import annotations

from dataclasses import dataclass
import os


def _configured(*names: str) -> bool:
    return any(str(os.getenv(name) or "").strip() for name in names)


@dataclass(frozen=True)
class PropertyArtifactProviderLane:
    provider_key: str
    title: str
    role: str
    allowed_use: str
    forbidden_use: str
    privacy_posture: str
    configured: bool
    live_tested_env: str
    fail_closed_rule: str

    def as_row(self) -> dict[str, str]:
        status = "Configured" if self.configured else "Needs config"
        return {
            "title": self.title,
            "detail": f"{self.allowed_use} {self.fail_closed_rule}",
            "tag": f"{self.role} · {status}",
        }


def property_artifact_provider_lanes() -> tuple[PropertyArtifactProviderLane, ...]:
    return (
        PropertyArtifactProviderLane(
            provider_key="matterport",
            title="Matterport",
            role="3D Tour",
            allowed_use="Hosted 3D tour viewer only.",
            forbidden_use="No fly-through rendering, no generated cube fallback.",
            privacy_posture="public tour link only; no private packet payload",
            configured=_configured("MATTERPORT_API_KEY", "PROPERTYQUARRY_MATTERPORT_BASE_URL"),
            live_tested_env="PROPERTYQUARRY_MATTERPORT_LIVE_SMOKE=1",
            fail_closed_rule="Missing export or load failure must block delivery.",
        ),
        PropertyArtifactProviderLane(
            provider_key="3dvista",
            title="3DVista",
            role="3D Tour",
            allowed_use="Self-hosted/exported virtual-tour viewer lane.",
            forbidden_use="No name-only route and no cube fallback.",
            privacy_posture="self-hosted static export with public-safe assets",
            configured=_configured("THREEDVISTA_LICENSE_EMAIL", "THREEDVISTA_LOGIN_EMAIL", "PROPERTYQUARRY_3DVISTA_EXPORT_ROOT"),
            live_tested_env="PROPERTYQUARRY_3DVISTA_LIVE_SMOKE=1",
            fail_closed_rule="Missing export must block delivery.",
        ),
        PropertyArtifactProviderLane(
            provider_key="magicfit",
            title="MagicFit",
            role="Video",
            allowed_use="Photorealistic lived-in fly-through and reference imagery.",
            forbidden_use="No choppy slowdowns, no slide transitions, no synthetic object-only render.",
            privacy_posture="private render input allowed only through controlled worker receipts",
            configured=_configured("PROPERTYQUARRY_MAGICFIT_EMAIL", "MAGICFIT_EMAIL"),
            live_tested_env="PROPERTYQUARRY_MAGICFIT_LIVE_SMOKE=1",
            fail_closed_rule="Continuous-shot, room-coverage, speed, and duration gates must pass before delivery.",
        ),
        PropertyArtifactProviderLane(
            provider_key="onemin",
            title="1min.AI",
            role="Video Probe",
            allowed_use="Candidate image-to-video segment probe.",
            forbidden_use="Cannot replace MagicFit unless the same photoreal and continuity gates pass.",
            privacy_posture="redacted prompt/input only unless owner-private mode is explicit",
            configured=_configured("ONEMIN_AI_API_KEY", "ONEMIN_DIRECT_API_KEYS_JSON", "ONEMIN_DIRECT_API_KEYS_JSON_FILE"),
            live_tested_env="PROPERTYQUARRY_ONEMIN_LIVE_SMOKE=1",
            fail_closed_rule="Provider output must be treated as candidate video until QA proves it.",
        ),
        PropertyArtifactProviderLane(
            provider_key="jogg",
            title="Jogg AI",
            role="Video Probe",
            allowed_use="Candidate photoreal video provider lane.",
            forbidden_use="No direct customer delivery without continuity QA.",
            privacy_posture="redacted prompt/input only until API and privacy receipts exist",
            configured=_configured("JOGG_API_KEY", "JOGG_LOGIN_EMAIL"),
            live_tested_env="PROPERTYQUARRY_JOGG_LIVE_SMOKE=1",
            fail_closed_rule="Must not publish without provider proof and visual QA receipt.",
        ),
        PropertyArtifactProviderLane(
            provider_key="poppy_ai",
            title="Poppy AI",
            role="Research Board",
            allowed_use="Research and prompt-board organization.",
            forbidden_use="Not a source of truth, not a final 3D or fly-through renderer.",
            privacy_posture="redacted topic/board inputs only",
            configured=_configured("POPPY_AI_API_KEY", "POPPY_AI_ACCOUNT_EMAIL"),
            live_tested_env="PROPERTYQUARRY_POPPY_LIVE_SMOKE=1",
            fail_closed_rule="Cannot publish property artifacts directly.",
        ),
        PropertyArtifactProviderLane(
            provider_key="dadan",
            title="Dadan",
            role="Feedback",
            allowed_use="Human video requests, reactions, and interactive feedback.",
            forbidden_use="Not a 3D tour engine, not a fly-through renderer, not source of truth.",
            privacy_posture="external video is untrusted until owner-reviewed",
            configured=_configured("DADAN_API_KEY", "DADAN_LOGIN_EMAIL"),
            live_tested_env="PROPERTYQUARRY_DADAN_LIVE_SMOKE=1",
            fail_closed_rule="Owner review is required before learning or dossier inclusion.",
        ),
        PropertyArtifactProviderLane(
            provider_key="neuronwriter",
            title="NeuronWriter",
            role="Writing",
            allowed_use="Redacted editorial intelligence for dossiers, reviews, email, and Telegram copy.",
            forbidden_use="Cannot decide truth, risk, legal posture, investment score, or private household fit.",
            privacy_posture="public-safe/redacted input only",
            configured=_configured("NEURONWRITER_API_KEY"),
            live_tested_env="PROPERTYQUARRY_NEURONWRITER_LIVE_SMOKE=1",
            fail_closed_rule="If required, missing config must block with an explicit receipt.",
        ),
        PropertyArtifactProviderLane(
            provider_key="pixefy",
            title="Pixefy",
            role="Visual QA",
            allowed_use="Responsive screenshot review and visual-regression evidence for customer surfaces.",
            forbidden_use="Not product truth, not a renderer, and not a substitute for browser overflow gates.",
            privacy_posture="public-safe screenshots only unless operator-private mode is explicit",
            configured=_configured("PIXEFY_API_KEY", "PIXEFY_LOGIN_EMAIL"),
            live_tested_env="PROPERTYQUARRY_PIXEFY_LIVE_SMOKE=1",
            fail_closed_rule="Screenshot findings must create local design-gate failures or repair tasks before release.",
        ),
        PropertyArtifactProviderLane(
            provider_key="rafter",
            title="Rafter",
            role="Ops/LTD",
            allowed_use="Tracked LTD capability candidate until product role is proven.",
            forbidden_use="No automatic artifact role without a verified service contract.",
            privacy_posture="disabled by default",
            configured=_configured("RAFTER_API_KEY", "RAFTER_LOGIN_EMAIL"),
            live_tested_env="PROPERTYQUARRY_RAFTER_LIVE_SMOKE=1",
            fail_closed_rule="Must stay out of customer delivery until a lane is assigned and gated.",
        ),
    )


def required_artifact_receipt_rows() -> tuple[dict[str, str], ...]:
    return (
        {
            "title": "Premium PDF",
            "detail": "MarkupGo or Playwright render receipt, PDF QA result, no artifact status text in the customer PDF.",
            "tag": "Required",
        },
        {
            "title": "3D tours",
            "detail": "Matterport and 3DVista export receipts. Fallback cube viewers are forbidden.",
            "tag": "Required",
        },
        {
            "title": "Fly-through",
            "detail": "Provider, duration, room coverage, continuity, and speed receipts before Telegram delivery.",
            "tag": "Required",
        },
        {
            "title": "Message links",
            "detail": "Every outbound link must be sent as a titled hyperlink, never as a bare full URL.",
            "tag": "Required",
        },
    )

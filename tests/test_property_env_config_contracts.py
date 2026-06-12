from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_env_example_lists_flagship_property_provider_switches() -> None:
    env = (ROOT / ".env.example").read_text(encoding="utf-8")

    for required in (
        "PROPERTYQUARRY_NEURONWRITER_ENABLED=1",
        "PROPERTYQUARRY_NEURONWRITER_REQUIRED=1",
        "NEURONWRITER_API_KEY=",
        "PROPERTYQUARRY_DADAN_ENABLED=0",
        "DADAN_API_KEY=",
        "DADAN_WEBHOOK_SECRET=",
        "MATTERPORT_API_KEY=",
        "PROPERTYQUARRY_MATTERPORT_LIVE_SMOKE=0",
        "THREEDVISTA_LOGIN_EMAIL=",
        "THREEDVISTA_LICENSE_EMAIL=",
        "PROPERTYQUARRY_3DVISTA_EXPORT_ROOT=",
        "PROPERTYQUARRY_3DVISTA_LIVE_SMOKE=0",
        "MAGICFIT_EMAIL=",
        "MAGICFIT_PASSWORD=",
        "PROPERTYQUARRY_MAGICFIT_LIVE_SMOKE=0",
        "ONEMIN_AI_API_KEY=",
        "PROPERTYQUARRY_ONEMIN_LIVE_SMOKE=0",
        "JOGG_API_KEY=",
        "PROPERTYQUARRY_JOGG_LIVE_SMOKE=0",
        "RAFTER_API_KEY=",
        "PROPERTYQUARRY_RAFTER_LIVE_SMOKE=0",
    ):
        assert required in env

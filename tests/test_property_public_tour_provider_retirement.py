from __future__ import annotations

from app.api.routes import public_tours


def _browser_proof() -> dict[str, object]:
    return {
        "provider": "3dvista",
        "status": "pass",
        "rendered_viewer": True,
    }


def test_public_tour_csp_allows_only_self_and_3dvista_frames() -> None:
    csp = public_tours._public_tour_security_headers()["Content-Security-Policy"]

    assert "frame-src 'self' https://3dvista.com https://*.3dvista.com;" in csp
    assert "matterport" not in csp.lower()
    assert "frame-src 'self' https:;" not in csp


def test_public_live_360_cannot_reenable_matterport_via_environment(monkeypatch) -> None:
    monkeypatch.setenv(
        "PROPERTYQUARRY_PUBLIC_360_ALLOWED_HOSTS",
        "my.matterport.com,*.matterport.com,3dvista.com,*.3dvista.com",
    )

    assert public_tours._safe_live_360_url("https://my.matterport.com/show/?m=HISTORICAL") == ""
    assert public_tours._safe_live_360_url("https://demo.3dvista.com/tour/index.htm") == (
        "https://demo.3dvista.com/tour/index.htm"
    )


def test_provider_layers_drop_historical_matterport_but_keep_verified_3dvista() -> None:
    payload = {
        "slug": "verified-home",
        "three_d_vista_browser_render_proof": _browser_proof(),
        "tour_layers": [
            {
                "id": "historical-matterport",
                "provider": "matterport",
                "url": "https://my.matterport.com/show/?m=HISTORICAL",
            },
            {
                "id": "verified-3dvista",
                "provider": "3dvista",
                "url": "https://demo.3dvista.com/tour/index.htm",
            },
        ],
    }

    layers = public_tours._tour_control_provider_layers(
        payload=payload,
        default_src="/tours/3dvista/verified-home/3dvista/index.htm",
        default_label="3DVista Control",
    )
    serialized = str(layers).lower()

    assert "matterport" not in serialized
    assert "my.matterport.com" not in serialized
    assert any(layer["src"] == "https://demo.3dvista.com/tour/index.htm" for layer in layers)


def test_provider_layers_fail_closed_when_default_frame_is_matterport() -> None:
    assert public_tours._tour_control_provider_layers(
        payload={"slug": "historical-home"},
        default_src="https://my.matterport.com/show/?m=HISTORICAL",
        default_label="3D tour",
    ) == []

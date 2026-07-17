from __future__ import annotations

from types import SimpleNamespace

from app.api.routes import public_tour_payloads
from app.product import service as product_service
from app.product.service import ProductService


WILLHABEN_URL = "https://www.willhaben.at/iad/immobilien/d/eigentumswohnung/wien/wien-1200/example-1739164131"


def _captured_packet(
    *,
    property_url: str = WILLHABEN_URL,
    captured_at: str = "",
) -> dict[str, object]:
    packet: dict[str, object] = {
        "property_url": property_url,
        "source_url": property_url,
        "listing_id": "1739164131",
        "title": "Captured listing",
        "property_facts_json": {
            "has_floorplan": True,
            "floorplan_urls_json": ["https://cache.willhaben.at/mmo/1/floorplan.jpg"],
        },
        "media_urls_json": [
            "https://cache.willhaben.at/mmo/1/room.jpg",
            "http://127.0.0.1/private.jpg",
            "javascript:alert(1)",
        ],
        "floorplan_urls_json": ["https://cache.willhaben.at/mmo/1/floorplan.jpg"],
        "media_assets_json": [
            {
                "url": "https://cache.willhaben.at/mmo/1/floorplan.jpg",
                "role": "floorplan",
                "floorplan_candidate": True,
                "floorplan_reason": "plan_like_document_image",
                "width": 1200,
                "height": 900,
                "aspect_ratio": 1.3333,
            }
        ],
    }
    validated = product_service._validated_willhaben_captured_packet(
        property_url=property_url,
        packet=packet,
    )
    provenance = {
        "kind": "property_search_run_snapshot",
        "run_id": "run-1",
        "candidate_ref": "candidate-1",
        "source_ref": "willhaben:1739164131",
        "captured_at": captured_at or product_service._now_iso(),
    }
    provenance["packet_sha256"] = product_service._property_tour_captured_packet_digest(
        validated,
        provenance=provenance,
    )
    packet["source_packet_provenance_json"] = provenance
    return packet


def test_captured_willhaben_packet_requires_exact_listing_identity_and_safe_urls() -> None:
    validated = product_service._validated_willhaben_captured_packet(
        property_url=WILLHABEN_URL,
        packet=_captured_packet(),
    )

    assert validated["property_url"] == WILLHABEN_URL
    assert validated["media_urls_json"] == ["https://cache.willhaben.at/mmo/1/room.jpg"]
    assert validated["floorplan_urls_json"] == ["https://cache.willhaben.at/mmo/1/floorplan.jpg"]
    assert validated["property_facts_json"]["has_floorplan"] is True
    assert product_service._willhaben_packet_panorama_media_urls(
        {
            "panorama_media_urls_json": [
                "https://cache.willhaben.at/mmo/1/panorama.jpg",
                "http://127.0.0.1/private-panorama.jpg",
            ],
            "media_assets_json": [
                {
                    "url": "https://cache.willhaben.at/mmo/1/panorama.jpg",
                    "panorama_candidate": True,
                    "panorama_reason": "xmp_equirectangular",
                    "width": 4000,
                    "height": 2000,
                }
            ],
        }
    ) == ["https://cache.willhaben.at/mmo/1/panorama.jpg"]
    assert product_service._validated_willhaben_captured_packet(
        property_url=WILLHABEN_URL,
        packet=_captured_packet(property_url=f"{WILLHABEN_URL}-different"),
    ) == {}

    hostile = _captured_packet()
    hostile["media_urls_json"] = [
        "https://attacker.invalid/tracker.jpg",
        "https://cache.willhaben.at/mmo/1/room.jpg",
    ]
    hostile["source_virtual_tour_url"] = "https://attacker.invalid/fake-360"
    hostile_validated = product_service._validated_willhaben_captured_packet(
        property_url=WILLHABEN_URL,
        packet=hostile,
    )
    assert hostile_validated["media_urls_json"] == ["https://cache.willhaben.at/mmo/1/room.jpg"]
    assert hostile_validated["source_virtual_tour_url"] == ""
    assert product_service._property_tour_safe_captured_360_url(
        "https://attacker.invalid/fake-360"
    ) == ""

    mixed_identity = _captured_packet()
    mixed_identity["listing_id"] = "9999999999"
    assert product_service._validated_willhaben_captured_packet(
        property_url=WILLHABEN_URL,
        packet=mixed_identity,
    ) == {}


def test_captured_packet_handles_malformed_facts_without_trusting_flags() -> None:
    packet = _captured_packet()
    packet["property_facts_json"] = "malformed"
    packet["floorplan_urls_json"] = []
    packet["media_assets_json"] = []

    validated = product_service._validated_willhaben_captured_packet(
        property_url=WILLHABEN_URL,
        packet=packet,
    )

    assert validated["property_facts_json"]["has_floorplan"] is False
    assert validated["property_facts_json"]["has_360"] is False


def test_search_candidate_persists_only_bounded_safe_tour_source_evidence() -> None:
    floorplan_url = "https://cache.willhaben.at/mmo/1/floorplan.jpg"
    source_fields = product_service._willhaben_candidate_tour_source_fields(
        property_url=WILLHABEN_URL,
        preview={
            "listing_id": "1739164131",
            "title": "Captured listing",
            "media_urls_json": [
                "https://cache.willhaben.at/mmo/1/room.jpg",
                "https://attacker.invalid/tracker.jpg",
            ],
            "floorplan_urls_json": [floorplan_url],
            "media_assets_json": [
                {
                    "url": floorplan_url,
                    "role": "floorplan",
                    "floorplan_candidate": True,
                    "floorplan_reason": "plan_like_document_image",
                    "width": 1200,
                    "height": 900,
                    "aspect_ratio": 1.3333,
                }
            ],
        },
        property_facts={"personal_fit_assessment": {"private": True}},
    )

    assert source_fields["media_urls_json"] == [
        "https://cache.willhaben.at/mmo/1/room.jpg"
    ]
    assert source_fields["floorplan_urls_json"] == [floorplan_url]
    assert source_fields["media_assets_json"][0]["floorplan_reason"] == (
        "plan_like_document_image"
    )
    assert "property_facts_json" not in source_fields
    assert "attacker.invalid" not in str(source_fields)
    assert "personal_fit_assessment" not in str(source_fields)

    ranked = product_service._property_search_ranked_candidates_from_sources(
        [
            {
                "source_label": "Willhaben",
                "top_candidates": [
                    {
                        "candidate_ref": "candidate-1",
                        "source_ref": "property-scout:1739164131",
                        "property_url": WILLHABEN_URL,
                        "title": "Captured listing",
                        **source_fields,
                    }
                ],
            }
        ]
    )
    assert ranked[0]["media_urls_json"] == source_fields["media_urls_json"]
    assert ranked[0]["media_assets_json"] == source_fields["media_assets_json"]


def test_floorplan_urls_require_content_backed_asset_evidence() -> None:
    packet = _captured_packet()
    packet["media_assets_json"] = []

    validated = product_service._validated_willhaben_captured_packet(
        property_url=WILLHABEN_URL,
        packet=packet,
    )

    assert validated["floorplan_urls_json"] == []
    assert validated["property_facts_json"]["has_floorplan"] is False
    assert validated["property_facts_json"]["floorplan_count"] == 0


def test_floorplan_evidence_rejects_role_only_mismatch_and_invalid_dimensions() -> None:
    floorplan_url = "https://cache.willhaben.at/mmo/1/floorplan.jpg"
    base_asset = {
        "url": floorplan_url,
        "role": "floorplan",
        "floorplan_candidate": True,
        "floorplan_reason": "plan_like_document_image",
        "width": 1200,
        "height": 900,
        "aspect_ratio": 1.3333,
    }
    invalid_assets = (
        {**base_asset, "floorplan_candidate": False},
        {**base_asset, "floorplan_reason": "filename_marker_only"},
        {**base_asset, "url": "https://cache.willhaben.at/mmo/1/different.jpg"},
        {**base_asset, "width": 200},
        {**base_asset, "aspect_ratio": 1.0},
    )
    for asset in invalid_assets:
        assert product_service._willhaben_packet_verified_floorplan_assets(
            {
                "floorplan_urls_json": [floorplan_url],
                "media_assets_json": [asset],
            }
        ) == []


def test_panorama_media_requires_xmp_equirectangular_evidence() -> None:
    panorama_url = "https://cache.willhaben.at/mmo/1/panorama.jpg"
    packet: dict[str, object] = {"panorama_media_urls_json": [panorama_url]}

    assert product_service._willhaben_packet_panorama_media_urls(packet) == []

    packet["media_assets_json"] = [
        {
            "url": panorama_url,
            "panorama_candidate": True,
            "panorama_reason": "marker_only",
            "width": 4000,
            "height": 2000,
        }
    ]
    assert product_service._willhaben_packet_panorama_media_urls(packet) == []

    packet["media_assets_json"] = [
        {
            "url": panorama_url,
            "panorama_candidate": True,
            "panorama_reason": "wide_2_to_1",
            "width": 4000,
            "height": 2000,
        }
    ]
    assert product_service._willhaben_packet_panorama_media_urls(packet) == []

    packet["media_assets_json"] = [
        {
            "url": panorama_url,
            "panorama_candidate": True,
            "panorama_reason": "xmp_equirectangular",
        }
    ]
    assert product_service._willhaben_packet_panorama_media_urls(packet) == [panorama_url]


def test_captured_provider_urls_require_real_tour_route_shapes() -> None:
    invalid_urls = (
        "https://my.matterport.com/",
        "https://my.matterport.com/login",
        "https://my.matterport.com/show/?m=",
        "https://my.matterport.com/show/?m=short",
        "http://my.matterport.com/show/?m=BmVWxvZQZLq",
        "https://client.3dvista.com/",
        "https://client.3dvista.com/login",
        "https://client.3dvista.com/tour/login",
        "https://client.3dvista.com/tour/%252e%252e/admin",
        "http://client.3dvista.com/tour/index.html",
    )
    for url in invalid_urls:
        assert product_service._property_tour_provider_url_shape_valid(url) is False
        assert product_service._property_tour_safe_captured_360_url(url) == ""

    valid_urls = (
        "https://my.matterport.com/show/?m=BmVWxvZQZLq",
        "https://client.3dvista.com/tour/index.html",
        "https://example.3dvista.com/tours/top22/index.html",
    )
    for url in valid_urls:
        assert product_service._property_tour_provider_url_shape_valid(url) is True
        assert product_service._property_tour_safe_captured_360_url(url) == url


def test_final_provider_verifiers_reject_invalid_route_shapes() -> None:
    invalid_urls = (
        "https://www.3dvista.com/",
        "https://www.3dvista.com/login",
        "https://client.3dvista.com/tour/login",
        "http://client.3dvista.com/tour/index.html",
    )
    for url in invalid_urls:
        assert product_service._hosted_property_tour_verified_provider(url) == ""
        assert product_service._hosted_property_tour_verified_open_url(url) == ""
        assert product_service._resolve_property_tour_urls({"public_url": url}) == ("", "")

    valid_url = "https://client.3dvista.com/tour/index.html"
    assert product_service._hosted_property_tour_verified_provider(valid_url) == "3dvista"
    assert product_service._hosted_property_tour_verified_open_url(valid_url) == valid_url
    assert product_service._resolve_property_tour_urls({"public_url": valid_url}) == (
        "",
        valid_url,
    )


def test_url_resolver_rejects_nonexistent_branded_tours_even_when_legacy_flag_is_set() -> None:
    for url in (
        "https://propertyquarry.com/tours/nonexistent-proofless-tour",
        "https://myexternalbrain.com/tours/nonexistent-proofless-tour",
    ):
        assert product_service._resolve_property_tour_urls(
            {"public_url": url},
            allow_unverified_branded=True,
        ) == ("", "")


def test_attribute_map_cannot_promote_an_arbitrary_url_to_a_live_tour() -> None:
    packet = _captured_packet()
    packet["property_facts_json"] = {
        "attribute_map": {
            "DESCRIPTION": "Virtual viewing: https://attacker.invalid/fake-360",
        }
    }

    assert product_service._willhaben_packet_source_virtual_tour_url(packet) == ""


def test_validated_packet_overwrites_nested_panorama_urls_and_renderer_strips_media() -> None:
    panorama_url = "https://cache.willhaben.at/mmo/1/panorama.jpg"
    packet = _captured_packet()
    packet["panorama_media_urls_json"] = [panorama_url]
    packet["media_assets_json"] = [
        {
            "url": panorama_url,
            "panorama_candidate": True,
            "panorama_reason": "xmp_equirectangular",
        }
    ]
    packet["property_facts_json"] = {
        "rooms": 3,
        "panorama_media_urls_json": ["https://attacker.invalid/private-panorama.jpg"],
    }

    validated = product_service._validated_willhaben_captured_packet(
        property_url=WILLHABEN_URL,
        packet=packet,
    )

    assert validated["panorama_media_urls_json"] == [panorama_url]
    assert validated["property_facts_json"]["panorama_media_urls_json"] == [panorama_url]
    renderer_facts = product_service._property_tour_renderer_facts(validated["property_facts_json"])
    assert renderer_facts["rooms"] == 3
    assert "panorama_media_urls_json" not in renderer_facts
    assert "attacker.invalid" not in str(renderer_facts)


def test_resolve_willhaben_packet_reuses_valid_capture_without_live_refetch(monkeypatch) -> None:
    def _unexpected_refetch(_property_url: str) -> dict[str, object]:
        raise AssertionError("live refetch must not run for an exact captured packet")

    monkeypatch.setattr(product_service, "_load_willhaben_property_packet", _unexpected_refetch)

    packet, origin = product_service._resolve_willhaben_property_packet(
        WILLHABEN_URL,
        captured_packet=_captured_packet(),
    )

    assert origin == "run_snapshot"
    assert packet["listing_id"] == "1739164131"


def test_resolve_willhaben_packet_falls_back_when_capture_identity_mismatches(monkeypatch) -> None:
    live_packet = {
        "listing_id": "1739164131",
        "title": "Live listing",
        "media_urls_json": ["https://cache.willhaben.at/mmo/1/live-room.jpg"],
    }
    monkeypatch.setattr(
        product_service,
        "_load_willhaben_property_packet",
        lambda property_url: {**live_packet, "property_url": property_url},
    )

    packet, origin = product_service._resolve_willhaben_property_packet(
        WILLHABEN_URL,
        captured_packet=_captured_packet(property_url=f"{WILLHABEN_URL}-different"),
    )

    assert origin == "live_refetch"
    assert packet["title"] == "Live listing"


def test_resolve_willhaben_packet_reuses_valid_live_prefetch_without_refetch(monkeypatch) -> None:
    def _unexpected_refetch(_property_url: str) -> dict[str, object]:
        raise AssertionError("live refetch must not run after a validated live prefetch")

    monkeypatch.setattr(product_service, "_load_willhaben_property_packet", _unexpected_refetch)

    packet, origin = product_service._resolve_willhaben_property_packet(
        WILLHABEN_URL,
        prefetched_packet=_captured_packet(),
    )

    assert origin == "live_prefetched"
    assert packet["listing_id"] == "1739164131"


def test_resolve_willhaben_packet_refetches_stale_snapshot(monkeypatch) -> None:
    calls: list[str] = []

    def _live_refetch(property_url: str) -> dict[str, object]:
        calls.append(property_url)
        return {
            "property_url": property_url,
            "listing_id": "1739164131",
            "title": "Fresh listing",
            "media_urls_json": ["https://cache.willhaben.at/mmo/1/fresh-room.jpg"],
        }

    monkeypatch.setattr(product_service, "_load_willhaben_property_packet", _live_refetch)

    packet, origin = product_service._resolve_willhaben_property_packet(
        WILLHABEN_URL,
        captured_packet=_captured_packet(captured_at="2000-01-01T00:00:00+00:00"),
    )

    assert origin == "live_refetch"
    assert packet["title"] == "Fresh listing"
    assert calls == [WILLHABEN_URL]


def test_captured_packet_digest_binds_run_provenance(monkeypatch) -> None:
    captured = _captured_packet()
    provenance = dict(captured["source_packet_provenance_json"])
    provenance["candidate_ref"] = "copied-to-another-candidate"
    captured["source_packet_provenance_json"] = provenance
    monkeypatch.setattr(
        product_service,
        "_load_willhaben_property_packet",
        lambda property_url: {
            "property_url": property_url,
            "listing_id": "1739164131",
            "title": "Fresh after provenance mismatch",
            "media_urls_json": ["https://cache.willhaben.at/mmo/1/fresh-room.jpg"],
        },
    )

    packet, origin = product_service._resolve_willhaben_property_packet(
        WILLHABEN_URL,
        captured_packet=captured,
    )

    assert origin == "live_refetch"
    assert packet["title"] == "Fresh after provenance mismatch"


def test_run_snapshot_visual_state_exposes_only_exact_candidate_packet() -> None:
    class _SnapshotService:
        def _snapshot_property_search_run(self, **_kwargs):
            return {
                "created_at": product_service._now_iso(),
                "summary": {
                    "ranked_candidates": [
                        {
                            "candidate_ref": "candidate-1",
                            "source_ref": "willhaben:1739164131",
                            "property_url": WILLHABEN_URL,
                            "title": "Captured listing",
                            "listing_id": "1739164131",
                            "media_urls_json": ["https://cache.willhaben.at/mmo/1/room.jpg"],
                            "property_facts": {"has_floorplan": False},
                        }
                    ],
                    "sources": [],
                }
            }

    state = ProductService._current_property_search_visual_state(
        _SnapshotService(),
        principal_id="principal-1",
        run_id="run-1",
        candidate_ref="candidate-1",
        source_ref="willhaben:1739164131",
        property_url=WILLHABEN_URL,
    )

    assert state["source_packet_status"] == "captured"
    assert state["source_packet_json"]["property_url"] == WILLHABEN_URL
    assert ProductService._current_property_search_visual_state(
        _SnapshotService(),
        principal_id="principal-1",
        run_id="run-1",
        candidate_ref="different-candidate",
        source_ref="",
        property_url=WILLHABEN_URL,
    ) == {}


def test_visual_request_passes_exact_run_snapshot_packet_to_tour_builder() -> None:
    captured_packet = _captured_packet()
    received: dict[str, object] = {}
    service = object.__new__(ProductService)
    service._container = SimpleNamespace(
        onboarding=SimpleNamespace(
            status=lambda **_kwargs: {"property_search_preferences": {}}
        )
    )
    service._current_property_search_visual_state = lambda **_kwargs: {
        "source_packet_json": captured_packet,
        "source_packet_status": "captured",
    }
    service._resolve_browseract_property_tour_binding_id = lambda **_kwargs: "binding-1"
    service._persist_property_search_visual_state = lambda **_kwargs: None
    service._materialize_property_generated_reconstruction_url = lambda **_kwargs: ""

    def _create_tour(**kwargs):
        received.update(kwargs)
        return {
            "status": "blocked",
            "blocked_reason": "property_tour_fallback_disabled",
            "title": "Captured listing",
            "tour_url": "",
            "vendor_tour_url": "",
            "tour_media_mode": "flat_images",
        }

    service.create_willhaben_property_tour = _create_tour

    result = ProductService.request_property_visual_asset(
        service,
        principal_id="principal-1",
        property_url=WILLHABEN_URL,
        request_kind="tour",
        run_id="run-1",
        candidate_ref="candidate-1",
        source_ref="willhaben:1739164131",
        queue_async_request=False,
    )

    assert received["captured_packet_json"] == captured_packet
    assert result["status"] == "blocked"
    assert result["blocked_reason"] == "property_tour_fallback_disabled"


def test_packet_failure_diagnostic_is_specific_and_redacted() -> None:
    diagnostic = product_service._property_tour_execution_diagnostic(
        RuntimeError(
            "willhaben_property_packet_failed:Traceback token=super-secret "
            "File /app/scripts/willhaben_property_packet.py"
        )
    )

    assert diagnostic["blocked_reason"] == "listing_packet_acquisition_failed"
    assert diagnostic["failure_stage"] == "listing_packet"
    assert diagnostic["error_code"] == "willhaben_property_packet_failed"
    assert len(diagnostic["error_fingerprint"]) == 16
    assert "super-secret" not in diagnostic["safe_detail"]
    assert "Traceback" not in diagnostic["safe_detail"]
    assert product_service._property_visual_unavailable_detail(
        request_kind="tour",
        reason=diagnostic["blocked_reason"],
    ) == "The listing source could not be refreshed. Retry while the listing is active."

    second = product_service._property_tour_execution_diagnostic(
        RuntimeError("willhaben_property_packet_failed:different private token and traceback")
    )
    assert second["error_fingerprint"] == diagnostic["error_fingerprint"]


def test_packet_diagnostic_preserves_visual_upgrade_requirement() -> None:
    for error_code in (
        "property_tour_upgrade_required:plus",
        "property_tour_upgrade_required:agent",
        "property_magic_fit_upgrade_required:plus",
    ):
        diagnostic = product_service._property_tour_execution_diagnostic(ValueError(error_code))
        assert diagnostic["blocked_reason"] == error_code
        assert diagnostic["error_code"] == error_code
        assert diagnostic["failure_stage"] == "quota"


def test_unverified_publication_diagnostic_stays_typed() -> None:
    diagnostic = product_service._property_tour_execution_diagnostic(
        RuntimeError("property_tour_output_unverified")
    )

    assert diagnostic["blocked_reason"] == "property_tour_output_unverified"
    assert diagnostic["error_code"] == "property_tour_output_unverified"
    assert diagnostic["failure_stage"] == "tour_publication"


def test_generic_blocked_status_uses_explicit_flat_listing_evidence() -> None:
    inferred = product_service._property_tour_evidence_blocked_reason(
        candidate={
            "property_url": WILLHABEN_URL,
            "property_facts": {
                "has_360": False,
                "has_floorplan": False,
                "media_count": 30,
            },
        },
        current_reason="property_tour_execution_failed",
    )

    assert inferred == "property_tour_fallback_disabled"
    assert product_service._property_visual_unavailable_detail(
        request_kind="tour",
        reason=inferred,
    ) == (
        "This listing only provides flat photos; no verified 360 tour or "
        "floorplan is available."
    )
    assert product_service._property_tour_evidence_blocked_reason(
        candidate={
            "property_url": WILLHABEN_URL,
            "property_facts": {"media_count": 30},
        },
        current_reason="property_tour_execution_failed",
    ) == "property_tour_execution_failed"


def test_renderer_facts_strip_private_and_arbitrary_fields() -> None:
    projected = product_service._property_tour_renderer_facts(
        {
            "listing_id": "1739164131",
            "rooms": 3,
            "personal_fit_assessment": {"private": True},
            "public_preference_snapshot": {"email": "private@example.com"},
            "arbitrary_private_field": "secret",
            "listing_research_snapshot": {
                "street_address": "Safe street",
                "nearest_supermarket_m": 450,
                "arbitrary_private_field": "secret",
            },
            "listing_research_meta": {
                "strategy": "provider_html_plus_geo",
                "token": "secret",
            },
        }
    )

    assert projected == {
        "listing_id": "1739164131",
        "rooms": 3,
        "listing_research_snapshot": {
            "street_address": "Safe street",
            "nearest_supermarket_m": 450,
        },
        "listing_research_meta": {"strategy": "provider_html_plus_geo"},
    }


def test_telegram_property_bundle_passes_validated_prefetch_to_tour_builder(monkeypatch) -> None:
    load_calls: list[str] = []
    create_calls: list[dict[str, object]] = []
    service = object.__new__(ProductService)
    service._container = SimpleNamespace(tool_runtime=SimpleNamespace())
    service._preference_profiles = SimpleNamespace(assess_candidate=lambda **_kwargs: {})
    service._default_property_person_motion_hint = lambda **_kwargs: ""
    service._record_product_event = lambda **_kwargs: None
    service._render_property_scout_dossier = lambda **_kwargs: {
        "status": "failed",
        "reason": "test_dossier_unavailable",
    }

    def _load(property_url: str, *, timeout_seconds: int = 180) -> dict[str, object]:
        del timeout_seconds
        load_calls.append(property_url)
        return _captured_packet(property_url=property_url)

    def _create(**kwargs):
        create_calls.append(dict(kwargs))
        return {
            "status": "blocked",
            "blocked_reason": "property_tour_fallback_disabled",
            "tour_url": "",
            "vendor_tour_url": "",
        }

    monkeypatch.setattr(product_service, "_load_willhaben_property_packet_compat", _load)
    monkeypatch.setattr(
        product_service,
        "_merge_property_facts_with_source_research",
        lambda **kwargs: dict(kwargs.get("property_facts") or {}),
    )
    monkeypatch.setattr(product_service, "resolve_primary_telegram_binding", lambda *_args, **_kwargs: None)
    service.create_willhaben_property_tour = _create

    result = ProductService.deliver_telegram_property_link_bundle(
        service,
        principal_id="principal-1",
        property_url=WILLHABEN_URL,
    )

    assert result["status"] == "pending"
    assert load_calls == [WILLHABEN_URL]
    assert len(create_calls) == 1
    assert create_calls[0]["prefetched_packet_json"]["property_url"] == WILLHABEN_URL


def test_telegram_packet_failure_skips_research_assessment_and_tour_creation(monkeypatch) -> None:
    events: list[dict[str, object]] = []
    service = object.__new__(ProductService)
    service._container = SimpleNamespace(tool_runtime=SimpleNamespace())
    service._preference_profiles = SimpleNamespace(
        assess_candidate=lambda **_kwargs: (_ for _ in ()).throw(
            AssertionError("assessment must not run after packet failure")
        )
    )
    service._default_property_person_motion_hint = lambda **_kwargs: ""
    service._record_product_event = lambda **kwargs: events.append(dict(kwargs))
    service._render_property_scout_dossier = lambda **_kwargs: {
        "status": "failed",
        "reason": "test_dossier_unavailable",
    }
    service.create_willhaben_property_tour = lambda **_kwargs: (_ for _ in ()).throw(
        AssertionError("tour creation must not run after packet failure")
    )

    monkeypatch.setattr(
        product_service,
        "_load_willhaben_property_packet_compat",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            RuntimeError("willhaben_property_packet_failed:token=private")
        ),
    )
    monkeypatch.setattr(
        product_service,
        "_merge_property_facts_with_source_research",
        lambda **_kwargs: (_ for _ in ()).throw(
            AssertionError("source research must not refetch after packet failure")
        ),
    )
    monkeypatch.setattr(product_service, "resolve_primary_telegram_binding", lambda *_args, **_kwargs: None)

    result = ProductService.deliver_telegram_property_link_bundle(
        service,
        principal_id="principal-1",
        property_url=WILLHABEN_URL,
    )

    assert result["status"] == "pending"
    assert "3D tour missing (listing packet acquisition failed)" in result["pending_reasons"]
    blocked_events = [event for event in events if event.get("event_type") == "willhaben_property_tour_blocked"]
    assert len(blocked_events) == 1
    assert blocked_events[0]["payload"]["blocked_reason"] == "listing_packet_acquisition_failed"
    assert "private" not in str(blocked_events[0])


def test_telegram_tour_creation_failure_preserves_upgrade_diagnostic(monkeypatch) -> None:
    events: list[dict[str, object]] = []
    service = object.__new__(ProductService)
    service._container = SimpleNamespace(tool_runtime=SimpleNamespace())
    service._preference_profiles = SimpleNamespace(assess_candidate=lambda **_kwargs: {})
    service._default_property_person_motion_hint = lambda **_kwargs: ""
    service._record_product_event = lambda **kwargs: events.append(dict(kwargs))
    service._render_property_scout_dossier = lambda **_kwargs: {
        "status": "failed",
        "reason": "test_dossier_unavailable",
    }
    service.create_willhaben_property_tour = lambda **_kwargs: (_ for _ in ()).throw(
        ValueError("property_tour_upgrade_required:plus")
    )

    monkeypatch.setattr(
        product_service,
        "_load_willhaben_property_packet_compat",
        lambda property_url, **_kwargs: _captured_packet(property_url=property_url),
    )
    monkeypatch.setattr(
        product_service,
        "_merge_property_facts_with_source_research",
        lambda **kwargs: dict(kwargs.get("property_facts") or {}),
    )
    monkeypatch.setattr(product_service, "resolve_primary_telegram_binding", lambda *_args, **_kwargs: None)

    result = ProductService.deliver_telegram_property_link_bundle(
        service,
        principal_id="principal-1",
        property_url=WILLHABEN_URL,
    )

    assert result["status"] == "pending"
    assert "3D tour missing (property tour upgrade required:plus)" in result["pending_reasons"]
    blocked_events = [event for event in events if event.get("event_type") == "willhaben_property_tour_blocked"]
    assert len(blocked_events) == 1
    assert blocked_events[0]["payload"]["blocked_reason"] == "property_tour_upgrade_required:plus"
    assert blocked_events[0]["payload"]["failure_stage"] == "quota"


def test_public_tour_manifest_excludes_private_identity_and_fit_context() -> None:
    manifest = public_tour_payloads.build_public_tour_manifest(
        {
            "slug": "safe-tour",
            "title": "Safe tour",
            "principal_id": "principal-private",
            "recipient_email": "private@example.test",
            "facts": {
                "rooms": 3,
                "personal_fit_assessment": {"fit_score": 91, "private_note": "secret"},
                "public_preference_snapshot": {"person_id": "private-person"},
                "principal_id": "principal-private",
            },
        },
        url_allowed=lambda _url: False,
        bundle_dir_resolver=lambda _slug: None,
    ).as_dict()

    assert manifest["facts"] == {"rooms": 3}
    assert "principal-private" not in str(manifest)
    assert "private@example.test" not in str(manifest)
    assert "fit_score" not in str(manifest)


def test_create_tour_blocks_flat_snapshot_without_refetch_or_variant(monkeypatch) -> None:
    captured = product_service._captured_willhaben_packet_from_candidate(
        candidate={
            "listing_id": "1739164131",
            "title": "Flat captured listing",
            "media_urls_json": ["https://cache.willhaben.at/mmo/1/flat-room.jpg"],
            "floorplan_urls_json": [],
            "property_facts_json": {},
        },
        property_url=WILLHABEN_URL,
        run_id="run-flat",
        candidate_ref="candidate-flat",
        source_ref="willhaben:1739164131",
        captured_at=product_service._now_iso(),
    )
    service = object.__new__(ProductService)
    service._container = SimpleNamespace(
        onboarding=SimpleNamespace(status=lambda **_kwargs: {"property_search_preferences": {}}),
    )
    service._preference_profiles = SimpleNamespace(assess_candidate=lambda **_kwargs: None)
    service._enforce_property_visual_quota = lambda **_kwargs: None
    service._record_product_event = lambda **_kwargs: None
    monkeypatch.setattr(
        product_service,
        "_merge_property_facts_with_source_research",
        lambda **kwargs: dict(kwargs.get("property_facts") or {}),
    )
    monkeypatch.setattr(product_service, "_public_property_preference_snapshot", lambda **_kwargs: {})
    monkeypatch.setattr(
        product_service,
        "_load_willhaben_property_packet",
        lambda _url: (_ for _ in ()).throw(AssertionError("flat snapshot must not refetch")),
    )

    result = ProductService.create_willhaben_property_tour(
        service,
        principal_id="principal-1",
        property_url=WILLHABEN_URL,
        binding_id="binding-1",
        captured_packet_json=captured,
        enforce_360_media=False,
        suppress_human_followup=True,
    )

    assert result["status"] == "blocked"
    assert result["blocked_reason"] == "property_tour_fallback_disabled"
    assert result["source_packet_origin"] == "run_snapshot"


def test_signal_auto_create_persists_redacted_packet_failure_diagnostic() -> None:
    events: list[dict[str, object]] = []

    class _SignalService:
        def property_alert_policy(self, **_kwargs):
            return {}

        def create_willhaben_property_tour(self, **_kwargs):
            raise RuntimeError("willhaben_property_packet_failed:Traceback token=super-secret")

        def _record_product_event(self, **kwargs):
            events.append(dict(kwargs))

    result = ProductService._maybe_create_willhaben_property_tour_from_signal(
        _SignalService(),
        principal_id="principal-1",
        title="Listing",
        summary=WILLHABEN_URL,
        text=WILLHABEN_URL,
        source_ref="willhaben:1739164131",
        external_id="1739164131",
        counterparty="Willhaben",
        payload={"auto_create_property_tour": True},
        actor="test",
    )

    assert result is None
    assert len(events) == 1
    event_payload = events[0]["payload"]
    assert event_payload["blocked_reason"] == "listing_packet_acquisition_failed"
    assert event_payload["failure_stage"] == "listing_packet"
    assert event_payload["error"] == "willhaben_property_packet_failed"
    assert "super-secret" not in str(event_payload)


def test_scout_auto_create_returns_specific_packet_failure_without_raw_traceback() -> None:
    class _ScoutService:
        def _latest_property_tour_event(self, **_kwargs):
            return None

        def create_willhaben_property_tour(self, **_kwargs):
            raise RuntimeError("willhaben_property_packet_timeout token=super-secret")

    result = ProductService._maybe_auto_create_property_scout_tour(
        _ScoutService(),
        principal_id="principal-1",
        actor="test",
        property_url=WILLHABEN_URL,
        source_ref="willhaben:1739164131",
        assessment={},
        allow_below_threshold=True,
    )

    assert result["status"] == "failed"
    assert result["blocked_reason"] == "listing_packet_timeout"
    assert result["failure_stage"] == "listing_packet"
    assert "super-secret" not in str(result)

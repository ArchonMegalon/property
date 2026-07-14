from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import stat
from typing import Mapping

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from app.api.dependencies import RequestContext
from app.api.routes import landing
from app.api.routes.public_tour_payloads import require_governed_spatial_public_tour_viewable
from app.product import property_tour_hosting


NOW = datetime(2026, 7, 11, 12, 0, tzinfo=timezone.utc)


def _digest(character: str) -> str:
    return "sha256:" + character * 64


def _property_packet() -> dict[str, object]:
    return {
        "contract_name": "propertyquarry.governed_spatial_tour_input.v1",
        "contract_version": "1.0.0",
        "source_owner_ref": "owner:first-party:property",
        "source_authority_ref": "authority:first-party:property:test-1",
        "source_authority_receipt_digest": _digest("1"),
        "source_packet_ref": "packet:property:test-1:v1",
        "source_digest": "a" * 64,
        "tenant_ref": "tenant:property:test",
        "subject_ref": "property:test-1",
        "purpose": "walkthrough",
        "locale": "en-AT",
        "privacy_policy_ref": "policy:property:test-1",
        "privacy_policy_version": "1.0.0",
        "rights_authorization_ref": "rights:property:test-1",
        "consent_authorization_ref": "consent:property:test-1",
        "publication_authorization_ref": "publication:property:test-1",
        "truth_refs": ["truth:property:test-1"],
        "evidence_refs": ["evidence:first-party:test-1"],
        "normalized_floorplan_ref": "artifact:floorplan:test-1",
        "room_graph_ref": "geometry:room-graph:test-1",
        "walkable_mesh_ref": "geometry:walkable-mesh:test-1",
        "portal_graph_ref": "geometry:portal-graph:test-1",
        "scale_m_per_unit": 1.0,
        "orientation_degrees": 90.0,
        "source_retrieved_at": "2026-07-11T10:00:00Z",
        "license_provenance_refs": ["license:first-party:test-1"],
        "source_media_assignments": [],
        "inaccessible_rooms": [
            {
                "room_id": "service",
                "reason": "source_verified_no_access",
                "provenance_ref": "provenance:property:test-1:service",
            }
        ],
        "route_exclusions": [],
        "rooms": [
            {
                "room_id": "living",
                "room_type": "living",
                "walkable": True,
                "accessible": True,
                "boundary_ref": "geometry:living:boundary",
                "ceiling_height_m": 2.7,
                "geometry_anchor_ref": "geometry:living:anchor",
                "texture_anchor_refs": ["texture:living:1"],
            },
            {
                "room_id": "bedroom",
                "room_type": "bedroom",
                "walkable": True,
                "accessible": True,
                "boundary_ref": "geometry:bedroom:boundary",
                "ceiling_height_m": 2.7,
                "geometry_anchor_ref": "geometry:bedroom:anchor",
                "texture_anchor_refs": ["texture:bedroom:1"],
            },
            {
                "room_id": "service",
                "room_type": "service",
                "walkable": False,
                "accessible": False,
                "boundary_ref": "geometry:service:boundary",
                "ceiling_height_m": 2.5,
                "geometry_anchor_ref": "geometry:service:anchor",
                "texture_anchor_refs": ["texture:service:1"],
            },
        ],
        "portals": [
            {
                "portal_id": "door-living-bedroom",
                "from_room_id": "living",
                "to_room_id": "bedroom",
                "walkable": True,
            }
        ],
        "route_room_ids": ["living", "bedroom"],
    }


def _v11_packet(
    room_ids: list[str],
    edges: list[tuple[str, str]],
    *,
    priority: list[str] | None = None,
    start: str | None = None,
) -> dict[str, object]:
    packet = _property_packet()
    packet["contract_version"] = "1.1.0"
    packet.pop("route_room_ids")
    selected_priority = list(priority or room_ids)
    packet["route_priority_room_ids"] = selected_priority
    packet["route_start_room_id"] = start if start is not None else selected_priority[0]
    packet["rooms"] = [
        {
            "room_id": room_id,
            "room_type": "room",
            "walkable": True,
            "accessible": True,
            "boundary_ref": f"geometry:{room_id}:boundary",
            "ceiling_height_m": 2.7,
            "geometry_anchor_ref": f"geometry:{room_id}:anchor",
            "texture_anchor_refs": [f"texture:{room_id}:1"],
        }
        for room_id in room_ids
    ] + [deepcopy(_property_packet()["rooms"][2])]  # type: ignore[index]
    packet["portals"] = [
        {
            "portal_id": f"door-{index}",
            "from_room_id": left,
            "to_room_id": right,
            "walkable": True,
        }
        for index, (left, right) in enumerate(edges)
    ]
    return packet


def _source_authority(packet: dict[str, object] | None = None) -> property_tour_hosting.VerifiedPropertyTourSourceAuthority:
    source = packet or _property_packet()
    return property_tour_hosting.VerifiedPropertyTourSourceAuthority(
        owner_ref=str(source["source_owner_ref"]),
        authority_ref=str(source["source_authority_ref"]),
        authority_receipt_digest=str(source["source_authority_receipt_digest"]),
        source_packet_ref=str(source["source_packet_ref"]),
        source_digest=str(source["source_digest"]),
        tenant_ref=str(source["tenant_ref"]),
        subject_ref=str(source["subject_ref"]),
        rights_authorization_ref=str(source["rights_authorization_ref"]),
        consent_authorization_ref=str(source["consent_authorization_ref"]),
        publication_authorization_ref=str(source["publication_authorization_ref"]),
        privacy_policy_ref=str(source["privacy_policy_ref"]),
        privacy_policy_version=str(source["privacy_policy_version"]),
        issued_at="2026-07-11T11:00:00Z",
        expires_at="2026-07-11T13:00:00Z",
    )


def _bridge(packet: dict[str, object] | None = None) -> dict[str, object]:
    source = packet or _property_packet()
    return property_tour_hosting.build_governed_property_tour_request(
        property_packet=source,
        request_id="3d0dfa6e-27bb-48d1-b00b-7675ae02416f",
        idempotency_key="property-test-1-walkthrough-v1",
        style_pack_id="decor-style:test-1",
        product_event_ref="event:property:test-1",
        verified_source_authority=_source_authority(source),
        observed_at=NOW,
    )


def _policy(*, source_days: int = 7) -> dict[str, object]:
    material = {
        "contract_name": "propertyquarry.governed_spatial_retention_policy.v1",
        "policy_id": "policy:property:test-1",
        "approval_ref": "approval:property:test-1",
        "approved_at": (NOW - timedelta(days=1)).isoformat().replace("+00:00", "Z"),
        "expires_at": (NOW + timedelta(days=30)).isoformat().replace("+00:00", "Z"),
        "source_retention_days": source_days,
        "receipt_retention_days": 30,
        "tombstone_retention_days": 90,
    }
    return {**material, "policy_digest": property_tour_hosting._governed_spatial_digest(material)}


def _publication(
    *,
    slug: str,
    composition_digest: str = _digest("3"),
    policy: dict[str, object] | None = None,
    expires_at: datetime | None = None,
) -> property_tour_hosting.VerifiedGovernedPropertyTourPublication:
    policy_payload = policy or _policy()
    material = {
        "tour_scope_digest": "sha256:" + hashlib.sha256(slug.encode("utf-8")).hexdigest(),
        "composition_digest": composition_digest,
        "composition_receipt_digest": _digest("4"),
        "artifact_digest": _digest("5"),
        "artifact_receipt_digest": _digest("6"),
        "quality_receipt_digest": _digest("7"),
        "rights_provenance_digest": _digest("8"),
        "capability_receipt_digest": _digest("9"),
        "publication_authorization_digest": _digest("b"),
        "privacy_policy_digest": str(policy_payload["policy_digest"]),
        "issued_at": (NOW - timedelta(minutes=1)).isoformat().replace("+00:00", "Z"),
        "expires_at": (expires_at or NOW + timedelta(hours=1)).isoformat().replace("+00:00", "Z"),
    }
    return property_tour_hosting.VerifiedGovernedPropertyTourPublication(
        **material,
        decision_digest=property_tour_hosting._governed_spatial_digest(material),
    )


def _intake(
    store: property_tour_hosting.GovernedPropertyTourLifecycleStore,
    *,
    slug: str = "tour-1",
    policy: dict[str, object] | None = None,
    publication: property_tour_hosting.VerifiedGovernedPropertyTourPublication | None = None,
    composition_digest: str = _digest("3"),
) -> dict[str, object]:
    return store.intake(
        slug=slug,
        policy_payload=policy or _policy(),
        observed_at=NOW,
        bridge_digest=_digest("2"),
        composition_digest=composition_digest,
        composition_receipt_digest=_digest("4"),
        publication_authority=publication,
        owner_principal_ref="principal:test",
        tenant_ref="tenant:property:test",
        subject_ref="property:test-1",
    )


def _legal_hold(*, slug: str, expires_at: datetime, review_due_at: datetime) -> dict[str, object]:
    material = {
        "contract_name": "propertyquarry.governed_spatial_legal_hold.v1",
        "scope_digest": "sha256:" + hashlib.sha256(slug.encode("utf-8")).hexdigest(),
        "case_ref_digest": _digest("c"),
        "authority_ref_digest": _digest("d"),
        "issued_at": (NOW - timedelta(minutes=5)).isoformat().replace("+00:00", "Z"),
        "expires_at": expires_at.isoformat().replace("+00:00", "Z"),
        "review_due_at": review_due_at.isoformat().replace("+00:00", "Z"),
    }
    return {**material, "hold_digest": property_tour_hosting._governed_spatial_digest(material)}


def test_property_bridge_maps_verified_first_party_truth_to_complete_provider_neutral_request() -> None:
    bridge = _bridge()
    request = bridge["request"]
    source = bridge["source_packet"]

    assert bridge["contract_version"] == "1.0.0"
    assert bridge["bridge_digest"].startswith("sha256:")
    assert request["quota"] == {"consume_quota": False, "maximum_provider_attempts": 0}
    assert request["spatial_plan"]["required_room_ids"] == ["living", "bedroom"]
    assert request["spatial_plan"]["route_room_ids"] == ["living", "bedroom"]
    assert request["spatial_plan"]["portal_edges"] == [
        {"from_room_id": "living", "to_room_id": "bedroom"}
    ]
    assert source["route_room_ids"] == ["living", "bedroom"]
    assert source["route_exclusions"] == []
    assert request["scene_overlays"] == []
    serialized = json.dumps(bridge).lower()
    assert "provider_url" not in serialized
    assert "provider_id" not in serialized
    assert "rules_result" not in serialized
    assert "damage" not in serialized


def test_property_v100_retains_inaccessible_portal_truth_without_emitting_request_edge() -> None:
    packet = _property_packet()
    packet["portals"].append(  # type: ignore[union-attr]
        {
            "portal_id": "door-bedroom-service",
            "from_room_id": "bedroom",
            "to_room_id": "service",
            "walkable": True,
        }
    )

    bridge = _bridge(packet)

    assert bridge["request"]["spatial_plan"]["portal_edges"] == [  # type: ignore[index]
        {"from_room_id": "living", "to_room_id": "bedroom"}
    ]
    assert len(bridge["source_packet"]["portals"]) == 2  # type: ignore[index]
    assert bridge["request"]["spatial_plan"]["route_room_ids"] == ["living", "bedroom"]  # type: ignore[index]
    assert bridge["request"]["spatial_plan"]["allow_revisit"] is False  # type: ignore[index]


@pytest.mark.parametrize(
    "mutator",
    [
        lambda packet: packet.__setitem__("unknown", "value"),
        lambda packet: packet["rooms"][0].__setitem__("metadata", {"safe": True}),
        lambda packet: packet["rooms"][0].__setitem__("provider_id", "task:private"),
        lambda packet: packet["rooms"][0].__setitem__("damage", 3),
        lambda packet: packet["rooms"][0].__setitem__("resident_email", "resident@example.test"),
        lambda packet: packet.__setitem__("first_party", True),
        lambda packet: packet.__setitem__("truth_refs", ["https://vendor.invalid/private/task"]),
    ],
)
def test_property_contract_rejects_unknown_provider_combat_and_sensitive_fields_recursively(mutator) -> None:
    packet = _property_packet()
    mutator(packet)

    with pytest.raises(property_tour_hosting.GovernedPropertyTourContractError):
        _bridge(packet)


@pytest.mark.parametrize(
    ("raw", "reason"),
    [
        (b'{"outer":{"same":1,"same":2}}', "duplicate_member"),
        (b'{"text":"\\ud800"}', "invalid_unicode"),
        (b"\xff", "invalid_utf8"),
        (b"[]", "root_object_required"),
    ],
)
def test_property_raw_ingress_rejects_duplicate_utf8_surrogate_and_non_object(raw: bytes, reason: str) -> None:
    with pytest.raises(property_tour_hosting.GovernedPropertyTourContractError, match=reason):
        property_tour_hosting.parse_governed_property_tour_raw_json(raw)


def test_source_authority_is_exactly_bound_and_not_replaced_by_caller_boolean() -> None:
    packet = _property_packet()
    authority = _source_authority(packet)
    packet["subject_ref"] = "property:other"

    with pytest.raises(property_tour_hosting.GovernedPropertyTourContractError, match="source_authority_binding_mismatch"):
        property_tour_hosting.build_governed_property_tour_request(
            property_packet=packet,
            request_id="3d0dfa6e-27bb-48d1-b00b-7675ae02416f",
            idempotency_key="property-test-1",
            style_pack_id="decor-style:test-1",
            product_event_ref="event:property:test-1",
            verified_source_authority=authority,
            observed_at=NOW,
        )


@pytest.mark.parametrize("mutation", ["partial_route", "route_exclusion", "portal_mismatch", "walkable_inaccessible"])
def test_full_walkable_route_and_portal_truth_fail_closed(mutation: str) -> None:
    packet = _property_packet()
    if mutation == "partial_route":
        packet["route_room_ids"] = ["living"]
    elif mutation == "route_exclusion":
        packet["route_exclusions"] = [{"room_id": "bedroom"}]
    elif mutation == "portal_mismatch":
        packet["portals"] = []
    else:
        packet["rooms"][2]["walkable"] = True
        packet["rooms"][2]["accessible"] = True

    with pytest.raises(property_tour_hosting.GovernedPropertyTourContractError):
        _bridge(packet)


def test_non_hamiltonian_hub_layout_fails_closed_without_fabricated_jump_or_revisit() -> None:
    packet = _property_packet()
    for room_id in ("kitchen", "bath"):
        packet["rooms"].append(
            {
                "room_id": room_id,
                "room_type": room_id,
                "walkable": True,
                "accessible": True,
                "boundary_ref": f"geometry:{room_id}:boundary",
                "ceiling_height_m": 2.7,
                "geometry_anchor_ref": f"geometry:{room_id}:anchor",
                "texture_anchor_refs": [f"texture:{room_id}:1"],
            }
        )
    packet["portals"] = [
        {"portal_id": "bedroom-hub", "from_room_id": "bedroom", "to_room_id": "living", "walkable": True},
        {"portal_id": "hub-kitchen", "from_room_id": "living", "to_room_id": "kitchen", "walkable": True},
        {"portal_id": "hub-bath", "from_room_id": "living", "to_room_id": "bath", "walkable": True},
    ]
    packet["route_room_ids"] = ["bedroom", "living", "kitchen", "bath"]

    with pytest.raises(property_tour_hosting.GovernedPropertyTourContractError, match="route_portal_truth_mismatch"):
        _bridge(packet)


@pytest.mark.parametrize(
    ("room_ids", "edges", "priority", "expected_route"),
    [
        (["a", "b", "c"], [("a", "b"), ("b", "c")], ["a", "b", "c"], ["a", "b", "c"]),
        (["a", "b", "c"], [("a", "b"), ("b", "c")], ["b", "a", "c"], ["b", "a", "b", "c"]),
        (["studio"], [], ["studio"], ["studio"]),
        (
            ["bedroom", "hall", "kitchen", "bathroom"],
            [("bedroom", "hall"), ("hall", "kitchen"), ("hall", "bathroom")],
            ["bedroom", "hall", "kitchen", "bathroom"],
            ["bedroom", "hall", "kitchen", "hall", "bathroom"],
        ),
        (
            ["a", "b", "c", "d", "e"],
            [("a", "b"), ("b", "c"), ("b", "d"), ("d", "e")],
            ["a", "b", "c", "d", "e"],
            ["a", "b", "c", "b", "d", "e"],
        ),
        (
            ["a", "b", "c"],
            [("a", "b"), ("b", "c"), ("c", "a")],
            ["a", "b", "c"],
            ["a", "b", "c"],
        ),
        (
            ["a", "b", "c", "d"],
            [("a", "b"), ("a", "c"), ("b", "d"), ("c", "d")],
            ["a", "b", "c", "d"],
            ["a", "b", "d", "c"],
        ),
    ],
)
def test_property_v110_deterministic_dfs_layout_matrix(
    room_ids: list[str],
    edges: list[tuple[str, str]],
    priority: list[str],
    expected_route: list[str],
) -> None:
    bridge = _bridge(_v11_packet(room_ids, edges, priority=priority))
    request_plan = bridge["request"]["spatial_plan"]  # type: ignore[index]
    source_route = bridge["source_packet"]["route_room_ids"]  # type: ignore[index]

    assert bridge["contract_version"] == "1.1.0"
    assert request_plan["required_room_ids"] == priority
    assert request_plan["route_room_ids"] == expected_route
    assert source_route == expected_route
    assert request_plan["allow_revisit"] is (len(expected_route) != len(set(expected_route)))
    assert set(expected_route) == set(room_ids)
    assert len(expected_route) <= 2 * len(room_ids) - 1
    assert all(left != right for left, right in zip(expected_route, expected_route[1:]))


def test_property_v110_room_portal_and_reverse_direction_permutations_are_identical() -> None:
    packet = _v11_packet(
        ["bedroom", "hall", "kitchen", "bathroom"],
        [("hall", "bedroom"), ("kitchen", "hall"), ("bathroom", "hall")],
        priority=["bedroom", "hall", "kitchen", "bathroom"],
    )
    permuted = deepcopy(packet)
    permuted["rooms"] = list(reversed(permuted["rooms"]))  # type: ignore[arg-type]
    permuted["portals"] = list(reversed(permuted["portals"]))  # type: ignore[arg-type]

    first = _bridge(packet)
    second = _bridge(permuted)

    assert first == second
    assert first["request"]["spatial_plan"]["route_room_ids"] == [  # type: ignore[index]
        "bedroom",
        "hall",
        "kitchen",
        "hall",
        "bathroom",
    ]


def test_property_v110_multiple_door_identities_collapse_only_request_adjacency() -> None:
    packet = _v11_packet(["a", "b"], [("a", "b")])
    packet["portals"].append(  # type: ignore[union-attr]
        {
            "portal_id": "second-door",
            "from_room_id": "b",
            "to_room_id": "a",
            "walkable": True,
        }
    )

    bridge = _bridge(packet)

    assert bridge["request"]["spatial_plan"]["portal_edges"] == [  # type: ignore[index]
        {"from_room_id": "a", "to_room_id": "b"}
    ]
    assert len(bridge["source_packet"]["portals"]) == 2  # type: ignore[index]
    assert bridge["request"]["spatial_plan"]["route_room_ids"] == ["a", "b"]  # type: ignore[index]


def test_property_contract_versions_use_disjoint_exact_route_fields() -> None:
    legacy = _property_packet()
    legacy["route_priority_room_ids"] = ["living", "bedroom"]
    legacy["route_start_room_id"] = "living"
    with pytest.raises(property_tour_hosting.GovernedPropertyTourContractError, match="unknown_field"):
        _bridge(legacy)

    current = _v11_packet(["a", "b"], [("a", "b")])
    current["route_room_ids"] = ["a", "b"]
    with pytest.raises(property_tour_hosting.GovernedPropertyTourContractError, match="unknown_field:route_room_ids"):
        _bridge(current)


@pytest.mark.parametrize(
    ("mutation", "reason"),
    [
        (lambda packet: packet.__setitem__("route_priority_room_ids", "a"), "nonempty_list_required"),
        (lambda packet: packet.__setitem__("route_priority_room_ids", ["a", "b"]), "must_equal_walkable"),
        (lambda packet: packet.__setitem__("route_priority_room_ids", ["a", "b", "b", "c"]), "unique_required"),
        (lambda packet: packet.__setitem__("route_priority_room_ids", ["a", "b", "c", "attic"]), "must_equal_walkable"),
        (lambda packet: packet.__setitem__("route_priority_room_ids", ["a", "b", "service"]), "must_equal_walkable"),
        (lambda packet: packet.__setitem__("route_start_room_id", "b"), "start_must_equal_first"),
        (lambda packet: packet.pop("route_priority_room_ids"), "missing_field:route_priority_room_ids"),
        (lambda packet: packet.pop("route_start_room_id"), "missing_field:route_start_room_id"),
    ],
)
def test_property_v110_rejects_malformed_priority_and_start(mutation, reason: str) -> None:
    packet = _v11_packet(["a", "b", "c"], [("a", "b"), ("b", "c")])
    mutation(packet)
    with pytest.raises(property_tour_hosting.GovernedPropertyTourContractError, match=reason):
        _bridge(packet)


@pytest.mark.parametrize(
    ("mutation", "reason"),
    [
        (
            lambda packet: packet["portals"].__setitem__(  # type: ignore[union-attr]
                0,
                {
                    "portal_id": "self-door",
                    "from_room_id": "a",
                    "to_room_id": "a",
                    "walkable": True,
                },
            ),
            "property_portal_truth_invalid",
        ),
        (
            lambda packet: packet["portals"].append(deepcopy(packet["portals"][0])),  # type: ignore[index,union-attr]
            "property_portal_truth_invalid",
        ),
        (lambda packet: packet.__setitem__("portals", packet["portals"][:1]), "graph_disconnected"),
        (
            lambda packet: packet["portals"][0].__setitem__("to_room_id", "unknown"),  # type: ignore[index]
            "property_portal_truth_invalid",
        ),
    ],
)
def test_property_v110_rejects_malicious_portal_and_disconnected_shapes(mutation, reason: str) -> None:
    packet = _v11_packet(["a", "b", "c"], [("a", "b"), ("b", "c")])
    mutation(packet)
    with pytest.raises(property_tour_hosting.GovernedPropertyTourContractError, match=reason):
        _bridge(packet)


def test_property_v110_replay_is_stable_and_priority_changes_bind_idempotency_material() -> None:
    packet = _v11_packet(["a", "b", "c"], [("a", "b"), ("b", "c")])
    first = _bridge(packet)
    replay = _bridge(deepcopy(packet))
    changed = deepcopy(packet)
    changed["route_priority_room_ids"] = ["a", "c", "b"]
    changed_bridge = _bridge(changed)

    assert replay == first
    assert first["request"]["spatial_plan"]["route_room_ids"] == ["a", "b", "c"]  # type: ignore[index]
    assert changed_bridge["request"]["spatial_plan"]["route_room_ids"] == ["a", "b", "c"]  # type: ignore[index]
    assert changed_bridge["bridge_digest"] != first["bridge_digest"]
    assert changed_bridge["request"]["evidence_refs"] != first["request"]["evidence_refs"]  # type: ignore[index]


def test_property_v110_iterative_planner_handles_deep_linear_inventory() -> None:
    room_ids = [f"room-{index:04d}" for index in range(1500)]
    portals = [
        {
            "portal_id": f"door-{index:04d}",
            "from_room_id": room_ids[index],
            "to_room_id": room_ids[index + 1],
            "walkable": True,
        }
        for index in range(len(room_ids) - 1)
    ]

    route = property_tour_hosting._governed_property_route_plan(
        priority_room_ids=room_ids,
        start_room_id=room_ids[0],
        portals=portals,
    )

    assert route == room_ids
    assert len(route) <= 2 * len(room_ids) - 1


def test_property_v110_priority_requires_generic_room_tokens() -> None:
    packet = _v11_packet(["valid", "bad/room"], [("valid", "bad/room")])
    with pytest.raises(
        property_tour_hosting.GovernedPropertyTourContractError,
        match="property_route_priority_room_token_required",
    ):
        _bridge(packet)


def test_property_v110_route_exclusions_and_unsafe_fields_remain_forbidden() -> None:
    packet = _v11_packet(["a", "b"], [("a", "b")])
    packet["route_exclusions"] = [{"room_id": "b"}]
    with pytest.raises(property_tour_hosting.GovernedPropertyTourContractError, match="route_exclusions_forbidden"):
        _bridge(packet)

    unsafe = _v11_packet(["a", "b"], [("a", "b")])
    unsafe["rooms"][0]["provider_id"] = "private"  # type: ignore[index]
    with pytest.raises(property_tour_hosting.GovernedPropertyTourContractError, match="unsafe_field"):
        _bridge(unsafe)


def test_numeric_policy_missing_mutated_or_naive_fails_closed(tmp_path: Path) -> None:
    store = property_tour_hosting.GovernedPropertyTourLifecycleStore(tmp_path)
    missing = store.intake(
        slug="tour-1",
        policy_payload=None,
        observed_at=NOW,
        bridge_digest=_digest("2"),
        composition_digest=_digest("3"),
        composition_receipt_digest=_digest("4"),
    )
    assert missing["status"] == "blocked"

    mutated = _policy()
    mutated["source_retention_days"] = 8
    with pytest.raises(property_tour_hosting.GovernedPropertyTourContractError, match="retention_policy_digest_invalid"):
        _intake(store, policy=mutated)
    with pytest.raises(property_tour_hosting.GovernedPropertyTourContractError, match="observed_at_timezone_required"):
        store.public_state(slug="tour-1", observed_at=NOW.replace(tzinfo=None))


def test_lifecycle_intake_is_restartable_idempotent_and_conflicts_on_changed_material(tmp_path: Path) -> None:
    store = property_tour_hosting.GovernedPropertyTourLifecycleStore(tmp_path)
    first = _intake(store)
    replay = _intake(property_tour_hosting.GovernedPropertyTourLifecycleStore(tmp_path))

    assert first == replay
    assert first["status"] == "active_private"
    assert stat.S_IMODE(store.private_root.stat().st_mode) == 0o700
    assert stat.S_IMODE(store.state_path("tour-1").stat().st_mode) == 0o600
    assert stat.S_IMODE(store.index_path.stat().st_mode) == 0o600
    with pytest.raises(property_tour_hosting.GovernedPropertyTourContractError, match="intake_conflict"):
        _intake(store, composition_digest=_digest("e"))


def test_lifecycle_concurrent_intake_has_one_lineage_and_no_temporary_files(tmp_path: Path) -> None:
    store = property_tour_hosting.GovernedPropertyTourLifecycleStore(tmp_path)

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda _index: _intake(store), range(16)))

    assert len({result["integrity_digest"] for result in results}) == 1
    assert list(store.state_root.glob("*.json")) == [store.state_path("tour-1")]
    assert not list(store.private_root.rglob("*.tmp"))
    restarted = property_tour_hosting.GovernedPropertyTourLifecycleStore(tmp_path)
    assert restarted.private_state(slug="tour-1")["integrity_digest"] == results[0]["integrity_digest"]


def test_concurrent_lifecycle_constructors_are_idempotent_and_symlink_safe(tmp_path: Path) -> None:
    def construct(_index: int) -> str:
        store = property_tour_hosting.GovernedPropertyTourLifecycleStore(tmp_path)
        return store.index_path.read_text(encoding="utf-8")

    with ThreadPoolExecutor(max_workers=12) as pool:
        indexes = list(pool.map(construct, range(24)))

    assert len(set(indexes)) == 1
    for directory in (
        tmp_path / ".governed-spatial-lifecycle",
        tmp_path / ".governed-spatial-lifecycle" / "states",
        tmp_path / ".governed-spatial-lifecycle" / "tombstones",
        tmp_path / ".governed-spatial-lifecycle" / "transactions",
    ):
        assert not directory.is_symlink()
        assert stat.S_IMODE(directory.stat().st_mode) == 0o700


def test_lifecycle_rejects_symlinked_parent_family_and_final_record(tmp_path: Path) -> None:
    real_root = tmp_path / "real"
    real_root.mkdir()
    linked_root = tmp_path / "linked"
    linked_root.symlink_to(real_root, target_is_directory=True)
    with pytest.raises(property_tour_hosting.GovernedPropertyTourIntegrityError):
        property_tour_hosting.GovernedPropertyTourLifecycleStore(linked_root)

    family_root = tmp_path / "family"
    family_root.mkdir()
    private = family_root / ".governed-spatial-lifecycle"
    private.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (private / "states").symlink_to(outside, target_is_directory=True)
    (private / "tombstones").mkdir()
    with pytest.raises((property_tour_hosting.GovernedPropertyTourIntegrityError, OSError)):
        property_tour_hosting.GovernedPropertyTourLifecycleStore(family_root)

    final_root = tmp_path / "final"
    final_root.mkdir()
    store = property_tour_hosting.GovernedPropertyTourLifecycleStore(final_root)
    target = tmp_path / "target.json"
    target.write_text("{}", encoding="utf-8")
    store.state_path("tour-1").symlink_to(target)
    with pytest.raises((property_tour_hosting.GovernedPropertyTourIntegrityError, OSError)):
        _intake(store)
    assert target.read_text(encoding="utf-8") == "{}"


def test_lifecycle_tamper_blocks_restart(tmp_path: Path) -> None:
    store = property_tour_hosting.GovernedPropertyTourLifecycleStore(tmp_path)
    _intake(store)
    path = store.state_path("tour-1")
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["status"] = "active"
    path.write_text(json.dumps(payload), encoding="utf-8")
    path.chmod(0o600)

    with pytest.raises(property_tour_hosting.GovernedPropertyTourIntegrityError):
        property_tour_hosting.GovernedPropertyTourLifecycleStore(tmp_path)


@pytest.mark.parametrize("fault_stage", ["after_intake_intent", "after_intake_state", "after_intake_index"])
def test_intake_transaction_recovers_every_durable_boundary(tmp_path: Path, fault_stage: str) -> None:
    store = property_tour_hosting.GovernedPropertyTourLifecycleStore(tmp_path)

    def inject(stage: str) -> None:
        if stage == fault_stage:
            raise RuntimeError(f"fault:{stage}")

    store._intake_fault = inject
    with pytest.raises(RuntimeError, match=fault_stage):
        _intake(store)

    assert list(store.transaction_root.glob("*.json"))
    restarted = property_tour_hosting.GovernedPropertyTourLifecycleStore(tmp_path)
    assert not list(restarted.transaction_root.glob("*.json"))
    state = restarted.private_state(slug="tour-1")
    assert state is not None
    assert state["status"] == "active_private"
    assert state["owner_principal_digest"].startswith("sha256:")


@pytest.mark.parametrize("fault_stage", ["after_intent", "after_bundle_delete", "after_tombstone", "after_index"])
def test_closeout_transaction_recovers_every_durable_boundary_without_restoring_bytes(
    tmp_path: Path,
    fault_stage: str,
) -> None:
    slug = f"tour-fault-{fault_stage}"
    bundle = tmp_path / slug
    bundle.mkdir()
    (bundle / "source.bin").write_bytes(b"private-source")
    store = property_tour_hosting.GovernedPropertyTourLifecycleStore(tmp_path)
    _intake(store, slug=slug)

    def inject(stage: str) -> None:
        if stage == fault_stage:
            raise RuntimeError(f"fault:{stage}")

    store._closeout_fault = inject
    with pytest.raises(RuntimeError, match=fault_stage):
        store.closeout(
            slug=slug,
            action="revoked",
            reason_digest=_digest("f"),
            observed_at=NOW,
            cascade_evidence_digests=[_digest("0")],
        )

    assert list(store.transaction_root.glob("*.json"))
    restarted = property_tour_hosting.GovernedPropertyTourLifecycleStore(tmp_path)
    assert not bundle.exists()
    assert not list(restarted.transaction_root.glob("*.json"))
    assert restarted.public_state(slug=slug, observed_at=NOW)["status"] == "blocked"
    tombstone = json.loads(restarted.tombstone_path(slug).read_text(encoding="utf-8"))
    assert tombstone["material_digest"].startswith("sha256:")
    assert tombstone["local_deletion_complete"] is True


@pytest.mark.parametrize("action", ["revoked", "deleted"])
def test_post_completion_privacy_closeout_blocks_replay_and_restart(tmp_path: Path, action: str) -> None:
    slug = f"tour-{action}"
    bundle = tmp_path / slug
    bundle.mkdir()
    (bundle / "tour.json").write_text("{}", encoding="utf-8")
    store = property_tour_hosting.GovernedPropertyTourLifecycleStore(tmp_path)
    policy = _policy()
    publication = _publication(slug=slug, policy=policy)
    _intake(store, slug=slug, policy=policy, publication=publication)
    assert store.public_state(slug=slug, observed_at=NOW)["serving_allowed"] is True

    tombstone = store.closeout(
        slug=slug,
        action=action,
        reason_digest=_digest("f"),
        observed_at=NOW,
        cascade_evidence_digests=[_digest("0")],
    )
    replay = store.closeout(
        slug=slug,
        action=action,
        reason_digest=_digest("f"),
        observed_at=NOW,
        cascade_evidence_digests=[_digest("0")],
    )

    assert tombstone == replay
    assert tombstone["revoked"] is True
    assert tombstone["deleted"] is True
    assert not bundle.exists()
    restarted = property_tour_hosting.GovernedPropertyTourLifecycleStore(tmp_path)
    assert restarted.public_state(slug=slug, observed_at=NOW)["status"] == "blocked"
    with pytest.raises(property_tour_hosting.GovernedPropertyTourContractError, match="self_restoration_forbidden"):
        restarted.restore(slug=slug)
    with pytest.raises(property_tour_hosting.GovernedPropertyTourContractError, match="privacy_closeout_conflict"):
        restarted.closeout(
            slug=slug,
            action="withdrawn",
            reason_digest=_digest("a"),
            observed_at=NOW,
        )


def test_valid_legal_hold_retains_only_evidence_and_never_serves_or_restores(tmp_path: Path) -> None:
    slug = "tour-hold"
    bundle = tmp_path / slug
    bundle.mkdir()
    store = property_tour_hosting.GovernedPropertyTourLifecycleStore(tmp_path)
    policy = _policy()
    _intake(store, slug=slug, policy=policy, publication=_publication(slug=slug, policy=policy))
    hold = _legal_hold(
        slug=slug,
        expires_at=NOW + timedelta(days=2),
        review_due_at=NOW + timedelta(days=1),
    )

    tombstone = store.closeout(
        slug=slug,
        action="revoked",
        reason_digest=_digest("f"),
        observed_at=NOW,
        legal_hold=hold,
    )

    assert tombstone["deleted"] is True
    assert tombstone["revoked"] is True
    assert tombstone["legal_hold"]["state"] == "valid_retain_evidence_only"
    assert not bundle.exists()
    assert store.public_state(slug=slug, observed_at=NOW)["serving_allowed"] is False
    with pytest.raises(property_tour_hosting.GovernedPropertyTourContractError):
        store.restore(slug=slug)


def test_expired_legal_hold_does_not_restore_or_prevent_local_deletion(tmp_path: Path) -> None:
    slug = "tour-expired-hold"
    bundle = tmp_path / slug
    bundle.mkdir()
    store = property_tour_hosting.GovernedPropertyTourLifecycleStore(tmp_path)
    _intake(store, slug=slug)
    expired = _legal_hold(
        slug=slug,
        expires_at=NOW - timedelta(seconds=1),
        review_due_at=NOW - timedelta(minutes=1),
    )

    tombstone = store.closeout(
        slug=slug,
        action="deleted",
        reason_digest=_digest("f"),
        observed_at=NOW,
        legal_hold=expired,
    )

    assert tombstone["deleted"] is True
    assert tombstone["legal_hold"]["state"] == "invalid_fail_closed"
    assert not bundle.exists()
    assert store.public_state(slug=slug, observed_at=NOW)["status"] == "blocked"


def test_retention_expiry_blocks_immediately_and_executes_idempotent_closeout(tmp_path: Path) -> None:
    slug = "tour-expiry"
    bundle = tmp_path / slug
    bundle.mkdir()
    store = property_tour_hosting.GovernedPropertyTourLifecycleStore(tmp_path)
    _intake(store, slug=slug, policy=_policy(source_days=1))
    after_expiry = NOW + timedelta(days=1, seconds=1)

    assert store.public_state(slug=slug, observed_at=after_expiry)["reason"] == "retention_expired"
    first = store.enforce_retention(slug=slug, observed_at=after_expiry)
    second = store.enforce_retention(slug=slug, observed_at=after_expiry)
    assert first == second
    assert first["deleted"] is True
    assert not bundle.exists()


def test_public_enforcement_ignores_unsigned_marker_and_uses_current_lifecycle(tmp_path: Path) -> None:
    slug = "tour-public"
    store = property_tour_hosting.GovernedPropertyTourLifecycleStore(tmp_path)
    policy = _policy()
    _intake(store, slug=slug, policy=policy, publication=_publication(slug=slug, policy=policy))
    active_state = store.public_state(slug=slug, observed_at=NOW)
    payload = {
        "slug": slug,
        "governed_spatial": {
            "contract_name": "propertyquarry.governed_spatial_public_binding.v1",
            "composition_digest": active_state["composition_digest"],
            "artifact_digest": active_state["artifact_digest"],
            "publication_decision_digest": active_state["publication_decision_digest"],
        },
    }
    resolver = lambda resolved_slug, observed: store.public_state(slug=resolved_slug, observed_at=observed)

    require_governed_spatial_public_tour_viewable(payload, observed_at=NOW, lifecycle_resolver=resolver)
    replayed_binding = deepcopy(payload)
    replayed_binding["governed_spatial"]["artifact_digest"] = _digest("e")
    with pytest.raises(HTTPException):
        require_governed_spatial_public_tour_viewable(
            replayed_binding,
            observed_at=NOW,
            lifecycle_resolver=resolver,
        )
    marker_removed = {"slug": slug}
    with pytest.raises(HTTPException) as marker_failure:
        require_governed_spatial_public_tour_viewable(
            marker_removed,
            observed_at=NOW,
            lifecycle_resolver=resolver,
        )
    assert marker_failure.value.status_code == 404
    store.closeout(
        slug=slug,
        action="revoked",
        reason_digest=_digest("f"),
        observed_at=NOW,
    )
    with pytest.raises(HTTPException) as failure:
        require_governed_spatial_public_tour_viewable(payload, observed_at=NOW, lifecycle_resolver=resolver)
    assert failure.value.status_code == 404

    require_governed_spatial_public_tour_viewable(
        {"slug": "legacy-tour"},
        observed_at=NOW,
        lifecycle_resolver=lambda _slug, _observed: {
            "status": "blocked",
            "reason": "privacy_lifecycle_missing",
        },
    )


def test_publication_decision_replay_with_wrong_output_or_policy_binding_is_rejected(tmp_path: Path) -> None:
    store = property_tour_hosting.GovernedPropertyTourLifecycleStore(tmp_path)
    policy = _policy()
    decision = _publication(slug="tour-1", policy=policy)
    material = decision.material()
    material["artifact_digest"] = _digest("e")
    replayed = property_tour_hosting.VerifiedGovernedPropertyTourPublication(
        **material,
        decision_digest=decision.decision_digest,
    )

    with pytest.raises(property_tour_hosting.GovernedPropertyTourContractError, match="decision_digest_invalid"):
        _intake(store, policy=policy, publication=replayed)


def _landing_client(
    tmp_path: Path,
    *,
    publication: bool = False,
    policy_verifier_mode: str = "approved",
) -> tuple[TestClient, dict[str, int], property_tour_hosting.GovernedPropertyTourLifecycleStore]:
    store = property_tour_hosting.GovernedPropertyTourLifecycleStore(tmp_path)
    calls = {"source": 0, "policy": 0, "compose": 0, "publication": 0}

    def verify_source(packet: Mapping[str, object], principal_id: str):
        assert principal_id == "principal:test"
        calls["source"] += 1
        return _source_authority(dict(packet))

    def compose(bridge: Mapping[str, object]):
        calls["compose"] += 1
        assert bridge["request"]["quota"] == {"consume_quota": False, "maximum_provider_attempts": 0}
        return {
            "status": "accepted",
            "audit_only": True,
            "executable": False,
            "quota_mutated": False,
            "provider_job_enqueued": False,
            "composition_digest": _digest("3"),
            "composition_receipt_digest": _digest("4"),
        }

    def verify_policy(payload: Mapping[str, object], principal_id: str):
        assert principal_id == "principal:test"
        calls["policy"] += 1
        if policy_verifier_mode == "wrong_type":
            return dict(payload)
        if policy_verifier_mode == "stale":
            stale_material = {
                **{key: value for key, value in _policy().items() if key != "policy_digest"},
                "approved_at": (NOW - timedelta(days=3)).isoformat().replace("+00:00", "Z"),
                "expires_at": (NOW - timedelta(days=1)).isoformat().replace("+00:00", "Z"),
            }
            stale_payload = {
                **stale_material,
                "policy_digest": property_tour_hosting._governed_spatial_digest(stale_material),
            }
            return property_tour_hosting.GovernedPropertyTourRetentionPolicy.from_payload(
                stale_payload,
                observed_at=NOW - timedelta(days=2),
            )
        approved_payload = _policy(source_days=8) if policy_verifier_mode == "binding_mismatch" else _policy()
        if policy_verifier_mode == "approved" and dict(payload) != approved_payload:
            raise property_tour_hosting.GovernedPropertyTourContractError("retention_policy_not_approved")
        return property_tour_hosting.GovernedPropertyTourRetentionPolicy.from_payload(
            approved_payload,
            observed_at=NOW,
        )

    def verify_publication(bridge, composition, policy, principal_id, slug):
        del bridge, principal_id
        calls["publication"] += 1
        return _publication(
            slug=slug,
            composition_digest=str(composition["composition_digest"]),
            policy=dict(policy),
        )

    runtime = landing.GovernedPropertyTourBridgeRuntime(
        lifecycle_store=store,
        source_authority_verifier=verify_source,
        retention_policy_verifier=None if policy_verifier_mode == "absent" else verify_policy,
        compose_audit=compose,
        publication_authority_verifier=verify_publication if publication else None,
        now=lambda: NOW,
    )
    app = FastAPI()
    runtime_factory_calls = {"count": 0}

    def runtime_factory():
        runtime_factory_calls["count"] += 1
        return runtime

    app.state.governed_property_tour_runtime_factory = runtime_factory
    app.state.governed_property_tour_runtime_factory_calls = runtime_factory_calls
    app.dependency_overrides[landing.get_request_context] = lambda: RequestContext(
        principal_id="principal:test",
        authenticated=True,
        auth_source="workspace_access_session",
        operator_id="",
    )
    app.include_router(landing.router)
    return TestClient(app), calls, store


def _intake_payload() -> dict[str, object]:
    return {
        "contract_name": "propertyquarry.governed_spatial_lifecycle_intake.v1",
        "property_packet": _property_packet(),
        "request_id": "3d0dfa6e-27bb-48d1-b00b-7675ae02416f",
        "idempotency_key": "property-test-1-walkthrough-v1",
        "style_pack_id": "decor-style:test-1",
        "product_event_ref": "event:property:test-1",
        "retention_policy": _policy(),
    }


def test_ordinary_authenticated_workspace_principal_can_manage_own_scope(tmp_path: Path) -> None:
    client, calls, store = _landing_client(tmp_path)
    intake = client.post(
        "/app/api/property/governed-spatial/tours/tour-1/intake",
        json=_intake_payload(),
    )
    status = client.get("/app/api/property/governed-spatial/tours/tour-1/status")
    closeout = client.post(
        "/app/api/property/governed-spatial/tours/tour-1/privacy-closeout",
        json={
            "contract_name": "propertyquarry.governed_spatial_privacy_closeout.v1",
            "action": "revoked",
            "reason_digest": _digest("f"),
            "cascade_evidence_digests": [_digest("0")],
            "legal_hold": None,
        },
    )

    assert intake.status_code == 200
    assert intake.json()["status"] == "active_private"
    assert intake.json()["public_ready"] is False
    assert intake.json()["serving_allowed"] is False
    assert status.status_code == 200
    assert closeout.status_code == 200
    assert closeout.json()["revoked"] is True
    assert closeout.json()["artifact_ref"] == ""
    assert calls == {"source": 1, "policy": 1, "compose": 1, "publication": 0}
    assert client.app.state.governed_property_tour_runtime_factory_calls["count"] == 3
    assert store.public_state(slug="tour-1", observed_at=NOW)["status"] == "blocked"
    serialized = json.dumps([intake.json(), status.json(), closeout.json()]).lower()
    for forbidden in ("source_packet_ref", "authorization_ref", "evidence_refs", "provider_url", "private_url"):
        assert forbidden not in serialized


def test_landing_raw_duplicate_rejected_before_source_or_compose(tmp_path: Path) -> None:
    client, calls, _store = _landing_client(tmp_path)
    response = client.post(
        "/app/api/property/governed-spatial/tours/tour-1/intake",
        content=b'{"contract_name":"x","property_packet":{"same":1,"same":2}}',
        headers={"content-type": "application/json"},
    )

    assert response.status_code == 422
    assert response.json() == {"detail": "duplicate_member"}
    assert calls == {"source": 0, "policy": 0, "compose": 0, "publication": 0}


@pytest.mark.parametrize(
    ("mode", "status_code", "detail", "policy_calls"),
    [
        ("absent", 503, "retention_policy_authority_unconfigured", 0),
        ("wrong_type", 503, "retention_policy_authority_invalid", 1),
        ("stale", 422, "retention_policy_not_current", 1),
        ("binding_mismatch", 422, "retention_policy_binding_mismatch", 1),
    ],
)
def test_landing_policy_authority_fails_closed_before_source_compose_or_store(
    tmp_path: Path,
    mode: str,
    status_code: int,
    detail: str,
    policy_calls: int,
) -> None:
    client, calls, store = _landing_client(tmp_path, policy_verifier_mode=mode)
    before_index = store.index_path.read_bytes()

    response = client.post(
        "/app/api/property/governed-spatial/tours/tour-1/intake",
        json=_intake_payload(),
    )

    assert response.status_code == status_code
    assert response.json() == {"detail": detail}
    assert calls == {"source": 0, "policy": policy_calls, "compose": 0, "publication": 0}
    assert store.index_path.read_bytes() == before_index
    assert store.private_state(slug="tour-1") is None


def test_caller_cannot_self_approve_mutated_numeric_policy_with_recomputed_digest(tmp_path: Path) -> None:
    client, calls, store = _landing_client(tmp_path)
    request_payload = _intake_payload()
    policy_material = {
        **{
            key: value
            for key, value in dict(request_payload["retention_policy"]).items()
            if key != "policy_digest"
        },
        "source_retention_days": 365,
    }
    request_payload["retention_policy"] = {
        **policy_material,
        "policy_digest": property_tour_hosting._governed_spatial_digest(policy_material),
    }

    response = client.post(
        "/app/api/property/governed-spatial/tours/tour-1/intake",
        json=request_payload,
    )

    assert response.status_code == 422
    assert response.json() == {"detail": "retention_policy_not_approved"}
    assert calls == {"source": 0, "policy": 1, "compose": 0, "publication": 0}
    assert store.private_state(slug="tour-1") is None


@pytest.mark.parametrize("operation", ["intake", "status", "closeout"])
@pytest.mark.parametrize(
    ("principal_id", "authenticated", "auth_source"),
    [
        ("", False, "anonymous"),
        ("local-user", True, "loopback_no_auth"),
    ],
)
def test_landing_lifecycle_routes_reject_unauthenticated_context_before_runtime(
    tmp_path: Path,
    operation: str,
    principal_id: str,
    authenticated: bool,
    auth_source: str,
) -> None:
    client, calls, _store = _landing_client(tmp_path)
    before_index = _store.index_path.read_bytes()

    client.app.dependency_overrides[landing.get_request_context] = lambda: RequestContext(
        principal_id=principal_id,
        authenticated=authenticated,
        auth_source=auth_source,
    )
    if operation == "intake":
        response = client.post(
            "/app/api/property/governed-spatial/tours/tour-1/intake",
            json=_intake_payload(),
        )
    elif operation == "status":
        response = client.get("/app/api/property/governed-spatial/tours/tour-1/status")
    else:
        response = client.post(
            "/app/api/property/governed-spatial/tours/tour-1/privacy-closeout",
            json={
                "contract_name": "propertyquarry.governed_spatial_privacy_closeout.v1",
                "action": "revoked",
                "reason_digest": _digest("f"),
                "cascade_evidence_digests": [],
                "legal_hold": None,
            },
        )

    assert response.status_code == 401
    assert response.json() == {"detail": "authentication_required"}
    assert client.app.state.governed_property_tour_runtime_factory_calls["count"] == 0
    assert calls == {"source": 0, "policy": 0, "compose": 0, "publication": 0}
    assert _store.index_path.read_bytes() == before_index
    assert _store.private_state(slug="tour-1") is None


def test_authenticated_principal_cannot_read_or_close_another_principals_tenant_scope(tmp_path: Path) -> None:
    client, calls, store = _landing_client(tmp_path)
    intake = client.post(
        "/app/api/property/governed-spatial/tours/tour-1/intake",
        json=_intake_payload(),
    )
    assert intake.status_code == 200
    original = store.private_state(slug="tour-1")
    client.app.dependency_overrides[landing.get_request_context] = lambda: RequestContext(
        principal_id="principal:other-tenant",
        authenticated=True,
        auth_source="workspace_access_session",
        operator_id="",
    )

    status = client.get("/app/api/property/governed-spatial/tours/tour-1/status")
    closeout = client.post(
        "/app/api/property/governed-spatial/tours/tour-1/privacy-closeout",
        json={
            "contract_name": "propertyquarry.governed_spatial_privacy_closeout.v1",
            "action": "revoked",
            "reason_digest": _digest("f"),
            "cascade_evidence_digests": [],
            "legal_hold": None,
        },
    )

    assert status.status_code == 404
    assert closeout.status_code == 404
    assert store.private_state(slug="tour-1") == original
    assert not store.tombstone_path("tour-1").exists()
    assert calls == {"source": 1, "policy": 1, "compose": 1, "publication": 0}


def test_exact_research_regression_route_remains_representable(tmp_path: Path) -> None:
    client, _calls, _store = _landing_client(tmp_path)
    route_paths = {route.path for route in client.app.routes}

    assert "/app/research/{candidate_ref}" in route_paths
    url = "/app/research/d907fa5b6b5d7308?run_id=727428e87aa544de82d2682a79e6da16"
    assert url.startswith("/app/research/d907fa5b6b5d7308?")


def test_product_projection_never_exposes_private_artifact_or_provider_fields() -> None:
    projection = property_tour_hosting.governed_property_tour_public_projection(
        composition_receipt={
            "status": "accepted",
            "composition_digest": _digest("3"),
            "request_id": "private-request",
            "provider_resolution": {"selected_provider_private": "private-provider"},
            "output_manifest_ref": "private:manifest:1",
        },
        lifecycle_state={"status": "active_private", "revoked": False, "deleted": False},
    )

    assert projection["state"] == "composed_private"
    assert projection["public_ready"] is False
    assert projection["serving_allowed"] is False
    assert projection["artifact_ref"] == ""
    serialized = json.dumps(projection)
    assert "private-provider" not in serialized
    assert "private:manifest" not in serialized

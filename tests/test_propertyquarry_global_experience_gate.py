from __future__ import annotations

import copy
import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from scripts.propertyquarry_global_experience_gate import (
    CONTRACT_SCHEMA,
    GATE_RECEIPT_SCHEMA,
    LIVE_RECEIPT_SCHEMA,
    _attested_payload_digest,
    build_global_experience_gate_receipt,
    main,
    validate_contract,
)


ROOT = Path(__file__).resolve().parents[1]
CONTRACT_PATH = ROOT / "config/monitoring/propertyquarry_global_experience.v1.json"
NOW = datetime(2026, 7, 19, 12, 0, tzinfo=timezone.utc)
COMMIT = "0123456789abcdef0123456789abcdef01234567"
IMAGE = "sha256:89abcdef0123456789abcdef0123456789abcdef0123456789abcdef01234567"
DIGEST = "sha256:fedcba9876543210fedcba9876543210fedcba9876543210fedcba9876543210"
ROUTES = (
    "/",
    "/pricing",
    "/security",
    "/support",
    "/privacy",
    "/terms",
    "/cookies",
    "/subprocessors",
    "/refunds",
    "/disclaimers",
    "/imprint",
    "/integrations",
    "/docs",
    "/guides/wohnung-kaufen-wien-checkliste",
    "/markets/vienna",
    "/sign-in",
    "/register",
    "/app/search",
    "/app/properties",
    "/app/shortlist",
    "/app/agents",
    "/app/alerts",
    "/app/research",
    "/app/account",
    "/app/billing",
    "/app/support",
    "/app/settings/google",
    "/app/settings/access",
    "/app/settings/usage",
    "/app/settings/support",
    "/app/settings/trust",
    "/app/settings/invitations",
    "/app/settings/outcomes",
    "/app/settings/plan",
    "/app/properties/packets",
    "/app/properties/notifications/preview",
    "/app/research/{candidate_ref}",
    "/app/shortlist/run/{run_id}",
    "/tours/{slug}",
)
CONCRETE_ROUTES = tuple(
    {
        "/app/research/{candidate_ref}": "/app/research/candidate-7f3a9c?run_id=run-91bd22",
        "/app/shortlist/run/{run_id}": "/app/shortlist/run/run-91bd22",
        "/tours/{slug}": "/tours/altbau-u6-3dvista",
    }.get(route, route)
    for route in ROUTES
)
CRITICAL_SCENARIOS = (
    "authentication_success",
    "authentication_failure",
    "expired_session_recovery",
    "billing_handoff_ready",
    "billing_handoff_unavailable",
    "http_401",
    "http_403",
    "http_404",
    "http_422",
    "http_429",
    "http_500",
    "http_503",
    "tour_ready",
    "tour_unavailable",
    "tour_revoked",
)


def _stamp(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


def _evidence(suffix: str, observed_at: datetime | None = None) -> dict[str, object]:
    return {
        "status": "pass",
        "observed_at": _stamp(observed_at or (NOW - timedelta(hours=1))),
        "evidence_digest": DIGEST,
        "workflow_ref": f"workflow:global-experience:{suffix}:8f27c4",
    }


def _market(country_code: str, locale: str) -> dict[str, object]:
    market_metadata = {
        "AT": {"currency": "EUR", "timezone": "Europe/Vienna"},
        "DE": {"currency": "EUR", "timezone": "Europe/Berlin"},
        "CR": {"currency": "CRC", "timezone": "America/Costa_Rica"},
    }[country_code]
    routes = list(CONCRETE_ROUTES)
    native_checks = {
        check: True
        for check in (
            "native_ui_copy",
            "native_public_content",
            "forms_and_validation",
            "currency_number_date_time",
            "address_and_region_conventions",
            "text_expansion_and_layout",
        )
    }
    manual_tasks = [
        {
            "task_id": task_id,
            "outcome": "pass",
            "evidence": _evidence(f"{country_code}:a11y:{task_id}"),
        }
        for task_id in (
            "keyboard_navigation",
            "screen_reader_desktop",
            "screen_reader_mobile",
            "zoom_200_percent",
            "zoom_400_percent",
            "reduced_motion",
        )
    ]
    screen_readers = [
        {
            "platform_id": platform_id,
            "outcome": "pass",
            "evidence": _evidence(f"{country_code}:reader:{platform_id}"),
        }
        for platform_id in (
            "nvda_windows",
            "voiceover_macos",
            "voiceover_ios",
            "talkback_android",
        )
    ]
    engines = [
        {
            "engine": engine,
            "outcome": "pass",
            "route_count": len(routes),
            "tested_routes": routes,
            "tested_scenarios": list(CRITICAL_SCENARIOS),
            "wcag_tags": ["wcag2a", "wcag2aa", "wcag21aa", "wcag22aa"],
            "serious_or_critical_violations": 0,
            "evidence": _evidence(f"{country_code}:axe:{engine}"),
        }
        for engine in ("chromium", "firefox", "webkit")
    ]
    desktop_runs = [
        {
            "engine": engine,
            "browser_version": f"{engine}-release-2026.07.19",
            "browser_binary_digest": DIGEST,
            "execution_environment": "isolated-browser-lab:eu-central-1",
            "outcome": "pass",
            "tested_routes": routes,
            "tested_scenarios": list(CRITICAL_SCENARIOS),
            "evidence": _evidence(f"{country_code}:desktop:{engine}"),
        }
        for engine in ("chromium", "firefox", "webkit")
    ]
    mobile_runs = [
        {
            "profile_id": "ios_safari_390x844",
            "engine": "webkit",
            "browser_family": "safari",
            "operating_system": "ios",
            "execution_environment": "physical_device",
            "browser_version": "mobile-safari-26.0-build-23A5318c",
            "operating_system_version": "ios-26.0-build-23A5318c",
            "device_model": "apple-iphone-16-pro-device-4fd8",
            "device_lab_ref": "device-lab:ios:physical:74cf3d9",
            "viewport_width": 390,
            "viewport_height": 844,
            "outcome": "pass",
            "tested_routes": routes,
            "tested_scenarios": list(CRITICAL_SCENARIOS),
            "evidence": _evidence(f"{country_code}:mobile:ios"),
        },
        {
            "profile_id": "android_chrome_412x915",
            "engine": "chromium",
            "browser_family": "chrome",
            "operating_system": "android",
            "execution_environment": "physical_device",
            "browser_version": "chrome-138.0.7204.168-stable",
            "operating_system_version": "android-16-build-BP2A.250605.031",
            "device_model": "google-pixel-9-pro-device-a28c",
            "device_lab_ref": "device-lab:android:physical:62ea91d",
            "viewport_width": 412,
            "viewport_height": 915,
            "outcome": "pass",
            "tested_routes": routes,
            "tested_scenarios": list(CRITICAL_SCENARIOS),
            "evidence": _evidence(f"{country_code}:mobile:android"),
        },
    ]
    network_scenarios = [
        {
            "scenario_id": scenario_id,
            "outcome": "pass",
            "recovered": True,
            "no_data_loss": True,
            "no_duplicate_mutation": True,
            "evidence": _evidence(f"{country_code}:network:{scenario_id}"),
        }
        for scenario_id in (
            "slow_3g",
            "offline_reconnect",
            "packet_loss_retry",
            "request_timeout_recovery",
        )
    ]
    seo_checks = {
        check: True
        for check in (
            "html_lang",
            "content_language",
            "self_canonical",
            "reciprocal_hreflang",
            "localized_title_and_description",
            "sitemap_membership",
            "robots_indexable",
        )
    }
    critical_states = [
        {
            "scenario_id": scenario_id,
            "outcome": "pass",
            "useful_next_action": True,
            "customer_data_preserved": True,
            "evidence": _evidence(f"{country_code}:critical-state:{scenario_id}"),
        }
        for scenario_id in CRITICAL_SCENARIOS
    ]
    return {
        "country_code": country_code,
        "locale": locale,
        **market_metadata,
        "native_content_review": {
            "reviewer_independent": True,
            "native_reviewer_ref": f"reviewer:{country_code}:native:74cf3d9",
            "reviewer_locale": locale,
            "reviewer_proficiency": "native",
            "reviewer_qualification_ref": f"qualification:{country_code}:{locale}:91bc48e",
            "reviewed_routes": routes,
            "reviewed_scenarios": list(CRITICAL_SCENARIOS),
            "checks": native_checks,
            "evidence": _evidence(f"{country_code}:native"),
        },
        "accessibility": {
            "standard": "WCAG 2.2 AA",
            "automated": {"runs": engines},
            "manual": {
                "tested_scenarios": list(CRITICAL_SCENARIOS),
                "tasks": manual_tasks,
                "screen_reader_platforms": screen_readers,
            },
        },
        "browser_device_coverage": {
            "desktop_runs": desktop_runs,
            "mobile_runs": mobile_runs,
        },
        "field_core_web_vitals": {
            "measurement_scope": "field_rum",
            "percentile": 75,
            "device_cohorts": [
                {
                    "cohort_id": cohort_id,
                    "window_start": _stamp(NOW - timedelta(days=29, hours=1)),
                    "window_end": _stamp(NOW - timedelta(hours=1)),
                    "sample_count": 250,
                    "metrics": {
                        "LCP": {"value": 2400, "unit": "ms"},
                        "INP": {"value": 190, "unit": "ms"},
                        "CLS": {"value": 0.09, "unit": "score"},
                    },
                    "evidence": _evidence(f"{country_code}:field-rum:{cohort_id}"),
                }
                for cohort_id in ("desktop", "mobile")
            ],
            "evidence": _evidence(f"{country_code}:field-rum"),
        },
        "degraded_network_recovery": {"scenarios": network_scenarios},
        "critical_state_scenarios": {"scenarios": critical_states},
        "localized_seo": {
            "html_lang": locale,
            "content_language": locale,
            "indexable_route_count": 7,
            "hreflang_values": ["de-AT", "de-DE", "es-CR", "x-default"],
            "checks": seo_checks,
            "evidence": _evidence(f"{country_code}:seo"),
        },
    }


def _live_receipt() -> dict[str, object]:
    contract_sha = hashlib.sha256(CONTRACT_PATH.read_bytes()).hexdigest()
    approvals = [
        {
            "role": role,
            "outcome": "approved",
            "approver_ref": f"approver:{role}:659d8f",
            "evidence": _evidence(f"approval:{role}"),
        }
        for role in (
            "global_experience_owner",
            "accessibility_owner",
            "localization_owner",
            "performance_owner",
            "seo_owner",
        )
    ]
    receipt = {
        "schema": LIVE_RECEIPT_SCHEMA,
        "profile": "launch",
        "claim_scope": "core",
        "generated_at": _stamp(NOW - timedelta(minutes=30)),
        "contract_sha256": contract_sha,
        "release_identity": {"git_commit": COMMIT, "image_digest": IMAGE},
        "markets": [
            _market("AT", "de-AT"),
            _market("DE", "de-DE"),
            _market("CR", "es-CR"),
        ],
        "approvals": approvals,
        "independent_attestation": {
            "independent": True,
            "authority": "independent_release_controller",
            "subject_git_commit": COMMIT,
            "subject_image_digest": IMAGE,
            "attestor_ref": "attestor:release-control:517e9a",
            "evidence": _evidence("independent-attestation"),
        },
    }
    receipt["independent_attestation"]["subject_payload_digest"] = _attested_payload_digest(receipt)
    return receipt


def _write_live(tmp_path: Path, receipt: dict[str, object]) -> Path:
    path = tmp_path / "live.json"
    path.write_text(json.dumps(receipt), encoding="utf-8")
    return path


def _evaluate(tmp_path: Path, receipt: dict[str, object]) -> dict[str, object]:
    return build_global_experience_gate_receipt(
        contract_path=CONTRACT_PATH,
        live_receipt_path=_write_live(tmp_path, receipt),
        expected_commit=COMMIT,
        expected_image=IMAGE,
        now=NOW,
    )


def test_checked_in_contract_is_strict_and_source_only_stays_blocked() -> None:
    contract = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
    assert contract["schema"] == CONTRACT_SCHEMA
    assert validate_contract(contract) == []

    receipt = build_global_experience_gate_receipt(
        contract_path=CONTRACT_PATH,
        live_receipt_path=None,
        expected_commit=COMMIT,
        expected_image=IMAGE,
        now=NOW,
    )
    assert receipt["schema"] == GATE_RECEIPT_SCHEMA
    assert receipt["status"] == "blocked"
    assert receipt["market_results"] == []
    assert receipt["independently_attested"] is False
    assert set(receipt["required_customer_routes"]) == set(ROUTES)
    assert set(receipt["required_critical_scenarios"]) == set(CRITICAL_SCENARIOS)
    assert any("source contract" in blocker for blocker in receipt["blockers"])


def test_complete_fresh_exactly_bound_live_receipt_passes(tmp_path: Path) -> None:
    receipt = _evaluate(tmp_path, _live_receipt())
    assert receipt["status"] == "pass"
    assert receipt["blockers"] == []
    assert receipt["independently_attested"] is True
    assert {row["country_code"] for row in receipt["market_results"]} == {"AT", "DE", "CR"}
    assert {row["status"] for row in receipt["market_results"]} == {"pass"}


def _missing_firefox(receipt: dict[str, object]) -> None:
    receipt["markets"][0]["accessibility"]["automated"]["runs"].pop(1)


def _missing_manual_zoom(receipt: dict[str, object]) -> None:
    receipt["markets"][0]["accessibility"]["manual"]["tasks"] = [
        row
        for row in receipt["markets"][0]["accessibility"]["manual"]["tasks"]
        if row["task_id"] != "zoom_400_percent"
    ]


def _missing_mobile_reader(receipt: dict[str, object]) -> None:
    receipt["markets"][0]["accessibility"]["manual"]["screen_reader_platforms"].pop()


def _missing_android(receipt: dict[str, object]) -> None:
    receipt["markets"][0]["browser_device_coverage"]["mobile_runs"].pop()


def _bad_lcp(receipt: dict[str, object]) -> None:
    receipt["markets"][0]["field_core_web_vitals"]["device_cohorts"][0]["metrics"]["LCP"]["value"] = 2501


def _too_few_samples(receipt: dict[str, object]) -> None:
    receipt["markets"][0]["field_core_web_vitals"]["device_cohorts"][1]["sample_count"] = 199


def _short_window(receipt: dict[str, object]) -> None:
    receipt["markets"][0]["field_core_web_vitals"]["device_cohorts"][0]["window_start"] = _stamp(NOW - timedelta(days=27))


def _unsafe_recovery(receipt: dict[str, object]) -> None:
    receipt["markets"][0]["degraded_network_recovery"]["scenarios"][0]["no_duplicate_mutation"] = False


def _unsafe_critical_state(receipt: dict[str, object]) -> None:
    receipt["markets"][0]["critical_state_scenarios"]["scenarios"][0]["useful_next_action"] = False


def _incomplete_hreflang(receipt: dict[str, object]) -> None:
    receipt["markets"][0]["localized_seo"]["hreflang_values"].remove("es-CR")


@pytest.mark.parametrize(
    ("mutate", "expected"),
    [
        (lambda receipt: receipt["markets"][0]["native_content_review"]["checks"].update({"native_ui_copy": False}), "native_ui_copy"),
        (_missing_firefox, "automated.runs"),
        (_missing_manual_zoom, "manual.tasks"),
        (_missing_mobile_reader, "screen_reader_platforms"),
        (_missing_android, "mobile_runs"),
        (_bad_lcp, "device_cohorts.desktop.metrics.LCP.value"),
        (_too_few_samples, "sample_count"),
        (_short_window, "field window"),
        (_unsafe_recovery, "duplicate mutation"),
        (_unsafe_critical_state, "useful_next_action"),
        (_incomplete_hreflang, "hreflang_values"),
    ],
)
def test_each_global_experience_dimension_fails_closed(tmp_path: Path, mutate, expected: str) -> None:
    live = _live_receipt()
    mutate(live)
    receipt = _evaluate(tmp_path, live)
    assert receipt["status"] == "blocked"
    assert any(expected in blocker for blocker in receipt["blockers"])


def test_stale_placeholder_and_non_independent_evidence_are_rejected(tmp_path: Path) -> None:
    live = _live_receipt()
    live["markets"][0]["native_content_review"]["native_reviewer_ref"] = "placeholder-reviewer"
    live["markets"][0]["native_content_review"]["evidence"]["observed_at"] = _stamp(
        NOW - timedelta(hours=25)
    )
    live["independent_attestation"]["independent"] = False
    receipt = _evaluate(tmp_path, live)
    assert receipt["status"] == "blocked"
    assert any("non-placeholder" in blocker for blocker in receipt["blockers"])
    assert any("evidence is stale" in blocker for blocker in receipt["blockers"])
    assert any("independently attest" in blocker for blocker in receipt["blockers"])


@pytest.mark.parametrize(
    ("mutate", "expected"),
    [
        (lambda receipt: receipt["markets"][0].update({"currency": "USD"}), "markets.AT.currency"),
        (lambda receipt: receipt["markets"][1].update({"timezone": "UTC"}), "markets.DE.timezone"),
        (
            lambda receipt: receipt["markets"][2]["native_content_review"].update(
                {"reviewer_proficiency": "professional"}
            ),
            "native proficiency",
        ),
        (
            lambda receipt: receipt["markets"][0]["browser_device_coverage"]["desktop_runs"][0].pop(
                "browser_binary_digest"
            ),
            "browser_binary_digest",
        ),
        (
            lambda receipt: receipt["markets"][0]["browser_device_coverage"]["mobile_runs"][0].update(
                {"execution_environment": "emulated"}
            ),
            "execution_environment",
        ),
    ],
)
def test_market_identity_reviewer_and_real_browser_proof_fail_closed(
    tmp_path: Path, mutate, expected: str
) -> None:
    live = _live_receipt()
    mutate(live)
    receipt = _evaluate(tmp_path, live)
    assert receipt["status"] == "blocked"
    assert any(expected in blocker for blocker in receipt["blockers"])


def test_dynamic_route_evidence_requires_concrete_governed_paths(tmp_path: Path) -> None:
    live = _live_receipt()
    market = live["markets"][0]
    market["native_content_review"]["reviewed_routes"] = list(ROUTES)
    market["accessibility"]["automated"]["runs"][0]["tested_routes"] = list(ROUTES)
    market["browser_device_coverage"]["desktop_runs"][0]["tested_routes"] = list(ROUTES)
    market["browser_device_coverage"]["mobile_runs"][0]["tested_routes"] = list(ROUTES)

    receipt = _evaluate(tmp_path, live)

    assert receipt["status"] == "blocked"
    route_blockers = [blocker for blocker in receipt["blockers"] if "routes" in blocker]
    assert len(route_blockers) >= 4
    assert all("non-concrete" in blocker or "route families are missing" in blocker for blocker in route_blockers)


@pytest.mark.parametrize(
    "bad_route",
    (
        "https://propertyquarry.example/app/research/candidate-7f3a9c",
        "/app/research/%257Bcandidate_ref%257D",
        "/app/research/../account",
    ),
)
def test_dynamic_route_evidence_rejects_external_encoded_or_traversal_paths(
    tmp_path: Path,
    bad_route: str,
) -> None:
    live = _live_receipt()
    routes = live["markets"][0]["accessibility"]["automated"]["runs"][0]["tested_routes"]
    routes[routes.index("/app/research/candidate-7f3a9c?run_id=run-91bd22")] = bad_route

    receipt = _evaluate(tmp_path, live)

    assert receipt["status"] == "blocked"
    assert any(
        "automated.runs.chromium.tested_routes" in blocker
        and ("invalid or non-concrete" in blocker or "route families are missing" in blocker)
        for blocker in receipt["blockers"]
    )


def test_independent_attestation_binds_the_complete_asserted_payload(tmp_path: Path) -> None:
    live = _live_receipt()
    live["markets"][0]["localized_seo"]["indexable_route_count"] = 8
    receipt = _evaluate(tmp_path, live)
    assert receipt["status"] == "blocked"
    assert any("independently attest" in blocker for blocker in receipt["blockers"])


def test_exact_release_binding_and_contract_digest_are_required(tmp_path: Path) -> None:
    live = _live_receipt()
    live["release_identity"]["git_commit"] = "4" * 40
    live["independent_attestation"]["subject_image_digest"] = "sha256:" + "5" * 64
    live["contract_sha256"] = "6" * 64
    receipt = _evaluate(tmp_path, live)
    assert receipt["status"] == "blocked"
    assert any("git_commit" in blocker for blocker in receipt["blockers"])
    assert any("source contract" in blocker for blocker in receipt["blockers"])
    assert any("independently attest" in blocker for blocker in receipt["blockers"])


def test_contract_cannot_be_weakened_and_age_override_cannot_relax_policy(tmp_path: Path) -> None:
    contract = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
    contract["field_core_web_vitals"]["minimum_window_days"] = 7
    contract["accessibility"]["standard"] = "WCAG 2.1 AA"
    assert any("minimum_window_days" in error for error in validate_contract(contract))
    assert any("WCAG 2.2 AA" in error for error in validate_contract(contract))

    nonfinite_contract = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
    nonfinite_contract["field_core_web_vitals"]["minimum_samples_per_market_device_cohort"] = float("nan")
    assert any(
        "minimum_samples_per_market_device_cohort" in error
        for error in validate_contract(nonfinite_contract)
    )

    live = _live_receipt()
    live["generated_at"] = _stamp(NOW - timedelta(hours=25))
    path = _write_live(tmp_path, live)
    receipt = build_global_experience_gate_receipt(
        contract_path=CONTRACT_PATH,
        live_receipt_path=path,
        expected_commit=COMMIT,
        expected_image=IMAGE,
        maximum_age_hours=72,
        now=NOW,
    )
    assert receipt["maximum_age_hours"] == 24
    assert receipt["status"] == "blocked"
    assert any("live_receipt.generated_at" in blocker for blocker in receipt["blockers"])

    nonfinite_age = build_global_experience_gate_receipt(
        contract_path=CONTRACT_PATH,
        live_receipt_path=None,
        expected_commit=COMMIT,
        expected_image=IMAGE,
        maximum_age_hours=float("nan"),
        now=NOW,
    )
    assert nonfinite_age["maximum_age_hours"] == 24
    assert any("must be finite" in blocker for blocker in nonfinite_age["blockers"])


def test_repeated_placeholder_release_identities_are_rejected() -> None:
    receipt = build_global_experience_gate_receipt(
        contract_path=CONTRACT_PATH,
        live_receipt_path=None,
        expected_commit="0" * 40,
        expected_image="sha256:" + "f" * 64,
        now=NOW,
    )
    assert receipt["status"] == "blocked"
    assert any("non-placeholder" in blocker for blocker in receipt["blockers"])


def test_cli_writes_blocked_source_only_receipt_and_returns_nonzero(tmp_path: Path, capsys) -> None:
    output = tmp_path / "gate.json"
    exit_code = main(
        [
            "--contract",
            str(CONTRACT_PATH),
            "--expected-commit",
            COMMIT,
            "--expected-image",
            IMAGE,
            "--output",
            str(output),
            "--fail-on-blocked",
        ]
    )
    assert exit_code == 1
    assert json.loads(output.read_text(encoding="utf-8"))["status"] == "blocked"
    assert '"status": "blocked"' in capsys.readouterr().out

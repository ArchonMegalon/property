from __future__ import annotations

import json

import pytest

from scripts import propertyquarry_deploy_monotonic_state as state


TARGET = state.sha256(b"postgres-system-id|db-oid|target-uuid")


def _cache(generation: int, entries: list[str]) -> bytes:
    return state.canonical_bytes({"generation": generation, "entries": entries})


def _seal(
    generation: int,
    payload: bytes,
    previous: str,
) -> state.MonotonicSeal:
    return state.build_reference_seal(
        authority_id="release-control-primary",
        kind="drain-ledger",
        target_identity_sha256=TARGET,
        generation=generation,
        previous_seal_sha256=previous,
        state_sha256=state.sha256(payload),
    )


def test_deleted_or_restored_ledger_cannot_match_external_generation() -> None:
    genesis_cache = _cache(0, [])
    genesis = _seal(0, genesis_cache, state.ZERO_HASH)
    consumed_cache = _cache(1, ["nonce-sha256"])
    consumed = _seal(1, consumed_cache, genesis.seal_sha256)
    state.validate_successor(genesis, consumed)

    with pytest.raises(state.MonotonicStateError, match="deleted"):
        state.validate_cache_against_authority(
            cache_payload=None,
            cache_generation=None,
            authoritative_seal=consumed,
            minimum_generation=0,
            expected_kind="drain-ledger",
            expected_target_identity_sha256=TARGET,
        )
    with pytest.raises(state.MonotonicStateError, match="rolled back"):
        state.validate_cache_against_authority(
            cache_payload=genesis_cache,
            cache_generation=0,
            authoritative_seal=consumed,
            minimum_generation=0,
            expected_kind="drain-ledger",
            expected_target_identity_sha256=TARGET,
        )


def test_restoring_earlier_terminal_journal_cannot_hide_incomplete_epoch() -> None:
    terminal_cache = state.canonical_bytes(
        {"generation": 8, "phase": "promotion_complete"}
    )
    terminal = state.build_reference_seal(
        authority_id="release-control-primary",
        kind="deploy-journal",
        target_identity_sha256=TARGET,
        generation=8,
        previous_seal_sha256="1" * 64,
        state_sha256=state.sha256(terminal_cache),
    )
    incomplete_cache = state.canonical_bytes(
        {"generation": 9, "phase": "ingress_starting"}
    )
    incomplete = state.build_reference_seal(
        authority_id="release-control-primary",
        kind="deploy-journal",
        target_identity_sha256=TARGET,
        generation=9,
        previous_seal_sha256=terminal.seal_sha256,
        state_sha256=state.sha256(incomplete_cache),
    )
    state.validate_successor(terminal, incomplete)

    with pytest.raises(state.MonotonicStateError, match="rolled back"):
        state.validate_cache_against_authority(
            cache_payload=terminal_cache,
            cache_generation=8,
            authoritative_seal=incomplete,
            minimum_generation=9,
            expected_kind="deploy-journal",
            expected_target_identity_sha256=TARGET,
        )


def test_cas_rejects_generation_skip_target_swap_and_broken_hash_chain() -> None:
    current_cache = _cache(3, ["a"])
    current = _seal(3, current_cache, "2" * 64)
    next_cache = _cache(4, ["a", "b"])
    valid = _seal(4, next_cache, current.seal_sha256)
    state.validate_successor(current, valid)

    for invalid in (
        _seal(5, next_cache, current.seal_sha256),
        _seal(4, next_cache, "3" * 64),
        state.build_reference_seal(
            authority_id="release-control-primary",
            kind="drain-ledger",
            target_identity_sha256="f" * 64,
            generation=4,
            previous_seal_sha256=current.seal_sha256,
            state_sha256=state.sha256(next_cache),
        ),
    ):
        with pytest.raises(state.MonotonicStateError, match="does not extend"):
            state.validate_successor(current, invalid)


def test_external_generation_floor_rejects_authority_rollback() -> None:
    payload = _cache(4, ["nonce"])
    rolled_back = _seal(4, payload, "2" * 64)

    with pytest.raises(state.MonotonicStateError, match="compiled floor"):
        state.validate_cache_against_authority(
            cache_payload=payload,
            cache_generation=4,
            authoritative_seal=rolled_back,
            minimum_generation=5,
            expected_kind="drain-ledger",
            expected_target_identity_sha256=TARGET,
        )

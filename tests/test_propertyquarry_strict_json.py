from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from scripts import propertyquarry_global_experience_gate as experience
from scripts import propertyquarry_global_market_envelope as market
from scripts import propertyquarry_gold_status as gold
from scripts import propertyquarry_incident_support_gate as incident
from scripts import propertyquarry_jurisdiction_privacy_rights_gate as rights
from scripts.propertyquarry_strict_json import (
    StrictJsonError,
    load_strict_json_object_snapshot,
    loads_strict_json_object,
)


@pytest.mark.parametrize(
    "raw",
    (
        b'{"status":"pass","status":"blocked"}',
        b'{"outer":{"value":1,"value":2}}',
        b'{"value":NaN}',
        b'{"value":Infinity}',
        b'{"value":-Infinity}',
        b'[1,2,3]',
        b'\xff',
    ),
)
def test_strict_json_rejects_ambiguous_or_non_object_payloads(raw: bytes) -> None:
    with pytest.raises(StrictJsonError):
        loads_strict_json_object(raw)


def test_strict_json_snapshots_exact_bytes_and_rejects_symlinks(tmp_path: Path) -> None:
    raw = b'{"schema":"example.v1","value":1}\n'
    source = tmp_path / "source.json"
    source.write_bytes(raw)

    payload, observed, digest = load_strict_json_object_snapshot(source)

    assert payload == {"schema": "example.v1", "value": 1}
    assert observed == raw
    assert digest == hashlib.sha256(raw).hexdigest()

    link = tmp_path / "link.json"
    link.symlink_to(source)
    with pytest.raises(StrictJsonError):
        load_strict_json_object_snapshot(link)


def test_strict_json_enforces_size_depth_and_node_bounds(tmp_path: Path) -> None:
    oversized = tmp_path / "oversized.json"
    oversized.write_bytes(b'{"value":"' + b"x" * 64 + b'"}')
    with pytest.raises(StrictJsonError):
        load_strict_json_object_snapshot(oversized, maximum_bytes=32)

    deep: object = {"leaf": True}
    for _index in range(10):
        deep = {"child": deep}
    import json

    with pytest.raises(StrictJsonError, match="depth"):
        loads_strict_json_object(json.dumps(deep).encode(), maximum_depth=4)
    with pytest.raises(StrictJsonError, match="node"):
        loads_strict_json_object(b'{"values":[1,2,3,4]}', maximum_nodes=3)


def test_all_flagship_gate_loaders_reject_duplicate_keys(tmp_path: Path) -> None:
    duplicate = tmp_path / "duplicate.json"
    duplicate.write_text('{"schema":"first","schema":"second"}', encoding="utf-8")

    with pytest.raises(market.EnvelopeError):
        market.load_envelope(duplicate)
    with pytest.raises(StrictJsonError):
        experience._load_json(duplicate)
    with pytest.raises(StrictJsonError):
        incident._load_json(duplicate)
    with pytest.raises(StrictJsonError):
        rights._load_json(duplicate)

    assert gold._load_json(duplicate)["status"] == "invalid"
    snapshot, digest = gold._load_json_snapshot(duplicate)
    assert snapshot["status"] == "invalid"
    assert digest == ""

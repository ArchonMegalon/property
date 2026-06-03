from __future__ import annotations

from app.domain.models import ToolDefinition, now_utc_iso
from app.repositories.connector_bindings import InMemoryConnectorBindingRepository
from app.repositories.tool_registry import InMemoryToolRegistryRepository


def test_inmemory_tool_registry_upsert_and_list_enabled() -> None:
    repo = InMemoryToolRegistryRepository()
    row = repo.upsert(
        ToolDefinition(
            tool_name="email.send",
            version="v1",
            input_schema_json={"type": "object"},
            output_schema_json={"type": "object"},
            policy_json={"risk": "low"},
            allowed_channels=("email",),
            approval_default="none",
            enabled=True,
            updated_at=now_utc_iso(),
        )
    )
    assert row.tool_name == "email.send"
    listed = repo.list_enabled(limit=10)
    assert len(listed) == 1
    assert listed[0].tool_name == "email.send"


def test_inmemory_connector_binding_upsert_and_status_change() -> None:
    repo = InMemoryConnectorBindingRepository()
    first = repo.upsert(
        principal_id="exec-1",
        connector_name="gmail",
        external_account_ref="acct-1",
        scope_json={"scopes": ["mail.readonly"]},
        auth_metadata_json={"provider": "google"},
        status="enabled",
    )
    second = repo.upsert(
        principal_id="exec-1",
        connector_name="gmail",
        external_account_ref="acct-1",
        scope_json={"scopes": ["mail.readwrite"]},
        auth_metadata_json={"provider": "google"},
        status="enabled",
    )
    assert second.binding_id == first.binding_id
    assert second.scope_json["scopes"] == ["mail.readwrite"]
    fetched = repo.get(first.binding_id)
    assert fetched is not None
    assert fetched.principal_id == "exec-1"
    updated = repo.set_status(first.binding_id, "disabled")
    assert updated is not None
    assert updated.status == "disabled"

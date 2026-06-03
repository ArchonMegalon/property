-- Tool/connector kernel baseline
-- Adds tool registry contracts and connector binding store.

CREATE TABLE IF NOT EXISTS tool_registry (
    tool_name TEXT PRIMARY KEY,
    version TEXT NOT NULL,
    input_schema_json JSONB NOT NULL,
    output_schema_json JSONB NOT NULL,
    policy_json JSONB NOT NULL,
    allowed_channels_json JSONB NOT NULL,
    approval_default TEXT NOT NULL,
    enabled BOOLEAN NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_tool_registry_enabled_updated
ON tool_registry(enabled, updated_at DESC);

CREATE TABLE IF NOT EXISTS connector_bindings (
    binding_id TEXT PRIMARY KEY,
    principal_id TEXT NOT NULL,
    connector_name TEXT NOT NULL,
    external_account_ref TEXT NOT NULL,
    scope_json JSONB NOT NULL,
    auth_metadata_json JSONB NOT NULL,
    status TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_connector_bindings_natural_key
ON connector_bindings(principal_id, connector_name, external_account_ref);

CREATE INDEX IF NOT EXISTS idx_connector_bindings_principal_updated
ON connector_bindings(principal_id, updated_at DESC);

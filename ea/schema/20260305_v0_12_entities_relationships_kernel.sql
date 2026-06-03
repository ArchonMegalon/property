-- v0_12: semantic memory seed (entities + relationships)

CREATE TABLE IF NOT EXISTS entities (
    entity_id TEXT PRIMARY KEY,
    principal_id TEXT NOT NULL,
    entity_type TEXT NOT NULL,
    canonical_name TEXT NOT NULL,
    attributes_json JSONB NOT NULL,
    confidence DOUBLE PRECISION NOT NULL,
    status TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_entities_identity_unique
ON entities(principal_id, entity_type, lower(canonical_name));

CREATE INDEX IF NOT EXISTS idx_entities_principal_updated
ON entities(principal_id, updated_at DESC);

CREATE TABLE IF NOT EXISTS relationships (
    relationship_id TEXT PRIMARY KEY,
    principal_id TEXT NOT NULL,
    from_entity_id TEXT NOT NULL,
    to_entity_id TEXT NOT NULL,
    relationship_type TEXT NOT NULL,
    attributes_json JSONB NOT NULL,
    confidence DOUBLE PRECISION NOT NULL,
    valid_from TIMESTAMPTZ NULL,
    valid_to TIMESTAMPTZ NULL,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_relationships_identity_unique
ON relationships(principal_id, from_entity_id, to_entity_id, relationship_type);

CREATE INDEX IF NOT EXISTS idx_relationships_principal_updated
ON relationships(principal_id, updated_at DESC);

CREATE INDEX IF NOT EXISTS idx_relationships_from_to
ON relationships(from_entity_id, to_entity_id, updated_at DESC);

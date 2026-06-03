-- v0_11: memory kernel seed (candidates + promoted items)

CREATE TABLE IF NOT EXISTS memory_candidates (
    candidate_id TEXT PRIMARY KEY,
    principal_id TEXT NOT NULL,
    category TEXT NOT NULL,
    summary TEXT NOT NULL,
    fact_json JSONB NOT NULL,
    source_session_id TEXT NOT NULL DEFAULT '',
    source_event_id TEXT NOT NULL DEFAULT '',
    source_step_id TEXT NOT NULL DEFAULT '',
    confidence DOUBLE PRECISION NOT NULL,
    sensitivity TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    reviewed_at TIMESTAMPTZ NULL,
    reviewer TEXT NOT NULL DEFAULT '',
    promoted_item_id TEXT NOT NULL DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_memory_candidates_status_created
ON memory_candidates(status, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_memory_candidates_principal_created
ON memory_candidates(principal_id, created_at DESC);

CREATE TABLE IF NOT EXISTS memory_items (
    item_id TEXT PRIMARY KEY,
    principal_id TEXT NOT NULL,
    category TEXT NOT NULL,
    summary TEXT NOT NULL,
    fact_json JSONB NOT NULL,
    provenance_json JSONB NOT NULL,
    confidence DOUBLE PRECISION NOT NULL,
    sensitivity TEXT NOT NULL,
    sharing_policy TEXT NOT NULL,
    last_verified_at TIMESTAMPTZ NULL,
    reviewer TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_memory_items_principal_updated
ON memory_items(principal_id, updated_at DESC);

CREATE INDEX IF NOT EXISTS idx_memory_items_category_updated
ON memory_items(category, updated_at DESC);

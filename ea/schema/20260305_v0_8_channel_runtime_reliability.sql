-- Channel runtime reliability extensions
-- Adds observation attribution/dedupe fields and outbox retry/idempotency fields.

ALTER TABLE observation_events
    ADD COLUMN IF NOT EXISTS source_id TEXT NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS external_id TEXT NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS dedupe_key TEXT NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS auth_context_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    ADD COLUMN IF NOT EXISTS raw_payload_uri TEXT NOT NULL DEFAULT '';

CREATE UNIQUE INDEX IF NOT EXISTS idx_observation_events_dedupe_key_unique
ON observation_events(dedupe_key)
WHERE dedupe_key <> '';

CREATE INDEX IF NOT EXISTS idx_observation_events_source_external
ON observation_events(source_id, external_id, created_at DESC);

ALTER TABLE delivery_outbox
    ADD COLUMN IF NOT EXISTS idempotency_key TEXT NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS attempt_count INT NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS next_attempt_at TIMESTAMPTZ NULL,
    ADD COLUMN IF NOT EXISTS last_error TEXT NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS receipt_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    ADD COLUMN IF NOT EXISTS dead_lettered_at TIMESTAMPTZ NULL;

CREATE UNIQUE INDEX IF NOT EXISTS idx_delivery_outbox_idempotency_key_unique
ON delivery_outbox(idempotency_key)
WHERE idempotency_key <> '';

CREATE INDEX IF NOT EXISTS idx_delivery_outbox_retry_schedule
ON delivery_outbox(status, next_attempt_at, created_at DESC);

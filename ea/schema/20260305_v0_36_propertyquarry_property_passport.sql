-- PropertyQuarry property passport kernel
-- Stores canonical property identity, listing instances, evidence claims, and property events.

CREATE TABLE IF NOT EXISTS propertyquarry_property_entities (
    principal_id TEXT NOT NULL,
    property_id TEXT NOT NULL,
    identity_key TEXT NOT NULL,
    title TEXT NOT NULL DEFAULT '',
    country_code TEXT NOT NULL DEFAULT '',
    postal_name TEXT NOT NULL DEFAULT '',
    area_sqm NUMERIC,
    rooms NUMERIC,
    facts_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    first_seen_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_seen_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (principal_id, property_id),
    UNIQUE (principal_id, identity_key)
);

CREATE TABLE IF NOT EXISTS propertyquarry_listing_instances (
    principal_id TEXT NOT NULL,
    listing_instance_id TEXT NOT NULL,
    property_id TEXT NOT NULL,
    provider_key TEXT NOT NULL DEFAULT '',
    provider_label TEXT NOT NULL DEFAULT '',
    listing_url TEXT NOT NULL DEFAULT '',
    listing_id TEXT NOT NULL DEFAULT '',
    title TEXT NOT NULL DEFAULT '',
    first_seen_run_id TEXT NOT NULL DEFAULT '',
    last_seen_run_id TEXT NOT NULL DEFAULT '',
    first_seen_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_seen_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    raw_listing_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (principal_id, listing_instance_id),
    FOREIGN KEY (principal_id, property_id)
        REFERENCES propertyquarry_property_entities(principal_id, property_id)
        ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS propertyquarry_property_claims (
    principal_id TEXT NOT NULL,
    claim_id TEXT NOT NULL,
    property_id TEXT NOT NULL,
    field_key TEXT NOT NULL,
    claim_value_json JSONB NOT NULL,
    source_type TEXT NOT NULL DEFAULT 'listing',
    source_ref TEXT NOT NULL DEFAULT '',
    observed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    valid_at TIMESTAMPTZ,
    confidence TEXT NOT NULL DEFAULT 'provider_only',
    verification_state TEXT NOT NULL DEFAULT 'provider_only',
    supersedes_claim_id TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (principal_id, claim_id),
    FOREIGN KEY (principal_id, property_id)
        REFERENCES propertyquarry_property_entities(principal_id, property_id)
        ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS propertyquarry_property_events (
    principal_id TEXT NOT NULL,
    event_id TEXT NOT NULL,
    property_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    field_key TEXT NOT NULL DEFAULT '',
    previous_value_json JSONB,
    current_value_json JSONB,
    source_ref TEXT NOT NULL DEFAULT '',
    run_id TEXT NOT NULL DEFAULT '',
    observed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (principal_id, event_id),
    FOREIGN KEY (principal_id, property_id)
        REFERENCES propertyquarry_property_entities(principal_id, property_id)
        ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_propertyquarry_property_entities_principal_seen
ON propertyquarry_property_entities(principal_id, last_seen_at DESC);

CREATE INDEX IF NOT EXISTS idx_propertyquarry_listing_instances_property_seen
ON propertyquarry_listing_instances(principal_id, property_id, last_seen_at DESC);

CREATE INDEX IF NOT EXISTS idx_propertyquarry_listing_instances_url
ON propertyquarry_listing_instances(principal_id, listing_url);

CREATE INDEX IF NOT EXISTS idx_propertyquarry_property_claims_property_field_seen
ON propertyquarry_property_claims(principal_id, property_id, field_key, observed_at DESC);

CREATE INDEX IF NOT EXISTS idx_propertyquarry_property_events_property_seen
ON propertyquarry_property_events(principal_id, property_id, observed_at DESC);

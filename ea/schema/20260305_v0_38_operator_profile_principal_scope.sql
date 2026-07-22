-- Operator identities are tenant scoped.  The v0.28 table used a global
-- operator_id primary key, while the repository has always upserted and read
-- profiles by (principal_id, operator_id).  Adopt legacy tables without
-- deleting or rewriting rows, and fail closed if existing data cannot satisfy
-- the canonical composite identity.

DO $operator_profile_principal_scope$
DECLARE
    operator_profiles_relation pg_catalog.regclass;
    operator_profiles_namespace pg_catalog.oid;
    operator_profiles_schema NAME;
    operator_profiles_table NAME;
    exact_unique_index_exists BOOLEAN := FALSE;
    duplicate_identity_exists BOOLEAN := FALSE;
BEGIN
    operator_profiles_relation := pg_catalog.to_regclass('operator_profiles');
    IF operator_profiles_relation IS NULL THEN
        RAISE EXCEPTION 'operator_profiles relation missing';
    END IF;

    SELECT
        relation_row.relnamespace,
        namespace_row.nspname,
        relation_row.relname
    INTO
        operator_profiles_namespace,
        operator_profiles_schema,
        operator_profiles_table
    FROM pg_catalog.pg_class AS relation_row
    JOIN pg_catalog.pg_namespace AS namespace_row
      ON namespace_row.oid = relation_row.relnamespace
    WHERE relation_row.oid = operator_profiles_relation;

    IF EXISTS (
        SELECT 1
        FROM pg_catalog.pg_constraint AS constraint_row
        WHERE constraint_row.conrelid = operator_profiles_relation
          AND constraint_row.conname = 'operator_profiles_pkey'
    ) THEN
        IF NOT EXISTS (
            SELECT 1
            FROM pg_catalog.pg_constraint AS constraint_row
            JOIN pg_catalog.pg_attribute AS attribute_row
              ON attribute_row.attrelid = constraint_row.conrelid
             AND attribute_row.attnum = constraint_row.conkey[1]
            WHERE constraint_row.conrelid = operator_profiles_relation
              AND constraint_row.conname = 'operator_profiles_pkey'
              AND constraint_row.contype = 'p'
              AND pg_catalog.cardinality(constraint_row.conkey) = 1
              AND attribute_row.attname = 'operator_id'
        ) THEN
            RAISE EXCEPTION 'operator_profiles_pkey constraint conflict';
        END IF;

        EXECUTE pg_catalog.format(
            'ALTER TABLE %I.%I '
            'DROP CONSTRAINT IF EXISTS operator_profiles_pkey',
            operator_profiles_schema,
            operator_profiles_table
        );
    END IF;

    SELECT COALESCE(
        pg_catalog.bool_or(
            index_row.indisunique
            AND index_row.indisvalid
            AND index_row.indisready
            AND index_row.indpred IS NULL
            AND index_row.indexprs IS NULL
            AND index_row.indnkeyatts = 2
            AND index_row.indnatts = 2
            AND pg_catalog.pg_get_indexdef(
                index_row.indexrelid,
                1,
                TRUE
            ) = 'principal_id'
            AND pg_catalog.pg_get_indexdef(
                index_row.indexrelid,
                2,
                TRUE
            ) = 'operator_id'
        ),
        FALSE
    )
    INTO exact_unique_index_exists
    FROM pg_catalog.pg_index AS index_row
    WHERE index_row.indrelid = operator_profiles_relation;

    IF exact_unique_index_exists THEN
        RETURN;
    END IF;

    EXECUTE pg_catalog.format(
        'SELECT EXISTS ('
        'SELECT 1 FROM %I.%I '
        'GROUP BY principal_id, operator_id '
        'HAVING pg_catalog.count(*) > 1'
        ')',
        operator_profiles_schema,
        operator_profiles_table
    )
    INTO duplicate_identity_exists;

    IF duplicate_identity_exists THEN
        RAISE EXCEPTION 'operator profile principal identity duplicates';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM pg_catalog.pg_class AS relation_row
        WHERE relation_row.relnamespace = operator_profiles_namespace
          AND relation_row.relname = 'idx_operator_profiles_principal_operator'
    ) THEN
        RAISE EXCEPTION 'operator profile principal identity index conflict';
    END IF;

    EXECUTE pg_catalog.format(
        'CREATE UNIQUE INDEX idx_operator_profiles_principal_operator '
        'ON %I.%I(principal_id, operator_id)',
        operator_profiles_schema,
        operator_profiles_table
    );
END
$operator_profile_principal_scope$;

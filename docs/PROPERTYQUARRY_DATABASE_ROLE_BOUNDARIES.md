# PropertyQuarry Database Role Boundaries

This is the credential contract for the standalone PropertyQuarry topology.
It separates one-shot schema authority from every long-lived process and gives
the API and render admission lanes standalone credentials for two write tables
plus the read-only two-row capacity ledger. Passwords,
tokens, DSNs, and provider-specific identity commands belong in the external
secret store; none appear in this document or in repository files.

## Compose-to-role contract

| Compose input | Process-local name | Required database role | Boundary |
| --- | --- | --- | --- |
| `PROPERTYQUARRY_API_DATABASE_URL` | `DATABASE_URL` | `propertyquarry_api_runtime` | Long-lived, non-owner application DML; no schema or database creation |
| `PROPERTYQUARRY_API_ADMISSION_DATABASE_URL` | same name | `propertyquarry_api_admission` | Long-lived, standalone login; exact DML on the two admission tables plus `SELECT` on capacity state |
| `PROPERTYQUARRY_WORKER_DATABASE_URL` | `DATABASE_URL` | `propertyquarry_worker_runtime` | Long-lived, non-owner application DML; no schema or database creation |
| `PROPERTYQUARRY_SCHEDULER_DATABASE_URL` | `DATABASE_URL` | `propertyquarry_scheduler_runtime` | Long-lived, non-owner application DML; no schema or database creation |
| `PROPERTYQUARRY_RENDER_DATABASE_URL` | `DATABASE_URL` | `propertyquarry_render_admission` | Long-lived, standalone login; exact DML on the two admission tables plus `SELECT` on capacity state |
| `PROPERTYQUARRY_MIGRATION_DATABASE_URL` | `DATABASE_URL` | `propertyquarry_migration` | One-shot schema owner; non-superuser; never started as a runtime service |
| `POSTGRES_PASSWORD` | `POSTGRES_PASSWORD` | database bootstrap administrator | Database sidecar initialization and health only; never injected into an application or migration process |

`DATABASE_URL` remains a CLI/development compatibility input, but the Compose
plan does not consume it. The API admission DSN is mandatory in production and
must not equal the API runtime DSN. API readiness opens and strictly probes the
dedicated connection. Development and tests use memory admission by default;
sharing a disposable primary PostgreSQL DSN requires
`PROPERTYQUARRY_DEV_ALLOW_PRIMARY_ADMISSION_DATABASE_URL=1`.

## Role properties

Provision these identities from the database administration plane. `LOGIN`
below creates no usable password by itself; bind the actual password or workload
identity out of band.

```sql
CREATE ROLE propertyquarry_migration
  LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT
  NOREPLICATION NOBYPASSRLS;
CREATE ROLE propertyquarry_admission_capacity_owner
  NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT
  NOREPLICATION NOBYPASSRLS;
GRANT propertyquarry_admission_capacity_owner TO propertyquarry_migration;
CREATE ROLE propertyquarry_api_runtime
  LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT
  NOREPLICATION NOBYPASSRLS;
CREATE ROLE propertyquarry_worker_runtime
  LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT
  NOREPLICATION NOBYPASSRLS;
CREATE ROLE propertyquarry_scheduler_runtime
  LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT
  NOREPLICATION NOBYPASSRLS;
CREATE ROLE propertyquarry_api_admission
  LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT
  NOREPLICATION NOBYPASSRLS;
CREATE ROLE propertyquarry_render_admission
  LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT
  NOREPLICATION NOBYPASSRLS;
```

The capacity owner is a dedicated `NOLOGIN` identity. It must have no role
memberships or elevated flags; the migration login is a member solely so the
one-shot v17 migration can transfer the three canonical trigger functions to
it. Its final authority is `USAGE` (not `CREATE`) on the application schema and
`SELECT, UPDATE` on `propertyquarry_admission_capacity_state`; it has no rights
on either admission write table.

The two admission logins must have no role memberships. They must not own the
database, schema, tables, sequences, or functions. They must not have `CREATE`
or `TEMPORARY` on the database, `CREATE` on any schema in their search path,
rights on any other user relation or sequence, or `EXECUTE` on a non-system
`SECURITY DEFINER` function. The production probe rejects row-level security
and every trigger except the six exact v17 statement triggers. It attests their
event, transition-table alias, argument, function source, safe `pg_catalog`
search path, `NOLOGIN` owner, and closed ACL before readiness can pass.

## Grant procedure

Run this only from the controlled administration/migration plane, with psql
identifier variables bound to the server-resolved database and application
schema. The examples assume:

```text
--set=app_db=<server-resolved-database-name>
--set=app_schema=<server-resolved-application-schema>
```

Do not assume the schema is `public`. Resolve it from the migrated relations:

```sql
SELECT n.nspname AS app_schema
FROM pg_catalog.pg_class AS c
JOIN pg_catalog.pg_namespace AS n ON n.oid = c.relnamespace
WHERE c.oid IN (
  to_regclass('propertyquarry_admission_quota_buckets'),
  to_regclass('propertyquarry_admission_leases'),
  to_regclass('propertyquarry_admission_capacity_state')
)
GROUP BY n.nspname
HAVING count(*) = 3;
```

Exactly one row is required. Then establish the database and schema boundary:

```sql
\set ON_ERROR_STOP on

REVOKE ALL PRIVILEGES ON DATABASE :"app_db" FROM PUBLIC;
GRANT CONNECT ON DATABASE :"app_db" TO
  propertyquarry_migration,
  propertyquarry_api_runtime,
  propertyquarry_worker_runtime,
  propertyquarry_scheduler_runtime,
  propertyquarry_api_admission,
  propertyquarry_render_admission;
REVOKE CREATE, TEMPORARY ON DATABASE :"app_db" FROM
  propertyquarry_api_runtime,
  propertyquarry_worker_runtime,
  propertyquarry_scheduler_runtime,
  propertyquarry_api_admission,
  propertyquarry_render_admission;

ALTER SCHEMA :"app_schema" OWNER TO propertyquarry_migration;
REVOKE ALL ON SCHEMA :"app_schema" FROM PUBLIC;
GRANT USAGE, CREATE ON SCHEMA :"app_schema" TO propertyquarry_migration;
GRANT USAGE ON SCHEMA :"app_schema" TO
  propertyquarry_api_runtime,
  propertyquarry_worker_runtime,
  propertyquarry_scheduler_runtime,
  propertyquarry_api_admission,
  propertyquarry_render_admission;

ALTER ROLE propertyquarry_migration
  IN DATABASE :"app_db" SET search_path TO :"app_schema", pg_catalog;
ALTER ROLE propertyquarry_api_runtime
  IN DATABASE :"app_db" SET search_path TO :"app_schema", pg_catalog;
ALTER ROLE propertyquarry_worker_runtime
  IN DATABASE :"app_db" SET search_path TO :"app_schema", pg_catalog;
ALTER ROLE propertyquarry_scheduler_runtime
  IN DATABASE :"app_db" SET search_path TO :"app_schema", pg_catalog;
ALTER ROLE propertyquarry_api_admission
  IN DATABASE :"app_db" SET search_path TO :"app_schema", pg_catalog;
ALTER ROLE propertyquarry_render_admission
  IN DATABASE :"app_db" SET search_path TO :"app_schema", pg_catalog;
```

After the one-shot migration has committed, reset all inherited relation
authority and grant the current compatibility DML boundary. Admission tables
are explicitly removed from every general runtime role:

```sql
REVOKE ALL PRIVILEGES ON ALL TABLES IN SCHEMA :"app_schema" FROM PUBLIC;
REVOKE ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA :"app_schema" FROM PUBLIC;
REVOKE EXECUTE ON ALL FUNCTIONS IN SCHEMA :"app_schema" FROM PUBLIC;

REVOKE ALL PRIVILEGES ON ALL TABLES IN SCHEMA :"app_schema" FROM
  propertyquarry_api_runtime,
  propertyquarry_worker_runtime,
  propertyquarry_scheduler_runtime,
  propertyquarry_api_admission,
  propertyquarry_render_admission;
REVOKE ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA :"app_schema" FROM
  propertyquarry_api_runtime,
  propertyquarry_worker_runtime,
  propertyquarry_scheduler_runtime,
  propertyquarry_api_admission,
  propertyquarry_render_admission;
REVOKE EXECUTE ON ALL FUNCTIONS IN SCHEMA :"app_schema" FROM
  propertyquarry_api_admission,
  propertyquarry_render_admission;

GRANT SELECT, INSERT, UPDATE, DELETE
  ON ALL TABLES IN SCHEMA :"app_schema"
  TO propertyquarry_api_runtime,
     propertyquarry_worker_runtime,
     propertyquarry_scheduler_runtime;
GRANT USAGE, SELECT, UPDATE
  ON ALL SEQUENCES IN SCHEMA :"app_schema"
  TO propertyquarry_api_runtime,
     propertyquarry_worker_runtime,
     propertyquarry_scheduler_runtime;

REVOKE ALL PRIVILEGES
  ON TABLE propertyquarry_admission_quota_buckets,
           propertyquarry_admission_leases,
           propertyquarry_admission_capacity_state
  FROM propertyquarry_api_runtime,
       propertyquarry_worker_runtime,
       propertyquarry_scheduler_runtime;
REVOKE INSERT, UPDATE, DELETE
  ON TABLE propertyquarry_schema_migrations,
           property_search_erasure_key_state
  FROM propertyquarry_api_runtime,
       propertyquarry_worker_runtime,
       propertyquarry_scheduler_runtime;
GRANT SELECT
  ON TABLE propertyquarry_schema_migrations,
           property_search_erasure_key_state
  TO propertyquarry_api_runtime,
     propertyquarry_worker_runtime,
     propertyquarry_scheduler_runtime;
GRANT SELECT, INSERT, UPDATE, DELETE
  ON TABLE propertyquarry_admission_quota_buckets,
           propertyquarry_admission_leases
  TO propertyquarry_api_admission,
     propertyquarry_render_admission;
GRANT SELECT
  ON TABLE propertyquarry_admission_capacity_state
  TO propertyquarry_api_admission,
     propertyquarry_render_admission;
REVOKE INSERT, UPDATE, DELETE, TRUNCATE, REFERENCES, TRIGGER
  ON TABLE propertyquarry_admission_capacity_state
  FROM propertyquarry_api_admission,
       propertyquarry_render_admission;
REVOKE EXECUTE
  ON FUNCTION propertyquarry_admission_capacity_after_insert(),
              propertyquarry_admission_capacity_after_delete(),
              propertyquarry_admission_capacity_after_truncate()
  FROM PUBLIC,
       propertyquarry_api_admission,
       propertyquarry_render_admission;
```

Do not grant runtime default privileges. A migration that adds a table must
ship and audit its corresponding grants before the new fleet starts. Keep the
owner's defaults closed:

```sql
ALTER DEFAULT PRIVILEGES FOR ROLE propertyquarry_migration
  IN SCHEMA :"app_schema" REVOKE ALL ON TABLES FROM PUBLIC;
ALTER DEFAULT PRIVILEGES FOR ROLE propertyquarry_migration
  IN SCHEMA :"app_schema" REVOKE ALL ON SEQUENCES FROM PUBLIC;
ALTER DEFAULT PRIVILEGES FOR ROLE propertyquarry_migration
  IN SCHEMA :"app_schema" REVOKE EXECUTE ON FUNCTIONS FROM PUBLIC;
```

## Mandatory verification

Before ingress reopens, verify that the admission identities have no membership
or elevated flags and exactly the intended relation grants:

```sql
SELECT role.rolname, role.rolsuper, role.rolcreaterole, role.rolcreatedb,
       role.rolreplication, role.rolbypassrls
FROM pg_catalog.pg_roles AS role
WHERE role.rolname IN (
  'propertyquarry_api_admission',
  'propertyquarry_render_admission'
);

SELECT member.rolname AS member, granted.rolname AS granted_role
FROM pg_catalog.pg_auth_members AS membership
JOIN pg_catalog.pg_roles AS member ON member.oid = membership.member
JOIN pg_catalog.pg_roles AS granted ON granted.oid = membership.roleid
WHERE member.rolname IN (
  'propertyquarry_api_admission',
  'propertyquarry_render_admission'
);

SELECT grantee, table_schema, table_name, privilege_type
FROM information_schema.role_table_grants
WHERE grantee IN (
  'propertyquarry_api_admission',
  'propertyquarry_render_admission'
)
ORDER BY grantee, table_schema, table_name, privilege_type;
```

The first query must show every elevated flag as false, the membership query
must return zero rows, and the grant query must show only `SELECT`, `INSERT`,
`UPDATE`, and `DELETE` on the two admission write tables and only `SELECT` on
`propertyquarry_admission_capacity_state`. Finally start API readiness
with its dedicated DSN. The strict runtime probe independently rejects excess
database, schema, ownership, relation, sequence, trigger, row-security,
capacity-owner, function-source, function-ACL, and security-definer authority;
a failed probe is a release blocker.

## Known general-runtime grant ambiguity

The current repository has a shared application repository layer, and the
migration manifest does not yet declare a trustworthy per-service table and
sequence allowlist for API versus worker versus scheduler. The compatibility
grant above is exact at the authority-class level—non-owner DML only, no DDL,
no admission state—but it is intentionally not described as per-relation least
privilege for those three roles. Guessing narrower grants would create an
untested availability or data-integrity failure. A later hardening change must
derive observed relation use under representative production flows, encode
reviewed per-role allowlists as release artifacts, and test revocation. This
ambiguity does not permit a generic DSN, a superuser, an owner credential, or
the migration credential in any long-lived service.

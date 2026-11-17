-- DBA-only psql script. Never pass a password on the command line.
-- Also pass owner_id=<existing DPMS UUID>, include_body=true/false, include_attachments=true/false.
\set ON_ERROR_STOP on
\if :{?app_schema}
\else
DO $$ BEGIN RAISE EXCEPTION 'Explicit app_schema required'; END $$;
\endif
\if :{?bridge_role}
\else
DO $$ BEGIN RAISE EXCEPTION 'Explicit new bridge_role required'; END $$;
\endif
\if :{?owner_id}
\else
DO $$ BEGIN RAISE EXCEPTION 'Explicit existing DPMS owner_id required'; END $$;
\endif
\if :{?include_body}
\else
DO $$ BEGIN RAISE EXCEPTION 'Explicit include_body true/false required'; END $$;
\endif
\if :{?include_attachments}
\else
DO $$ BEGIN RAISE EXCEPTION 'Explicit include_attachments true/false required'; END $$;
\endif

BEGIN;
SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '30s';
SELECT EXISTS (SELECT 1 FROM pg_catalog.pg_namespace WHERE nspname = :'app_schema')
    AND :'app_schema' !~ '^pg_' AND :'app_schema' <> 'information_schema'
    AND NOT EXISTS (SELECT 1 FROM pg_catalog.pg_roles WHERE rolname = :'bridge_role')
    AND octet_length(:'bridge_role') BETWEEN 1 AND 63 AS provision_ready \gset
\if :provision_ready
\else
DO $$ BEGIN RAISE EXCEPTION 'Existing app schema and a NEW dedicated role required'; END $$;
\endif

SELECT EXISTS (SELECT 1 FROM :"app_schema".users WHERE id=:'owner_id'::uuid AND is_active)
    AND (NOT :'include_attachments'::boolean OR :'include_body'::boolean) AS owner_ready \gset
\if :owner_ready
\else
DO $$ BEGIN RAISE EXCEPTION 'Active DPMS owner required; attachments require body permission'; END $$;
\endif

SELECT format('CREATE ROLE %I LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOREPLICATION NOBYPASSRLS CONNECTION LIMIT 2', :'bridge_role') \gexec
SELECT format('ALTER ROLE %I SET statement_timeout = %L', :'bridge_role', '45s') \gexec
SELECT format('ALTER ROLE %I SET lock_timeout = %L', :'bridge_role', '10s') \gexec
SELECT format('ALTER ROLE %I SET idle_in_transaction_session_timeout = %L', :'bridge_role', '30s') \gexec
SELECT format('ALTER ROLE %I SET search_path = pg_catalog', :'bridge_role') \gexec
SELECT format('GRANT CONNECT ON DATABASE %I TO %I', current_database(), :'bridge_role') \gexec
SELECT format('GRANT USAGE ON SCHEMA %I TO %I', :'app_schema', :'bridge_role') \gexec
SELECT format('GRANT EXECUTE ON FUNCTION %I.mail_import_db_protocol() TO %I', :'app_schema', :'bridge_role') \gexec
SELECT format('GRANT EXECUTE ON FUNCTION %I.mail_import_db_connect(text,text) TO %I', :'app_schema', :'bridge_role') \gexec
SELECT format('GRANT EXECUTE ON FUNCTION %I.mail_import_db_enqueue(text,uuid,text) TO %I', :'app_schema', :'bridge_role') \gexec
SELECT format('GRANT EXECUTE ON FUNCTION %I.mail_import_db_status(text,uuid) TO %I', :'app_schema', :'bridge_role') \gexec
INSERT INTO :"app_schema".mail_import_db_logins
    (role_oid,role_name,owner_id,include_body,include_attachments,enabled)
    SELECT oid,rolname,:'owner_id'::uuid,:'include_body'::boolean,:'include_attachments'::boolean,true
    FROM pg_catalog.pg_roles WHERE rolname=:'bridge_role';

-- PUBLIC grants also count. Do not silently change privileges of existing roles.
SELECT NOT has_database_privilege(:'bridge_role', current_database(), 'CREATE')
    AND NOT EXISTS (
        SELECT 1 FROM pg_catalog.pg_namespace n WHERE n.nspname !~ '^pg_' AND n.nspname <> 'information_schema'
        AND has_schema_privilege(:'bridge_role', n.oid, 'CREATE'))
    AND NOT EXISTS (
        SELECT 1 FROM pg_catalog.pg_class c JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname !~ '^pg_' AND n.nspname <> 'information_schema'
        AND CASE WHEN c.relkind IN ('r','p','v','m','f') THEN
            (has_table_privilege(:'bridge_role', c.oid, 'SELECT,INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER')
             OR has_any_column_privilege(:'bridge_role', c.oid, 'SELECT,INSERT,UPDATE,REFERENCES')) ELSE false END)
    AND NOT EXISTS (
        SELECT 1 FROM pg_catalog.pg_class c JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname !~ '^pg_' AND n.nspname <> 'information_schema'
        AND CASE WHEN c.relkind = 'S' THEN
            has_sequence_privilege(:'bridge_role', c.oid, 'USAGE,SELECT,UPDATE') ELSE false END)
    AND NOT EXISTS (
        SELECT 1 FROM pg_catalog.pg_proc p JOIN pg_catalog.pg_namespace n ON n.oid = p.pronamespace
        WHERE n.nspname !~ '^pg_' AND n.nspname <> 'information_schema'
        AND has_function_privilege(:'bridge_role', p.oid, 'EXECUTE')
        AND p.oid NOT IN (
            format('%I.mail_import_db_protocol()', :'app_schema')::regprocedure,
            format('%I.mail_import_db_connect(text,text)', :'app_schema')::regprocedure,
            format('%I.mail_import_db_enqueue(text,uuid,text)', :'app_schema')::regprocedure,
            format('%I.mail_import_db_status(text,uuid)', :'app_schema')::regprocedure)) AS limited_role \gset
\if :limited_role
COMMIT;
\else
DO $$ BEGIN RAISE EXCEPTION 'Unsafe inherited/PUBLIC privileges; provisioning rolled back. Review with DBA'; END $$;
\endif

-- Interactive password prompt; no secret in this script or shell arguments.
SET password_encryption = 'scram-sha-256';
\password :bridge_role
\echo Dedicated role provisioned. Verify hostssl/SCRAM and network ACL before distribution.

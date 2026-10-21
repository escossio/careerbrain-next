-- Only for a new, isolated cluster. No passwords or existing service roles.
DO $$
DECLARE r text;
BEGIN
  FOREACH r IN ARRAY ARRAY['cb_owner','cb_migrator','cb_auth','cb_api','cb_ingest','cb_global_worker','cb_private_worker','cb_privacy'] LOOP
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = r) THEN
      EXECUTE format('CREATE ROLE %I NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS NOINHERIT', r);
    END IF;
    IF EXISTS (SELECT FROM pg_roles WHERE rolname = r AND (rolsuper OR rolbypassrls OR rolcreaterole OR rolcreatedb)) THEN
      RAISE EXCEPTION 'unsafe existing role';
    END IF;
  END LOOP;
END $$;
ALTER ROLE cb_migrator LOGIN;
ALTER ROLE cb_auth LOGIN;
ALTER ROLE cb_api LOGIN;
ALTER ROLE cb_ingest LOGIN;
ALTER ROLE cb_global_worker LOGIN;
ALTER ROLE cb_private_worker LOGIN;
ALTER ROLE cb_privacy LOGIN;
GRANT cb_owner TO cb_migrator;
REVOKE ALL ON SCHEMA public FROM PUBLIC;
CREATE SCHEMA IF NOT EXISTS ops AUTHORIZATION cb_owner;
REVOKE ALL ON SCHEMA ops FROM PUBLIC;

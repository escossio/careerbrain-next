SELECT format('REVOKE ALL ON DATABASE %I FROM PUBLIC', current_database()) \gexec
SELECT format('GRANT CONNECT ON DATABASE %I TO cb_migrator, cb_auth, cb_api, cb_ingest, cb_global_worker, cb_private_worker, cb_privacy', current_database()) \gexec
SELECT format('GRANT CREATE, CONNECT ON DATABASE %I TO cb_owner', current_database()) \gexec

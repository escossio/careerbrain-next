#!/bin/sh
set -eu
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" -f /bootstrap.sql
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" -f /runtime-permissions.sql
for role in cb_migrator cb_auth cb_api cb_ingest cb_global_worker cb_private_worker cb_privacy; do
  file="/run/secrets/${role}_password"
  test -r "$file"
  value=$(cat "$file")
  test -n "$value"
  printf "ALTER ROLE %s PASSWORD :'role_password';\\n" "$role" | \
    psql -v ON_ERROR_STOP=1 -v role_password="$value" --username "$POSTGRES_USER" --dbname "$POSTGRES_DB"
done

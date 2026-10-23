#!/bin/sh
set -eu
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" -f /bootstrap.sql
for role in cb_migrator cb_auth cb_api cb_ingest cb_global_worker cb_private_worker cb_privacy; do
  file="/run/secrets/${role}_password"
  test -r "$file"
  value=$(cat "$file")
  test -n "$value"
  psql -v ON_ERROR_STOP=1 -v role_name="$role" -v role_password="$value" \
    --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
    -c "ALTER ROLE :\"role_name\" PASSWORD :'role_password';"
done

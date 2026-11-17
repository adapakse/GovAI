#!/bin/sh
# Uruchamiany raz, przy inicjalizacji klastra (docker-entrypoint-initdb.d).
# Gdy SSL włączony: połączenia sieciowe tylko po TLS (hostssl) — Container Apps łączą się
# z sslmode=require, backup z sslmode=prefer. Połączenia lokalne (gniazdo) bez zmian.
set -e
if [ "${PG_REQUIRE_SSL:-on}" = "on" ]; then
  sed -i 's/^host[[:space:]]\{1,\}all[[:space:]]\{1,\}all[[:space:]]\{1,\}all[[:space:]]/hostssl all all all /' \
    "$PGDATA/pg_hba.conf"
  echo "pg_hba.conf: połączenia sieciowe tylko przez TLS (hostssl)"
fi

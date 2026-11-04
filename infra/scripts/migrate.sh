#!/bin/sh
# Stosuje migracje z db/migrations/ do bazy w kontenerze postgres (docker compose).
# Uruchamiany przez deploy-remote.sh; lokalnie z katalogu repo:
#   sh infra/scripts/migrate.sh        (w Git Bash na Windows: MSYS_NO_PATHCONV=1)
#
# Rejestr wykonanych migracji: tabela schema_migrations. Każda migracja idzie
# w jednej transakcji z ON_ERROR_STOP — błąd przerywa deploy zamiast (jak
# wcześniej) cicho iść dalej i powtarzać migracje przy każdym deployu.
set -e

psql_exec() {
  # app.platform=on: migracje działają ponad RLS (FORCE dotyczy też właściciela tabel).
  docker compose exec -T -e PGOPTIONS="-c app.platform=on" postgres psql -U govai -d "${GOVAI_DB:-govai}" -v ON_ERROR_STOP=1 -q "$@"
}

psql_exec -c "CREATE TABLE IF NOT EXISTS schema_migrations (
  filename   TEXT PRIMARY KEY,
  applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
)"

# Baza sprzed rejestru (INT, lokalne środowiska): migracje 001–013 były już
# stosowane przy każdym deployu — oznacz je jako wykonane zamiast uruchamiać
# ponownie. Świeża baza (tylko init.sql, bez app_settings) przechodzi wszystkie.
BASELINE="001_ai_act_requirements.sql 002_auth.sql 003_providers.sql 004_settings.sql \
005_settings_audit.sql 006_requirements_dynamic.sql 007_audit_error_result.sql \
008_fix_text_encoding.sql 009_fix_provider_sensitivity_ceiling.sql \
010_agent_profile_and_policy_code.sql 011_deployer_obligations.sql 012_i18n.sql \
013_i18n_content.sql"
registered=$(psql_exec -tAc "SELECT count(*) FROM schema_migrations")
legacy=$(psql_exec -tAc "SELECT to_regclass('public.app_settings') IS NOT NULL")
if [ "$registered" = "0" ] && [ "$legacy" = "t" ]; then
  echo "Rejestr migracji: baseline 001–013 (baza sprzed rejestru)"
  for name in $BASELINE; do
    psql_exec -c "INSERT INTO schema_migrations (filename) VALUES ('$name') ON CONFLICT DO NOTHING"
  done
fi

container=$(docker compose ps -q postgres)
for f in db/migrations/*.sql; do
  name=$(basename "$f")
  applied=$(psql_exec -tAc "SELECT 1 FROM schema_migrations WHERE filename = '$name'")
  if [ "$applied" = "1" ]; then
    continue
  fi
  echo "Migracja: $name"
  docker cp "$f" "$container:/tmp/$name"
  psql_exec -1 -f "/tmp/$name"
  psql_exec -c "INSERT INTO schema_migrations (filename) VALUES ('$name')"
done

# Hasło roli aplikacji (govai_app, migracja 015) — z DB_APP_PASSWORD w środowisku
# albo w .env. Przez stdin, żeby nie pojawiło się w liście procesów.
app_password=${DB_APP_PASSWORD:-$(grep '^DB_APP_PASSWORD=' .env 2>/dev/null | cut -d= -f2-)}
has_role=$(psql_exec -tAc "SELECT 1 FROM pg_roles WHERE rolname = 'govai_app'")
if [ "$has_role" = "1" ]; then
  if [ -z "$app_password" ]; then
    echo "Brak DB_APP_PASSWORD — API i gateway nie połączą się z bazą jako govai_app" >&2
    exit 1
  fi
  printf "ALTER ROLE govai_app WITH PASSWORD '%s';\n" "$app_password" \
    | docker compose exec -T postgres psql -U govai -d "${GOVAI_DB:-govai}" -v ON_ERROR_STOP=1 -q
fi

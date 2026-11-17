#!/usr/bin/env bash
# GovAI — backup i odtwarzanie baz Postgres/TimescaleDB (kontener govai-backup).
#
#   govai-backup schedule                  codziennie o BACKUP_TIME w strefie TZ (domyślne polecenie)
#   govai-backup run [env...]              backup teraz (domyślnie wszystkie z BACKUP_SOURCES)
#   govai-backup check <env> <max_godzin>  czy najnowszy backup (latest.json) jest młodszy niż N godzin
#   govai-backup fetch <env> <latest|ścieżka.dump> <katalog>   pobranie + weryfikacja sha256
#   govai-backup restore <env> [latest|ścieżka.dump] [--from <env>] [--test] [--yes]
#       --test  odtworzenie do bazy govai_restore_test, porównanie liczności, usunięcie bazy
#       --yes   (bez --test) podmiana bazy govai na odtworzoną; stara zostaje jako govai_pre_restore_<ts>
#       --from  środowisko źródłowe dla „latest” (domyślnie to samo co docelowe)
#
# Konfiguracja (env): BACKUP_TARGET=azure-blob|local|s3, BACKUP_SOURCES="prod=pg-prod:5432 int=pg-int:5432",
# BACKUP_REQUIRED="prod" (pozostałe pomijane, gdy nieosiągalne), DB_ADMIN_PASSWORD_<ENV>, DB_APP_PASSWORD_<ENV>,
# AZURE_STORAGE_ACCOUNT / AZURE_STORAGE_CONTAINER (azure-blob, managed identity przez IMDS),
# BACKUP_LOCAL_DIR + BACKUP_RETENTION_DAYS (local), BACKUP_S3_URI (s3 — wymaga aws cli, patrz README).
# Układ plików: <env>/YYYY/MM/DD/govai-<ts>.dump | .globals.sql | .json oraz <env>/latest.json.
set -euo pipefail

DB=${BACKUP_DB:-govai}
export PGDATABASE=$DB
export PGUSER=${BACKUP_PGUSER:-govai}
export PGSSLMODE=${BACKUP_PGSSLMODE:-prefer}
export PGCONNECT_TIMEOUT=10
export LC_ALL=C
TARGET=${BACKUP_TARGET:-local}
SOURCES=${BACKUP_SOURCES:-prod=pg-prod:5432}
REQUIRED=${BACKUP_REQUIRED:-prod}
WORK=${BACKUP_WORK_DIR:-/work}
STATE=${BACKUP_STATE_DIR:-/var/lib/govai-backup}
LOCAL_DIR=${BACKUP_LOCAL_DIR:-/backups}
RETENTION_DAYS=${BACKUP_RETENTION_DAYS:-7}
RETRY_MIN=${BACKUP_RETRY_MINUTES:-60}
CONTAINER=${AZURE_STORAGE_CONTAINER:-backups}
# Tabele, których liczności trafiają do metadanych i są porównywane po odtworzeniu.
COUNT_TABLES="tenants users agents policies oversight_queue audit_log providers api_keys ai_act_requirements app_settings_values platform_audit_log schema_migrations"

log() { printf '%s [govai-backup] %s\n' "$(date '+%F %T %Z')" "$*"; }
die() { log "BŁĄD: $*" >&2; exit 1; }

# ── środowiska ───────────────────────────────────────────────────────────────
source_of() {   # source_of <env> → host:port
  local e
  for e in $SOURCES; do
    if [ "${e%%=*}" = "$1" ]; then echo "${e#*=}"; return 0; fi
  done
  return 1
}
admin_password_of() { local v="DB_ADMIN_PASSWORD_${1^^}"; printf '%s' "${!v:-}"; }
app_password_of()   { local v="DB_APP_PASSWORD_${1^^}";   printf '%s' "${!v:-}"; }

use_env() {   # ustawia PGHOST/PGPORT/PGPASSWORD dla środowiska
  local hp
  hp=$(source_of "$1") || die "środowisko '$1' nie występuje w BACKUP_SOURCES ($SOURCES)"
  export PGHOST=${hp%:*} PGPORT=${hp##*:}
  PGPASSWORD=$(admin_password_of "$1"); export PGPASSWORD
  [ -n "$PGPASSWORD" ] || die "brak DB_ADMIN_PASSWORD_${1^^}"
}
reachable() { pg_isready -q -t 5; }
sql() { psql -X -q -t -A -v ON_ERROR_STOP=1 "$@"; }

# Statystyki bazy (JSON): wersje + liczności tabel. Przez query_to_xml, bo działa w transakcji
# READ ONLY i nie wymaga funkcji w bazie. Wymaga zmiennej psql :tables.
STATS_SQL="SELECT json_build_object(
  'server_version', current_setting('server_version'),
  'timescaledb_version', (SELECT extversion FROM pg_extension WHERE extname = 'timescaledb'),
  'schema_migrations_max', CASE WHEN to_regclass('public.schema_migrations') IS NULL THEN NULL
      ELSE (xpath('/row/m/text()', query_to_xml('SELECT max(filename) AS m FROM public.schema_migrations', false, true, '')))[1]::text END,
  'counts', (SELECT json_object_agg(t, CASE WHEN to_regclass('public.' || t) IS NULL THEN NULL
      ELSE (xpath('/row/c/text()', query_to_xml(format('SELECT count(*) AS c FROM public.%I', t), false, true, '')))[1]::text::bigint END)
    FROM unnest(string_to_array(:'tables', ' ')) AS t)
);"

# ── magazyn (azure-blob | local | s3) ────────────────────────────────────────
AZ_HDR=""
azure_headers() {   # plik z nagłówkami (token nie trafia do argumentów procesu)
  [ -n "${AZURE_STORAGE_ACCOUNT:-}" ] || die "brak AZURE_STORAGE_ACCOUNT (BACKUP_TARGET=azure-blob)"
  local url token
  url="http://169.254.169.254/metadata/identity/oauth2/token?api-version=2018-02-01&resource=https%3A%2F%2Fstorage.azure.com%2F"
  [ -n "${AZURE_CLIENT_ID:-}" ] && url="$url&client_id=$AZURE_CLIENT_ID"
  token=$(curl -fsS --retry 3 -H Metadata:true "$url" | jq -r .access_token) || die "brak tokenu managed identity (IMDS)"
  [ -n "$token" ] && [ "$token" != null ] || die "pusty token managed identity (IMDS)"
  mkdir -p "$WORK"
  AZ_HDR=$(mktemp "$WORK/.hdr.XXXXXX")
  chmod 600 "$AZ_HDR"
  {
    echo "Authorization: Bearer $token"
    echo "x-ms-version: 2021-08-06"
    echo "x-ms-date: $(date -u '+%a, %d %b %Y %H:%M:%S GMT')"
  } > "$AZ_HDR"
}
blob_url() { echo "https://${AZURE_STORAGE_ACCOUNT}.blob.core.windows.net/$CONTAINER/$1"; }
cleanup_hdr() { [ -n "$AZ_HDR" ] && rm -f "$AZ_HDR"; AZ_HDR=""; }
trap cleanup_hdr EXIT

need_s3() { command -v aws >/dev/null || die "BACKUP_TARGET=s3 wymaga aws cli w obrazie (patrz infra/db-vm/README.md)"; [ -n "${BACKUP_S3_URI:-}" ] || die "brak BACKUP_S3_URI"; }

store_put() {   # store_put <plik> <ścieżka>
  case $TARGET in
    azure-blob)
      azure_headers
      curl -fsS --retry 3 -T "$1" -H "@$AZ_HDR" -H "x-ms-blob-type: BlockBlob" \
        -H "Content-Type: application/octet-stream" "$(blob_url "$2")"
      cleanup_hdr ;;
    local)
      mkdir -p "$(dirname "$LOCAL_DIR/$2")"
      cp "$1" "$LOCAL_DIR/$2.tmp" && mv "$LOCAL_DIR/$2.tmp" "$LOCAL_DIR/$2" ;;
    s3) need_s3; aws s3 cp --only-show-errors "$1" "${BACKUP_S3_URI%/}/$2" ;;
    *) die "nieznany BACKUP_TARGET=$TARGET" ;;
  esac
}
store_get() {   # store_get <ścieżka> <plik>
  case $TARGET in
    azure-blob)
      azure_headers
      curl -fsS --retry 3 -H "@$AZ_HDR" -o "$2" "$(blob_url "$1")" || { cleanup_hdr; return 1; }
      cleanup_hdr ;;
    local) [ -f "$LOCAL_DIR/$1" ] && cp "$LOCAL_DIR/$1" "$2" ;;
    s3) need_s3; aws s3 cp --only-show-errors "${BACKUP_S3_URI%/}/$1" "$2" ;;
    *) die "nieznany BACKUP_TARGET=$TARGET" ;;
  esac
}
store_exists() {   # store_exists <ścieżka>
  case $TARGET in
    azure-blob)
      azure_headers
      curl -fsS -o /dev/null -I -H "@$AZ_HDR" "$(blob_url "$1")" || { cleanup_hdr; return 1; }
      cleanup_hdr ;;
    local) [ -f "$LOCAL_DIR/$1" ] ;;
    s3) need_s3; aws s3 ls "${BACKUP_S3_URI%/}/$1" >/dev/null ;;
    *) die "nieznany BACKUP_TARGET=$TARGET" ;;
  esac
}
prune_local() {   # retencja dla BACKUP_TARGET=local (azure-blob: lifecycle policy konta)
  [ "$TARGET" = local ] || return 0
  [ -d "$LOCAL_DIR/$1" ] || return 0
  local n
  n=$(find "$LOCAL_DIR/$1" -type f -name 'govai-*' -mmin +$((RETENTION_DAYS * 1440)) -print -delete | wc -l)
  find "$LOCAL_DIR/$1" -mindepth 1 -type d -empty -delete
  log "Retencja $1: usunięto $n plików starszych niż $RETENTION_DAYS dni"
}

with_lock() {   # jeden backup/restore naraz
  mkdir -p "$STATE"
  exec 9>"$STATE/lock"
  flock 9 || die "nie udało się uzyskać blokady $STATE/lock"
}

# ── backup ───────────────────────────────────────────────────────────────────
backup_env() {
  local env=$1
  use_env "$env"
  if ! reachable; then
    case " $REQUIRED " in
      *" $env "*) die "baza $env ($PGHOST:$PGPORT) nieosiągalna" ;;
    esac
    log "Pomijam $env: baza $PGHOST:$PGPORT nieosiągalna (kontener zatrzymany?)"
    return 0
  fi
  local ts day base dir
  ts=$(date -u +%Y%m%dT%H%M%SZ)
  day=$(date -u +%Y/%m/%d)
  base="$env/$day/govai-$ts"
  dir="$WORK/$env-$ts"
  rm -rf "$dir"; mkdir -p "$dir"
  log "Backup $env ($PGHOST:$PGPORT) → $base"

  # Liczności tabel i pg_dump z tej samej migawki (pg_export_snapshot) — porównanie po
  # odtworzeniu jest dokładne mimo zapisów w trakcie backupu. pg_dump uruchamia \! wewnątrz
  # otwartej transakcji; jego wynik sygnalizuje plik .ok (psql nie przekazuje kodu wyjścia \!).
  sql -v tables="$COUNT_TABLES" -v stats_out="$dir/stats.json" -v dump_out="$dir/db.dump" <<SQL
BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY;
SELECT pg_export_snapshot() AS snap \gset
\setenv GOVAI_SNAPSHOT :snap
\setenv GOVAI_DUMP_OUT :dump_out
\o :stats_out
$STATS_SQL
\o
\! pg_dump -Fc --snapshot="\$GOVAI_SNAPSHOT" -f "\$GOVAI_DUMP_OUT" && touch "\$GOVAI_DUMP_OUT.ok"
COMMIT;
SQL
  [ -f "$dir/db.dump.ok" ] || die "pg_dump $env nieudany"
  pg_restore -l "$dir/db.dump" >/dev/null || die "zrzut $env nieczytelny (pg_restore -l)"
  # Role bez haseł — hasła są w Key Vault / pliku env i ustawia je restore.
  pg_dumpall --globals-only --no-role-passwords -l "$DB" -f "$dir/globals.sql" || die "pg_dumpall --globals-only $env nieudany"

  local sha_dump sha_glob
  sha_dump=$(sha256sum "$dir/db.dump" | cut -d' ' -f1)
  sha_glob=$(sha256sum "$dir/globals.sql" | cut -d' ' -f1)
  jq -n --slurpfile s "$dir/stats.json" --arg env "$env" --arg ts "$ts" --argjson epoch "$(date -u +%s)" \
     --arg dump "$base.dump" --arg globals "$base.globals.sql" --arg meta "$base.json" \
     --arg sd "$sha_dump" --arg sg "$sha_glob" --argjson size "$(stat -c %s "$dir/db.dump")" \
     --arg src "$PGHOST:$PGPORT" \
     '{format: 1, env: $env, timestamp: $ts, epoch: $epoch,
       files: {dump: $dump, globals: $globals, meta: $meta},
       sha256: {dump: $sd, globals: $sg}, dump_bytes: $size, source: $src} + $s[0]' > "$dir/meta.json"

  store_put "$dir/db.dump" "$base.dump"
  store_put "$dir/globals.sql" "$base.globals.sql"
  store_put "$dir/meta.json" "$base.json"
  store_put "$dir/meta.json" "$env/latest.json"   # wskaźnik na najnowszy — zapisywany na końcu
  log "Backup $env OK: $(jq -c '{dump_bytes, timescaledb_version, schema_migrations_max, counts}' "$dir/meta.json")"
  rm -rf "$dir"
  prune_local "$env"
}

cmd_run() {
  with_lock
  local envs=("$@") e
  if [ ${#envs[@]} -eq 0 ]; then
    for e in $SOURCES; do envs+=("${e%%=*}"); done
  fi
  log "Start backupu: ${envs[*]} (cel: $TARGET)"
  for e in "${envs[@]}"; do backup_env "$e"; done
  log "Backup zakończony"
}

# ── harmonogram ──────────────────────────────────────────────────────────────
# Prosta pętla zamiast crona: raz dziennie po BACKUP_TIME (czas lokalny TZ — DST obsługuje tzdata).
# Po niedostępności (restart VM o 02:30) backup nadrabia przy starcie; po błędzie ponowienie co RETRY_MIN.
cmd_schedule() {
  mkdir -p "$STATE"
  log "Harmonogram: codziennie od $BACKUP_TIME ($TZ), cel: $TARGET, źródła: $SOURCES"
  local today now last_ok last_try
  while true; do
    today=$(date +%F); now=$(date +%H:%M)
    last_ok=$(cat "$STATE/last_success_date" 2>/dev/null || true)
    last_try=$(cat "$STATE/last_attempt_epoch" 2>/dev/null || echo 0)
    if [[ ! "$now" < "$BACKUP_TIME" ]] && [ "$last_ok" != "$today" ] \
       && [ $(( $(date +%s) - last_try )) -ge $((RETRY_MIN * 60)) ]; then
      date +%s > "$STATE/last_attempt_epoch"
      if "$0" run; then
        echo "$today" > "$STATE/last_success_date"
      else
        log "Backup NIEUDANY — ponowienie za $RETRY_MIN min" >&2
      fi
    fi
    sleep 30
  done
}

# ── check ────────────────────────────────────────────────────────────────────
cmd_check() {
  local env=${1:?env} max_h=${2:?max_godzin} tmp epoch age dump
  tmp=$(mktemp)
  store_get "$env/latest.json" "$tmp" || die "brak $env/latest.json w magazynie ($TARGET)"
  epoch=$(jq -r .epoch "$tmp"); dump=$(jq -r .files.dump "$tmp")
  age=$(( $(date -u +%s) - epoch ))
  store_exists "$dump" || die "$env: plik $dump wskazany w latest.json nie istnieje"
  log "$env: najnowszy backup $(jq -r .timestamp "$tmp") ($((age / 3600)) h temu), $dump, $(jq -r .dump_bytes "$tmp") B"
  rm -f "$tmp"
  [ "$age" -le $((max_h * 3600)) ] || die "$env: najnowszy backup starszy niż $max_h h"
  echo "GOVAI_CHECK_OK env=$env age_h=$((age / 3600))"
}

# ── fetch ────────────────────────────────────────────────────────────────────
cmd_fetch() {   # cmd_fetch <env> <latest|ścieżka> <katalog>
  local env=$1 ref=$2 out=$3 dump base
  mkdir -p "$out"
  if [ "$ref" = latest ]; then
    store_get "$env/latest.json" "$out/latest.json" || die "brak $env/latest.json w magazynie ($TARGET)"
    dump=$(jq -r .files.dump "$out/latest.json")
  else
    dump=${ref#/}
    dump=${dump#"$CONTAINER"/}
    case $dump in *.dump) ;; *.json) dump=${dump%.json}.dump ;; *) dump=$dump.dump ;; esac
  fi
  base=${dump%.dump}
  log "Pobieranie $base.{dump,globals.sql,json}"
  store_get "$base.json" "$out/meta.json" || die "brak $base.json"
  store_get "$dump" "$out/db.dump" || die "brak $dump"
  store_get "$base.globals.sql" "$out/globals.sql" || die "brak $base.globals.sql"
  [ "$(sha256sum "$out/db.dump" | cut -d' ' -f1)" = "$(jq -r .sha256.dump "$out/meta.json")" ] \
    || die "suma sha256 zrzutu niezgodna z metadanymi"
  [ "$(sha256sum "$out/globals.sql" | cut -d' ' -f1)" = "$(jq -r .sha256.globals "$out/meta.json")" ] \
    || die "suma sha256 globals niezgodna z metadanymi"
  log "sha256 OK ($(jq -r .timestamp "$out/meta.json"), środowisko źródłowe: $(jq -r .env "$out/meta.json"))"
}

# ── restore ──────────────────────────────────────────────────────────────────
cmd_restore() {
  local target=${1:?"użycie: restore <env> [latest|ścieżka] [--from env] [--test] [--yes]"}; shift
  local ref=latest from="" test=0 yes=0
  if [ $# -gt 0 ] && [[ $1 != --* ]]; then ref=$1; shift; fi
  while [ $# -gt 0 ]; do
    case $1 in
      --from) from=${2:?--from <env>}; shift 2 ;;
      --test) test=1; shift ;;
      --yes) yes=1; shift ;;
      *) die "nieznana opcja: $1" ;;
    esac
  done
  [ -n "$from" ] || from=$target
  if [ $test = 0 ] && [ $yes = 0 ]; then
    die "odtworzenie podmienia bazę $DB w środowisku $target — potwierdź opcją --yes (albo użyj --test)"
  fi
  with_lock

  local dir tmpdb tsv stamp
  stamp=$(date -u +%Y%m%d%H%M%S)
  dir="$WORK/restore-$stamp"
  cmd_fetch "$from" "$ref" "$dir"
  use_env "$target"
  reachable || die "baza docelowa $target ($PGHOST:$PGPORT) nieosiągalna"

  tsv=$(jq -r .timescaledb_version "$dir/meta.json")
  [ "$(sql -d postgres -c "SELECT count(*) FROM pg_available_extension_versions WHERE name = 'timescaledb' AND version = '$tsv'")" = 1 ] \
    || die "serwer docelowy nie ma TimescaleDB $tsv (wersja z backupu) — uruchom obraz z tą wersją"
  if [ $test = 1 ]; then tmpdb=govai_restore_test; else tmpdb="govai_restore_$stamp"; fi

  log "Odtwarzanie $(jq -r .files.dump "$dir/meta.json") → $target, baza tymczasowa $tmpdb"
  sql -d postgres -c "DROP DATABASE IF EXISTS $tmpdb WITH (FORCE)"
  sql -d postgres -c "CREATE DATABASE $tmpdb TEMPLATE template0"

  # Role (globals): istniejące zgłaszają „already exists” — to oczekiwane, pozostałe błędy logujemy.
  psql -X -q -d postgres -f "$dir/globals.sql" > "$dir/globals.log" 2>&1 || true
  local gerr
  gerr=$(grep -E 'ERROR' "$dir/globals.log" | grep -vc 'already exists' || true)
  [ "$gerr" = 0 ] || { log "UWAGA: $gerr błędów przy odtwarzaniu ról:"; grep ERROR "$dir/globals.log" | grep -v 'already exists' | head -20; }

  sql -d "$tmpdb" -c "CREATE EXTENSION IF NOT EXISTS timescaledb VERSION '$tsv'"
  sql -d "$tmpdb" -c "SELECT timescaledb_pre_restore()" >/dev/null
  local rc=0
  pg_restore -d "$tmpdb" --no-password "$dir/db.dump" > "$dir/restore.log" 2>&1 || rc=$?
  sql -d "$tmpdb" -c "SELECT timescaledb_post_restore()" >/dev/null
  if [ $rc != 0 ]; then
    log "UWAGA: pg_restore zakończył się kodem $rc — komunikaty (decyduje porównanie liczności niżej):"
    grep -E 'error|ERROR' "$dir/restore.log" | head -30 || true
  fi

  # Porównanie z metadanymi backupu.
  sql -d "$tmpdb" -v tables="$COUNT_TABLES" > "$dir/restored.json" <<SQL
$STATS_SQL
SQL
  local expected actual
  expected=$(jq -S -c '{timescaledb_version, schema_migrations_max, counts}' "$dir/meta.json")
  actual=$(jq -S -c '{timescaledb_version, schema_migrations_max, counts}' "$dir/restored.json")
  if [ "$expected" != "$actual" ]; then
    log "NIEZGODNOŚĆ po odtworzeniu:"
    log "  backup:     $expected"
    log "  odtworzone: $actual"
    if [ $test = 1 ]; then sql -d postgres -c "DROP DATABASE IF EXISTS $tmpdb WITH (FORCE)"; fi
    die "weryfikacja odtworzenia nie powiodła się (baza $tmpdb $([ $test = 1 ] && echo usunięta || echo "zostawiona do analizy"))"
  fi
  log "Weryfikacja OK: $actual"

  if [ $test = 1 ]; then
    local backup_ts
    backup_ts=$(jq -r .timestamp "$dir/meta.json")
    sql -d postgres -c "DROP DATABASE IF EXISTS $tmpdb WITH (FORCE)"
    rm -rf "$dir"
    log "Test odtworzenia OK (baza $tmpdb usunięta)"
    echo "GOVAI_RESTORE_OK mode=test env=$target backup=$backup_ts"
    return 0
  fi

  # Hasło govai_app z pliku env środowiska docelowego (backup nie zawiera haseł ról).
  local app_pw
  app_pw=$(app_password_of "$target")
  if [ -n "$app_pw" ] && [ "$(sql -d postgres -c "SELECT count(*) FROM pg_roles WHERE rolname = 'govai_app'")" = 1 ]; then
    printf "ALTER ROLE govai_app WITH PASSWORD '%s';\n" "$(printf '%s' "$app_pw" | sed "s/'/''/g")" | sql -d postgres
    log "Hasło govai_app ustawione z DB_APP_PASSWORD_${target^^}"
  else
    log "UWAGA: nie ustawiono hasła govai_app (brak DB_APP_PASSWORD_${target^^} albo roli) — aplikacje się nie połączą"
  fi

  # Podmiana: govai → govai_pre_restore_<ts>, baza tymczasowa → govai.
  local old="govai_pre_restore_$stamp" has_db
  has_db=$(sql -d postgres -c "SELECT count(*) FROM pg_database WHERE datname = '$DB'")
  if [ "$has_db" = 1 ]; then
    sql -d postgres -c "ALTER DATABASE $DB ALLOW_CONNECTIONS false"
    sql -d postgres -c "SELECT count(pg_terminate_backend(pid)) FROM pg_stat_activity WHERE datname IN ('$DB', '$tmpdb') AND pid <> pg_backend_pid()" >/dev/null
    sql -d postgres -c "ALTER DATABASE $DB RENAME TO $old"
  fi
  sql -d postgres -c "ALTER DATABASE $tmpdb RENAME TO $DB"
  sql -d postgres -c "DO \$\$ BEGIN IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'govai_app') THEN GRANT CONNECT ON DATABASE $DB TO govai_app; END IF; END \$\$"
  # Zmiana nazwy bazy zatrzymuje workery tła TimescaleDB — uruchamiamy je ponownie.
  sql -d "$DB" -c "SELECT _timescaledb_functions.start_background_workers()" >/dev/null 2>&1 \
    || log "UWAGA: nie udało się wznowić workerów TimescaleDB (zrobi to restart kontenera)"
  rm -rf "$dir"
  log "Odtworzono bazę $DB w środowisku $target."
  [ "$has_db" = 1 ] && log "Poprzednia baza: $old — po sprawdzeniu usuń: DROP DATABASE $old;"
  echo "GOVAI_RESTORE_OK mode=replace env=$target"
}

case "${1:-schedule}" in
  schedule) cmd_schedule ;;
  run)      shift; cmd_run "$@" ;;
  check)    shift; cmd_check "$@" ;;
  fetch)    shift; with_lock; cmd_fetch "${1:?env}" "${2:-latest}" "${3:?katalog}" ;;
  restore)  shift; cmd_restore "$@" ;;
  *) sed -n '2,20p' "$0"; exit 2 ;;
esac

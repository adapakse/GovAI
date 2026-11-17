#!/usr/bin/env bash
# Odtworzenie bazy GovAI z backupu — na VM vm-govai-data (az vm run-command / Bastion) albo on-prem.
#
#   restore.sh <int|prod> [latest|<ścieżka.dump>] [--from <env>] [--test] [--yes]
#
#   latest           najnowszy backup środowiska (albo --from <env>, np. kopia PROD na INT — patrz README)
#   <ścieżka.dump>   konkretny plik, np. prod/2026/11/17/govai-20261117T013000Z.dump
#   --test           odtworzenie do govai_restore_test, porównanie liczności z metadanymi, usunięcie bazy
#   --yes            podmiana bazy govai (stara zostaje jako govai_pre_restore_<ts>)
#
# Właściwa logika jest w kontenerze govai-backup (govai-backup restore): pobranie, sha256, role,
# timescaledb_pre_restore → pg_restore → timescaledb_post_restore, hasło govai_app, porównanie liczności.
# Skrypt nie skaluje Container Apps (VM nie ma az) — wypisuje komendy dla człowieka.
set -euo pipefail
BACKUP_CONTAINER=${BACKUP_CONTAINER:-govai-backup}
SUB=${GOVAI_SUBSCRIPTION:-5e23c5f2-d269-41d3-b558-7d65dad68f1e}

env=${1:-}
case "$env" in
  int|prod) ;;
  *) sed -n '2,13p' "$0"; exit 2 ;;
esac
replace=1
for a in "$@"; do [ "$a" = --test ] && replace=0; done
sfx=""; [ "$env" = int ] && sfx="-int"

docker inspect -f '{{.State.Running}}' "$BACKUP_CONTAINER" 2>/dev/null | grep -qx true \
  || { echo "Kontener $BACKUP_CONTAINER nie działa (docker compose up -d backup)" >&2; exit 1; }

if [ "$replace" = 1 ]; then
  cat <<EOF
== Odtworzenie podmienia bazę govai ($env); zapisy aplikacji w trakcie trafią do starej bazy.
   Zalecane przed (Azure, z laptopa — AZURE_CONFIG_DIR GovAI): wyłączenie aktywnych rewizji api i gateway
   for a in api gateway; do r=\$(az containerapp show --subscription $SUB -g rg-govai -n govai-\$a$sfx --query properties.latestRevisionName -o tsv); az containerapp revision deactivate --subscription $SUB -g rg-govai -n govai-\$a$sfx --revision \$r; done
   Po odtworzeniu to samo z „revision activate”.
EOF
fi

docker exec "$BACKUP_CONTAINER" govai-backup restore "$@"
echo "GOVAI_RESULT=OK"

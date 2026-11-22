#!/usr/bin/env bash
# GovAI — usługi danych na VM vm-govai-data (uruchamia root: systemd govai-data.service,
# az vm run-command z bootstrapu i workflowów GitHub).
#
#   govai-data.sh boot        sekrety z Key Vault → certyfikaty TLS → logowanie ACR → PROD (+ INT w godzinach pracy)
#   govai-data.sh secrets     tylko pobranie haseł z Key Vault do /etc/govai/data.env
#   govai-data.sh int-start   uruchomienie pg-int i redis-int (czeka na healthcheck)
#   govai-data.sh int-stop    backup INT, potem zatrzymanie pg-int i redis-int
#   govai-data.sh status      stan kontenerów
#
# Konfiguracja bez sekretów: /etc/govai/vm.env (z bootstrapu). Hasła: Key Vault przez managed identity
# VM (IMDS) — nigdy w custom data / cloud-init. Wynik pomyślny kończy linia GOVAI_RESULT=OK
# (az vm run-command nie przekazuje kodu wyjścia skryptu — workflowy sprawdzają ten znacznik).
set -euo pipefail

DIR=/opt/govai-data
CONF=/etc/govai/vm.env
ENV_FILE=/etc/govai/data.env
[ -f "$CONF" ] || { echo "Brak $CONF" >&2; exit 1; }
# shellcheck disable=SC1090
. "$CONF"
DATA_DIR=${DATA_DIR:-/data}
INT_TZ=${INT_TZ:-Europe/Warsaw}

log() { printf '%s [govai-data] %s\n' "$(date '+%F %T')" "$*"; }
die() { log "BŁĄD: $*" >&2; exit 1; }
compose() { docker compose -f "$DIR/docker-compose.yml" --env-file "$ENV_FILE" "$@"; }

imds_token() {   # imds_token <resource>
  local url="http://169.254.169.254/metadata/identity/oauth2/token?api-version=2018-02-01&resource=$1"
  curl -fsS --retry 5 --retry-delay 3 -H Metadata:true "$url" | jq -r .access_token
}

# Pobranie sekretu; pusta wartość, gdy sekretu nie ma (404). Inne błędy (np. 403 przed
# propagacją roli) kończą skrypt — systemd ponowi start usługi.
kv_get() {   # kv_get <token> <nazwa>
  local body code
  body=$(mktemp)
  code=$(curl -sS -o "$body" -w '%{http_code}' -H "Authorization: Bearer $1" \
    "https://${KEY_VAULT_NAME}.vault.azure.net/secrets/$2?api-version=7.4")
  case $code in
    200) jq -r .value "$body"; rm -f "$body" ;;
    404) rm -f "$body" ;;
    *) rm -f "$body"; die "Key Vault $KEY_VAULT_NAME: sekret $2 — HTTP $code (rola Key Vault Secrets User dla VM?)" ;;
  esac
}

cmd_secrets() {
  [ -n "${KEY_VAULT_NAME:-}" ] || die "brak KEY_VAULT_NAME w $CONF"
  local token tmp
  token=$(imds_token "https%3A%2F%2Fvault.azure.net") || die "brak tokenu managed identity (IMDS)"
  [ -n "$token" ] && [ "$token" != null ] || die "pusty token managed identity"
  umask 077
  mkdir -p /etc/govai
  tmp=$(mktemp /etc/govai/.data.env.XXXXXX)
  trap 'rm -f "$tmp"' EXIT
  {
    echo "# Wygenerowane przez govai-data.sh secrets — NIE edytuj (źródło: $CONF + Key Vault $KEY_VAULT_NAME)."
    grep -v '^[[:space:]]*#' "$CONF" | grep -v '^[[:space:]]*$' || true
  } > "$tmp"
  local e sfx name var value
  for e in prod int; do
    sfx=""; [ "$e" = int ] && sfx="-int"
    for name in db-admin-password db-app-password redis-password; do
      var=$(echo "${name}_$e" | tr 'a-z-' 'A-Z_')
      value=$(kv_get "$token" "$name$sfx")   # przypisanie — błąd kv_get przerywa skrypt (set -e)
      printf '%s=%s\n' "$var" "$value" >> "$tmp"
    done
  done
  trap - EXIT
  chmod 600 "$tmp"
  mv "$tmp" "$ENV_FILE"
  local missing
  missing=$(grep -E '^(DB_ADMIN_PASSWORD|DB_APP_PASSWORD|REDIS_PASSWORD)_[A-Z]+=$' "$ENV_FILE" | cut -d= -f1 | tr '\n' ' ' || true)
  log "Zapisano $ENV_FILE${missing:+ (brak w Key Vault: $missing)}"
}

has_secrets() {   # has_secrets <PROD|INT>
  grep -qE "^DB_ADMIN_PASSWORD_$1=.+" "$ENV_FILE" && grep -qE "^REDIS_PASSWORD_$1=.+" "$ENV_FILE"
}

# Certyfikat TLS Postgresa (samopodpisany, 10 lat) — klienci używają sslmode=require
# (szyfrowanie bez weryfikacji CA; ruch i tak tylko w prywatnym VNet). uid 70 = postgres w obrazie alpine.
cmd_certs() {
  local e d
  for e in prod int; do
    d="$DATA_DIR/ssl/$e"
    mkdir -p "$d"
    if [ ! -s "$d/server.key" ] || [ ! -s "$d/server.crt" ]; then
      openssl req -x509 -newkey rsa:2048 -nodes -days 3650 -subj "/CN=govai-pg-$e" \
        -keyout "$d/server.key" -out "$d/server.crt" 2>/dev/null
      log "Certyfikat TLS Postgres $e wygenerowany"
    fi
    # Postgres w kontenerze działa jako uid 70 — musi przejść przez katalogi (mkdir z umask 077 daje 700 root).
    chown 70:70 "$d" "$d/server.key" "$d/server.crt"
    chmod 700 "$d"; chmod 600 "$d/server.key"; chmod 644 "$d/server.crt"
  done
  chmod 755 "$DATA_DIR/ssl"
}

# docker login do ACR tokenem managed identity (wymiana tokenu AAD na refresh token ACR).
cmd_acr_login() {
  [ -n "${ACR_NAME:-}" ] || { log "Brak ACR_NAME — pomijam logowanie do rejestru"; return 0; }
  local aad refresh server="$ACR_NAME.azurecr.io"
  aad=$(imds_token "https%3A%2F%2Fmanagement.azure.com%2F") || return 1
  refresh=$(curl -fsS --retry 3 -X POST -H "Content-Type: application/x-www-form-urlencoded" \
    --data-urlencode "grant_type=access_token" --data-urlencode "service=$server" \
    --data-urlencode "access_token=$aad" "https://$server/oauth2/exchange" | jq -r .refresh_token) || return 1
  [ -n "$refresh" ] && [ "$refresh" != null ] || return 1
  printf '%s' "$refresh" | docker login "$server" -u 00000000-0000-0000-0000-000000000000 --password-stdin >/dev/null
  log "Zalogowano do $server (managed identity)"
}

in_business_hours() {   # pn–pt 09:00–18:00 czasu INT_TZ (domyślnie Europe/Warsaw, DST przez tzdata)
  local dow hm
  dow=$(TZ=$INT_TZ date +%u); hm=$(TZ=$INT_TZ date +%H%M)
  [ "$dow" -le 5 ] && [ "$((10#$hm))" -ge 900 ] && [ "$((10#$hm))" -lt 1800 ]
}

wait_healthy() {   # wait_healthy <kontener...>
  local c i s
  for c in "$@"; do
    for i in $(seq 1 60); do
      s=$(docker inspect -f '{{.State.Health.Status}}' "$c" 2>/dev/null || echo missing)
      [ "$s" = healthy ] && break
      [ "$i" = 60 ] && die "$c nie osiągnął stanu healthy (ostatni: $s)"
      sleep 3
    done
    log "$c: healthy"
  done
}

cmd_int_start() {
  has_secrets INT || die "brak haseł INT w Key Vault (bootstrap: secrets int)"
  compose up -d pg-int redis-int
  wait_healthy govai-pg-int govai-redis-int
}

cmd_int_stop() {
  if [ "$(docker inspect -f '{{.State.Running}}' govai-pg-int 2>/dev/null || echo false)" = true ]; then
    # INT działa tylko w godzinach pracy — backup przed zatrzymaniem (o 02:30 baza INT nie działa).
    if docker exec govai-backup govai-backup run int; then
      log "Backup INT przed zatrzymaniem: OK"
    else
      log "UWAGA: backup INT przed zatrzymaniem NIEUDANY"
      echo "GOVAI_WARN=int-backup-failed"
    fi
  fi
  compose stop pg-int redis-int
  log "INT zatrzymany"
}

cmd_boot() {
  mkdir -p "$DATA_DIR"/{pg-prod,pg-int,backup-state,backup-work,backups,ssl}
  cmd_secrets
  has_secrets PROD || die "brak haseł PROD w Key Vault (bootstrap: secrets prod) — systemd ponowi start"
  cmd_certs
  cmd_acr_login || log "UWAGA: logowanie do ACR nieudane — używam obrazów z lokalnego cache"
  compose pull --ignore-pull-failures --quiet pg-prod redis-prod backup || true
  compose up -d pg-prod redis-prod
  # Obraz backupu: z ACR, a gdy go brak — build lokalny z ./backup (compose robi to sam).
  compose up -d backup || log "UWAGA: kontener backupu nie wystartował"
  wait_healthy govai-pg-prod govai-redis-prod
  if [ "${INT_ALWAYS_ON:-false}" = true ] || in_business_hours; then
    if has_secrets INT; then
      compose pull --ignore-pull-failures --quiet pg-int redis-int || true
      cmd_int_start
    else
      log "INT: brak haseł w Key Vault — pomijam"
    fi
  else
    log "INT: poza godzinami pracy — nie uruchamiam"
  fi
}

case "${1:-}" in
  boot)      cmd_boot ;;
  secrets)   cmd_secrets ;;
  certs)     cmd_certs ;;
  acr-login) cmd_acr_login ;;
  int-start) cmd_int_start ;;
  int-stop)  cmd_int_stop ;;
  status)    compose ps --all ;;
  *) sed -n '2,13p' "$0"; exit 2 ;;
esac
echo "GOVAI_RESULT=OK"

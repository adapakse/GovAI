#!/usr/bin/env bash
# GovAI — infrastruktura Azure Container Apps (INT + PROD), bazy na VM w prywatnym VNet.
# Plan: docs/azure-environments-plan.md, VM danych: infra/db-vm/README.md, nazwy: sekcja "Nazwy" niżej.
#
# Użycie (Git Bash / WSL / Linux, zalogowany `az login` do tenanta subskrypcji), w tej kolejności:
#   bash infra/aca/bootstrap.sh base         # RG, Log Analytics, ACR, Key Vault
#   bash infra/aca/bootstrap.sh network      # VNet, podsieci, NSG, środowisko Container Apps govai-env w VNet
#   bash infra/aca/bootstrap.sh backup       # konto Storage na backupy (kontener backups, retencja 7 dni)
#   bash infra/aca/bootstrap.sh secrets prod # hasła baz/Redis + sekrety aplikacji w Key Vault (int: secrets int)
#   bash infra/aca/bootstrap.sh datavm       # VM z Postgres+TimescaleDB i Redis (PROD+INT), role, pliki na VM
#   bash infra/aca/bootstrap.sh github       # tożsamość OIDC dla GitHub Actions + role
#   bash infra/aca/bootstrap.sh apps int     # Container Apps + job migracji (obrazy startowe; CI podmienia)
#
# Idempotentny: istniejące zasoby są pomijane, istniejące sekrety nie są nadpisywane.
# Hasła generuje skrypt i zapisuje wyłącznie w Key Vault (nie wypisuje ich).
set -euo pipefail
export MSYS_NO_PATHCONV=1
REPO=$(cd "$(dirname "$0")/../.." && pwd)

# ── Nazwy ────────────────────────────────────────────────────────────────────
SUB="${GOVAI_SUBSCRIPTION:-5e23c5f2-d269-41d3-b558-7d65dad68f1e}"
LOC="${GOVAI_LOCATION:-polandcentral}"
RG=rg-govai
LOGS=govai-logs
ENV_NAME=govai-env
ACR=govaicr
KV=kv-govai
GH_ID=id-govai-github
GH_REPO=adapakse/GovAI
DB_NAME=govai
DB_ADMIN=govai                      # superużytkownik Postgresa w kontenerze (POSTGRES_USER)
# Sieć (decyzja 2026-11-17: Azure Postgres Flexible niedostępny dla subskrypcji — bazy na VM w VNet)
VNET=vnet-govai;   VNET_PREFIX=10.50.0.0/16
SNET_ACA=snet-aca; SNET_ACA_PREFIX=10.50.0.0/23     # delegowana do Microsoft.App/environments
SNET_DATA=snet-data; SNET_DATA_PREFIX=10.50.2.0/27
NSG_DATA=nsg-govai-data
DATA_IP=10.50.2.10
# VM danych (quota subskrypcji: tylko rodziny BS i DSv3) — rozmiar nadpisywalny, np. Standard_D2s_v3
DATA_VM=vm-govai-data
# B2ms i D2s_v3 bez wolnej mocy w Poland Central (2026-11-17) — D2as_v5 (wymaga quoty DASv5 >= 2 vCPU).
DATA_VM_SIZE="${GOVAI_DATA_VM_SIZE:-Standard_D2as_v5}"
DATA_PIP=pip-govai-data
DATA_NIC=nic-govai-data
PG_IMAGE_TAG=2.31.0-pg16            # timescale/timescaledb — ten sam w infra/db-vm/docker-compose.yml
REDIS_IMAGE_TAG=7.4-alpine
# Backup
STG="stgovaibkp$(printf '%s' "$SUB" | sha256sum | cut -c1-6)"   # deterministyczna, globalnie unikalna nazwa
BKP_CONTAINER=backups
BKP_RETENTION_DAYS=7

# Osobny katalog konfiguracji az dla GovAI (tylko konto adamgmanka@gmail.com) — wspólnego ~/.azure
# używają równolegle sesje innych projektów, więc nie wolno w nim przełączać subskrypcji.
export AZURE_CONFIG_DIR="${AZURE_CONFIG_DIR:-C:/Users/apt/.azure-govai}"
case "$AZURE_CONFIG_DIR" in
  *.azure-govai*) ;;
  *) echo "Uruchom z AZURE_CONFIG_DIR wskazującym katalog GovAI (C:/Users/apt/.azure-govai)" >&2; exit 1 ;;
esac
# Przełącznik --subscription musi stać PO nazwie komendy, więc subskrypcję ustawiamy raz —
# tylko w katalogu konfiguracji GovAI, bez wpływu na inne projekty.
az account set --subscription "$SUB"
AZ="az"

suffix() { [ "$1" = "prod" ] && echo "" || echo "-$1"; }   # prod → "", int → "-int"
log() { printf '\n== %s\n' "$*"; }
rand() { openssl rand -hex "${1:-24}"; }
winpath() { if command -v cygpath >/dev/null 2>&1; then cygpath -w "$1"; else echo "$1"; fi; }   # pliki dla az w Git Bash

kv_has() { $AZ keyvault secret show --vault-name "$KV" -n "$1" --query id -o tsv >/dev/null 2>&1; }
kv_set_if_missing() {   # kv_set_if_missing <nazwa> <wartość>
  if kv_has "$1"; then
    echo "  sekret $1 — istnieje (bez zmian)"
  else
    $AZ keyvault secret set --vault-name "$KV" -n "$1" --value "$2" --output none
    echo "  sekret $1 — utworzony"
  fi
}
kv_get() { $AZ keyvault secret show --vault-name "$KV" -n "$1" --query value -o tsv; }
# URL-e baz/Redis: ustawiane, gdy brak albo gdy wskazują inny host (np. pozostałość po Azure Postgres
# Flexible) — porównanie bez wypisywania wartości.
kv_set_url() {   # kv_set_url <nazwa> <wartość> <oczekiwany fragment>
  if kv_has "$1" && kv_get "$1" | grep -qF "$3"; then
    echo "  sekret $1 — istnieje (bez zmian)"
  else
    $AZ keyvault secret set --vault-name "$KV" -n "$1" --value "$2" --output none
    echo "  sekret $1 — ustawiony (host $3)"
  fi
}
role() {   # role <principalId> <rola> <scope>
  $AZ role assignment create --assignee-object-id "$1" --assignee-principal-type ServicePrincipal \
    --role "$2" --scope "$3" --output none 2>/dev/null || true
}

# ── base ─────────────────────────────────────────────────────────────────────
step_base() {
  log "Grupa zasobów $RG ($LOC)"
  $AZ group create -n "$RG" -l "$LOC" --output none

  log "Log Analytics $LOGS"
  $AZ monitor log-analytics workspace show -g "$RG" -n "$LOGS" --output none 2>/dev/null \
    || $AZ monitor log-analytics workspace create -g "$RG" -n "$LOGS" -l "$LOC" --retention-time 30 --output none
  # Dzienny limit ingestu logów (oszczędność; przy przekroczeniu reszta logów z danego dnia przepada).
  $AZ monitor log-analytics workspace update -g "$RG" -n "$LOGS" --quota "${GOVAI_LOGS_DAILY_GB:-0.2}" --output none

  log "Rejestr obrazów $ACR (Basic, bez admin usera — pull przez managed identity)"
  $AZ acr show -n "$ACR" --output none 2>/dev/null \
    || $AZ acr create -g "$RG" -n "$ACR" -l "$LOC" --sku Basic --admin-enabled false --output none

  log "Key Vault $KV (RBAC)"
  $AZ keyvault show -n "$KV" --output none 2>/dev/null \
    || $AZ keyvault create -g "$RG" -n "$KV" -l "$LOC" --enable-rbac-authorization true --output none

  # Zalogowany użytkownik zarządza sekretami (skrypt zapisuje hasła do KV).
  local me kv_id
  me=$(az ad signed-in-user show --query id -o tsv)
  kv_id=$($AZ keyvault show -n "$KV" --query id -o tsv)
  $AZ role assignment create --assignee-object-id "$me" --assignee-principal-type User \
    --role "Key Vault Secrets Officer" --scope "$kv_id" --output none 2>/dev/null || true
  echo "  (rola Key Vault Secrets Officer dla zalogowanego użytkownika — propagacja do kilku minut)"
}

# ── network ──────────────────────────────────────────────────────────────────
# VNet z dwiema podsieciami: snet-aca (środowisko Container Apps, workload profiles) i snet-data
# (VM baz, prywatny IP 10.50.2.10). NSG na snet-data: do Postgresa/Redisa tylko z snet-aca,
# żadnego innego ruchu przychodzącego (także SSH — administracja przez az vm run-command).
step_network() {
  log "NSG $NSG_DATA"
  $AZ network nsg show -g "$RG" -n "$NSG_DATA" --output none 2>/dev/null \
    || $AZ network nsg create -g "$RG" -n "$NSG_DATA" -l "$LOC" --output none
  # nsg rule create = PUT (tworzy albo aktualizuje) — idempotentne.
  $AZ network nsg rule create -g "$RG" --nsg-name "$NSG_DATA" -n allow-data-from-aca --priority 100 \
    --direction Inbound --access Allow --protocol Tcp \
    --source-address-prefixes "$SNET_ACA_PREFIX" --source-port-ranges '*' \
    --destination-address-prefixes "$DATA_IP" --destination-port-ranges 5432 5433 6379 6380 --output none
  # Domyślna reguła AllowVnetInBound wpuszczałaby cały ruch z VNet (np. SSH z snet-aca) — blokujemy resztę.
  $AZ network nsg rule create -g "$RG" --nsg-name "$NSG_DATA" -n deny-all-inbound --priority 4096 \
    --direction Inbound --access Deny --protocol '*' \
    --source-address-prefixes '*' --source-port-ranges '*' \
    --destination-address-prefixes '*' --destination-port-ranges '*' --output none

  log "VNet $VNET ($VNET_PREFIX)"
  $AZ network vnet show -g "$RG" -n "$VNET" --output none 2>/dev/null \
    || $AZ network vnet create -g "$RG" -n "$VNET" -l "$LOC" --address-prefixes "$VNET_PREFIX" --output none
  if ! $AZ network vnet subnet show -g "$RG" --vnet-name "$VNET" -n "$SNET_ACA" --output none 2>/dev/null; then
    $AZ network vnet subnet create -g "$RG" --vnet-name "$VNET" -n "$SNET_ACA" \
      --address-prefixes "$SNET_ACA_PREFIX" --delegations Microsoft.App/environments --output none
  fi
  if ! $AZ network vnet subnet show -g "$RG" --vnet-name "$VNET" -n "$SNET_DATA" --output none 2>/dev/null; then
    $AZ network vnet subnet create -g "$RG" --vnet-name "$VNET" -n "$SNET_DATA" \
      --address-prefixes "$SNET_DATA_PREFIX" --network-security-group "$NSG_DATA" \
      --service-endpoints Microsoft.Storage --output none
  else
    $AZ network vnet subnet update -g "$RG" --vnet-name "$VNET" -n "$SNET_DATA" \
      --network-security-group "$NSG_DATA" --service-endpoints Microsoft.Storage --output none
  fi

  log "Środowisko Container Apps $ENV_NAME (workload profiles, VNet $VNET/$SNET_ACA, ingress zewnętrzny)"
  local snet_id
  snet_id=$($AZ network vnet subnet show -g "$RG" --vnet-name "$VNET" -n "$SNET_ACA" --query id -o tsv)
  if $AZ containerapp env show -g "$RG" -n "$ENV_NAME" --output none 2>/dev/null; then
    local cur env_id napps njobs
    cur=$($AZ containerapp env show -g "$RG" -n "$ENV_NAME" --query properties.vnetConfiguration.infrastructureSubnetId -o tsv)
    if [ "${cur,,}" = "${snet_id,,}" ]; then
      echo "  $ENV_NAME — istnieje w $SNET_ACA"
      return 0
    fi
    # Środowiska nie da się przenieść do VNet — tylko utworzyć od nowa. Nie usuwamy automatycznie.
    env_id=$($AZ containerapp env show -g "$RG" -n "$ENV_NAME" --query id -o tsv)
    napps=$($AZ containerapp list -g "$RG" --query "length([?properties.managedEnvironmentId=='$env_id'])" -o tsv)
    njobs=$($AZ containerapp job list -g "$RG" --query "length([?properties.environmentId=='$env_id'])" -o tsv)
    echo "  $ENV_NAME istnieje bez VNet ${cur:+(podsieć: $cur)} — aplikacje: $napps, joby: $njobs." >&2
    if [ "$napps" = 0 ] && [ "$njobs" = 0 ]; then
      echo "  Środowisko jest puste — usuń je (wgrane certyfikaty też znikną) i uruchom ten krok ponownie:" >&2
      echo "    az containerapp env delete --subscription $SUB -g $RG -n $ENV_NAME --yes" >&2
    else
      echo "  Środowisko ma aplikacje/joby — migracja do VNet wymaga ręcznego planu (nowe środowisko, przeniesienie aplikacji)." >&2
    fi
    exit 1
  fi
  local ws_id ws_key
  ws_id=$($AZ monitor log-analytics workspace show -g "$RG" -n "$LOGS" --query customerId -o tsv)
  ws_key=$($AZ monitor log-analytics workspace get-shared-keys -g "$RG" -n "$LOGS" --query primarySharedKey -o tsv)
  $AZ containerapp env create -g "$RG" -n "$ENV_NAME" -l "$LOC" \
    --logs-workspace-id "$ws_id" --logs-workspace-key "$ws_key" \
    --infrastructure-subnet-resource-id "$snet_id" --enable-workload-profiles true \
    --internal-only false --output none
  echo "  $ENV_NAME — utworzone (profil Consumption)"
}

# ── backup ───────────────────────────────────────────────────────────────────
# Konto Storage na zrzuty baz: tylko tożsamości (bez kluczy współdzielonych), dostęp sieciowy tylko
# z snet-data (service endpoint) + zaufane usługi Azure; retencja przez lifecycle management.
step_backup() {
  log "Konto Storage $STG (backupy baz)"
  if ! $AZ storage account show -g "$RG" -n "$STG" --output none 2>/dev/null; then
    local sku
    for sku in Standard_ZRS Standard_LRS; do
      if $AZ storage account create -g "$RG" -n "$STG" -l "$LOC" --sku "$sku" --kind StorageV2 \
           --min-tls-version TLS1_2 --https-only true --allow-blob-public-access false \
           --allow-shared-key-access false --default-action Deny --bypass AzureServices --output none; then
        echo "  $STG — utworzone ($sku)"; break
      fi
      echo "  $sku niedostępne — próbuję kolejne"
      [ "$sku" = Standard_LRS ] && exit 1
    done
  else
    echo "  $STG — istnieje"
  fi
  local snet_id
  snet_id=$($AZ network vnet subnet show -g "$RG" --vnet-name "$VNET" -n "$SNET_DATA" --query id -o tsv)
  if ! $AZ storage account network-rule list -g "$RG" --account-name "$STG" \
       --query "virtualNetworkRules[].virtualNetworkResourceId" -o tsv | grep -qiF "$snet_id"; then
    $AZ storage account network-rule add -g "$RG" --account-name "$STG" --subnet "$snet_id" --output none
    echo "  reguła sieciowa: $SNET_DATA"
  fi
  # Kontener przez API zarządzania (ARM) — płaszczyzna danych jest zamknięta zaporą konta.
  $AZ storage container-rm show -g "$RG" --storage-account "$STG" -n "$BKP_CONTAINER" --output none 2>/dev/null \
    || $AZ storage container-rm create -g "$RG" --storage-account "$STG" -n "$BKP_CONTAINER" --public-access off --output none

  log "Lifecycle: usuwanie zrzutów po $BKP_RETENTION_DAYS dniach (prod/ i int/)"
  local tmp; tmp=$(mktemp)
  cat > "$tmp" <<EOF
{
  "rules": [
    {
      "enabled": true,
      "name": "govai-backup-retention",
      "type": "Lifecycle",
      "definition": {
        "filters": { "blobTypes": ["blockBlob"], "prefixMatch": ["$BKP_CONTAINER/prod/", "$BKP_CONTAINER/int/"] },
        "actions": { "baseBlob": { "delete": { "daysAfterModificationGreaterThan": $BKP_RETENTION_DAYS } } }
      }
    }
  ]
}
EOF
  $AZ storage account management-policy create -g "$RG" --account-name "$STG" --policy @"$(winpath "$tmp")" --output none
  rm -f "$tmp"
  echo "  konto: $STG, kontener: $BKP_CONTAINER"
}

# ── secrets <int|prod> ───────────────────────────────────────────────────────
step_secrets() {
  local env="$1" sfx pg_port redis_port
  sfx=$(suffix "$env")
  if [ "$env" = prod ]; then pg_port=5432; redis_port=6379; else pg_port=5433; redis_port=6380; fi

  log "Sekrety ($env) w $KV — bazy na $DATA_IP:$pg_port, Redis $DATA_IP:$redis_port"
  kv_set_if_missing "jwt-secret$sfx" "$(rand 32)"
  kv_set_if_missing "provider-keys-secret$sfx" "$(rand 32)"
  kv_set_if_missing "db-admin-password$sfx" "$(rand 24)"
  kv_set_if_missing "db-app-password$sfx" "$(rand 24)"
  kv_set_if_missing "redis-password$sfx" "$(rand 24)"
  local admin_pw app_pw redis_pw
  admin_pw=$(kv_get "db-admin-password$sfx")
  app_pw=$(kv_get "db-app-password$sfx")
  redis_pw=$(kv_get "redis-password$sfx")
  kv_set_url "database-admin-url$sfx" "postgresql://$DB_ADMIN:$admin_pw@$DATA_IP:$pg_port/$DB_NAME?sslmode=require" "@$DATA_IP:$pg_port/"
  kv_set_url "database-url$sfx" "postgresql://govai_app:$app_pw@$DATA_IP:$pg_port/$DB_NAME?sslmode=require" "@$DATA_IP:$pg_port/"
  kv_set_url "redis-url$sfx" "redis://:$redis_pw@$DATA_IP:$redis_port/0" "@$DATA_IP:$redis_port/"

  # Klucze dostawców LLM — prawdziwe wartości wpisuje człowiek (od dostawcy / z poprzedniego
  # Key Vault). Do tego czasu wartość tymczasowa: referencja KV w Container App wymaga istniejącego
  # sekretu; aplikacja działa, tylko wywołania LLM zwracają błąd autoryzacji dostawcy.
  for s in anthropic-api-key deepseek-api-key; do
    if ! kv_has "$s$sfx"; then
      kv_set_if_missing "$s$sfx" "do-ustawienia"
      echo "  UWAGA: $s$sfx ma wartość tymczasową — ustaw prawdziwy klucz:"
      echo "         az keyvault secret set --subscription $SUB --vault-name $KV -n $s$sfx --value <klucz>"
    fi
  done
  # Token Cloudflare (wspólny dla INT i PROD) — dla .github/workflows/renew-certs.yml.
  if ! kv_has cloudflare-api-token; then
    echo "  UWAGA: brak cloudflare-api-token (token „Edit zone DNS” dla govai.pl) — bez niego certyfikaty się nie odnowią:"
    echo "         az keyvault secret set --subscription $SUB --vault-name $KV -n cloudflare-api-token --value <token>"
  fi
  echo "  VM danych pobiera nowe hasła przy starcie usługi: infra/db-vm/vm-run.sh 'systemctl restart govai-data'"
}

# ── datavm ───────────────────────────────────────────────────────────────────
# Pakiet plików VM (infra/db-vm + vm.env bez sekretów) jako tar.gz — dostarczany przez cloud-init
# (nowa VM) i przez run-command (aktualizacja istniejącej). Nie zależy od dostępu VM do GitHuba.
build_bundle() {   # build_bundle <katalog_tymczasowy> → <katalog>/bundle.tgz
  local stage="$1/stage"
  mkdir -p "$stage"
  cp -r "$REPO/infra/db-vm/docker-compose.yml" "$REPO/infra/db-vm/govai-data.sh" "$REPO/infra/db-vm/install.sh" \
        "$REPO/infra/db-vm/restore.sh" "$REPO/infra/db-vm/initdb" "$REPO/infra/db-vm/backup" "$stage/"
  cat > "$stage/vm.env" <<EOF
# Konfiguracja VM danych GovAI (bez sekretów) — generowana przez infra/aca/bootstrap.sh datavm.
KEY_VAULT_NAME=$KV
ACR_NAME=$ACR
DATA_DIR=/data
DATA_BIND_IP=$DATA_IP
PG_SSL=on
PG_IMAGE=$ACR.azurecr.io/timescale/timescaledb:$PG_IMAGE_TAG
REDIS_IMAGE=$ACR.azurecr.io/library/redis:$REDIS_IMAGE_TAG
BACKUP_IMAGE=$ACR.azurecr.io/govai-backup:prod
BACKUP_TARGET=azure-blob
BACKUP_STORAGE_ACCOUNT=$STG
BACKUP_STORAGE_CONTAINER=$BKP_CONTAINER
BACKUP_PGSSLMODE=require
BACKUP_TZ=Europe/Warsaw
BACKUP_TIME=02:30
INT_TZ=Europe/Warsaw
EOF
  # Pliki z checkoutu na Windows mogą mieć CRLF — na VM tylko LF.
  find "$stage" -type f -exec sed -i 's/\r$//' {} +
  (cd "$stage" && tar -czf ../bundle.tgz .)
}

step_datavm() {
  local tmp; tmp=$(mktemp -d)
  DATAVM_TMP=$tmp
  trap 'rm -rf "$DATAVM_TMP"' EXIT

  for s in db-admin-password db-app-password redis-password; do
    kv_has "$s" || echo "  UWAGA: brak sekretu $s — najpierw: bootstrap.sh secrets prod (usługa na VM będzie ponawiać start)"
  done

  log "Obrazy baz w $ACR (import z Docker Hub)"
  local img
  for img in "timescale/timescaledb:$PG_IMAGE_TAG" "library/redis:$REDIS_IMAGE_TAG"; do
    if $AZ acr repository show -n "$ACR" --image "$img" --output none 2>/dev/null; then
      echo "  $img — jest"
    else
      $AZ acr import -n "$ACR" --source "docker.io/$img" --image "$img" --output none
      echo "  $img — zaimportowany"
    fi
  done
  if ! $AZ acr repository show -n "$ACR" --image govai-backup:prod --output none 2>/dev/null; then
    # ACR Tasks bywają wyłączone w nowych subskrypcjach — wtedy VM zbuduje obraz lokalnie,
    # a docelowo wypchnie go deploy PROD (_deploy-aca.yml).
    $AZ acr build -r "$ACR" -t govai-backup:prod "$(winpath "$REPO/infra/db-vm/backup")" --output none 2>/dev/null \
      && echo "  govai-backup:prod — zbudowany (ACR Tasks)" \
      || echo "  govai-backup:prod — brak (ACR Tasks niedostępne); VM zbuduje obraz lokalnie"
  fi

  log "Publiczny IP $DATA_PIP (tylko ruch wychodzący) i NIC $DATA_NIC ($DATA_IP)"
  # Standard Public IP zamiast NAT Gateway: tańsze, a „default outbound access” Azure jest wygaszany.
  # NSG podsieci nie wpuszcza żadnego ruchu z internetu (Standard IP jest domyślnie zamknięty).
  $AZ network public-ip show -g "$RG" -n "$DATA_PIP" --output none 2>/dev/null \
    || $AZ network public-ip create -g "$RG" -n "$DATA_PIP" -l "$LOC" --sku Standard \
         --allocation-method Static --version IPv4 --output none
  $AZ network nic show -g "$RG" -n "$DATA_NIC" --output none 2>/dev/null \
    || $AZ network nic create -g "$RG" -n "$DATA_NIC" -l "$LOC" --vnet-name "$VNET" --subnet "$SNET_DATA" \
         --private-ip-address "$DATA_IP" --public-ip-address "$DATA_PIP" --output none

  build_bundle "$tmp"
  local created=0
  log "VM $DATA_VM ($DATA_VM_SIZE, Ubuntu 24.04, dysk danych 64 GB Premium SSD)"
  if $AZ vm show -g "$RG" -n "$DATA_VM" --output none 2>/dev/null; then
    echo "  $DATA_VM — istnieje"
  else
    cat > "$tmp/cloud-init.yaml" <<EOF
#cloud-config
# GovAI vm-govai-data - no secrets here: passwords are fetched by govai-data.sh from Key Vault (managed identity).
write_files:
  - path: /opt/govai-data/bundle.tgz
    encoding: b64
    permissions: '0600'
    content: $(base64 -w0 "$tmp/bundle.tgz")
runcmd:
  - [bash, -c, "tar -xzf /opt/govai-data/bundle.tgz -C /opt/govai-data && bash /opt/govai-data/install.sh"]
EOF
    # Klucz SSH jednorazowy (klucz prywatny od razu usuwany) — Linux wymaga poświadczeń przy tworzeniu,
    # a administracja idzie przez az vm run-command. Dostęp awaryjny: az vm user update (nowy klucz).
    ssh-keygen -q -t ed25519 -N "" -C govai-data-bootstrap -f "$tmp/id"
    rm -f "$tmp/id"
    $AZ vm create -g "$RG" -n "$DATA_VM" -l "$LOC" --image Ubuntu2404 --size "$DATA_VM_SIZE" \
      --nics "$DATA_NIC" --admin-username govaiadmin --authentication-type ssh \
      --ssh-key-values "$(winpath "$tmp/id.pub")" --assign-identity '[system]' \
      --os-disk-name osdisk-govai-data --os-disk-size-gb 30 --storage-sku StandardSSD_LRS \
      --data-disk-sizes-gb 64 --data-disk-caching ReadOnly \
      --custom-data "$(winpath "$tmp/cloud-init.yaml")" --tags project=govai role=data --output none \
      || { echo "  Tworzenie VM nieudane — przy braku mocy/quoty spróbuj innego rozmiaru: GOVAI_DATA_VM_SIZE=Standard_D2s_v5 (quota DSv5)" >&2; exit 1; }
    $AZ vm boot-diagnostics enable -g "$RG" -n "$DATA_VM" --output none   # konsola szeregowa / log cloud-init
    created=1
    echo "  $DATA_VM — utworzona"
  fi

  log "Role tożsamości VM (AcrPull, Key Vault Secrets User, Storage Blob Data Contributor)"
  local pid
  pid=$($AZ vm show -g "$RG" -n "$DATA_VM" --query identity.principalId -o tsv)
  role "$pid" AcrPull "$($AZ acr show -n "$ACR" --query id -o tsv)"
  role "$pid" "Key Vault Secrets User" "$($AZ keyvault show -n "$KV" --query id -o tsv)"
  role "$pid" "Storage Blob Data Contributor" "$($AZ storage account show -g "$RG" -n "$STG" --query id -o tsv)"
  if [ "$created" = 1 ]; then
    echo "  Czekam na propagację ról (90 s)…"; sleep 90
  fi

  log "Synchronizacja plików na VM i start govai-data.service (az vm run-command)"
  {
    echo 'set -e'
    echo 'cloud-init status --wait >/dev/null 2>&1 || true'
    echo 'mkdir -p /opt/govai-data'
    echo "echo '$(base64 -w0 "$tmp/bundle.tgz")' | base64 -d > /opt/govai-data/bundle.tgz"
    echo 'tar -xzf /opt/govai-data/bundle.tgz -C /opt/govai-data'
    echo 'bash /opt/govai-data/install.sh'
    echo 'for i in $(seq 1 60); do st=$(systemctl is-active govai-data || true); [ "$st" = active ] && break; sleep 10; done'
    echo 'systemctl is-active --quiet govai-data || { journalctl -u govai-data -n 40 --no-pager; exit 1; }'
    echo 'bash /opt/govai-data/govai-data.sh status'
  } > "$tmp/sync.sh"
  bash "$REPO/infra/db-vm/vm-run.sh" @"$tmp/sync.sh" | tail -n 25

  # Azure Backup całej VM świadomie pominięty (decyzja 2026-11-22, oszczędność ~11 EUR/mies.):
  # dane chroni codzienny zrzut baz do Blob (govai-backup), a VM odtwarza ten krok (datavm).
}

# ── github ───────────────────────────────────────────────────────────────────
step_github() {
  log "Tożsamość OIDC GitHub Actions $GH_ID"
  $AZ identity show -g "$RG" -n "$GH_ID" --output none 2>/dev/null \
    || $AZ identity create -g "$RG" -n "$GH_ID" -l "$LOC" --output none
  # ops — opcjonalne środowisko GitHub dla workflowów harmonogramowych (int-schedule, backup-check,
  # restore-test, renew-certs), gdyby „prod” dostało wymagane zatwierdzenia (zmienna repo OPS_ENVIRONMENT).
  for e in int prod ops; do
    $AZ identity federated-credential show -g "$RG" --identity-name "$GH_ID" -n "gh-env-$e" --output none 2>/dev/null \
      || $AZ identity federated-credential create -g "$RG" --identity-name "$GH_ID" -n "gh-env-$e" \
           --issuer https://token.actions.githubusercontent.com \
           --subject "repo:$GH_REPO:environment:$e" --audiences api://AzureADTokenExchange --output none
  done
  local pid rg_id acr_id kv_id
  pid=$($AZ identity show -g "$RG" -n "$GH_ID" --query principalId -o tsv)
  rg_id=$($AZ group show -n "$RG" --query id -o tsv)
  acr_id=$($AZ acr show -n "$ACR" --query id -o tsv)
  kv_id=$($AZ keyvault show -n "$KV" --query id -o tsv)
  # Contributor na RG obejmuje też az vm run-command (workflowy INT/backup) i joby Container Apps.
  for pair in "Contributor|$rg_id" "AcrPush|$acr_id" "Key Vault Secrets User|$kv_id"; do
    role "$pid" "${pair%%|*}" "${pair#*|}"
  done
  echo "  Sekrety GitHub (środowiska int i prod): AZURE_CLIENT_ID=$($AZ identity show -g "$RG" -n "$GH_ID" --query clientId -o tsv)"
  echo "  AZURE_TENANT_ID=$(az account show --subscription "$SUB" --query tenantId -o tsv)  AZURE_SUBSCRIPTION_ID=$SUB"
}

# ── apps <int|prod> ──────────────────────────────────────────────────────────
# Tworzy 4 aplikacje z obrazem startowym (CI podmienia obrazy przy pierwszym deployu) i job migracji,
# system-assigned identity (AcrPull + Key Vault Secrets User), sekrety jako referencje KV.
# Bazy i Redis: VM vm-govai-data w VNet (database-url / redis-url z kroku secrets).
step_apps() {
  local env="$1" sfx; sfx=$(suffix "$env")
  local acr_id kv_id kv_uri
  acr_id=$($AZ acr show -n "$ACR" --query id -o tsv)
  kv_id=$($AZ keyvault show -n "$KV" --query id -o tsv)
  kv_uri="https://$KV.vault.azure.net/secrets"
  local placeholder=mcr.microsoft.com/k8se/quickstart:latest
  local domain base_hosts
  if [ "$env" = prod ]; then domain=govai.pl; base_hosts="govai.pl www.govai.pl"; else domain=int.govai.pl; base_hosts="int.govai.pl"; fi

  create_app() {   # create_app <nazwa> <port> <external|internal> <min> <max> <cpu> <pamięć>
    local name="$1" port="$2" ingress="$3" min="$4" max="$5" cpu="$6" mem="$7"
    if $AZ containerapp show -g "$RG" -n "$name" --output none 2>/dev/null; then
      echo "  $name — istnieje"; allow_http "$name" "$ingress"; return
    fi
    $AZ containerapp create -g "$RG" -n "$name" --environment "$ENV_NAME" --image "$placeholder" \
      --target-port "$port" --ingress "$ingress" --min-replicas "$min" --max-replicas "$max" \
      --cpu "$cpu" --memory "$mem" --system-assigned --output none
    local pid; pid=$($AZ containerapp show -g "$RG" -n "$name" --query identity.principalId -o tsv)
    role "$pid" AcrPull "$acr_id"
    role "$pid" "Key Vault Secrets User" "$kv_id"
    $AZ containerapp registry set -g "$RG" -n "$name" --server "$ACR.azurecr.io" --identity system --output none
    allow_http "$name" "$ingress"
    echo "  $name — utworzona"
  }

  # Edge woła aplikacje wewnętrzne po http://<nazwa> — bez allowInsecure ingress
  # odpowiada przekierowaniem na HTTPS. Dotyczy tylko ingressu wewnętrznego.
  allow_http() {   # allow_http <nazwa> <external|internal>
    [ "$2" = internal ] || return 0
    $AZ containerapp ingress update -g "$RG" -n "$1" --allow-insecure true --output none
  }

  # Job migracji (uruchamiany przez CI przed aktualizacją aplikacji) — runner GitHub nie ma
  # dostępu do bazy w VNet. Obraz govai-migrate: infra/migrate/Dockerfile.
  create_migrate_job() {
    local name="govai-migrate$sfx"
    if $AZ containerapp job show -g "$RG" -n "$name" --output none 2>/dev/null; then
      echo "  $name — istnieje"; return
    fi
    $AZ containerapp job create -g "$RG" -n "$name" --environment "$ENV_NAME" \
      --trigger-type Manual --replica-timeout 1800 --replica-retry-limit 0 \
      --replica-completion-count 1 --parallelism 1 \
      --image mcr.microsoft.com/k8se/quickstart-jobs:latest --cpu 0.5 --memory 1.0Gi \
      --mi-system-assigned --output none
    local pid; pid=$($AZ containerapp job show -g "$RG" -n "$name" --query identity.principalId -o tsv)
    role "$pid" AcrPull "$acr_id"
    role "$pid" "Key Vault Secrets User" "$kv_id"
    $AZ containerapp job registry set -g "$RG" -n "$name" --server "$ACR.azurecr.io" --identity system --output none
    echo "  $name — utworzony"
  }

  log "Container Apps ($env) w $ENV_NAME"
  # Rozmiary wg zmierzonego zużycia (2026-11-22: api ~90 MB, frontend ~60 MB, edge ~25 MB,
  # gateway ~380 MB ze spaCy/Presidio) — dozwolone pary ACA: 0.25/0.5Gi, 0.5/1Gi, …
  create_app "govai-api$sfx"      8000 internal 1 3 0.25 0.5Gi
  create_app "govai-gateway$sfx"  8001 internal 1 3 0.5  1.0Gi
  create_app "govai-frontend$sfx" 3000 internal "$([ "$env" = prod ] && echo 1 || echo 0)" 3 0.25 0.5Gi
  create_app "govai-edge$sfx"     80   external 1 3 0.25 0.5Gi
  create_migrate_job

  echo "  Czekam na propagację ról (60 s) przed podpięciem sekretów Key Vault…"
  sleep 60
  local secrets="database-url=keyvaultref:$kv_uri/database-url$sfx,identityref:system \
redis-url=keyvaultref:$kv_uri/redis-url$sfx,identityref:system \
jwt-secret=keyvaultref:$kv_uri/jwt-secret$sfx,identityref:system \
provider-keys-secret=keyvaultref:$kv_uri/provider-keys-secret$sfx,identityref:system \
anthropic-api-key=keyvaultref:$kv_uri/anthropic-api-key$sfx,identityref:system \
deepseek-api-key=keyvaultref:$kv_uri/deepseek-api-key$sfx,identityref:system"
  local common_env="DATABASE_URL=secretref:database-url REDIS_URL=secretref:redis-url JWT_SECRET=secretref:jwt-secret \
PROVIDER_KEYS_SECRET=secretref:provider-keys-secret ANTHROPIC_API_KEY=secretref:anthropic-api-key \
DEEPSEEK_API_KEY=secretref:deepseek-api-key ALLOWED_ORIGINS=https://app.$domain TENANT_BASE_DOMAINS=$domain \
TRUST_FORWARDED_HOST=true DB_POOL_MAX=8 LOG_LEVEL=INFO"
  for app in "govai-api$sfx" "govai-gateway$sfx"; do
    # shellcheck disable=SC2086
    $AZ containerapp secret set -g "$RG" -n "$app" --secrets $secrets --output none
    # shellcheck disable=SC2086
    $AZ containerapp update -g "$RG" -n "$app" --set-env-vars $common_env GATEWAY_URL="http://govai-gateway$sfx" --output none
  done
  $AZ containerapp update -g "$RG" -n "govai-edge$sfx" --set-env-vars \
    API_UPSTREAM="http://govai-api$sfx" GATEWAY_UPSTREAM="http://govai-gateway$sfx" \
    FRONTEND_UPSTREAM="http://govai-frontend$sfx" SITE_HOSTS="$base_hosts" DOMAIN_NAME="$domain" --output none
  $AZ containerapp job secret set -g "$RG" -n "govai-migrate$sfx" --secrets \
    "database-admin-url=keyvaultref:$kv_uri/database-admin-url$sfx,identityref:system" \
    "db-app-password=keyvaultref:$kv_uri/db-app-password$sfx,identityref:system" --output none
  $AZ containerapp job update -g "$RG" -n "govai-migrate$sfx" --set-env-vars \
    DATABASE_ADMIN_URL=secretref:database-admin-url DB_APP_PASSWORD=secretref:db-app-password --output none
  echo "  Adres techniczny edge: https://$($AZ containerapp show -g "$RG" -n "govai-edge$sfx" --query properties.configuration.ingress.fqdn -o tsv)"
}

case "${1:-}" in
  base)    step_base ;;
  network) step_network ;;
  backup)  step_backup ;;
  secrets) step_secrets "${2:?int|prod}" ;;
  datavm)  step_datavm ;;
  github)  step_github ;;
  apps)    step_apps "${2:?int|prod}" ;;
  *) sed -n '2,17p' "$0"; exit 2 ;;
esac

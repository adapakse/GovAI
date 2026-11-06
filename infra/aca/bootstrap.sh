#!/usr/bin/env bash
# GovAI — infrastruktura Azure Container Apps (INT + PROD), wzorem CRMtree.
# Plan: docs/azure-environments-plan.md, nazwy: sekcja "Nazwy" niżej.
#
# Użycie (Git Bash / WSL / Linux, zalogowany `az login` do tenanta subskrypcji):
#   bash infra/aca/bootstrap.sh base        # RG, Log Analytics, środowisko Container Apps, ACR, Key Vault
#   bash infra/aca/bootstrap.sh data int    # Postgres Flexible + Redis dla INT (prod: data prod)
#   bash infra/aca/bootstrap.sh secrets int # sekrety aplikacji w Key Vault (bez nadpisywania istniejących)
#   bash infra/aca/bootstrap.sh github      # tożsamość OIDC dla GitHub Actions + role
#   bash infra/aca/bootstrap.sh apps int    # Container Apps (obraz startowy; CI podmienia obrazy)
#
# Idempotentny: istniejące zasoby są pomijane, istniejące sekrety nie są nadpisywane.
# Hasła generuje skrypt i zapisuje wyłącznie w Key Vault (nie wypisuje ich).
set -euo pipefail
export MSYS_NO_PATHCONV=1

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
PG_VERSION=15
PG_SKU=Standard_B1ms
# Region Postgresa i strefa — nadpisywalne, bo nowe subskrypcje PAYG dostają
# SkuNotAvailable w regionach/strefach z ograniczoną pojemnością.
PG_LOC="${GOVAI_PG_LOCATION:-$LOC}"
PG_ZONE="${GOVAI_PG_ZONE:-}"
PG_ADMIN=govaiadmin
DB_NAME=govai

# Globalny przełącznik --subscription musi stać PO nazwie komendy (az <grupa> <cmd> --subscription),
# więc zamiast doklejać go do każdego wywołania ustawiamy subskrypcję raz.
# UWAGA: zmienia domyślną subskrypcję az CLI. Obie subskrypcje (GovAI i CRMtree) nazywają się
# "Azure subscription 1" — przełączaj po ID/tenancie (az account list -o table), nie po nazwie.
az account set --subscription "$SUB"
AZ="az"

suffix() { [ "$1" = "prod" ] && echo "" || echo "-$1"; }   # prod → "", int → "-int"
log() { printf '\n== %s\n' "$*"; }
rand() { openssl rand -hex "${1:-24}"; }

kv_set_if_missing() {   # kv_set_if_missing <nazwa> <wartość>
  if $AZ keyvault secret show --vault-name "$KV" -n "$1" --query id -o tsv >/dev/null 2>&1; then
    echo "  sekret $1 — istnieje (bez zmian)"
  else
    $AZ keyvault secret set --vault-name "$KV" -n "$1" --value "$2" --output none
    echo "  sekret $1 — utworzony"
  fi
}
kv_get() { $AZ keyvault secret show --vault-name "$KV" -n "$1" --query value -o tsv; }

# ── base ─────────────────────────────────────────────────────────────────────
step_base() {
  log "Grupa zasobów $RG ($LOC)"
  $AZ group create -n "$RG" -l "$LOC" --output none

  log "Log Analytics $LOGS"
  $AZ monitor log-analytics workspace show -g "$RG" -n "$LOGS" --output none 2>/dev/null \
    || $AZ monitor log-analytics workspace create -g "$RG" -n "$LOGS" -l "$LOC" --retention-time 30 --output none
  local ws_id ws_key
  ws_id=$($AZ monitor log-analytics workspace show -g "$RG" -n "$LOGS" --query customerId -o tsv)
  ws_key=$($AZ monitor log-analytics workspace get-shared-keys -g "$RG" -n "$LOGS" --query primarySharedKey -o tsv)

  log "Środowisko Container Apps $ENV_NAME (Consumption)"
  $AZ containerapp env show -g "$RG" -n "$ENV_NAME" --output none 2>/dev/null \
    || $AZ containerapp env create -g "$RG" -n "$ENV_NAME" -l "$LOC" \
         --logs-workspace-id "$ws_id" --logs-workspace-key "$ws_key" --output none

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

# ── data <int|prod> ──────────────────────────────────────────────────────────
step_data() {
  local env="$1" sfx pg redis
  sfx=$(suffix "$env"); pg="govai-db$sfx"; redis="govai-redis$sfx"

  log "Postgres Flexible $pg (PG $PG_VERSION, $PG_SKU)"
  if ! $AZ postgres flexible-server show -g "$RG" -n "$pg" --output none 2>/dev/null; then
    local admin_pw; admin_pw=$(rand 24)
    kv_set_if_missing "db-admin-password$sfx" "$admin_pw"
    admin_pw=$(kv_get "db-admin-password$sfx")
    $AZ postgres flexible-server create -g "$RG" -n "$pg" -l "$PG_LOC" ${PG_ZONE:+--zone "$PG_ZONE"} \
      --version "$PG_VERSION" --tier Burstable --sku-name "$PG_SKU" --storage-size 32 \
      --admin-user "$PG_ADMIN" --admin-password "$admin_pw" \
      --public-access 0.0.0.0 --backup-retention "$([ "$env" = prod ] && echo 35 || echo 7)" \
      --yes --output none
  fi
  # TimescaleDB (dziennik audytowy = hypertable) + rozszerzenia z db/init.sql
  $AZ postgres flexible-server parameter set -g "$RG" -s "$pg" -n azure.extensions \
    --value "TIMESCALEDB,UUID-OSSP,PGCRYPTO" --output none
  local preload; preload=$($AZ postgres flexible-server parameter show -g "$RG" -s "$pg" -n shared_preload_libraries --query value -o tsv)
  if ! echo "$preload" | grep -qi timescaledb; then
    $AZ postgres flexible-server parameter set -g "$RG" -s "$pg" -n shared_preload_libraries \
      --value "${preload:+$preload,}timescaledb" --output none
    $AZ postgres flexible-server restart -g "$RG" -n "$pg" --output none
  fi
  $AZ postgres flexible-server db show -g "$RG" -s "$pg" -d "$DB_NAME" --output none 2>/dev/null \
    || $AZ postgres flexible-server db create -g "$RG" -s "$pg" -d "$DB_NAME" --output none

  log "Redis $redis (Azure Cache for Redis Basic C0, TLS) — tworzenie trwa ~15–20 min"
  $AZ redis show -g "$RG" -n "$redis" --output none 2>/dev/null \
    || $AZ redis create -g "$RG" -n "$redis" -l "$LOC" --sku Basic --vm-size c0 \
         --minimum-tls-version 1.2 --output none --no-wait
  echo "  (Redis tworzy się w tle; sekret redis-url$sfx zapisze krok 'secrets $env' po zakończeniu)"
}

# ── secrets <int|prod> ───────────────────────────────────────────────────────
step_secrets() {
  local env="$1" sfx pg redis host
  sfx=$(suffix "$env"); pg="govai-db$sfx"; redis="govai-redis$sfx"
  host=$($AZ postgres flexible-server show -g "$RG" -n "$pg" --query fullyQualifiedDomainName -o tsv)

  log "Sekrety aplikacji ($env) w $KV"
  kv_set_if_missing "jwt-secret$sfx" "$(rand 32)"
  kv_set_if_missing "provider-keys-secret$sfx" "$(rand 32)"
  kv_set_if_missing "db-app-password$sfx" "$(rand 24)"
  local admin_pw app_pw
  admin_pw=$(kv_get "db-admin-password$sfx")
  app_pw=$(kv_get "db-app-password$sfx")
  kv_set_if_missing "database-admin-url$sfx" "postgresql://$PG_ADMIN:$admin_pw@$host:5432/$DB_NAME?sslmode=require"
  kv_set_if_missing "database-url$sfx" "postgresql://govai_app:$app_pw@$host:5432/$DB_NAME?sslmode=require"

  local state; state=$($AZ redis show -g "$RG" -n "$redis" --query provisioningState -o tsv 2>/dev/null || echo missing)
  if [ "$state" = "Succeeded" ]; then
    local rkey rhost
    rkey=$($AZ redis list-keys -g "$RG" -n "$redis" --query primaryKey -o tsv)
    rhost=$($AZ redis show -g "$RG" -n "$redis" --query hostName -o tsv)
    kv_set_if_missing "redis-url$sfx" "rediss://:$rkey@$rhost:6380/0"
  else
    echo "  Redis $redis: $state — uruchom 'secrets $env' ponownie po zakończeniu tworzenia"
  fi
  # Klucze dostawców LLM — prawdziwe wartości wpisuje człowiek (od dostawcy / z poprzedniego
  # Key Vault). Do tego czasu wartość tymczasowa: referencja KV w Container App wymaga istniejącego
  # sekretu; aplikacja działa, tylko wywołania LLM zwracają błąd autoryzacji dostawcy.
  for s in anthropic-api-key deepseek-api-key; do
    if ! $AZ keyvault secret show --vault-name "$KV" -n "$s$sfx" --query id -o tsv >/dev/null 2>&1; then
      kv_set_if_missing "$s$sfx" "do-ustawienia"
      echo "  UWAGA: $s$sfx ma wartość tymczasową — ustaw prawdziwy klucz:"
      echo "         az keyvault secret set --subscription $SUB --vault-name $KV -n $s$sfx --value <klucz>"
    fi
  done
}

# ── github ───────────────────────────────────────────────────────────────────
step_github() {
  log "Tożsamość OIDC GitHub Actions $GH_ID"
  $AZ identity show -g "$RG" -n "$GH_ID" --output none 2>/dev/null \
    || $AZ identity create -g "$RG" -n "$GH_ID" -l "$LOC" --output none
  for e in int prod; do
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
  for pair in "Contributor|$rg_id" "AcrPush|$acr_id" "Key Vault Secrets User|$kv_id"; do
    $AZ role assignment create --assignee-object-id "$pid" --assignee-principal-type ServicePrincipal \
      --role "${pair%%|*}" --scope "${pair#*|}" --output none 2>/dev/null || true
  done
  echo "  Sekrety GitHub (środowiska int i prod): AZURE_CLIENT_ID=$($AZ identity show -g "$RG" -n "$GH_ID" --query clientId -o tsv)"
  echo "  AZURE_TENANT_ID=$(az account show --subscription "$SUB" --query tenantId -o tsv)  AZURE_SUBSCRIPTION_ID=$SUB"
}

# ── apps <int|prod> ──────────────────────────────────────────────────────────
# Tworzy 4 aplikacje z obrazem startowym (CI podmienia obrazy przy pierwszym deployu),
# system-assigned identity (AcrPull + Key Vault Secrets User), sekrety jako referencje KV.
step_apps() {
  local env="$1" sfx; sfx=$(suffix "$env")
  local acr_id kv_id kv_uri
  acr_id=$($AZ acr show -n "$ACR" --query id -o tsv)
  kv_id=$($AZ keyvault show -n "$KV" --query id -o tsv)
  kv_uri="https://$KV.vault.azure.net/secrets"
  local placeholder=mcr.microsoft.com/k8se/quickstart:latest
  local domain base_hosts
  if [ "$env" = prod ]; then domain=govai.pl; base_hosts="govai.pl www.govai.pl"; else domain=int.govai.pl; base_hosts="int.govai.pl"; fi

  create_app() {   # create_app <nazwa> <port> <external|internal> <min> <max>
    local name="$1" port="$2" ingress="$3" min="$4" max="$5"
    if $AZ containerapp show -g "$RG" -n "$name" --output none 2>/dev/null; then
      echo "  $name — istnieje"; allow_http "$name" "$ingress"; return
    fi
    $AZ containerapp create -g "$RG" -n "$name" --environment "$ENV_NAME" --image "$placeholder" \
      --target-port "$port" --ingress "$ingress" --min-replicas "$min" --max-replicas "$max" \
      --cpu 0.5 --memory 1.0Gi --system-assigned --output none
    local pid; pid=$($AZ containerapp show -g "$RG" -n "$name" --query identity.principalId -o tsv)
    $AZ role assignment create --assignee-object-id "$pid" --assignee-principal-type ServicePrincipal \
      --role AcrPull --scope "$acr_id" --output none 2>/dev/null || true
    $AZ role assignment create --assignee-object-id "$pid" --assignee-principal-type ServicePrincipal \
      --role "Key Vault Secrets User" --scope "$kv_id" --output none 2>/dev/null || true
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

  log "Container Apps ($env)"
  create_app "govai-api$sfx"      8000 internal 1 3
  create_app "govai-gateway$sfx"  8001 internal 1 3
  create_app "govai-frontend$sfx" 3000 internal "$([ "$env" = prod ] && echo 1 || echo 0)" 3
  create_app "govai-edge$sfx"     80   external 1 3

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
  echo "  Adres techniczny edge: https://$($AZ containerapp show -g "$RG" -n "govai-edge$sfx" --query properties.configuration.ingress.fqdn -o tsv)"
}

case "${1:-}" in
  base)    step_base ;;
  data)    step_data "${2:?int|prod}" ;;
  secrets) step_secrets "${2:?int|prod}" ;;
  github)  step_github ;;
  apps)    step_apps "${2:?int|prod}" ;;
  *) sed -n '2,12p' "$0"; exit 2 ;;
esac

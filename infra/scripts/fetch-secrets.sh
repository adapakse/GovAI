#!/bin/sh
# Uruchamiany NA VM (nie w kontenerze), tuż przed `docker compose up` —
# docker-compose.yml składa DATABASE_URL z ${DB_PASSWORD} w momencie `up`,
# więc sekrety muszą trafić do .env na hoście przed startem stosu, nie do
# env kontenera po jego starcie (patrz plan Faza 1 / Etap 3).
set -e

AZURE_ENV_FILE=/opt/govai-azure.env
TARGET_ENV_FILE=/opt/govai/.env

if ! command -v jq >/dev/null 2>&1; then
  echo "jq nieobecne — instaluję..." >&2
  sudo apt-get update -qq && sudo apt-get install -y -qq jq
fi

if [ ! -f "$AZURE_ENV_FILE" ]; then
  echo "Brak $AZURE_ENV_FILE — ta VM nie ma skonfigurowanego backendu Azure Key Vault (SECRETS_BACKEND=azure-keyvault)." >&2
  exit 1
fi

# shellcheck disable=SC1090
. "$AZURE_ENV_FILE"

if [ -z "$AZURE_CLIENT_ID" ] || [ -z "$AZURE_KEY_VAULT_NAME" ]; then
  echo "AZURE_CLIENT_ID / AZURE_KEY_VAULT_NAME nieustawione w $AZURE_ENV_FILE" >&2
  exit 1
fi

token_response=$(curl -sf -H "Metadata: true" \
  "http://169.254.169.254/metadata/identity/oauth2/token?api-version=2018-02-01&resource=https%3A%2F%2Fvault.azure.net&client_id=${AZURE_CLIENT_ID}")
token=$(printf '%s' "$token_response" | jq -r '.access_token')

if [ -z "$token" ] || [ "$token" = "null" ]; then
  echo "Nie udało się pobrać tokenu IMDS dla tożsamości ${AZURE_CLIENT_ID}" >&2
  exit 1
fi

get_secret() {
  name="$1"
  curl -sf -H "Authorization: Bearer ${token}" \
    "https://${AZURE_KEY_VAULT_NAME}.vault.azure.net/secrets/${name}?api-version=7.4" \
    | jq -r '.value'
}

jwt_secret=$(get_secret jwt-secret)
db_password=$(get_secret db-password)
anthropic_api_key=$(get_secret anthropic-api-key)
deepseek_api_key=$(get_secret deepseek-api-key)
# Opcjonalny: token API Cloudflare (strefa DNS domeny) — włącza subdomeny
# organizacji {slug}.<DOMAIN_NAME> (certyfikat wildcard przez ACME DNS-01,
# caddy/Caddyfile.tenants.template). Brak sekretu = bez subdomen.
cloudflare_api_token=$(get_secret cloudflare-api-token 2>/dev/null || true)
[ "$cloudflare_api_token" = "null" ] && cloudflare_api_token=""

# Z DOMAIN_NAME (z $AZURE_ENV_FILE) — bez tego api korzysta z domyślnego
# ALLOWED_ORIGINS=https://localhost i blokuje przeglądarkę na app.<domena>
# ("Disallowed CORS origin", logowanie nie działa mimo poprawnego JWT/CORS
# lokalnie).
allowed_origins=""
if [ -n "$DOMAIN_NAME" ]; then
  allowed_origins="https://app.${DOMAIN_NAME}"
fi

mkdir -p "$(dirname "$TARGET_ENV_FILE")"
{
  echo "# Wygenerowane automatycznie przez infra/scripts/fetch-secrets.sh — NIE edytuj ręcznie."
  echo "JWT_SECRET=${jwt_secret}"
  echo "DB_PASSWORD=${db_password}"
  # Klucz szyfrowania własnych kluczy LLM organizacji (providers.api_key_encrypted) — wyliczany z JWT_SECRET.
  echo "PROVIDER_KEYS_SECRET=$(printf '%s' "${jwt_secret}:provider-keys" | sha256sum | cut -c1-64)"
  # Rola aplikacji govai_app (RLS) — hasło wyliczane z DB_PASSWORD, bez osobnego sekretu w Key Vault.
  echo "DB_APP_PASSWORD=$(printf '%s' "${db_password}:govai_app" | sha256sum | cut -c1-48)"
  echo "ANTHROPIC_API_KEY=${anthropic_api_key}"
  echo "DEEPSEEK_API_KEY=${deepseek_api_key}"
  [ -n "$allowed_origins" ] && echo "ALLOWED_ORIGINS=${allowed_origins}"
  if [ -n "$cloudflare_api_token" ] && [ -n "$DOMAIN_NAME" ]; then
    echo "CLOUDFLARE_API_TOKEN=${cloudflare_api_token}"
    echo "TENANT_BASE_DOMAINS=${DOMAIN_NAME}"
  fi
  grep -v '^AZURE_CLIENT_ID=\|^AZURE_KEY_VAULT_NAME=\|^SECRETS_BACKEND=' "$AZURE_ENV_FILE" || true
} > "$TARGET_ENV_FILE"

chmod 600 "$TARGET_ENV_FILE"
echo "Zapisano $TARGET_ENV_FILE"

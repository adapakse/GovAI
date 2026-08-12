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

mkdir -p "$(dirname "$TARGET_ENV_FILE")"
{
  echo "# Wygenerowane automatycznie przez infra/scripts/fetch-secrets.sh — NIE edytuj ręcznie."
  echo "JWT_SECRET=${jwt_secret}"
  echo "DB_PASSWORD=${db_password}"
  echo "ANTHROPIC_API_KEY=${anthropic_api_key}"
  echo "DEEPSEEK_API_KEY=${deepseek_api_key}"
  grep -v '^AZURE_CLIENT_ID=\|^AZURE_KEY_VAULT_NAME=\|^SECRETS_BACKEND=' "$AZURE_ENV_FILE" || true
} > "$TARGET_ENV_FILE"

chmod 600 "$TARGET_ENV_FILE"
echo "Zapisano $TARGET_ENV_FILE"

#!/usr/bin/env bash
# Testy izolacji organizacji (multitenancy) — uruchamiane w jednorazowym
# kontenerze w sieci docker compose (API http://api:8000, gateway http://gateway:8001,
# Postgres postgres:5432). Wymaga działającego stosu: docker compose up -d.
#
# Użycie (z dowolnego katalogu, Git Bash / Linux):
#   sh tests/isolation/run.sh                 # wszystkie testy
#   sh tests/isolation/run.sh -k gateway -x   # dodatkowe argumenty → pytest
set -eu

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
ENV_FILE="$REPO_DIR/.env"

env_value() {
    # Wartość zmiennej z .env (bez cudzysłowów i CR z plików CRLF)
    grep -E "^$1=" "$ENV_FILE" | tail -n 1 | cut -d= -f2- | tr -d '\r' | sed -e 's/^"//' -e 's/"$//' -e "s/^'//" -e "s/'$//"
}

DB_PASSWORD="$(env_value DB_PASSWORD)"
DB_APP_PASSWORD="$(env_value DB_APP_PASSWORD)"
if [ -z "$DB_PASSWORD" ] || [ -z "$DB_APP_PASSWORD" ]; then
    echo "Brak DB_PASSWORD / DB_APP_PASSWORD w $ENV_FILE" >&2
    exit 2
fi

API_CONTAINER="${API_CONTAINER:-govai-api-1}"
# Sieć, w której działa kontener API (np. govai_default)
NETWORK="${GOVAI_NETWORK:-$(docker inspect -f '{{range $k, $v := .NetworkSettings.Networks}}{{$k}} {{end}}' "$API_CONTAINER" | awk '{print $1}')}"
if [ -z "$NETWORK" ]; then
    echo "Nie znaleziono sieci kontenera $API_CONTAINER — czy stos działa?" >&2
    exit 2
fi
# Test subdomen ma sens tylko, gdy API ma skonfigurowane domeny organizacji
TENANT_BASE_DOMAINS="$(docker exec "$API_CONTAINER" printenv TENANT_BASE_DOMAINS 2>/dev/null || true)"

# Ścieżka hosta do katalogu tests (Git Bash: /c/dev/... → C:/dev/...)
TESTS_DIR="$REPO_DIR/tests"
if command -v cygpath >/dev/null 2>&1; then
    TESTS_DIR="$(cygpath -m "$TESTS_DIR")"
fi

echo "Sieć: $NETWORK; TENANT_BASE_DOMAINS='${TENANT_BASE_DOMAINS}'"

MSYS_NO_PATHCONV=1 docker run --rm \
    --network "$NETWORK" \
    -v "$TESTS_DIR:/tests" \
    -v govai-isolation-pip-cache:/root/.cache/pip \
    -e GOVAI_DB_PASSWORD="$DB_PASSWORD" \
    -e GOVAI_DB_APP_PASSWORD="$DB_APP_PASSWORD" \
    -e TENANT_BASE_DOMAINS="$TENANT_BASE_DOMAINS" \
    -e PYTHONDONTWRITEBYTECODE=1 \
    python:3.12-slim sh -c \
    "pip install -q --root-user-action=ignore --disable-pip-version-check pytest pytest-asyncio httpx asyncpg bcrypt websockets \
     && cd /tests/isolation && pytest -q -p no:cacheprovider $*"

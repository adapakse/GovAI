#!/bin/sh
# Uruchamiany NA VM przez `az vm run-command` z .github/workflows/deploy.yml.
# Zakłada, że repo w /opt/govai jest już na właściwym branchu (checkout robi
# wywołujący, przed odpaleniem tego skryptu).
set -e
cd /opt/govai

./infra/scripts/fetch-secrets.sh

# Postgres musi działać przed aplikacją migracji.
docker compose up -d postgres
timeout 60 sh -c 'until docker compose exec -T postgres pg_isready -U govai -d govai; do sleep 1; done'

for f in db/migrations/*.sql; do
  name=$(basename "$f")
  echo "Migracja: $name"
  docker cp "$f" "$(docker compose ps -q postgres):/tmp/${name}"
  docker compose exec -T postgres psql -U govai -d govai -f "/tmp/${name}"
done

docker compose up -d --build

# GovAI — obraz migracji bazy (Container Apps Job govai-migrate / govai-migrate-int).
# Uruchamia infra/scripts/migrate.sh w trybie zdalnym (DATABASE_ADMIN_URL, DB_APP_PASSWORD z Key Vault)
# — runner GitHub nie ma dostępu do prywatnej bazy na VM w VNet.
# Build z katalogu repo: docker build -f infra/migrate/Dockerfile -t govai-migrate .
FROM alpine:3.22

RUN apk add --no-cache postgresql16-client

WORKDIR /app
COPY db/init.sql db/init.sql
COPY db/migrations/ db/migrations/
COPY infra/scripts/migrate.sh infra/scripts/migrate.sh

USER nobody
CMD ["sh", "infra/scripts/migrate.sh"]

# GovAI — kontener backupu baz (Azure VM vm-govai-data albo on-prem).
# Klient PostgreSQL 16 = wersja serwera (pg_dump/pg_restore muszą być >= wersji serwera).
FROM alpine:3.22

RUN apk add --no-cache bash postgresql16-client curl jq tzdata coreutils findutils

COPY govai-backup.sh /usr/local/bin/govai-backup
RUN chmod 0755 /usr/local/bin/govai-backup \
    && mkdir -p /var/lib/govai-backup /work /backups

ENV TZ=Europe/Warsaw \
    BACKUP_TIME=02:30 \
    BACKUP_TARGET=local \
    BACKUP_LOCAL_DIR=/backups \
    BACKUP_RETENTION_DAYS=7

ENTRYPOINT ["/usr/local/bin/govai-backup"]
CMD ["schedule"]

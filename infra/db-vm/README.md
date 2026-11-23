# VM danych GovAI — Postgres + TimescaleDB, Redis, backup

Usługi danych dla **PROD i INT** na jednej VM w prywatnym VNet (Azure: `vm-govai-data`, `10.50.2.10`)
albo na serwerze on-prem. Decyzja 2026-11-17: Azure Database for PostgreSQL Flexible jest dla subskrypcji
GovAI niedostępny (Burstable w Poland Central bez wolnej mocy, inne regiony UE zablokowane), więc bazy
działają w kontenerach — tym samym obrazem co lokalny `docker-compose.yml`. Kontekst: `docs/azure-environments-plan.md` §4.

| Kontener | Obraz | Port (tylko IP prywatny VM) | Dane | Pamięć |
|---|---|---|---|---|
| `govai-pg-prod` | `timescale/timescaledb:2.31.0-pg16` | 5432 | `/data/pg-prod` | 3 GB |
| `govai-pg-int` | j.w. | 5433 | `/data/pg-int` | 1,5 GB |
| `govai-redis-prod` | `redis:7.4-alpine` | 6379 | — (bez trwałości, tylko pub/sub) | 256 MB |
| `govai-redis-int` | j.w. | 6380 | — | 256 MB |
| `govai-backup` | `govai-backup` (`backup/`) | — | `/data/backup-state`, `/data/backup-work` | 512 MB |

Na Azure obrazy są w `govaicr` (import z Docker Hub w `bootstrap.sh datavm`, `govai-backup:prod` z deployu PROD;
gdy go brak, compose buduje go lokalnie z `backup/`). Limity pamięci (VM B2ms = 8 GB) zmienia się zmiennymi
`PG_PROD_MEM_LIMIT`, `PG_INT_MEM_LIMIT` (+ `PG_*_TUNE_MEMORY` — działa tylko przy inicjalizacji klastra).

## Pliki

| Plik | Rola |
|---|---|
| `docker-compose.yml` | usługi (projekt `govai-data`); konfiguracja przez plik env |
| `initdb/10-hba.sh` | przy inicjalizacji klastra: połączenia sieciowe tylko po TLS (`hostssl`) |
| `govai-data.sh` | VM: `boot` (Key Vault → `/etc/govai/data.env`, certyfikaty TLS, logowanie do ACR, start), `int-start`, `int-stop`, `status` |
| `install.sh` | VM: Docker, dysk danych `/data`, unattended-upgrades, systemd `govai-data.service` |
| `restore.sh` | odtworzenie bazy (wrapper na `govai-backup restore` w kontenerze) |
| `backup/` | obraz backupu: `govai-backup schedule|run|check|fetch|restore` |
| `vm-run.sh` | z laptopa / CI: skrypt na VM przez `az vm run-command` (sukces = `GOVAI_RESULT=OK`) |

## Azure

### Zakładanie (raz)
```sh
export AZURE_CONFIG_DIR=C:/Users/apt/.azure-govai     # konto GovAI, nigdy wspólne ~/.azure
bash infra/aca/bootstrap.sh base
bash infra/aca/bootstrap.sh network        # VNet 10.50.0.0/16, snet-aca /23, snet-data /27, NSG, govai-env w VNet
bash infra/aca/bootstrap.sh backup         # konto Storage stgovaibkp<6 znaków>, kontener backups, retencja 7 dni
bash infra/aca/bootstrap.sh secrets prod   # i: secrets int
bash infra/aca/bootstrap.sh datavm         # obrazy → IP publiczny/NIC → VM (cloud-init) → role → start usług
```
Pliki trafiają na VM jako pakiet tar.gz (ten katalog + `vm.env` bez sekretów): przy tworzeniu przez
cloud-init (`write_files`), później przez `az vm run-command` przy każdym `bootstrap.sh datavm`. VM nie
pobiera nic z GitHuba; hasła pobiera sama z Key Vault (managed identity, IMDS) — nigdy nie ma ich
w custom data. Kolejne uruchomienie `datavm` = aktualizacja plików + restart `govai-data.service`
(`docker compose up -d` — kontenery bez zmian nie są restartowane).

### Sieć i bezpieczeństwo
- Postgres/Redis nasłuchują tylko na `10.50.2.10`. NSG `nsg-govai-data`: 5432/5433/6379/6380 wyłącznie
  z `snet-aca` (10.50.0.0/23), reszta ruchu przychodzącego zablokowana (`deny-all-inbound`, także z VNet).
- Brak SSH z internetu. Administracja: `bash infra/db-vm/vm-run.sh '<polecenia>'`. Bastion Developer wymaga
  czasowej reguły NSG (22 z `168.63.129.16`) i klucza: `az vm user update -u govaiadmin --ssh-key-value ...`
  (klucz z bootstrapu jest jednorazowy i usunięty).
- IP publiczny `pip-govai-data` (Standard) służy **tylko do ruchu wychodzącego** (apt, Docker Hub/ACR,
  Key Vault): Azure wygasza „default outbound access” dla nowych podsieci, a NAT Gateway kosztuje więcej
  niż IP. Standard IP jest domyślnie zamknięty — bez reguł NSG nic nie wejdzie.
- Konto Storage: dostęp tylko z `snet-data` (service endpoint) + zaufane usługi Azure, bez kluczy
  współdzielonych (tylko Entra ID — rola Storage Blob Data Contributor dla tożsamości VM).
- TLS Postgresa: certyfikat samopodpisany (`/data/ssl/<env>`, generuje `govai-data.sh`), aplikacje
  `sslmode=require` (szyfrowanie bez weryfikacji CA — ruch i tak w prywatnym VNet).
- Superużytkownik `govai` (hasło `db-admin-password[-int]`) — tylko migracje (job `govai-migrate[-int]`) i backup.
  Aplikacje: rola `govai_app` (RLS), hasło `db-app-password[-int]` ustawia migracja przy każdym deployu.

### Codzienna obsługa
```sh
bash infra/db-vm/vm-run.sh 'bash /opt/govai-data/govai-data.sh status'
bash infra/db-vm/vm-run.sh 'journalctl -u govai-data -n 50 --no-pager; echo GOVAI_RESULT=OK'
bash infra/db-vm/vm-run.sh 'docker logs --tail 50 govai-backup; echo GOVAI_RESULT=OK'
bash infra/db-vm/vm-run.sh 'systemctl restart govai-data && echo GOVAI_RESULT=OK'   # nowe hasła z KV / nowy obraz backupu
```
- **INT tylko w godzinach pracy** (pn–pt 09–18 Europe/Warsaw): `.github/workflows/int-schedule.yml`
  (backup INT → stop `pg-int`/`redis-int`, aplikacje `-int` z min. replik 0; rano odwrotnie). Deploy INT poza
  godzinami sam uruchamia i zatrzymuje bazy. Po restarcie VM `boot` uruchamia INT tylko w godzinach pracy.
- **Rotacja haseł:** hasło superużytkownika i Redisa w kontenerze pochodzi z pliku env; Postgres czyta je
  tylko przy inicjalizacji klastra. Zmiana: nowy sekret w KV → `ALTER ROLE govai PASSWORD ...` w kontenerze
  → `systemctl restart govai-data` → aktualizacja `database-admin-url[-int]`. `govai_app`: nowy
  `db-app-password` + `database-url` w KV, deploy (migracja ustawi hasło), restart aplikacji.
- **Aktualizacja jądra:** unattended-upgrades instaluje poprawki bez restartu; restart VM planować poza
  godzinami pracy (`az vm restart`) — po starcie `govai-data.service` podnosi usługi sama.
- **Wersja TimescaleDB:** podbicie tagu obrazu (compose + `PG_IMAGE_TAG` w bootstrapie) wymaga po starcie
  `ALTER EXTENSION timescaledb UPDATE;` w każdej bazie. Backup odtwarza się tylko na tej samej wersji
  rozszerzenia (restore to sprawdza) — obraz zawiera też starsze wersje.

## Backup

**Logiczny (główny):** kontener `govai-backup`, codziennie o **02:30 Europe/Warsaw** (`BACKUP_TIME`, `TZ`),
prosty harmonogram w pętli — po niedostępności (VM wyłączona o 02:30) nadrabia przy starcie, po błędzie
ponawia co 60 min. Dla każdej bazy z `BACKUP_SOURCES`:
- `pg_dump -Fc` bazy `govai` i liczności kluczowych tabel z **tej samej migawki** (`pg_export_snapshot`)
  — porównanie po odtworzeniu jest dokładne;
- `pg_dumpall --globals-only --no-role-passwords` (role bez haseł — hasła są w Key Vault/pliku env);
- metadane JSON: czas, wersja PG i TimescaleDB, sumy sha256, liczności (`tenants`, `users`, `agents`,
  `policies`, `oversight_queue`, `audit_log`, `providers`, `api_keys`, …), `schema_migrations_max`.

PROD jest wymagany (błąd = kod ≠ 0 i ponowienie); INT pomijany z wpisem w logu, gdy nie działa — backup INT
robi `int-stop` przed wieczornym zatrzymaniem.

Układ (Azure: konto `stgovaibkp*`, kontener `backups`; on-prem: katalog):
```
prod/2026/11/17/govai-20261117T013000Z.dump | .globals.sql | .json
prod/latest.json          ← kopia metadanych najnowszego backupu (zapisywana na końcu)
int/...
```
Cele (`BACKUP_TARGET`): `azure-blob` (REST + token managed identity z IMDS; pojedynczy Put Blob — do 5000 MiB
na plik), `local` (`BACKUP_LOCAL_DIR`, retencja `BACKUP_RETENTION_DAYS` przez usuwanie starych plików),
`s3` (szkic: wymaga dodania `aws-cli` do obrazu i `BACKUP_S3_URI`; retencja przez lifecycle bucketu).

**Retencja 7 dni:** Azure — lifecycle management konta (usuwa bloby `prod/`, `int/` starsze niż 7 dni,
zadanie Azure działa raz dziennie, więc faktycznie 7–8 dni); local — w kontenerze po każdym backupie.

**Snapshot VM:** świadomie bez Azure Backup VM (decyzja 2026-11-22, koszt) — VM jest odtwarzalna skryptem
(`bootstrap.sh datavm`), a dane z backupu logicznego.

**Monitoring:** `.github/workflows/backup-check.yml` (codziennie ~08:00: PROD < 26 h, INT wt–pt < 26 h,
pn < 74 h) i `restore-test.yml` (niedziela: odtworzenie najnowszego PROD do `govai_restore_test`, porównanie,
usunięcie). Oba po włączeniu zmiennej repo `DATAVM_ENABLED=true`; nieudany run = mail z GitHub Actions.

**RPO 24 h** (backup dobowy). **RTO ~30 min** dla bazy (odtworzenie z backupu logicznego), **~1 h** przy utracie
VM (nowa VM z `bootstrap.sh datavm` + restore).

## Odtwarzanie (runbook)

`restore.sh` uruchamia się **na VM** (przez `vm-run.sh`) albo na serwerze on-prem:
```
restore.sh <int|prod> [latest|<ścieżka.dump>] [--from <env>] [--test] [--yes]
```
Kroki: pobranie dump + globals + metadanych → weryfikacja sha256 → kontrola wersji TimescaleDB → nowa baza
tymczasowa → role (`already exists` ignorowane) → `timescaledb_pre_restore()` → `pg_restore` →
`timescaledb_post_restore()` → porównanie liczności z metadanymi → (bez `--test`) hasło `govai_app` z pliku
env środowiska docelowego, podmiana `govai` ↔ baza tymczasowa (stara zostaje jako `govai_pre_restore_<ts>`).
Przy niezgodności liczności baza `govai` nie jest ruszana.

1. **Błąd logiczny / uszkodzenie bazy PROD**
   ```sh
   bash infra/db-vm/vm-run.sh 'bash /opt/govai-data/restore.sh prod latest --test'   # najpierw próba
   # (opcjonalnie) wyłączenie rewizji api/gateway — komendy wypisuje restore.sh
   bash infra/db-vm/vm-run.sh 'bash /opt/govai-data/restore.sh prod latest --yes'
   # konkretny backup: ... restore.sh prod prod/2026/11/16/govai-20261116T013000Z.dump --yes
   ```
   Po sprawdzeniu aplikacji: `DROP DATABASE govai_pre_restore_<ts>;` (`docker exec govai-pg-prod psql -U govai -d postgres`).
   `vm-run.sh` pokazuje tylko ostatnie ~4 KB wyjścia — przy problemach uruchom `restore.sh` przez Bastion.
2. **Utrata VM / dysku:** usuń VM
   i uruchom `bootstrap.sh datavm` (pusty dysk, nowe klastry z haseł w KV), potem dla każdego środowiska
   `restore.sh <env> latest --yes` i deploy (migracje ustawią hasło `govai_app`).
3. **Kopia PROD → INT** (`restore.sh int latest --from prod --yes`) — technicznie działa (hasło `govai_app`
   z pliku INT), ale **dane klientów na INT tylko po decyzji Adama** (incydent CRMtree 2026-10-23: maile z INT
   do prawdziwych osób).

## On-prem / instancja dedykowana

Ten sam compose bez Azure (polecenia z katalogu `infra/db-vm` — ścieżka `./initdb`): plik env (np. `/etc/govai/data.env`, `chmod 600`):
```
DATA_DIR=/srv/govai-data
DATA_BIND_IP=10.0.0.5            # IP serwera w sieci aplikacji
PG_SSL=on
BACKUP_IMAGE=govai-backup:local
BACKUP_TARGET=local
BACKUP_LOCAL_DIR=/srv/govai-backups   # najlepiej osobny dysk / zasób sieciowy
BACKUP_SOURCES=prod=pg-prod:5432
DB_ADMIN_PASSWORD_PROD=<hasło>
DB_APP_PASSWORD_PROD=<hasło govai_app>
REDIS_PASSWORD_PROD=<hasło>
```
```sh
mkdir -p /srv/govai-data/ssl/prod && openssl req -x509 -newkey rsa:2048 -nodes -days 3650 -subj /CN=govai-pg \
  -keyout /srv/govai-data/ssl/prod/server.key -out /srv/govai-data/ssl/prod/server.crt \
  && chown 70:70 /srv/govai-data/ssl/prod/* && chmod 600 /srv/govai-data/ssl/prod/server.key
docker compose --env-file /etc/govai/data.env build backup
docker compose --env-file /etc/govai/data.env up -d pg-prod redis-prod backup
# migracje: obraz infra/migrate (DATABASE_ADMIN_URL=postgresql://govai:...@<IP>:5432/govai?sslmode=require)
docker exec govai-backup govai-backup run            # backup na żądanie
bash restore.sh prod latest --test                   # test odtworzenia
```
Istniejąca instalacja z głównego `docker-compose.yml` (usługa `postgres`, użytkownik `govai`): sam kontener
backupu działa z `BACKUP_SOURCES=prod=postgres:5432` w sieci tego projektu.

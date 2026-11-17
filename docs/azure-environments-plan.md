# GovAI — środowiska i infrastruktura Azure (plan docelowy)

Status: plan (2026-11-04), w realizacji; bazy i Redis na VM zamiast Azure PG Flexible / Azure Cache for Redis
— decyzja 2026-11-17 (§4). Wzorzec: **CRMtree** (ta sama subskrypcja Azure,
`rg-crmtree-prod`) — te same usługi i konwencje, z poprawkami tam, gdzie CRMtree ma znane słabości
(oznaczone **[poprawka względem CRMtree]**).

## 1. Środowiska

| Środowisko | Gałąź | Gdzie | Adresy | Deploy |
|---|---|---|---|---|
| **Lokalne** | dowolna | Docker Compose na laptopie | `https://localhost:8443`, subdomeny `<slug>.localhost:8443` | ręcznie (`ENVIRONMENTS.md`) |
| **INT** | `develop` | Azure Container Apps, aplikacje z sufiksem `-int` | `app.int.govai.pl`, `<slug>.int.govai.pl`, landing `int.govai.pl` | automatycznie po push do `develop` |
| **PROD** | `master` | Azure Container Apps | `govai.pl` (landing), `app.govai.pl`, `<slug>.govai.pl` (np. `gessel.govai.pl`) | automatycznie po push do `master` (GitHub Environment `prod` z zatwierdzeniem) |

Przepływ (jak CRMtree): `feature/*` → PR → `develop` → test na INT → PR `develop` → `master` → PROD.
Bezpośrednio na `master` tylko hotfix produkcyjny.

**Gałąź PROD = `master`** (decyzja Adama, jak CRMtree). Zmiana nazwy `main` → `master` zrobiona 2026-11-07
(gałąź domyślna w GitHub; lokalnie: `git branch -m main master && git fetch origin && git branch -u origin/master master`).

### Stan obecny (do wygaszenia po migracji)
INT działa dziś na **VM** (`rg-govai-int`: `vm-govai-int` 74.248.18.114, `kv-govai-int`, Bicep `infra/`,
deploy `deploy.yml` → `az vm run-command` → `deploy-remote.sh` → docker compose z Caddy) i **obsługuje publiczne
`govai.pl` / `app.govai.pl`**. Model VM zostaje w repo jako wzorzec **instancji dedykowanej** (klient na własnym
Azure / on-prem), ale INT i PROD przechodzą na Container Apps.

## 2. Zasoby Azure (wzór CRMtree)

Subskrypcja: „Azure subscription 1” (`e9d1538e-d592-4dd8-afcb-6571c6af15bf`), tenant `8fc0088b-…`,
region **polandcentral**. Zawsze `az … --subscription "Azure subscription 1"` (na laptopie Adama domyślna jest inna).

| Zasób | Nazwa | Konfiguracja (CRMtree → GovAI) |
|---|---|---|
| Resource group | `rg-govai-prod` | jedna grupa dla PROD i INT (jak `rg-crmtree-prod`); INT rozróżniane sufiksem `-int` |
| Log Analytics | `govai-logs` | PerGB2018, retencja 30 dni |
| Container Apps Environment | `govai-env` | workload profiles (profil Consumption) **w VNet** `vnet-govai` / `snet-aca` (10.50.0.0/23), ingress zewnętrzny dozwolony (`govai-edge`). **[zmiana 2026-11-17]** — wcześniej bez VNet jak `crmtree-env`; VNet potrzebny do prywatnej VM baz (§4) |
| VNet | `vnet-govai` 10.50.0.0/16 | `snet-aca` 10.50.0.0/23 (delegacja `Microsoft.App/environments`), `snet-data` 10.50.2.0/27 (VM baz, NSG `nsg-govai-data`, service endpoint `Microsoft.Storage`) |
| Container Registry | `govairegistry` | Basic. **[poprawka]** pull przez managed identity (rola AcrPull), bez admin usera |
| Key Vault | `kv-govai` | tryb RBAC; aplikacje czytają sekrety referencjami KV przez system-assigned identity (jak CRMtree). **[poprawka]** osobne nazwy sekretów per środowisko (`*-int`) — w CRMtree INT dzieli sekrety z PROD |
| VM danych | `vm-govai-data` (10.50.2.10) | **[zmiana 2026-11-17]** zamiast Azure PostgreSQL Flexible i Azure Cache for Redis: Standard_B2ms (zapas: Standard_D2s_v3), Ubuntu 24.04, dysk danych 64 GB Premium SSD; w kontenerach Postgres 16 + TimescaleDB i Redis 7 osobno dla PROD (5432/6379) i INT (5433/6380) + kontener backupu — §4, `infra/db-vm/README.md` |
| Storage | `stgovaibkp<6 znaków>` | backupy baz (kontener `backups`, ZRS, retencja 7 dni przez lifecycle), dostęp tylko z `snet-data`, bez kluczy współdzielonych. GovAI nie przechowuje innych plików; raporty PDF generowane w locie |
| Recovery Services | `rsv-govai` | Azure Backup VM danych (polityka `pol-govai-data-daily`, codziennie, 7 dni) |

Kontenery (Container Apps, Single revision mode, jak CRMtree):

| Aplikacja | Obraz | Ingress | Repliki | Uwagi |
|---|---|---|---|---|
| `govai-edge` / `-int` | `govairegistry.azurecr.io/govai-edge` (Caddy, HTTP) | **zewnętrzny**, port 80, domeny niestandardowe | 1–3 | routing hostów i ścieżek + statyczny landing (`website/`) — patrz §3 |
| `govai-frontend` / `-int` | `govai-frontend` (Next.js standalone) | wewnętrzny, 3000 | 1–5 (INT 0–3) | adresy względne `/api`, `/gateway` (już w kodzie) |
| `govai-api` / `-int` | `govai-api` (FastAPI) | wewnętrzny, 8000 | 1–5 | probe HTTP `/health`; WebSocket `/ws/live-feed` |
| `govai-gateway` / `-int` | `govai-gateway` (FastAPI + spaCy) | wewnętrzny, 8001 | 1–5 | probe HTTP `/health`; ~1 GiB RAM (modele spaCy) |

Ollama/Bielik (model lokalny) — **nie** w chmurze w pierwszej wersji (provider „Bielik On-Prem” pozostaje nieaktywny);
dotyczy instancji dedykowanych / on-prem z GPU.

## 3. Ruch, domeny i certyfikaty

### Routing (`govai-edge`)
Container Apps ingress nie routuje po ścieżkach, a GovAI potrzebuje na jednym hoście: `/` → frontend,
`/api/*` → api (z WebSocket), `/gateway/*` → gateway. Dlatego (zamiast proxy w aplikacji frontendowej jak w CRMtree)
mały kontener **Caddy w trybie HTTP** (`govai-edge`), który:
- `govai.pl`, `www.govai.pl` → statyczny `website/` (zamiast VM; alternatywa jak CRMtree: Cloudflare Worker z assets),
- `app.<domena>` i `*.<domena>` → `handle_path /api/*` → `govai-api`, `/gateway/*` → `govai-gateway`, reszta → `govai-frontend`,
- do aplikacji wewnętrznych wysyła `Host` = ich wewnętrzny FQDN (`header_up Host {upstream_hostport}` — wymóg
  routingu wewnętrznego Container Apps) i **oryginalny host w `X-Forwarded-Host`**.

**Zmiana w kodzie (do zrobienia):** rozpoznawanie organizacji z subdomeny (`api/services/tenant_host.py`,
logowanie, `GET /public/tenant`, blokada subdomeny w `dependencies/auth.py`, gateway) musi czytać `X-Forwarded-Host`,
gdy żądanie przyszło od `govai-edge` (api/gateway mają ingress wyłącznie wewnętrzny, więc nagłówek można ufać;
lokalnie i na VM — `Host`). To samo zrobił CRMtree (`x-crm-tenant-host`), bo proxy podmienia `Host`.

Szablon `caddy/Caddyfile.edge` (do utworzenia) — na wzór `caddy/Caddyfile.domain.template`, ale `:80`, bez TLS,
z upstreamami z env (`API_UPSTREAM`, `GATEWAY_UPSTREAM`, `FRONTEND_UPSTREAM`).
Timeouty proxy: wywołania LLM (raporty, bramka) bywają długie — w CRMtree podniesiono timeout proxy do 600 s.

### DNS: Cloudflare
Strefa `govai.pl` przenoszona z home.pl do Cloudflare (decyzja podjęta; zmiana NS — Adam). Rekordy pocztowe Zoho
(MX `mx/mx2/mx3.zoho.eu`, SPF `include:zohomail.eu`, `zoho-verification`, DKIM `zmail._domainkey`) muszą zostać
przeniesione bez zmian. Rekordy aplikacji: `@`, `www`, `app`, `*`, `int`, `app.int`, `*.int` → CNAME/A na
`govai-edge` / `govai-edge-int` (+ rekordy TXT `asuid.*` do weryfikacji domen w Container Apps).

### Certyfikaty — **[poprawka względem CRMtree]**
Container Apps nie wystawia zarządzanych certyfikatów wildcard (subdomeny organizacji `<slug>.govai.pl`).
**Decyzja (2026-11-06): Cloudflare DNS-only (szara chmurka) + Let's Encrypt z automatycznym odnawianiem**
— zamiast wcześniej planowanego proxy Cloudflare + Origin CA, bo:
- Universal SSL Cloudflare (Free) nie obejmuje `*.int.govai.pl` (wildcard drugiego poziomu wymaga płatnego
  Advanced Certificate Manager),
- proxy Cloudflare (Free) ucina żądania po ~100 s, a wywołania LLM bywają dłuższe.

Realizacja: workflow `.github/workflows/renew-certs.yml` — jeden certyfikat SAN `govai.pl, *.govai.pl, *.int.govai.pl`
(DNS-01 przez API Cloudflare, token w Key Vault jako `cloudflare-api-token`), wgrywany do `govai-env` jako
`govai-le-YYYYMMDD` i podpinany do hostów `govai.pl`, `*.govai.pl` (`govai-edge`) oraz `int.govai.pl`,
`*.int.govai.pl` (`govai-edge-int`). Co tydzień sprawdza ważność, odnawia przy < 30 dniach, usuwa stare
certyfikaty. Hosty dodaje się raz przy przełączeniu DNS (`az containerapp hostname add` + TXT `asuid.<host>`),
potem pierwsze wystawienie: ręczne uruchomienie workflow z `force=true`.
Kod etapu 5 (Caddy z `caddy-dns/cloudflare`, DNS-01) dotyczy modelu VM / instancji dedykowanych — w Container Apps
TLS kończy się na ingress Azure.

## 4. Baza danych i Redis — VM w prywatnym VNet

**Decyzja 2026-11-17 (Adam):** Azure Database for PostgreSQL Flexible jest dla nowej subskrypcji GovAI
nieosiągalny — Burstable w Poland Central bez wolnej mocy (Microsoft, case 2611060050003896), Germany West
Central zablokowany dla subskrypcji (restricted). Zamiast PG Flexible i Azure Cache for Redis: **jedna VM
`vm-govai-data`** w Poland Central z kontenerami (szczegóły, obsługa i runbook: `infra/db-vm/README.md`):

| Usługa | PROD | INT |
|---|---|---|
| Postgres 16 + TimescaleDB 2.31 (`timescale/timescaledb:2.31.0-pg16`, jak lokalnie) | `10.50.2.10:5432`, `/data/pg-prod`, 3 GB | `10.50.2.10:5433`, `/data/pg-int`, 1,5 GB |
| Redis 7 (hasło, bez trwałości — tylko pub/sub gateway → API → WebSocket) | `:6379` | `:6380` |

- Quota subskrypcji: tylko rodziny BS i DSv3 (po 10 rdzeni) → Standard_B2ms (8 GB), zapas Standard_D2s_v3
  (`GOVAI_DATA_VM_SIZE`).
- **Osobne klastry dla INT i PROD** (osobne kontenery i dane) — z tych samych powodów co wcześniej osobne serwery:
  rola `govai_app` jest obiektem klastra (inne hasła INT/PROD) i incydent CRMtree (kopia PROD na INT → maile do
  prawdziwych osób, 2026-10-23).
- Superużytkownik `govai` (hasło `db-admin-password[-int]`) — tylko migracje i backup; aplikacje jako `govai_app`
  (RLS; rola z migracji 015, hasło ustawia `migrate.sh` z `DB_APP_PASSWORD`). `app.platform=on` w `migrate.sh`
  zostaje (nieszkodliwe dla superużytkownika).
- `db/init.sql` uruchamia `migrate.sh` na świeżej bazie (brak tabeli `agents`), potem migracje.
- **Sieć:** Postgres/Redis tylko na prywatnym IP; NSG na `snet-data` wpuszcza 5432/5433/6379/6380 wyłącznie
  z `snet-aca`, resztę blokuje (bez SSH z internetu — administracja przez `az vm run-command` / Bastion Developer).
  VM ma Standard Public IP **tylko do ruchu wychodzącego** (wygaszanie „default outbound access”; tańsze niż NAT Gateway).
  TLS: certyfikat samopodpisany, aplikacje `sslmode=require`.
- **Migracje:** runner GitHub nie ma dostępu do VNet → **Container Apps Job** `govai-migrate[-int]` (obraz
  `infra/migrate/Dockerfile`, `migrate.sh` w trybie zdalnym, sekrety jako referencje Key Vault) — §6.
- **INT tylko w godzinach pracy** (pn–pt 09–18 Europe/Warsaw): `int-schedule.yml` zatrzymuje `pg-int`/`redis-int`
  (po backupie) i skaluje aplikacje `-int` do min. 0 replik, rano odwrotnie.
- `max_connections` = 100 (domyślne) → pule API/gateway `DB_POOL_MAX=8` na replikę.

### Backup i odtwarzanie
- **Logiczny (główny):** kontener `govai-backup` na VM, codziennie 02:30 Europe/Warsaw — `pg_dump -Fc` + role
  (`pg_dumpall --globals-only`, bez haseł) + metadane (sha256, wersje, liczności tabel z tej samej migawki) do konta
  Storage `stgovaibkp*` (kontener `backups`, `<env>/YYYY/MM/DD/…`, `<env>/latest.json`), managed identity VM.
  Retencja 7 dni (lifecycle management). INT: backup przy wieczornym zatrzymaniu.
- **Snapshot VM (zapasowy):** Azure Backup `rsv-govai`, codziennie, 7 dni.
- **Odtwarzanie:** `infra/db-vm/restore.sh <int|prod> [latest|ścieżka] [--test|--yes]` (pre/post_restore TimescaleDB,
  weryfikacja liczności, podmiana bazy z zachowaniem poprzedniej). Ten sam mechanizm działa on-prem (`BACKUP_TARGET=local`).
- **Monitoring:** `backup-check.yml` (codziennie: PROD < 26 h, INT w dni robocze) i `restore-test.yml` (niedziela:
  pełne odtworzenie PROD do bazy tymczasowej i porównanie). **RPO 24 h, RTO ~30 min.**
- Rollback bazy przez PITR (jak w PG Flexible) **nie jest dostępny** — punkt przywracania = ostatni backup dobowy
  (lub snapshot VM).

## 5. Sekrety i konfiguracja

Key Vault `kv-govai`, referencje `keyvaultref:https://kv-govai.vault.azure.net/secrets/<nazwa>,identityref:system`
→ `secretRef` w env aplikacji (jak CRMtree). Proponowane nazwy (PROD / INT z sufiksem `-int`):

| Sekret KV | Zmienna | Aplikacje |
|---|---|---|
| `jwt-secret` | `JWT_SECRET` | api, gateway |
| `db-app-password` | `DB_APP_PASSWORD` → składany w `DATABASE_URL` | api, gateway |
| `db-admin-password` | `POSTGRES_PASSWORD` superużytkownika `govai` (VM danych) | VM (`govai-data.sh`), backup |
| `redis-password` | hasło Redisa (VM danych) | VM |
| `database-url` | `DATABASE_URL` = `postgresql://govai_app:<pw>@10.50.2.10:5432/govai?sslmode=require` (INT: `:5433`) | api, gateway |
| `database-admin-url` | `DATABASE_ADMIN_URL` (superużytkownik, ten sam host/port) | job `govai-migrate[-int]` |
| `redis-url` | `REDIS_URL` = `redis://:<pw>@10.50.2.10:6379/0` (INT: `:6380`) | api, gateway |
| `provider-keys-secret` | `PROVIDER_KEYS_SECRET` | api, gateway |
| `anthropic-api-key` | `ANTHROPIC_API_KEY` | api, gateway |
| `deepseek-api-key` | `DEEPSEEK_API_KEY` | gateway |

Wszystkie hasła i URL-e generuje `infra/aca/bootstrap.sh secrets <int|prod>` (bez wypisywania wartości; URL-e
wskazujące inny host — np. pozostałość po PG Flexible — są nadpisywane). VM danych pobiera hasła z Key Vault
przy starcie usługi (managed identity), nigdy przez custom data.

Zwykłe zmienne: `ALLOWED_ORIGINS=https://app.govai.pl`, `TENANT_BASE_DOMAINS=govai.pl` (INT: `int.govai.pl`),
`GATEWAY_URL` (api → gateway, wewnętrzny FQDN), `LOG_LEVEL`.
Frontend: bez zmiennych (adresy względne wkompilowane w obraz — jeden obraz dla INT i PROD, jak CRMtree).

## 6. CI/CD (GitHub Actions)

Jak CRMtree (`deploy-int.yml` na push `develop`, `deploy.yml` na push `master`), z poprawkami:

1. Logowanie do Azure przez **OIDC** (bez sekretu klienta) — tożsamość `id-govai-github` w `rg-govai`
   (subskrypcja GovAI `5e23c5f2-…`, konto Azure adamgmanka@gmail.com) z federated credentials
   `repo:adapakse/GovAI:environment:int` i `…:prod` (`adapakse` = właściciel repo na GitHubie, nie konto Azure);
   role: Contributor na `rg-govai`, AcrPush na `govaicr`, Key Vault Secrets User na `kv-govai`
   (tworzy `infra/aca/bootstrap.sh github`). Stara tożsamość `oidc-msi-govai` (`rg-adapakse-8986`, stara
   subskrypcja) obsługuje tylko deploy na VM do czasu przełączenia. **[poprawka]** CRMtree używa sekretu klienta service principala.
2. Build i push 4 obrazów (`edge`, `frontend`, `api`, `gateway`) z tagami
   `int-<run_number>` / `<run_number>` (jak CRMtree) + etykieta z SHA commita.
3. **Migracje przed aktualizacją aplikacji** (jak CRMtree), ale baza jest w prywatnym VNet, więc nie z runnera:
   CI buduje obraz `govai-migrate` (`infra/migrate/Dockerfile`: klient psql 16 + `db/` + `migrate.sh`),
   ustawia go w Container Apps Job `govai-migrate[-int]` (`az containerapp job update --image`), uruchamia
   (`job start`) i czeka na wynik (`job execution show`; `Failed` = nieudany deploy). Job ma
   `DATABASE_ADMIN_URL` i `DB_APP_PASSWORD` jako referencje Key Vault. Migracje muszą być wstecznie zgodne
   (stary kod chwilę działa na nowym schemacie). Deploy INT poza godzinami pracy uruchamia bazy INT na czas
   migracji i smoke testu. CI buduje też `govai-backup` i po udanym deployu przesuwa tag `govai-backup:<int|prod>`.
4. `az containerapp update --image …` dla każdej aplikacji; potem smoke test `/health` przez `app.<domena>`.
5. GitHub Environments: `int` (bez zatwierdzeń), `prod` (wymagane zatwierdzenie Adama).
6. Rollback: `az containerapp update --image <poprzedni tag>` (ACR trzyma numerowane tagi); bazy — odtworzenie
   z backupu dobowego (`infra/db-vm/restore.sh`, §4).
7. Workflowy harmonogramowe (działają tylko z gałęzi domyślnej): `int-schedule.yml` (INT w godzinach pracy,
   zmienna `ACA_INT_ENABLED`), `backup-check.yml` i `restore-test.yml` (zmienna `DATAVM_ENABLED`), `renew-certs.yml`.
   Logują się środowiskiem `prod` (środowisko `int` do przełączenia trzyma sekrety starej subskrypcji); gdy `prod`
   dostanie wymagane zatwierdzenia, harmonogramy czekałyby na akceptację — wtedy środowisko GitHub `ops`
   (federated credential `gh-env-ops` z `bootstrap.sh github`) i zmienna repo `OPS_ENVIRONMENT=ops`.

**Realizacja:** `deploy-aca-int.yml` (push `develop`) i `deploy-aca-prod.yml` (push `master`) wołają wspólny
`_deploy-aca.yml`. Automatyczny deploy po push jest wyłączony do przełączenia — włączają go zmienne repo
`ACA_INT_ENABLED=true` / `ACA_PROD_ENABLED=true` (`gh variable set ACA_INT_ENABLED -R adapakse/GovAI --body true`).
Przełączenie INT: najpierw sekrety środowiska `int` na nową subskrypcję (te same wartości co w `prod`), potem zmienna.
Ręczne uruchomienie z `build_only=true` buduje i wypycha obrazy bez migracji i aktualizacji aplikacji; gdy aplikacji
`govai-*` jeszcze nie ma, workflow i tak kończy na obrazach. Stary `deploy.yml` (VM) — do usunięcia po przełączeniu.

Obecne `ci.yml` (i18n, build obrazów, testy izolacji na pełnym stosie docker compose) zostaje bez zmian.

## 7. Kolejność wdrożenia

1. Dostępy (Adam): Kacper w GitHub (write) i Azure (Contributor na `rg-govai-prod`, Key Vault Secrets Officer),
   Cloudflare (strefa `govai.pl`).
2. DNS `govai.pl` → Cloudflare (Adam) + token `cloudflare-api-token` w `kv-govai`; certyfikaty: `renew-certs.yml` (§3).
3. Zasoby wspólne i sieć — `infra/aca/bootstrap.sh` (kroki w nagłówku skryptu): `base` (RG `rg-govai`, Log Analytics,
   `govaicr`, `kv-govai`), `network` (VNet, NSG, `govai-env` w VNet), `backup` (konto Storage), `secrets prod|int`,
   `datavm` (VM baz + Azure Backup), `github`, `apps int|prod` (aplikacje + job migracji).
4. INT na Container Apps: baza INT na `vm-govai-data` (init.sql + migracje przez job `govai-migrate-int`), aplikacje `-int`, domeny `*.int.govai.pl`,
   `deploy-int.yml`. Test: logowanie, `govai-demo`, testy izolacji przeciw INT (opcjonalnie).
5. Przełączenie publicznego `govai.pl` z VM na `govai-edge` (PROD) — dopiero gdy PROD działa; do tego czasu
   landing może zostać na VM.
6. PROD: baza PROD na `vm-govai-data`, aplikacje, domeny, `deploy.yml` (gałąź `master`), organizacja **Gessel** (`gessel.govai.pl`)
   z panelu super-admina, zmiana hasła admina platformy.
7. Wygaszenie VM INT (`rg-govai-int`) po migracji; Bicep VM zostaje jako szablon instancji dedykowanej.

## 8. Uprawnienia agentów Claude
W CRMtree agent ma osobny service principal `sp-claude-agent-crmtree` (Reader na grupie, Contributor tylko na
aplikacjach `-int` i `rg-govai-int`). Dla GovAI analogicznie: agent może wdrażać INT, PROD — tylko człowiek
(zatwierdzenie w GitHub Environment `prod`). Tryb auto agenta blokuje m.in. zapis sekretów, nadawanie ról Azure i merge
bez wyraźnego polecenia — kroki wymagające tych uprawnień podawać jako gotowe komendy dla człowieka.

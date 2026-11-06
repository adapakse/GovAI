# GovAI — środowiska i infrastruktura Azure (plan docelowy)

Status: plan (2026-11-04), do realizacji. Wzorzec: **CRMtree** (ta sama subskrypcja Azure,
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

**Gałąź PROD = `master`** (decyzja Adama, jak CRMtree). Dziś w repo gałęzią produkcyjną jest `main`
(domyślna w GitHub) — do zrobienia: zmiana nazwy `main` → `master` (GitHub → Settings → Branches →
rename; GitHub przekieruje stare odwołania) i aktualizacja odwołań w repo (`infra/params/prod.bicepparam`,
`.github/workflows/*`, `ENVIRONMENTS.md`).

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
| Container Apps Environment | `govai-env` | profil Consumption, bez VNet (jak `crmtree-env`) |
| Container Registry | `govairegistry` | Basic. **[poprawka]** pull przez managed identity (rola AcrPull), bez admin usera |
| Key Vault | `kv-govai` | tryb RBAC; aplikacje czytają sekrety referencjami KV przez system-assigned identity (jak CRMtree). **[poprawka]** osobne nazwy sekretów per środowisko (`*-int`) — w CRMtree INT dzieli sekrety z PROD |
| PostgreSQL Flexible | `govai-db` (PROD), `govai-db-int` (INT) | PG 15, Standard_B1ms (Burstable), backup 7 dni (PROD: rozważ 35). **[poprawka]** osobny serwer dla INT — patrz §4 |
| Redis | `govai-redis` (PROD), `govai-redis-int` | **Azure Cache for Redis Basic C0** (TLS 6380). GovAI używa Redis tylko do pub/sub zdarzeń na żywo (gateway → API → WebSocket) — trwałość niepotrzebna. Redis jako Container App wymagałby ingressu TCP, a ten działa tylko w środowisku z własnym VNet |
| Storage | (na razie niepotrzebny) | GovAI nie przechowuje plików; raporty PDF generowane w locie |

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
Container Apps nie wystawia zarządzanych certyfikatów wildcard. CRMtree wgrał ręcznie certyfikaty
`*.crmtree.pl` / `*.int.crmtree.pl`, których nic nie odnawia (wygasają 8 i 10.11.2026 — ryzyko awarii).
Dla GovAI: **Cloudflare w trybie proxy (pomarańczowa chmurka) + Cloudflare Origin CA**:
- certyfikat Origin CA na `govai.pl, *.govai.pl, *.int.govai.pl` (ważność do 15 lat) wgrany jako PFX do `govai-env`
  i podpięty do domen `govai-edge` / `govai-edge-int`;
- Cloudflare SSL/TLS: **Full (strict)**; publiczny certyfikat przy kliencie obsługuje Cloudflare (odnawia sam);
- uwagi: limit czasu żądania przez proxy Cloudflare (plan Free ~100 s) — długie operacje LLM muszą się mieścić albo
  przejść na tryb asynchroniczny; WebSocket przez proxy Cloudflare działa.
Kod etapu 5 (Caddy z `caddy-dns/cloudflare`, DNS-01) dotyczy modelu VM / instancji dedykowanych — w Container Apps
TLS kończy się na ingress Azure.

## 4. Baza danych

- **PG 15 + TimescaleDB** — sprawdzone: `timescaledb` jest na liście dozwolonych rozszerzeń Azure Flexible
  (także na PG 15, serwer `crmtree-db`). Konfiguracja serwera: `azure.extensions = TIMESCALEDB,UUID-OSSP,PGCRYPTO`,
  `shared_preload_libraries = timescaledb` (restart). GovAI używa tylko `create_hypertable` (`db/init.sql`).
- **Osobny serwer dla INT** (`govai-db-int`) zamiast dwóch baz na jednym serwerze jak w CRMtree, bo:
  1. rola aplikacji `govai_app` (RLS, migracja 015) jest **obiektem całego serwera** — przy wspólnym serwerze INT i PROD
     miałyby tę samą rolę i hasło;
  2. CRMtree miał incydent: kopia danych PROD na INT → maile do prawdziwych osób z INT (2026-10-23).
- **Azure nie daje superużytkownika.** Admin serwera (`govaiadmin`) jest właścicielem tabel i podlega RLS (FORCE) —
  dlatego `infra/scripts/migrate.sh` ustawia `app.platform=on` (`PGOPTIONS`). Aplikacje: rola `govai_app`
  (tworzona w migracji 015, hasło ustawiane przez skrypt migracji z `DB_APP_PASSWORD`).
- `db/init.sql` (dziś montowany do kontenera Postgresa) trzeba uruchomić **raz** przy zakładaniu bazy, potem migracje.
- Sieć: publiczny dostęp z regułą „Allow Azure services” (jak CRMtree — potrzebne dla Container Apps i runnerów
  GitHub). Lepiej docelowo: VNet + migracje jako Container Apps Job. Doraźne reguły IP do pracy lokalnej — usuwać po użyciu
  (w CRMtree zostają śmieci).
- `max_connections` B1ms = 50 → małe pule: API `max_size` (dziś 20) i gateway (10) **zmniejszyć** przy wielu replikach.

## 5. Sekrety i konfiguracja

Key Vault `kv-govai`, referencje `keyvaultref:https://kv-govai.vault.azure.net/secrets/<nazwa>,identityref:system`
→ `secretRef` w env aplikacji (jak CRMtree). Proponowane nazwy (PROD / INT z sufiksem `-int`):

| Sekret KV | Zmienna | Aplikacje |
|---|---|---|
| `jwt-secret` | `JWT_SECRET` | api, gateway |
| `db-app-password` | `DB_APP_PASSWORD` → składany w `DATABASE_URL` | api, gateway |
| `db-admin-password` | (tylko CI — migracje) | — |
| `provider-keys-secret` | `PROVIDER_KEYS_SECRET` | api, gateway |
| `anthropic-api-key` | `ANTHROPIC_API_KEY` | api, gateway |
| `deepseek-api-key` | `DEEPSEEK_API_KEY` | gateway |

`DATABASE_URL` aplikacje dziś biorą w całości — w Container Apps najprościej trzymać **cały URL** jako sekret
(`database-url`, z hasłem `govai_app`) albo dodać składanie z `DB_HOST/DB_USER/DB_APP_PASSWORD` w `config.py`.

Zwykłe zmienne: `ALLOWED_ORIGINS=https://app.govai.pl`, `TENANT_BASE_DOMAINS=govai.pl` (INT: `int.govai.pl`),
`REDIS_URL=rediss://:<klucz>@govai-redis.redis.cache.windows.net:6380` (klucz jako sekret KV `redis-url`), `GATEWAY_URL` (api → gateway, wewnętrzny FQDN), `LOG_LEVEL`.
Frontend: bez zmiennych (adresy względne wkompilowane w obraz — jeden obraz dla INT i PROD, jak CRMtree).

## 6. CI/CD (GitHub Actions)

Jak CRMtree (`deploy-int.yml` na push `develop`, `deploy.yml` na push `master`), z poprawkami:

1. Logowanie do Azure przez **OIDC** (bez sekretu klienta) — tożsamość `oidc-msi-govai` (`rg-adapakse-8986`) ma już
   federated credential `repo:adapakse/GovAI:environment:int`; dodać `…:environment:prod` i role: AcrPush na
   `govairegistry`, Contributor na aplikacjach w `rg-govai-prod`, Key Vault Secrets User (odczyt hasła admina do migracji).
   **[poprawka]** CRMtree używa sekretu klienta service principala.
2. Build i push 4 obrazów (`edge`, `frontend`, `api`, `gateway`) z tagami
   `int-<run_number>` / `<run_number>` (jak CRMtree) + etykieta z SHA commita.
3. **Migracje przed aktualizacją aplikacji** (jak CRMtree): runner pobiera hasło admina z KV i uruchamia migracje
   `psql` na właściwym serwerze. `infra/scripts/migrate.sh` dziś używa `docker compose exec` — dodać tryb
   „zdalny” (`psql "$DATABASE_ADMIN_URL"`). Migracje muszą być wstecznie zgodne (stary kod chwilę działa na nowym schemacie).
4. `az containerapp update --image …` dla każdej aplikacji; potem smoke test `/health` przez `app.<domena>`.
5. GitHub Environments: `int` (bez zatwierdzeń), `prod` (wymagane zatwierdzenie Adama).
6. Rollback: `az containerapp update --image <poprzedni tag>` (ACR trzyma numerowane tagi); bazy — PITR.

Obecne `ci.yml` (i18n, build obrazów, testy izolacji na pełnym stosie docker compose) zostaje bez zmian.

## 7. Kolejność wdrożenia

1. Dostępy (Adam): Kacper w GitHub (write) i Azure (Contributor na `rg-govai-prod`, Key Vault Secrets Officer),
   Cloudflare (strefa `govai.pl`).
2. DNS `govai.pl` → Cloudflare (Adam) + certyfikat Origin CA.
3. Zasoby wspólne: `rg-govai-prod`, Log Analytics, `govai-env`, `govairegistry`, `kv-govai` (skrypt `az` w repo,
   np. `infra/aca/bootstrap.sh` — do napisania; CRMtree nie ma IaC, ale GovAI ma Bicep dla VM — warto dopisać
   `infra/aca/*.bicep`).
4. INT na Container Apps: `govai-db-int` (+ init.sql + migracje), aplikacje `-int`, domeny `*.int.govai.pl`,
   `deploy-int.yml`. Test: logowanie, `govai-demo`, testy izolacji przeciw INT (opcjonalnie).
5. Przełączenie publicznego `govai.pl` z VM na `govai-edge` (PROD) — dopiero gdy PROD działa; do tego czasu
   landing może zostać na VM.
6. PROD: `govai-db`, aplikacje, domeny, `deploy.yml` (gałąź `master`), organizacja **Gessel** (`gessel.govai.pl`)
   z panelu super-admina, zmiana hasła admina platformy.
7. Wygaszenie VM INT (`rg-govai-int`) po migracji; Bicep VM zostaje jako szablon instancji dedykowanej.

## 8. Uprawnienia agentów Claude
W CRMtree agent ma osobny service principal `sp-claude-agent-crmtree` (Reader na grupie, Contributor tylko na
aplikacjach `-int` i `rg-govai-int`). Dla GovAI analogicznie: agent może wdrażać INT, PROD — tylko człowiek
(zatwierdzenie w GitHub Environment `prod`). Tryb auto agenta blokuje m.in. zapis sekretów, nadawanie ról Azure i merge
bez wyraźnego polecenia — kroki wymagające tych uprawnień podawać jako gotowe komendy dla człowieka.

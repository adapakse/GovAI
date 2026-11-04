# GovAI — instrukcje dla agentów (Claude Code) i developerów

Platforma nadzoru i zgodności agentów AI z EU AI Act: rejestr agentów + ocena luk
AI Act, bramka bezpieczeństwa (PII, polityki, routing do dostawców LLM), nadzór
człowieka, niezmienny dziennik audytowy. **SaaS multi-tenant** (organizacje
izolowane przez Row Level Security) + opcjonalnie instancje dedykowane.

**Zacznij od:** `docs/HANDOFF.md` (stan projektu, co dalej), potem
`docs/multitenancy-plan.md` (model izolacji), `docs/azure-environments-plan.md`
(docelowa infrastruktura INT/PROD), `ENVIRONMENTS.md` (uruchomienie, deploy).

## Komunikacja
- Z właścicielem projektu (Adam) i zespołem — **po polsku**. Komentarze w kodzie po
  polsku (oszczędnie), identyfikatory po angielsku. Commity po polsku,
  konwencja `typ(zakres): opis` (feat/fix/docs/chore).

## Struktura
| Katalog | Co |
|---|---|
| `api/` | FastAPI — panel/REST (`routers/`, `repositories/` = jedyne miejsce SQL, `services/`, `dependencies/auth.py`, `database.py`) |
| `gateway/` | FastAPI — bramka OpenAI-compatible `/v1/chat/completions` (PII Presidio+spaCy, polityki, wybór providera, audyt) |
| `frontend/` | Next.js 14 (App Router) + next-intl, Tailwind |
| `website/` | statyczny landing + blog (`i18n.js`, `i18n/<lang>/*.json`) |
| `db/` | `init.sql` (świeży wolumen) + `migrations/NNN_*.sql` (rejestr `schema_migrations`) |
| `caddy/` | reverse proxy + TLS (model VM/dedykowany), `Dockerfile` z modułem Cloudflare DNS |
| `infra/` | Bicep (model VM), `scripts/` (deploy-remote, fetch-secrets, migrate) |
| `tests/isolation/` | testy izolacji organizacji (pytest, pełny stos) — uruchamiane w CI |
| `scripts/` | `i18n-check.mjs`, `gen-db-i18n.mjs` |

## Twarde zasady (łamanie = błąd bezpieczeństwa lub zepsuty deploy)

### Multitenancy / RLS
- API i gateway łączą się z bazą rolą **`govai_app`** (bez superużytkownika — superużytkownik omija RLS!).
  Rola `govai` tylko dla migracji. Nigdy nie zmieniaj `DATABASE_URL` aplikacji na `govai`.
- Każde zapytanie aplikacji idzie w kontekście: `tenant_db(tenant_id)` / `platform_db()` (API, `api/database.py`),
  `tenant_conn` / `platform_conn` (gateway). W żądaniach HTTP kontekst otwiera `get_current_user`.
  `get_pool()` poza kontekstem rzuca błąd — to celowe (fail closed). **Nie obchodź tego.**
- `tenant_id` przy INSERT wpisuje baza (`DEFAULT current_tenant_id()`). Nie przekazuj `tenant_id` z danych od klienta.
- Nowa tabela z danymi organizacji = kolumna `tenant_id` + FK + `ENABLE/FORCE ROW LEVEL SECURITY` + polityka
  `tenant_isolation` (wzór: `db/migrations/015_multitenancy.sql`) + test w `tests/isolation/`.
- Klucze obce nie podlegają RLS — powiązania z obiektami organizacji przez złożony FK `(tenant_id, x_id)` albo jawną kontrolę w API.
- `platform_db()` tylko: logowanie, panel super-admina (`/platform/*`), zadania tła. Każda operacja super-admina → `platform_audit_log`.
- `audit_log` jest niezmienny (trigger). Nie dodawaj UPDATE/DELETE na nim (wyjątek: reset danych organizacji demo z `app.audit_purge`).

### Baza i migracje
- Każda zmiana schematu = nowy plik `db/migrations/NNN_opis.sql`, **idempotentny** (`IF NOT EXISTS`, `ON CONFLICT`, bloki `DO $$`).
  Nigdy ręcznych zmian schematu (był już dryf schematu — patrz `ENVIRONMENTS.md`).
- Migracje stosuje `infra/scripts/migrate.sh` (rejestr `schema_migrations`, transakcja + `ON_ERROR_STOP`).
- Kolumny JSONB: przekazuj dict/list — **nigdy `json.dumps()`** (pule asyncpg mają kodek jsonb; podwójne kodowanie
  psuje dane po cichu). Gateway: jak w istniejącym kodzie.
- Windows: migracji nie przepuszczaj przez `Get-Content | psql` (psuje polskie znaki); Git Bash: `MSYS_NO_PATHCONV=1`.

### Bezpieczeństwo
- Repozytorium jest **publiczne** — żadnych sekretów w kodzie, `.env` nie commitujemy. Sekrety: Azure Key Vault.
- Klucze providerów: `api_key_env` tylko z białej listy kluczy platformy (`PLATFORM_KEY_ENVS`) i nigdy z własnym `base_url`;
  własne klucze organizacji tylko zaszyfrowane (`secret_box.py`, AES-GCM, `PROVIDER_KEYS_SECRET`) i nigdy w odpowiedziach API.
- Hasło startowe admina z `002_auth.sql` jest publiczne — każde środowisko musi je zmienić po instalacji.

### i18n (10 języków + pt na landingu)
- Teksty UI/API/gateway/landing tylko przez klucze tłumaczeń; nowy klucz we **wszystkich** językach
  (pl, en, de, it, es, fr, ro, ru, sl, hr; landing dodatkowo pt). `node scripts/i18n-check.mjs --fix` musi dać OK (jest w CI).
- Opis mechanizmu: `docs/i18n.md`. Pliki JSON edytuj skryptem Node (JSON.parse/stringify), nie ręcznie.

## Lokalnie
- Docker Desktop; `.env` z `.env.example` (wymagane: `DB_PASSWORD`, `DB_APP_PASSWORD`, `JWT_SECRET`, `PROVIDER_KEYS_SECRET`;
  `TENANT_BASE_DOMAINS=govai.test,localhost` do testów subdomen — `govai-demo.localhost:8443`).
- Kod jest kopiowany do obrazów (bez bind mountów): zmiana kodu → `docker compose up -d --build <serwis>`.
- Ollama/Bielik pobiera kilka GB — lokalnie: `docker compose up -d --no-deps api gateway frontend caddy` (+ postgres, redis).
- Migracje: `MSYS_NO_PATHCONV=1 sh infra/scripts/migrate.sh`. Konto startowe: `admin@kancelaria.local` (super-admin, hasło w `002_auth.sql`).
- Python lokalnie (Windows) najprościej w kontenerze: `docker run --rm -v "C:/dev/govai:/src" python:3.12-slim python -m py_compile /src/<plik>`.

## Weryfikacja przed PR (CI robi to samo)
1. `node scripts/i18n-check.mjs`
2. `cd frontend && npx tsc --noEmit -p tsconfig.json`
3. Testy gatewaya: `docker compose build gateway && docker run --rm govai-gateway sh -c "pip install -q pytest && python -m pytest tests/ -q"`
4. Testy izolacji (stos musi działać): `sh tests/isolation/run.sh` — wszystkie muszą przejść.

## Git i środowiska
- `feature/*` → PR do `develop` → deploy na **INT** → PR `develop` → gałąź PROD → deploy na **PROD**.
  Szczegóły i docelowy model Azure (Container Apps jak CRMtree): `docs/azure-environments-plan.md`.
- Nie commituj ani nie wypychaj bez prośby; merge do `develop`/PROD i deploy tylko na wyraźne polecenie Adama.
- Commity kończ linią `Co-Authored-By:` zgodnie z ustawieniami Twojego agenta.

# GovAI — środowiska wewnętrzne

Środowiska **GovAI do rozwoju, integracji i testów przed spakowaniem
release'u** — nie mylić z wdrożeniem u klienta (klient dostaje własną,
odizolowaną instancję we własnej infrastrukturze, patrz sekcja "Model
wdrożenia" niżej).

| Środowisko | Branch    | Gdzie                                   | Domena      |
|------------|-----------|------------------------------------------|-------------|
| lokalne    | dowolny (feature / `develop` / `main`) | maszyna developera, `docker compose` | — (`localhost`) |
| INT        | `develop` | Azure: `vm-govai-int` w `rg-govai-int`   | brak (wewnętrzne) |
| PROD       | `main`    | Azure: `vm-govai-prod` w `rg-govai-prod` | `govai.pl`  |

Parametry instancji Azure: `infra/params/int.bicepparam`,
`infra/params/prod.bicepparam` (szablon: `infra/instance.bicep`). Region
`polandcentral`, VM `Standard_D2s_v3` (quota B-series = 0 na subskrypcji).

## Przepływ pracy

1. Praca lokalnie na branchu feature → push na GitHub.
2. Merge do `develop` (PR) → CI (`.github/workflows/ci.yml`, odpala się na
   push/PR do `develop` i `main`) → deploy na **INT** → testy integracyjne.
3. Gdy stabilne: merge `develop` → `main` (PR) → deploy na **PROD**.

Lokalnie wystarcza jeden klon repo — nie ma potrzeby stawiania drugiego
stosu (`govai-int`) na maszynie developera; INT żyje na Azure.

## Deploy na INT / PROD

Ręcznie przez GitHub Actions: **Actions → Deploy → Run workflow**
(`.github/workflows/deploy.yml`):

- `Use workflow from` = branch do wdrożenia (`develop` dla INT, `main` dla PROD),
- `environment` = `int` albo `prod` (GitHub Environment + nazwa RG/VM).

Workflow loguje się do Azure przez OIDC i przez `az vm run-command` robi na
VM: `git reset --hard origin/<branch>` w `/opt/govai`, a potem
`infra/scripts/deploy-remote.sh`, który:

1. pobiera sekrety z Azure Key Vault do `/opt/govai/.env`
   (`infra/scripts/fetch-secrets.sh`, tożsamość zarządzana VM),
2. startuje Postgresa i stosuje **niewykonane** migracje z `db/migrations/`
   (`infra/scripts/migrate.sh`: rejestr w tabeli `schema_migrations`, każda
   migracja w jednej transakcji z `ON_ERROR_STOP` — błąd przerywa deploy;
   migracje i tak pisz idempotentnie: `IF NOT EXISTS`, `ON CONFLICT ...`),
3. `docker compose up -d --build`, restart Caddy (odświeża landing page).

## Lokalne uruchomienie

```powershell
cd C:\dev\govai
copy .env.example .env            # uzupełnij sekrety (JWT_SECRET, DB_PASSWORD...)
docker compose up -d --build
```

Lokalnie migracje **nie są auto-stosowane** (tylko `db/init.sql` przy
świeżym wolumenie) — po każdej nowej migracji w `db/migrations/` (Git Bash):

```sh
MSYS_NO_PATHCONV=1 sh infra/scripts/migrate.sh
```

Skrypt stosuje tylko migracje nieobecne w `schema_migrations`.

`.env` musi zawierać `DB_APP_PASSWORD` (rola `govai_app`, której używają API i gateway —
wymagana przez RLS, migracja 015); opcjonalnie `TENANT_BASE_DOMAINS` (np. `govai.test`)
do testowania logowania przez subdomenę organizacji. Testy izolacji organizacji
(wymagają działającego stosu): `sh tests/isolation/run.sh` — szczegóły w
`tests/isolation/README.md`, opis modelu w `docs/multitenancy-plan.md`.
(Nigdy `Get-Content -Raw | ... psql` — psuje polskie znaki, zob.
`db/migrations/008_fix_text_encoding.sql`.)

Kod w `api/`, `gateway/`, `frontend/` jest kopiowany do obrazu (bez bind
mountów) — po zmianie kodu `docker compose up -d --build <serwis>`, sam
restart nie wystarczy.

## Sekrety i dane logowania

- `.env` jest niewersjonowany. Lokalnie — tworzony ręcznie z `.env.example`;
  na INT/PROD — generowany przy deployu z Key Vault. Nie kopiuj sekretów
  między środowiskami.
- Hasło startowe partnera (`admin@kancelaria.local`) pochodzi z
  `db/migrations/002_auth.sql` — zmień je po pierwszej instalacji każdego
  środowiska.

## Znany dryf schematu (naprawiony 16.07.2026)

Baza `govai` miała tabelę `ai_act_requirements` i 17 kolumn
(`agents.compliance_decl`, `policies.policy_code` i in.) dodane ad-hoc, bez
wersjonowanej migracji — wyszło na jaw dopiero przy stawianiu środowiska na
świeżym wolumenie Postgresa. Naprawione w `001_ai_act_requirements.sql` i
`010_agent_profile_and_policy_code.sql` (oba idempotentne).
**Wniosek na przyszłość:** każda zmiana schematu musi dostać odpowiadającą
migrację w `db/migrations/`, inaczej INT, PROD (i każde przyszłe wdrożenie
klienckie) się rozjadą. Weryfikacja: `pg_dump --schema-only` na obu bazach
+ diff.

## Model wdrożenia (docelowy, poza zakresem tego dokumentu)

INT/PROD to środowiska **wewnętrzne** GovAI. Wdrożenie u klienta = osobna,
w pełni odizolowana instancja **w infrastrukturze klienta** (jego Azure
albo on-prem) — bez multitenancy, bez współdzielonego SaaS. Pakowanie do
wysyłki klientowi to osobny, nierozpoczęty jeszcze wątek.

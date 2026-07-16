# GovAI — środowiska wewnętrzne

Dwa niezależne stosy `docker compose` na tej samej maszynie, każdy z osobnym
`.env`, portami i wolumenem Postgresa. To środowiska **GovAI do integracji
i testów przed spakowaniem release'u** — nie mylić z wdrożeniem u klienta
(klient dostaje własną, odizolowaną instancję we własnej infrastrukturze,
patrz sekcja "Model wdrożenia" niżej).

| Środowisko | Branch    | Katalog                        | Frontend | API   | Gateway | Ollama  |
|------------|-----------|---------------------------------|----------|-------|---------|---------|
| `govai`    | `main`    | `C:\Users\Adam\govai`           | 4000     | 8000  | 8001    | 11434   |
| `govai-int`| `develop` | `C:\Users\Adam\govai-int` (git worktree) | 4001 | 8010 | 8011 | 11435 |

## Przepływ pracy

1. Praca bieżąca → commity na `develop` → test na `govai-int`.
2. Gdy stabilne: `git checkout main && git merge develop --ff-only` (albo PR na GitHub) → `main` → deploy na `govai`.
3. `docker-compose.yml` jest **wspólny** dla obu środowisk — porty sterowane zmiennymi `FRONTEND_PORT`/`API_PORT`/`GATEWAY_PORT`/`OLLAMA_PORT` w `.env` (domyślne = porty `govai`, więc `govai` działa bez zmian w `.env`).

## Uruchomienie / aktualizacja `govai-int`

```powershell
cd C:\Users\Adam\govai-int
git merge main --ff-only          # albo: git pull, jeśli branch ma upstream
docker compose build
docker compose up -d
```

Migracje **nie są auto-stosowane** — po każdej nowej migracji w `db/migrations/`:

```powershell
docker cp db/migrations/0XX_nazwa.sql govai-int-postgres-1:/tmp/m.sql
docker compose exec -T postgres psql -U govai -d govai -f /tmp/m.sql
```

(Nigdy `Get-Content -Raw | ... psql` — psuje polskie znaki, zob. `db/migrations/008_fix_text_encoding.sql`.)

## Dane logowania `govai-int`

- Hasło startowe partnera (`admin@kancelaria.local`): `GovAI_Admin_2026!` (z `002_auth.sql` — na `govai` zostało zmienione ręcznie po instalacji, na `govai-int` **nie**).
- `.env` z sekretami (`JWT_SECRET`, `DB_PASSWORD`) jest lokalny, niewersjonowany — wygenerowany osobno dla tego środowiska, nie kopiuj z `govai`.

## Znany dryf schematu (naprawiony 16.07.2026)

Baza `govai` miała tabelę `ai_act_requirements` i 17 kolumn (`agents.compliance_decl`,
`policies.policy_code` i in.) dodane ad-hoc, bez wersjonowanej migracji —
wyszło na jaw dopiero przy stawianiu `govai-int` na świeżym wolumenie
Postgresa. Naprawione w `001_ai_act_requirements.sql` i
`010_agent_profile_and_policy_code.sql` (oba idempotentne — bezpieczne na
`govai`, zweryfikowane: `ALTER TABLE` → same "already exists, skipping").
**Wniosek na przyszłość:** każda zmiana schematu robiona ręcznie na `govai`
(np. przez `psql` wprost) musi dostać odpowiadającą migrację w
`db/migrations/`, inaczej `govai-int` (i każde przyszłe wdrożenie klienckie)
znowu się rozjedzie.

## Model wdrożenia (docelowy, poza zakresem tego dokumentu)

`govai`/`govai-int` to środowiska **wewnętrzne**. Produkcja = osobna,
w pełni odizolowana instancja **w infrastrukturze klienta** (jego Azure
albo on-prem) — bez multitenancy, bez współdzielonego SaaS. Pakowanie do
wysyłki klientowi to osobny, nierozpoczęty jeszcze wątek.

# Plan: GovAI multi-tenant (SaaS)

Status: plan zatwierdzony 2026-11-01, realizacja etapami (każdy etap = PR do
`develop` + test na INT). Wzorzec: CRMtree (opis różnic niżej).

## Decyzje

| Obszar | Decyzja |
|---|---|
| Izolacja danych | Wspólna baza, `tenant_id` we wszystkich tabelach danych klienta + **Row Level Security** w Postgresie jako druga linia obrony |
| Adresy | Subdomeny `{slug}.govai.pl` (PROD), `{slug}.int.govai.pl` (INT); `app.govai.pl` — logowanie uniwersalne i panel super-admina |
| Ustalanie organizacji | Zawsze z rekordu użytkownika (JWT `tenant_id` + odczyt z bazy przy każdym żądaniu); w gatewayu z klucza API. Subdomena = branding/język + blokada niezgodności (403) |
| Użytkownicy | Jedno konto = jedna organizacja; e-mail unikalny w obrębie organizacji |
| Klucze LLM | Klucze platformy (domyślnie) + opcjonalnie własne klucze organizacji (szyfrowane w bazie, klucz szyfrujący w Key Vault) |
| Zakładanie organizacji | Ręcznie przez super-admina platformy (bez samodzielnej rejestracji) |
| Limity / rozliczenia | Na razie brak |
| Środowisko SaaS | PROD (`govai.pl`, `infra/params/prod.bicepparam`); testy na INT |
| DNS | Strefa `govai.pl` z home.pl do Cloudflare (jak `crmtree.pl`) — wymagane dla certyfikatu `*.govai.pl` (DNS-01) |
| Tryb dedykowany | Zostaje — ten sam kod z jedną organizacją |

### Różnice względem CRMtree (świadome ulepszenia)

- CRMtree nie ma RLS — izolacja zależy wyłącznie od ręcznego `AND tenant_id = $n`
  w każdym zapytaniu (były realne wycieki). GovAI: filtr w zapytaniach **i** RLS.
- Dziennik audytowy faktycznie niezmienny (odebrane `UPDATE/DELETE` roli aplikacji).
- Zawieszenie organizacji sprawdzane spójnie przy każdym żądaniu (w CRMtree tylko część ścieżek).
- Testy izolacji dla każdego endpointu w CI (CRMtree: wybiórczo).

## Etapy

### Etap 0 — poprawki bezpieczeństwa (niezależne od multitenancy)
- `/ws/live-feed` wymaga access tokenu (`?token=`).
- Gateway: klucz API przypisany do agenta działa tylko dla tego agenta.
- Providerzy: `api_key_env` tylko z białej listy kluczy platformy, nigdy razem z własnym `base_url`.
- Rejestr migracji (`schema_migrations`, `infra/scripts/migrate.sh`), `ON_ERROR_STOP`, migracja w transakcji.
- `003_providers.sql` idempotentna + `014_dedupe_providers.sql` (na INT po 7 kopii providerów).

### Etap 1 — model danych
- `tenants` (id, slug, nazwa, status active/suspended, `deleted_at`, `default_locale`, created_at); `users.is_super_admin`.
- `tenant_id NOT NULL` + FK: agents, policies, oversight_queue, audit_log (hypertable), users, api_keys, refresh_tokens, app_settings_audit.
- Unikalności per organizacja: `(tenant_id, email)`, `(tenant_id, policy_code)`; indeksy z `tenant_id` na początku.
- Katalogi globalne z nadpisaniem: `providers` (`tenant_id NULL` = platforma, tylko odczyt dla organizacji),
  `ai_act_requirements` (katalog platformy + własne/nadpisania organizacji),
  `app_settings` (definicje globalne + wartości per organizacja, klucz `(tenant_id, key)`).
- Backfill: istniejące dane → organizacja `govai-demo`; zastąpienie stałych UUID z seedów.
- RLS: polityki `tenant_id = current_setting('app.tenant_id')::uuid` (+ `OR tenant_id IS NULL` dla katalogów);
  rola aplikacji bez `BYPASSRLS`, osobna rola platformy dla zadań tła i super-admina;
  `REVOKE UPDATE, DELETE ON audit_log` dla roli aplikacji.

### Etap 2 — API
- JWT z `tenant_id`; `get_current_user` sprawdza status organizacji przy każdym żądaniu; blokada subdomena ≠ organizacja (403).
- Połączenie z bazą per żądanie z `SET LOCAL app.tenant_id` (zależność FastAPI); przepisanie ~100 zapytań w repozytoriach i serwisach.
- Per organizacja: cache parametrów, domyślny język, kanały Redis `t:{tenant}:*`, klucz LLM do raportów/klasyfikatora.
- Symulator demo tylko w obrębie organizacji; reset bez kasowania dziennika.

### Etap 3 — Gateway
- Organizacja z klucza API (lub JWT); agent musi należeć do organizacji (i do klucza).
- Polityki, parametry, wybór providera per organizacja (cache z kluczem organizacji).
- Dziennik i kolejka nadzoru z `tenant_id`; zdarzenia na kanały organizacji; pętla TTL jako zadanie platformy.

### Etap 4 — panele
- Super-admin (`app.govai.pl`): organizacje — lista, zakładanie (slug, nazwa, język, pierwszy admin z hasłem tymczasowym),
  zawieszanie, miękkie usuwanie, wejście w kontekst organizacji (zapis w audycie).
- Admin organizacji: użytkownicy, klucze API agentów (endpointy są, brak UI), providerzy z własnymi kluczami.

### Etap 5 — subdomeny i infrastruktura
- Cloudflare: strefa `govai.pl`, rekordy `*.govai.pl`, `*.int.govai.pl`.
- Caddy z modułem `caddy-dns/cloudflare` (własny obraz), certyfikat wildcard; zarezerwowane slugi (app, www, api, int, admin…).
- Frontend: adresy API/WS liczone w przeglądarce (względne `/api`), publiczny endpoint nazwy/języka organizacji dla ekranu logowania; CORS przez regex.

### Etap 6 — PROD jako host SaaS
- Instancja `rg-govai-prod`, sekrety w Key Vault (klucz szyfrujący, token Cloudflare).
- Przeniesienie landingu i `govai.pl` z INT na PROD.
- Kopie zapasowe bazy z procedurą odtworzenia (dziś brak).

### Etap 7 — testy w CI
- Integracyjne z Postgresem: dwie organizacje, każdy endpoint krzyżowo (B → 404); RLS blokuje zapytanie bez filtra;
  gateway: klucz ↔ agent ↔ organizacja; migracje na świeżej bazie.

### Etap 8 — dokumentacja i spójność
- `ENVIRONMENTS.md`, `docs/`; artykuł na blogu krytykujący multi-tenant → „jak robimy to bezpiecznie (RLS)”.

## Poza zakresem tej wersji
Limity planów, rozliczenia, samodzielna rejestracja, członkostwo w wielu organizacjach,
eksport organizacji do instancji dedykowanej (obiecany na landing page — później).

## Otwarte
- Przeniesienie strefy DNS `govai.pl` do Cloudflare (zmiana NS w panelu home.pl — właściciel domeny).
- Pierwszy klient: nazwa, slug, termin startu.
- Dane z INT jako organizacja demonstracyjna `govai-demo`.

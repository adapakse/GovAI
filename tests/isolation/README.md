# Testy izolacji organizacji (multitenancy)

Testy czarnoskrzynkowe działającego stosu: API, gateway, WebSocket i baza (RLS).
Sprawdzają, że organizacja nie widzi, nie zmienia i nie wykorzystuje danych innej organizacji.

## Uruchomienie

Wymagany działający stos (`docker compose up -d` w katalogu repozytorium). Potem:

```sh
sh tests/isolation/run.sh                    # wszystkie testy
sh tests/isolation/run.sh test_gateway.py    # jeden plik
sh tests/isolation/run.sh -k rls -x          # dowolne argumenty pytest
```

`run.sh`:
- czyta `DB_PASSWORD` (rola `govai`) i `DB_APP_PASSWORD` (rola `govai_app`) z `.env`,
- wykrywa sieć kontenera `govai-api-1` (np. `govai_default`) i odczytuje z niego `TENANT_BASE_DOMAINS`,
- uruchamia jednorazowy kontener `python:3.12-slim` w tej sieci z zamontowanym `tests/`
  (pip cache w wolumenie `govai-isolation-pip-cache`).

W kontenerze: API `http://api:8000`, gateway `http://gateway:8001`, Postgres `postgres:5432`
(nadpisywane zmiennymi `GOVAI_API_URL`, `GOVAI_GATEWAY_URL`, `GOVAI_DB_HOST`;
nazwę kontenera API i sieć: `API_CONTAINER`, `GOVAI_NETWORK`).

## Dane testowe

`conftest.py` tworzy na sesję dwie świeże organizacje A i B (slug `iso-test-<a|b>-<losowy>`),
SQL-em jako `govai` (superużytkownik). W każdej: partner (ten sam e-mail w A i B, różne hasła),
it_admin, trzech agentów (model platformy, model własnego providera, model providera drugiej
organizacji), polityka deny ze słowem kluczowym i `policy_code`, klucz API przypięty do agenta,
własne wymaganie AI Act, własny provider, nadpisanie parametru, zadanie nadzoru i wpis audytu.

Po sesji organizacje są usuwane z wszystkimi danymi (audit_log w jednej transakcji z
`app.platform=on` i `app.audit_purge=on`). Pozostałości po przerwanych uruchomieniach
(starsze niż godzina) są sprzątane na starcie.

## Pliki

| Plik | Zakres |
|---|---|
| `test_login.py` | wspólny e-mail w A i B — hasło wybiera konto; 409 przy identycznym haśle; subdomeny (pomijane bez `TENANT_BASE_DOMAINS`) |
| `test_api_cross_access.py` | token A na zasobach B (i odwrotnie) → 403/404, stan B bez zmian (SQL); klucz API / polityka z agentem B → 404 |
| `test_api_lists.py` | listy i agregaty bez identyfikatorów drugiej organizacji; wiersze platformy widoczne dla obu |
| `test_api_writes.py` | parametry per organizacja, `tenant_id` zasobów tworzonych przez API, katalog platformy tylko do odczytu, `/demo/*` → 403 |
| `test_rls.py` | RLS dla `govai_app`: brak kontekstu → 0 wierszy, brak wierszy B w kontekście A, INSERT z cudzym `tenant_id` → błąd, złożone FK, niezmienny audit_log, brak DDL/TRUNCATE |
| `test_gateway.py` | klucz/JWT A z agentem B → 403, polityki i providerzy B nie działają dla A, audit_log z właściwym `tenant_id`, izolacja WebSocket live-feed |

Testy oznaczone `xfail` dokumentują znane błędy aplikacji niezwiązane z wyciekiem danych
(opis w powodzie `xfail`); po naprawie zaczną przechodzić (XPASS).

Lokalny klucz Anthropic jest zaślepką — dozwolone wywołania gatewaya kończą się 502 (błąd modelu);
testy sprawdzają tylko, że to nie 401/403 i że audyt trafia do właściwej organizacji.

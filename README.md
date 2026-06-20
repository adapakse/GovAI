# GovAI

**Platforma nadzoru i zgodności agentów AI z EU AI Act.**

GovAI stoi pomiędzy Twoimi agentami AI a dostawcami modeli. Każde wywołanie jest
skanowane pod kątem danych osobowych (PII), oceniane przez silnik polityk,
kierowane do właściwego dostawcy w zależności od wrażliwości danych i zapisywane
w niezmiennym dzienniku audytowym — zgodnie z wymogami Rozporządzenia UE w sprawie
sztucznej inteligencji (AI Act).

---

## Architektura

```
   Agent AI
      │  POST /v1/chat/completions  (zgodne z OpenAI API)
      ▼
┌─────────────────┐     skan PII → silnik polityk → wybór dostawcy → audyt
│  Gateway :8001  │ ──────────────────────────────────────────────────────►  Anthropic / DeepSeek
└─────────────────┘
      │                                   ▲
      ▼                                   │ polityki, rejestr, nadzór
┌─────────────────┐                ┌──────┴──────────┐
│ PostgreSQL +    │ ◄──────────────│   API  :8000    │ ◄──── Frontend :4000 (Next.js)
│ TimescaleDB     │                └─────────────────┘
│ Redis           │
└─────────────────┘
```

| Usługa | Port | Opis |
|--------|------|------|
| **gateway** | 8001 | Bramka bezpieczeństwa — proxy zgodne z OpenAI Chat Completions. Skan PII, egzekwowanie polityk, routing dostawców, audyt. |
| **api** | 8000 | Panel zarządzania — rejestr agentów, polityki, nadzór człowieka, dziennik audytowy, raporty zgodności, uwierzytelnianie. |
| **frontend** | 4000 | Konsola webowa (Next.js): logowanie, dashboard, rejestr, polityki, audyt, nadzór, raporty. |
| **postgres** | — | TimescaleDB (PG16) — dane aplikacji + szereg czasowy dziennika audytowego. |
| **redis** | — | Live-feed dashboardu oraz kolejka/TTL zadań nadzoru człowieka. |

---

## Kluczowe funkcje

- **Bramka bezpieczeństwa** — agenci wołają `/v1/chat/completions` zamiast dostawcy
  bezpośrednio; identyfikują się nagłówkiem `X-Agent-ID`.
- **Skaner PII** — wykrywa dane osobowe w treści wywołań przed wysłaniem do modelu.
- **Silnik polityk** — reguły `allow` / `block` / `oversight_required` egzekwowane
  w locie; reguły odświeżane z bazy co 60 s bez restartu bramki.
- **Routing wielodostawcowy** — automatyczny wybór dostawcy modelu na podstawie
  klasyfikacji wrażliwości danych (`/providers`, `gateway/services`).
- **Klasyfikator AI Act** — automatyczna ocena poziomu ryzyka agenta:
  `unacceptable` (art. 5) · `high` (Aneks III) · `limited` (art. 50) · `minimal`.
- **Nadzór człowieka (HITL)** — wywołania oznaczone `oversight_required` trafiają
  do kolejki recenzenta z minimalnym czasem przeglądu.
- **Dziennik audytowy** — niezmienny zapis każdego wywołania (TimescaleDB).
- **Raporty zgodności** — generowanie raportów per-agent oraz korporacyjnych.
- **RBAC** — uwierzytelnianie JWT z rolami: `partner`, `it_admin`,
  `compliance_officer`, `associate`, `reviewer`.

---

## Szybki start

Wymagania: Docker + Docker Compose.

```bash
# 1. Skonfiguruj zmienne środowiskowe
cp .env.example .env
# Uzupełnij ANTHROPIC_API_KEY i wygeneruj JWT_SECRET:
#   python -c "import secrets; print(secrets.token_hex(32))"

# 2. Uruchom cały stos
docker compose up --build
```

Po starcie:

- Konsola: <http://localhost:4000>
- API + dokumentacja: <http://localhost:8000/docs>
- Bramka + dokumentacja: <http://localhost:8001/docs>

### Zmienne środowiskowe

| Zmienna | Wymagana | Opis |
|---------|----------|------|
| `ANTHROPIC_API_KEY` | tak | Klucz API Anthropic (domyślny dostawca). |
| `JWT_SECRET` | tak | Sekret JWT — **identyczny** dla `api` i `gateway`. Wygeneruj losowy 32-bajtowy hex. |
| `DB_PASSWORD` | nie | Hasło do PostgreSQL (domyślnie `govai_secret`). |
| `DEEPSEEK_API_KEY` | nie | Klucz alternatywnego dostawcy (routing wielodostawcowy). |
| `DEMO_MODE` | nie | `true` → bramka zwraca gotowe odpowiedzi bez wywoływania dostawcy. |
| `LOG_LEVEL` | nie | Poziom logowania (domyślnie `INFO`). |

---

## Przykład wywołania przez bramkę

```bash
curl http://localhost:8001/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "X-Agent-ID: <UUID agenta z rejestru>" \
  -H "Authorization: Bearer <token JWT>" \
  -d '{
    "model": "claude-haiku-4-5-20251001",
    "messages": [{"role": "user", "content": "Podsumuj tę umowę."}]
  }'
```

Bramka przeskanuje treść, zastosuje polityki, wybierze dostawcę, zapisze wpis
audytowy i zwróci odpowiedź modelu (lub zablokuje / skieruje do nadzoru).

---

## Struktura repozytorium

```
gateway/      Bramka bezpieczeństwa (FastAPI) — proxy, PII, polityki, routing, audyt
  services/   provider_selector, data_sensitivity
api/          API panelu zarządzania (FastAPI)
  routers/    auth, agents, policies, compliance, oversight, audit,
              dashboard, reports, providers, demo
  services/   ai_act_classifier, compliance, auth_service, report_generator,
              enterprise_report
  dependencies/  auth (JWT, RBAC)
frontend/     Konsola webowa (Next.js + Tailwind)
db/           Schemat init.sql + migracje (002_auth, 003_providers, ...)
branding/     Logo, favicon, przewodnik marki
```

---

## Stos technologiczny

Python · FastAPI · PostgreSQL/TimescaleDB · Redis · Next.js · TypeScript · Tailwind · Docker

---

## Uwagi bezpieczeństwa

- `JWT_SECRET` w plikach konfiguracyjnych to wyłącznie placeholder — prawdziwy sekret
  trzymaj tylko w `.env` (ignorowany przez Git).
- Plik `.env` oraz lokalne skrypty deweloperskie nie są wersjonowane.
- W produkcji ogranicz `allowed_origins` (CORS) do domeny kancelarii.

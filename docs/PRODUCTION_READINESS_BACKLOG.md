# GovAI — backlog uprodukcyjnienia (stan: 2026-08-11)

Skonsolidowany plan pracy przed pierwszym wdrożeniem u klienta. Łączy przegląd
techniczny (Dockerfile/CORS/sekrety/testy/CI) z wątkiem zgodności AI Act i
modelu dystrybucji przez kancelarię partnerską. Faza 0 (uporządkowanie
schematu DB, dwa środowiska wewnętrzne) już zrobiona — patrz `ENVIRONMENTS.md`.

Legenda priorytetu: 🔴 blokujące (nie wolno wysłać klientowi bez tego) ·
🟡 ważne przed pierwszym płatnym wdrożeniem · 🟢 może poczekać do kolejnej iteracji.

---

## Faza 1 — Hardening bezpieczeństwa runtime

| # | Zadanie | Priorytet | Uwagi |
|---|---------|-----------|-------|
| 1.1 | `frontend/Dockerfile`: `npm run build && npm start` zamiast `npm run dev` | 🔴 | dziś kontener produkcyjny serwuje dev-server Next.js |
| 1.2 | `allowed_origins` (CORS) jako zmienna env, nie hardcode w `api/config.py` | 🔴 | blokuje konfigurację per-klient bez zmiany kodu |
| 1.3 | Non-root `USER` w Dockerfile'ach gateway/api/frontend | 🟡 | dziś wszystkie kontenery chodzą jako root |
| 1.4 | TLS — reverse proxy (Caddy/nginx) dopięty do `docker-compose.yml` | 🔴 | dziś same porty HTTP, nic nie terminuje TLS w stosie |
| 1.5 | **Abstrakcja "secrets provider"** w kodzie (jedna warstwa, dwa backendy) | 🔴 | patrz sekcja *Sekrety* niżej — fundament dla 1.6/1.7 |
| 1.6 | Backend A: sekrety klienta (self-hosted) — plikowe montowanie (`secrets:` w compose) + opcjonalny fetch z zewnętrznego vaulta klienta (Key Vault/Secrets Manager/HashiCorp Vault) przez init-skrypt | 🟡 | fallback: `.env` chmod 600, GovAI nigdy nie przechowuje kopii sekretu klienta |
| 1.7 | Backend B: sekrety GovAI Azure — Key Vault per klient + Managed Identity, private endpoint, RBAC, soft-delete + purge protection | 🔴 (tylko gdy hostujemy) | dotyczy wyłącznie modelu "instancja na naszym Azure" |
| 1.8 | Runbook rotacji `JWT_SECRET` (dziś unieważnia sesje — brak dual-key) | 🟡 | |
| 1.9 | Provider API keys — zalecenie kluczy scoped/budget-capped per klient (nie master org key) | 🟡 | do runbooka wdrożeniowego (Faza 2) |
| 1.10 | `.dockerignore` dla wszystkich trzech serwisów | 🟢 | brak dziś w repo |
| 1.11 | Przegląd `security-review` na całość diffu po 1.1–1.7 | 🔴 | przed jakimkolwiek audytem zewnętrznym (Faza 5) |

## Faza 2 — Packaging pod wysyłkę do klienta

| # | Zadanie | Priorytet |
|---|---------|-----------|
| 2.1 | Skrypt instalacyjny "jedna komenda" (`.env.example` → generacja sekretów lokalnie u klienta → `docker compose up`) | 🔴 |
| 2.2 | Tryb offline dla modelu Bielik — dziś `ollama-init` ciągnie z HuggingFace CDN w runtime; ryzykowne dla klienta bez wyjścia do internetu (częste przy on-prem/AI Act) | 🟡 |
| 2.3 | Runbook wdrożeniowy dla admina klienta — dwie ścieżki: (a) infrastruktura klienta, (b) instancja na Azure GovAI, z osobnym opisem obsługi sekretów dla każdej (1.6 vs 1.7) | 🔴 |
| 2.4 | Healthchecki w `docker-compose.yml` dla `gateway`/`api`/`frontend` (dziś tylko postgres/redis/ollama je mają) | 🟡 |
| 2.5 | Checklist compliance AI Act do przekazania klientowi razem z wdrożeniem | 🟢 | powiązane z Fazą 5 |

## Faza 3 — Ops / observability

| # | Zadanie | Priorytet |
|---|---------|-----------|
| 3.1 | Structured logging + kolektor (choćby lokalny stack, np. Loki/ELK — do ustalenia z klientem czy chce własny) | 🟡 |
| 3.2 | Backup/restore Postgresa — skrypt + harmonogram, udokumentowana procedura DR | 🔴 |
| 3.3 | Alerting na błędy bramki/audytu | 🟢 |

## Faza 4 — Testy i CI

| # | Zadanie | Priorytet |
|---|---------|-----------|
| 4.1 | Rozszerzenie testów — dziś tylko 2 pliki (`gateway/tests`: PII scanner, policy engine), zero testów API i frontendu | 🟡 |
| 4.2 | Pipeline CI (GitHub Actions): lint + testy + build obrazów | 🟡 |

## Faza 5 — Weryfikacja zgodności AI Act (ścieżka partnerska — Kancelaria)

Może iść **równolegle** z Fazą 3/4, ale wymaga stabilnego stanu po Fazie 1 (audyt bezpieczeństwa nie ma sensu przed 1.1–1.7).

| # | Zadanie | Priorytet |
|---|---------|-----------|
| 5.1 | Pakiet dokumentacji technicznej + macierz funkcja→artykuł AI Act | 🔴 |
| 5.2 | Środowisko sandbox udostępnione Kancelarii do własnych testów | 🔴 |
| 5.3 | Niezależny audyt zewnętrzny (bezpieczeństwo + opinia prawna) | 🔴 |
| 5.4 | Raport końcowy + plan naprawczy luk | 🔴 |
| 5.5 | Cykliczny re-audyt (rocznie / przy istotnej zmianie funkcjonalnej) | 🟢 |

## Faza 6 — Formalizacja partnerstwa dystrybucyjnego

| # | Zadanie | Priorytet |
|---|---------|-----------|
| 6.1 | NDA + ramowe porozumienie z Kancelarią | 🔴 |
| 6.2 | Mechanizm atrybucji poleceń (kod partnerski / rejestr, po stronie ops GovAI, nie produktu — brak SaaS multitenant, więc to CRM/billing, nie kod aplikacji) | 🟡 |
| 6.3 | Umowa partnerska z warunkami komercyjnymi (prowizja malejąca w czasie) | 🔴 |

## Faza 7 — Pilotaż

| # | Zadanie | Priorytet |
|---|---------|-----------|
| 7.1 | Wdrożenie u 2–3 pierwszych klientów poleconych przez Kancelarię | 🔴 |
| 7.2 | Zbiórka feedbacku, iteracja na backlogu | 🟢 |

---

## Zależności między fazami

- Faza 1 blokuje Fazę 5.3 (audyt bez sensu na niehardened kodzie) i Fazę 7 (nie wysyłamy klientowi `npm run dev`).
- Faza 2 blokuje Fazę 7 (nie ma czym wdrożyć bez instalatora i runbooka).
- Faza 5 i Faza 6 mogą iść równolegle z Fazą 3/4 — to ścieżka biznesowa/prawna, nie inżynierska.
- Faza 4 (testy/CI) nie blokuje pilotażu wprost, ale silnie obniża ryzyko regresji przy szybkim tempie zmian pod pilotaż — rekomendowane przed 7.1, nie po.

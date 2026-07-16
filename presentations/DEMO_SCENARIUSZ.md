# GovAI — Scenariusz demonstracji

> Dokument dla osoby prowadzącej demo. Część A — co i jak system pokazuje.
> Część B — przygotowanie środowiska (checklista). Część C — przebieg krok po kroku.

---

## A. Co demonstrujemy i dlaczego

**Problem:** Firma wdraża agentów AI. EU AI Act wymaga: nadzoru człowieka nad
systemami wysokiego ryzyka (art. 14), ochrony danych osobowych, rejestru
systemów, dziennika zdarzeń i udokumentowanej zgodności. Bez kontroli każdy
agent to ryzyko regulacyjne i wyciek danych.

**Rozwiązanie GovAI:** bramka, przez którą przechodzi **każde** wywołanie agenta.
Zanim zapytanie trafi do modelu, system:

1. **Weryfikuje agenta** w rejestrze (status aktywny / zawieszony).
2. **Skanuje PII** (Presidio) — maskuje PESEL, IBAN, NIP itp. przed wysłaniem do modelu.
3. **Egzekwuje polityki** — reguły słów kluczowych blokują niedozwolone operacje.
4. **Klasyfikuje wrażliwość danych** i **dobiera providera** (chmura vs on‑prem).
5. **Kieruje do nadzoru człowieka** decyzje agentów wysokiego ryzyka.
6. **Zapisuje wszystko** w niezmiennym dzienniku audytowym (TimescaleDB).

Demo pokazuje to na 3 agentach banku „TrustBank":

| Agent | Model | Ryzyko AI Act | Zachowanie |
|-------|-------|---------------|------------|
| **A1** Asystent Obsługi Klienta | claude-haiku | ograniczone | przepuszcza, maskuje PII, blokuje nadużycia |
| **A2** Agent Oceny Kredytowej | claude-sonnet | **wysokie** | każda decyzja → nadzór człowieka (art. 14) |
| **A3** Agent Rekrutacji | claude-sonnet | **wysokie** | nadzór + blokada prompt‑injection w CV |

---

## B. Przygotowanie środowiska (przed demo)

> Wykonać **raz**, najlepiej 15–20 min przed prezentacją. Wszystko z katalogu projektu.

### B1. Konfiguracja `.env`
```
cp .env.example .env
```
Ustaw w `.env`:
- `JWT_SECRET` — dowolny losowy 32‑bajtowy hex (`python -c "import secrets; print(secrets.token_hex(32))"`). **Ten sam** dla API i bramki (compose podaje go obu).
- **Tryb modelu — wybierz jeden:**
  - **Demo bez kosztów (zalecane):** `DEMO_MODE=true` — bramka zwraca gotowe odpowiedzi zamiast wołać Anthropic. Skan PII, polityki, nadzór i audyt **działają normalnie** (dzieją się przed wywołaniem modelu). Nie wymaga klucza API.
  - **Demo „na żywo":** `ANTHROPIC_API_KEY=sk-ant-...` i `DEMO_MODE=false` — realne odpowiedzi modelu (kosztuje grosze, scenariusze „pozytywny" i „PII" zwracają prawdziwą treść).

### B2. Uruchomienie i migracje
```
docker compose up -d --build           # WAŻNE: --build, by bramka miała aktualny kod
# zastosuj migracje (NIE są auto-stosowane). NIGDY przez Get-Content -Raw | ... psql —
# w Windows PowerShell 5.1 pipe do procesu natywnego psuje polskie znaki (zob. memoria
# deploy-migrations-gotchas). Zawsze przez docker cp + psql -f:
$env:MSYS_NO_PATHCONV = "1"   # tylko jeśli używasz Git Bash zamiast PowerShell
foreach ($f in "002_auth","003_providers","004_settings","005_settings_audit","006_requirements_dynamic","007_audit_error_result","008_fix_text_encoding") {
  docker cp "db/migrations/$f.sql" govai-postgres-1:/tmp/m.sql
  docker compose exec -T postgres psql -U govai -d govai -f /tmp/m.sql
}
```
Sprawdź zdrowie: `http://localhost:8000/health` i `http://localhost:8001/health` → `200`.

### B3. Konta
- **Partner (właściciel biznesowy):** `admin@kancelaria.local` / `GovAI2026Admin`
- **IT Admin (do panelu Parametry):** `it@kancelaria.local` / `GovAI2026Admin`
  (jeśli nie istnieje — zaloguj się jako partner, *Agenci/Użytkownicy* lub utwórz przez API `POST /auth/users`).
- Zmień domyślne hasła, jeśli demo jest publiczne.

### B4. Dane historyczne
1. Wejdź na `http://localhost:4000` → zaloguj jako partner.
2. **Symulator** → kliknij **„▦ Zasil 30 dni danych"** → potwierdzenie: ~500 wpisów audytu + ~23 pozycje nadzoru.
   To wypełnia Pulpit, Dziennik i kolejkę Nadzoru realistycznymi danymi z 30 dni.

### B5. Karty w przeglądarce (otwórz przed startem)
Pulpit · Agenci · Polityki · Nadzór · Dziennik · Providerzy · **Parametry** · **Symulator**.
Trzymaj **Symulator** jako kartę „sterującą" — stąd odpalasz scenariusze.

### B6. Szybki test „na sucho" (2 min przed widownią)
Symulator → przy agencie A1 uruchom **„Próba mutacji finansowej"** → oczekiwane:
status **Zablokowane (G‑001)**. Jeśli działa — środowisko gotowe.

> Symulator ma wbudowany **„Przewodnik Demo — 7 kroków"** (rozwijany u góry). Można go pokazać widowni jako agendę.

---

## C. Przebieg demonstracji (krok po kroku)

Czas: ~15–20 min. Każdy akt: **cel → co robisz → co dzieje się w systemie → co pokazać**.

### Akt 1 — Kontekst i Pulpit (2 min)
- **Cel:** pokazać skalę i kontrolę „z lotu ptaka".
- **Robisz:** otwórz **Pulpit**.
- **System:** agreguje 30 dni z dziennika — łączne wywołania, blokady, wykrycia PII, koszty (EUR), liczba oczekujących w nadzorze, top agenci, wykres 24 h, ostatnie alerty.
- **Pokaż/powiedz:** „Każde wywołanie każdego agenta jest tu widoczne. X blokad, Y zamaskowanych danych osobowych, Z decyzji skierowanych do człowieka — wszystko bez dotykania kodu agentów."

### Akt 2 — Rejestr i klasyfikacja AI Act (2 min)
- **Cel:** pokazać, że system „rozumie" ryzyko regulacyjne.
- **Robisz:** **Agenci** → otwórz **A2 Agent Oceny Kredytowej**.
- **System:** przy rejestracji klasyfikator (Claude) przypisał poziom ryzyka, kategorię z Aneksu III i podstawę prawną; agent ma włączony wymóg nadzoru.
- **Pokaż:** poziom **WYSOKIE**, zakładka zgodności/raport — luki i obowiązki wg artykułów (art. 9, 10, 12, 13, 14...). „System sam sklasyfikował agenta jako wysokiego ryzyka i wie, jakie obowiązki z tego wynikają."

### Akt 3 — Wywołanie „czyste" (allowed) (1–2 min)
- **Cel:** happy path — bramka nie przeszkadza, gdy wszystko jest OK.
- **Robisz:** **Symulator** → A1 → **„Zapytanie o ubezpieczenie"** → *Uruchom ▶*.
- **System:** brak PII, brak naruszeń → wybór providera wg wrażliwości → odpowiedź modelu → wpis w dzienniku.
- **Pokaż:** zielony status **Dozwolone**, treść odpowiedzi, link **→ Dziennik** (świeży wpis).

### Akt 4 — Ochrona danych osobowych (PII) (2 min)
- **Cel:** RODO/PII w praktyce.
- **Robisz:** A1 → **„Klient podaje PESEL i numer konta"** → *Uruchom ▶*.
- **System:** Presidio wykrywa PESEL i IBAN i **maskuje** je (`[PESEL]`, `[IBAN]`) zanim cokolwiek trafi do modelu. Wpis audytu odnotowuje kategorie PII.
- **Pokaż:** status **Dozwolone + PII**; w Dzienniku wpis z wykrytymi kategoriami. „Model nigdy nie zobaczył surowego PESEL‑u — został zamaskowany w bramce."

### Akt 5 — Blokada nadużycia: mutacja finansowa (G‑001) (1–2 min)
- **Cel:** polityka bezpieczeństwa zatrzymuje niebezpieczną operację.
- **Robisz:** A1 → **„Próba mutacji finansowej"** → *Uruchom ▶*.
- **System:** silnik polityk dopasowuje słowo kluczowe („zmień saldo") z reguły **G‑001** i **blokuje przed wywołaniem modelu**.
- **Pokaż:** czerwony status **Zablokowane**, komunikat polityki, wpis w Dzienniku z powodem.

### Akt 6 — Blokada prompt‑injection (G‑002) (1 min)
- **Robisz:** A1 → **„Atak prompt injection"** → *Uruchom ▶* (albo A3 → „CV z atakiem injection").
- **System:** reguła **G‑002** wykrywa „ignore previous instructions" i blokuje natychmiast.
- **Pokaż:** **Zablokowane (G‑002)**. „Klasyczny atak na agenta — zatrzymany, zanim dotarł do modelu."

### Akt 7 — Nadzór człowieka (art. 14) (3 min) — *punkt kulminacyjny*
- **Cel:** Human‑in‑the‑loop dla decyzji wysokiego ryzyka.
- **Robisz:** A2 → **„Dobry wniosek kredytowy"** → *Uruchom ▶*. Następnie przejdź do **Nadzór**.
- **System:** agent wysokiego ryzyka nie kończy decyzji sam — wywołanie trafia do **kolejki nadzoru** z licznikiem TTL (eskalacja, jeśli nikt nie zatwierdzi).
- **Pokaż:**
  1. W **Nadzór** pojawia się pozycja oczekująca. Otwórz ją, „Rozpocznij przegląd".
  2. **Zatwierdź zbyt szybko** (poniżej progu) → system zgłasza **alert pozornego nadzoru („rubber‑stamp")** — wykrywa, że recenzent kliknął bez realnej analizy.
  3. Zatwierdź normalnie — decyzja zostaje wykonana, ślad w Dzienniku.
- **Powiedz:** „System nie tylko wymusza nadzór — pilnuje też, czy nadzór jest realny."

### Akt 8 — Polityki bez kodu (2 min)
- **Cel:** zgodność konfigurowalna przez biznes, nie przez programistów.
- **Robisz:** **Polityki** → otwórz regułę → dodaj nowe słowo kluczowe (np. `przelej wszystkie środki`) → **Zapisz**. (Możesz też dodać całą nową regułę.)
- **System:** bramka **odświeża reguły z bazy co 60 s** — bez restartu. Po chwili nowa fraza blokuje.
- **Pokaż:** (opcjonalnie) w Symulatorze wpisz wiadomość z nową frazą → **Zablokowane**. „Compliance officer zmienił regułę w 10 sekund, bez wdrożenia."

### Akt 9 — Routing wielodostawcowy (1–2 min)
- **Cel:** dane wrażliwe nie wychodzą tam, gdzie nie powinny.
- **Robisz:** **Providerzy** — pokaż listę (Anthropic, OpenAI, DeepSeek, Google, Bielik on‑prem) z **maksymalnym poziomem wrażliwości** każdego.
- **System:** klasyfikuje wrażliwość zapytania i dobiera providera — np. dane objęte tajemnicą → tylko provider on‑prem; DeepSeek (serwery poza UE) → wyłącznie dane publiczne.
- **Pokaż:** „Ten sam agent, ale dane poufne trafią do innego, bezpieczniejszego modelu — automatycznie."

### Akt 10 — Parametry bez wdrożenia (1–2 min) — *nowość*
- **Cel:** strojenie systemu w locie przez administratora.
- **Robisz:** wyloguj się i zaloguj jako **it_admin** → **Parametry**.
- **System:** wszystkie progi i stawki są w bazie; zmiana propaguje do API i bramki w ≤60 s.
- **Pokaż:**
  - zmień np. **„Min. czas przeglądu"** (nadzór) lub **stawkę cennika** → zapisz;
  - (RBAC) zaloguj jako partner → wejdź w **Parametry** → tryb **podglądu**, edycja zablokowana. „Tylko IT może zmieniać parametry techniczne — role są egzekwowane."

### Akt 11 — Dziennik i raport zgodności (1–2 min) — *domknięcie*
- **Robisz:** **Dziennik** — pokaż, że każdy akt z demo zostawił niezmienny wpis (PII, blokady, nadzór, koszty). Następnie **Agenci → A2 → Raport** (PDF/zgodność).
- **System:** generuje raport zgodności agenta z lukami i planem naprawczym wg AI Act.
- **Pokaż:** „Pełna ścieżka audytowa i gotowy raport dla regulatora — dowód, że firma panuje nad swoimi agentami."

---

## D. Puenta (zamknięcie)
> „Pokazaliśmy jeden bank z trzema agentami. GovAI skaluje to na setki agentów:
> jedna bramka, jeden dziennik, jedna konsola — pełna zgodność z EU AI Act bez
> przepisywania kodu agentów. To różnica między *mamy AI* a *panujemy nad AI*."

---

## E. Plan awaryjny (gdy coś nie działa)
- **Scenariusz „na żywo" zwraca błąd modelu / 502** → przełącz `DEMO_MODE=true` w `.env`, `docker compose up -d gateway`. Blokady, PII, nadzór działają dalej.
- **`/providers` lub `/settings` → 500/404** → brak migracji 003/004 — zastosuj (B2).
- **Bramka odrzuca wywołania (401)** → bramka wymaga autoryzacji; Symulator dokłada token automatycznie. Jeśli wołasz bramkę spoza panelu — wystaw klucz w *Auth → API keys*.
- **Login pętli / token błędny** → odśwież twardo (Ctrl+Shift+R), zaloguj ponownie.
- **Pulpit pusty** → nie zasilono danych: Symulator → „Zasil 30 dni danych".
- **Reset stanu między próbami** → Symulator → „Resetuj dane", potem ponownie „Zasil".

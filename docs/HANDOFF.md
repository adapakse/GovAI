# GovAI — przekazanie projektu (stan na 2026-11-04)

Dla: **Kacper** (developer) i jego agenta Claude Code. Od: Adam (właściciel projektu).
Ten dokument + `CLAUDE.md` (zasady pracy w repo) wystarczą agentowi do kontynuacji.
Kolejność lektury: `CLAUDE.md` → ten plik → `docs/multitenancy-plan.md` → `docs/azure-environments-plan.md`
→ `ENVIRONMENTS.md` → `docs/i18n.md`.

## 1. Produkt w skrócie
GovAI = platforma nadzoru i zgodności agentów AI z **EU AI Act** dla kancelarii, działów compliance i IT:
- **rejestr agentów AI** + automatyczna klasyfikacja ryzyka (Claude jako klasyfikator) + ocena luk wobec katalogu wymagań AI Act;
- **bramka bezpieczeństwa** (OpenAI-compatible `/gateway/v1/chat/completions`): skan PII (Presidio + spaCy),
  silnik polityk (słowa kluczowe → blokada / nadzór), routing do dostawcy wg wrażliwości danych, budżety;
- **nadzór człowieka** (kolejka do akceptacji, art. 14), **niezmienny dziennik audytowy**, raporty PDF;
- panel w 10 językach, landing `govai.pl` (+ blog, polityka prywatności) w 11 językach.

Pierwszy klient SaaS: **Gessel** (kancelaria) → organizacja `gessel`, adres docelowy `gessel.govai.pl` na PROD.

## 2. Co jest zrobione

| Obszar | Stan | Gdzie |
|---|---|---|
| Wielojęzyczność (pl, en, de, it, es, fr, ro, ru, sl, hr; landing + pt) | **na INT** | `docs/i18n.md` |
| Multitenancy etap 0 — bezpieczeństwo (WS z tokenem, klucz API ↔ agent, biała lista kluczy providerów, rejestr migracji) | **na INT** (PR #7) | |
| Multitenancy etapy 1–3 — organizacje, **RLS**, rola `govai_app`, API i gateway per organizacja, 194 testy izolacji w CI | **na INT** (PR #8) | `docs/multitenancy-plan.md` |
| Multitenancy etap 4 — panel super-admina (`/platform/*`: organizacje, wejście w organizację, dziennik platformy), hasła tymczasowe + wymuszona zmiana, UI użytkowników i kluczy API, szyfrowane własne klucze LLM organizacji, gateway sprawdza użytkownika | **gotowe, NIESCALONE — PR #9** (CI zielone, 224 testy) | PR #9 |
| Multitenancy etap 5 — subdomeny (Caddy wildcard DNS-01 z Cloudflare, adresy względne we frontendzie, CORS) | **gotowe w PR #9**, wymaga DNS w Cloudflare | `docs/multitenancy-plan.md` |

**Pierwszy krok Kacpra: przejrzeć i (po akceptacji Adama) scalić PR #9 do `develop`, deploy na INT**
(`Actions → Deploy → environment: int`, gałąź `develop`).

## 3. Środowiska — stan obecny vs docelowy

**Obecnie:**
- **Lokalnie**: docker compose (`ENVIRONMENTS.md`, `CLAUDE.md` → „Lokalnie”).
- **INT** (`develop`): VM `vm-govai-int` w `rg-govai-int` (74.248.18.114), Key Vault `kv-govai-int`, Bicep `infra/`,
  deploy: GitHub Actions `deploy.yml` (ręczny `workflow_dispatch`, OIDC `oidc-msi-govai`) → `az vm run-command` →
  `infra/scripts/deploy-remote.sh`. **INT obsługuje dziś publiczne `govai.pl` i `app.govai.pl`.**
- **PROD**: nie istnieje (jest tylko `infra/params/prod.bicepparam` dla modelu VM).

**Docelowo (decyzja Adama):** 3 środowiska — lokalne, **INT na `develop`**, **PROD na `master`** — na
**Azure Container Apps wzorem CRMtree** (ta sama subskrypcja; CRMtree: `rg-crmtree-prod`, `crmtree-env`,
`crmtreeregistry`, `crmtree-vault`, `crmtree-db`, aplikacje PROD i `-int` obok siebie, deploy GitHub Actions
`deploy-int.yml`/`deploy.yml` → ACR → `az containerapp update`). Pełny plan, nazwy zasobów, różnice i poprawki
względem CRMtree: **`docs/azure-environments-plan.md`**. Model VM zostaje jako szablon instancji dedykowanej (klient on-prem / własny Azure).

## 4. Plan prac (kolejność)

### P0 — natychmiast
0. **CRMtree — odnowić certyfikaty wildcard przed 8.11.2026** (procedura: §9). Bez tego przestają działać
   subdomeny wszystkich organizacji CRMtree (`*.crmtree.pl` wygasa 2026-11-08, `*.int.crmtree.pl` 2026-11-10).
1. **Zmienić hasło `admin@kancelaria.local` na INT** — repozytorium jest **publiczne**, hasło startowe jest w
   `db/migrations/002_auth.sql`, a INT obsługuje publiczne `app.govai.pl`. (Po wdrożeniu PR #9 — w UI; przed — `POST /auth/me/password`.)
2. PR #9 → `develop` → deploy INT; zalogować się ponownie (stare tokeny są nieważne).
3. (Adam) Przeniesienie strefy DNS `govai.pl` z home.pl do Cloudflare — rekordy Zoho (MX/SPF/DKIM) bez zmian
   (lista w `docs/azure-environments-plan.md` §3).

### P1 — infrastruktura INT/PROD na Container Apps (`docs/azure-environments-plan.md` §7)
4. Gałąź PROD: `main` → **`master`** (rename w GitHub + odwołania w repo).
5. Zasoby wspólne (`rg-govai-prod`, `govai-env`, `govairegistry`, `govai-vault`, Log Analytics) — jako skrypt/Bicep w `infra/aca/`.
6. Zmiany w kodzie pod Container Apps:
   - `caddy/Caddyfile.edge` + obraz `govai-edge` (routing hostów/ścieżek, landing, `X-Forwarded-Host`);
   - rozpoznawanie organizacji z `X-Forwarded-Host` (API: `services/tenant_host.py`, `dependencies/auth.py`,
     `routers/auth.py`, `routers/public.py`; gateway) + test;
   - `infra/scripts/migrate.sh` — tryb zdalny (psql na Azure Postgres zamiast `docker compose exec`);
   - `DATABASE_URL`/Redis z sekretów KV (`config.py`), mniejsze pule połączeń (B1ms ma 50 połączeń);
   - probe HTTP `/health` (api, gateway).
7. INT na Container Apps: `govai-db-int` (PG 15 + TimescaleDB, `init.sql` + migracje), `govai-redis-int`, aplikacje `-int`,
   domeny `app.int.govai.pl`, `*.int.govai.pl` (Cloudflare proxy + certyfikat Origin CA), workflow `deploy-int.yml` (push `develop`).
8. PROD: `govai-db`, `govai-redis`, aplikacje, domeny `govai.pl`, `app.govai.pl`, `*.govai.pl`, workflow `deploy.yml`
   (push `master`, GitHub Environment `prod` z zatwierdzeniem Adama), backup bazy (rozważ 35 dni).
9. Przełączenie `govai.pl` z VM na PROD; organizacja **Gessel** z panelu super-admina; hasło admina platformy PROD.
10. Wygaszenie VM INT po migracji.

### P2 — dokończenie multitenancy i produktu
11. Nadpisywanie/wyłączanie wymagań platformy (katalog AI Act) przez organizację (dziś tylko własne wymagania).
12. Seed demo z agentami per organizacja (dziś stałe UUID A1–A3 tylko w `govai-demo`).
13. Etap 8: `ENVIRONMENTS.md`, README, artykuł na blogu „dedykowana instancja vs multi-tenant” (dziś krytykuje
    multi-tenant — przepisać na „jak robimy to bezpiecznie: RLS”).
14. Eksport organizacji do instancji dedykowanej (obiecany na landingu) — później.
15. Limity planów / rozliczenia — świadomie poza zakresem (decyzja Adama), wrócić przy kolejnych klientach.

### P3 — jakość treści
16. Tłumaczenia poza pl/en są maszynowe — przegląd native speakerów; polityka prywatności (wszystkie języki) — przegląd prawnika.
17. Katalog wymagań AI Act: art. 50 ust. 4 przy oznaczaniu treści AI (powinien być ust. 2); art. 26 ust. 8 („podmiot publiczny”) — zweryfikować merytorycznie.

## 5. Decyzje podjęte z Adamem (nie zmieniać bez konsultacji)
- Izolacja: wspólna baza + **Row Level Security** (nie schema/baza per klient).
- Subdomeny `{slug}.govai.pl`; `app.govai.pl` = logowanie uniwersalne i panel super-admina.
- Klucze LLM: platformy (domyślnie) + opcjonalnie własne organizacji (szyfrowane).
- Organizacje zakłada super-admin ręcznie (bez samodzielnej rejestracji); jedno konto = jedna organizacja.
- Bez limitów planów i rozliczeń w tej wersji.
- Dane z INT = organizacja demonstracyjna `govai-demo` (jedyna z symulatorem).
- Środowiska: lokalne / INT (`develop`) / PROD (`master`); infrastruktura Azure wzorem CRMtree.
- DNS `govai.pl` → Cloudflare (jak `crmtree.pl`).

## 6. Dostępy do nadania (Adam)
- GitHub `adapakse/GovAI`: Kacper jako collaborator (write). Repo jest publiczne.
- Azure („Azure subscription 1”, tenant `8fc0088b-…`): konto Kacpra (gość) z rolą Contributor na `rg-govai-prod`
  (po utworzeniu) i `rg-govai-int`, Key Vault Secrets Officer na `govai-vault`. Dla agenta Claude — osobny
  service principal z ograniczonymi uprawnieniami (jak `sp-claude-agent-crmtree` w CRMtree).
- Cloudflare: dostęp do strefy `govai.pl`.
- Sekrety przekazywać przez Key Vault, nigdy w czacie / repo.

## 7. Pułapki (już raz kosztowały czas)
- **Superużytkownik omija RLS** — aplikacja musi łączyć się jako `govai_app`. Na Azure Postgres admin nie jest superużytkownikiem,
  ale jest właścicielem tabel i podlega RLS (FORCE) → migracje z `app.platform=on` (już w `migrate.sh`).
- Klucze obce nie podlegają RLS → złożone FK `(tenant_id, …)` / kontrola w API.
- JSONB: bez `json.dumps()`; migracje idempotentne; zero ręcznych zmian schematu.
- Obrazy bez bind mountów — po zmianie kodu `--build`.
- Gateway buduje się z pobieraniem modeli spaCy z GitHub (wymaga sieci).
- Git Bash na Windows: `MSYS_NO_PATHCONV=1` przy ścieżkach `/…` (`az --scope`, `docker cp`).
- Lokalny Caddy ma niezaufany certyfikat — przeglądarka wymaga akceptacji; testy przez `curl -k`.
- `docker restart` nie przeładowuje `.env` — `docker compose up -d <serwis>`.
- Agent Claude w trybie auto nie zapisze sekretów, nie nada ról Azure i nie scali PR bez wyraźnego polecenia — przygotować komendę dla człowieka.
- Nowa rola Azure dla tożsamości CI działa po kilku minutach (pierwszy deploy: „No subscriptions found”).
- Pierwsze logowanie po deployu z nową wersją auth — stare tokeny bez `tenant_id` są odrzucane (to zamierzone).

## 8. Przydatne komendy
```sh
# lokalny stos (bez Ollamy)
docker compose up -d postgres redis && MSYS_NO_PATHCONV=1 sh infra/scripts/migrate.sh
docker compose up -d --build --no-deps api gateway frontend caddy
# testy
node scripts/i18n-check.mjs
(cd frontend && npx tsc --noEmit -p tsconfig.json)
sh tests/isolation/run.sh
# deploy INT (obecny model VM) — z GitHub Actions: Deploy → environment=int, ref=develop
gh workflow run deploy.yml --ref develop -f environment=int
# Azure — zawsze z jawną subskrypcją
az containerapp list --subscription "Azure subscription 1" -g rg-crmtree-prod -o table   # wzorzec CRMtree
```

## 9. CRMtree — odnowienie certyfikatów wildcard (pilne, potem co ~60 dni)

**Stan (sprawdzony 2026-11-04):** w środowisku Container Apps `crmtree-env` (`rg-crmtree-prod`) są dwa
certyfikaty wgrane ręcznie jako PFX, wystawione przez **Let's Encrypt** (ważność 90 dni, nic ich nie odnawia):

| Certyfikat w Azure | Domena | Wygasa | Podpięty do |
|---|---|---|---|
| `wildcard-crmtree-pl` | `*.crmtree.pl` | **2026-11-08** | `crmtree-frontend` (PROD — subdomeny organizacji) |
| `wildcard-int-crmtree-pl` | `*.int.crmtree.pl` | **2026-11-10** | `crmtree-frontend-int` (INT) |

`app.crmtree.pl` i `api.crmtree.pl` mają certyfikaty zarządzane przez Azure (odnawiają się same) — nie ruszać.
DNS `crmtree.pl` jest w Cloudflare, rekordy **bez proxy** (szara chmurka) → CNAME na `crmtree-frontend(-int)…azurecontainerapps.io`.

**Wymagane:** token API Cloudflare (Profile → API Tokens → Create Token → szablon „Edit zone DNS”, strefa
`crmtree.pl`), uprawnienia Azure do `rg-crmtree-prod` (Contributor), Docker, openssl, az CLI.
Kroki wykonuje człowiek (agent Claude w trybie auto nie zapisze sekretów i nie zmieni produkcji CRMtree).
Polecenia dla Git Bash (Windows) albo WSL/Linux; w Git Bash poprzedź je `export MSYS_NO_PATHCONV=1`.

```sh
export MSYS_NO_PATHCONV=1
S="Azure subscription 1"; RG=rg-crmtree-prod; ENV=crmtree-env
mkdir -p ~/crmtree-certs && cd ~/crmtree-certs
# Katalog bieżący w formacie dla `docker -v` (Git Bash: C:/..., Linux/WSL: /home/...)
HERE=$(pwd -W 2>/dev/null || pwd)

# 1. Token Cloudflare do pliku (nie commitować, usunąć po wszystkim)
printf 'dns_cloudflare_api_token = %s\n' '<TOKEN_CLOUDFLARE>' > cloudflare.ini && chmod 600 cloudflare.ini

# 2. Wystawienie certyfikatów Let's Encrypt (wyzwanie DNS-01 przez Cloudflare)
for D in crmtree.pl int.crmtree.pl; do
  docker run --rm -v "$HERE/le:/etc/letsencrypt" -v "$HERE/cloudflare.ini:/cf.ini:ro" \
    certbot/dns-cloudflare certonly \
    --dns-cloudflare --dns-cloudflare-credentials /cf.ini --dns-cloudflare-propagation-seconds 60 \
    -d "*.$D" --cert-name "wildcard-$D" --agree-tos -m adapakse@gmail.com --non-interactive
done

# 3. Konwersja do PFX (Container Apps wymaga PFX z hasłem)
PFXPASS=$(openssl rand -hex 16)
for D in crmtree.pl int.crmtree.pl; do
  openssl pkcs12 -export -out "wildcard-$D.pfx" -passout "pass:$PFXPASS" \
    -inkey "le/live/wildcard-$D/privkey.pem" -in "le/live/wildcard-$D/fullchain.pem"
done

# 4. Wgranie do środowiska Container Apps — NOWE nazwy (stare zostają do czasu przepięcia)
TAG=$(date +%Y%m%d)
az containerapp env certificate upload --subscription "$S" -g $RG -n $ENV \
  --certificate-file wildcard-crmtree.pl.pfx --certificate-name "wildcard-crmtree-pl-$TAG" --password "$PFXPASS"
az containerapp env certificate upload --subscription "$S" -g $RG -n $ENV \
  --certificate-file wildcard-int.crmtree.pl.pfx --certificate-name "wildcard-int-crmtree-pl-$TAG" --password "$PFXPASS"

# 5. Przepięcie domen na nowe certyfikaty (bez przerwy w działaniu)
az containerapp hostname bind --subscription "$S" -g $RG -n crmtree-frontend \
  --hostname "*.crmtree.pl" --environment $ENV --certificate "wildcard-crmtree-pl-$TAG"
az containerapp hostname bind --subscription "$S" -g $RG -n crmtree-frontend-int \
  --hostname "*.int.crmtree.pl" --environment $ENV --certificate "wildcard-int-crmtree-pl-$TAG"

# 6. Weryfikacja — data ważności ~90 dni od dziś
for H in gessel.crmtree.pl app.int.crmtree.pl; do
  echo | openssl s_client -connect $H:443 -servername $H 2>/dev/null | openssl x509 -noout -subject -enddate
done
az containerapp env certificate list --subscription "$S" -g $RG -n $ENV \
  --query "[].{n:name,s:properties.subjectName,exp:properties.expirationDate}" -o table

# 7. Sprzątanie: stare certyfikaty (po potwierdzeniu, że domeny używają nowych) i lokalne pliki
az containerapp env certificate delete --subscription "$S" -g $RG -n $ENV --certificate wildcard-crmtree-pl --yes
az containerapp env certificate delete --subscription "$S" -g $RG -n $ENV --certificate wildcard-int-crmtree-pl --yes
rm -f cloudflare.ini *.pfx    # katalog le/ (klucze prywatne) — usunąć albo trzymać bezpiecznie do kolejnego odnowienia
```

Kolejne odnowienie: ~60 dni po wystawieniu (Let's Encrypt zaleca odnawiać na 30 dni przed wygaśnięciem).
Ustaw przypomnienie albo wdroż trwałe rozwiązanie:
- **Zalecane (jak w planie GovAI):** Cloudflare w trybie proxy (pomarańczowa chmurka) dla `*.crmtree.pl` i
  `*.int.crmtree.pl` + certyfikat **Cloudflare Origin CA** (ważny do 15 lat) wgrany zamiast Let's Encrypt,
  SSL/TLS „Full (strict)”. Przed włączeniem sprawdzić: SSR CRMtree za proxy (nagłówki `x-forwarded-*`,
  `allowedHosts`), limit czasu żądań przez Cloudflare (~100 s na planie Free) dla długich wywołań LLM.
- **Albo:** zaplanowany workflow GitHub Actions w `crmtree-backend` (co miesiąc) wykonujący kroki 2–5 z sekretami
  (token Cloudflare + OIDC do Azure).

-- GovAI — Obowiązki podmiotu wdrażającego (deployera), Art. 26-27 AI Act
-- Uruchomić: psql -U govai -d govai -f 011_deployer_obligations.sql
--
-- Katalog ai_act_requirements (001 + 006) obejmował dotąd wyłącznie stronę
-- dostawcy systemu AI (Art. 9-17, 43, 49). Większość klientów GovAI prawnie
-- jest bliżej roli deployera niż dostawcy — wdrażają agenty zbudowane na
-- modelach zewnętrznych (Anthropic/DeepSeek/Bielik), nie budują własnego
-- systemu AI od zera. Art. 26 (obowiązki deployera) i Art. 27 (ocena wpływu
-- na prawa podstawowe — FRIA) były dotąd całkowicie nieobecne w katalogu.
--
-- Weryfikacja źródła: tekst Digital Omnibus (Rozporządzenie UE 2026/1744,
-- L_202601744EN) nie zmienia treści Art. 26/27 — zmienia tylko termin
-- stosowania całej Sekcji 3 Rozdziału III (a więc też Art. 26-27) z
-- 2 sierpnia 2026 na 2 grudnia 2027 (Annex III) / 2 sierpnia 2028 (Annex I).
--
-- default_deadline_days liczone tak samo jak w 006 — dni od oznaczenia luki,
-- nie dni do 2 grudnia 2027 (ten termin regulacyjny jest wspólny dla całej
-- sekcji i pokazany osobno na landing page, nie w tej kolumnie).

INSERT INTO ai_act_requirements
    (risk_level, article_ref, requirement_title, requirement_text, sort_order, default_severity, default_deadline_days, decl_key)
SELECT * FROM (VALUES
    ('high'::risk_level, 'Art. 26 ust. 2', 'Nadzór człowieka przypisany do kompetentnej osoby',
     'Deployer wysokiego ryzyka musi przypisać nadzór człowieka osobom mającym niezbędne kompetencje, przeszkolenie, '
     'uprawnienia i wsparcie do jego wykonywania.',
     100, 'critical', 30, 'art26_2_human_oversight'),

    ('high', 'Art. 26 ust. 5', 'Monitorowanie działania i informowanie dostawcy',
     'Deployer musi monitorować działanie systemu zgodnie z instrukcją użycia i informować dostawcę oraz — gdy dotyczy — '
     'organ nadzoru rynku o zidentyfikowanym ryzyku lub poważnym incydencie.',
     110, 'major', 60, 'art26_5_monitoring'),

    ('high', 'Art. 26 ust. 6', 'Przechowywanie automatycznych logów',
     'Deployer musi przechowywać automatycznie generowane logi systemu przez okres odpowiedni do przeznaczenia systemu, '
     'co najmniej 6 miesięcy, o ile prawo unijne lub krajowe nie stanowi inaczej.',
     120, 'major', 30, 'art26_6_log_retention'),

    ('high', 'Art. 26 ust. 8', 'Weryfikacja rejestracji w unijnej bazie danych',
     'Deployer będący podmiotem publicznym musi przestrzegać obowiązków rejestracyjnych z Art. 49 i, przed uruchomieniem '
     'systemu, zweryfikować że jest on zarejestrowany w unijnej bazie danych.',
     130, 'major', 60, 'art26_8_registration_check'),

    ('high', 'Art. 27', 'Ocena wpływu na prawa podstawowe (FRIA)',
     'Przed wdrożeniem systemu wysokiego ryzyka z pkt 5(b)/(c) Załącznika III (ocena zdolności kredytowej, ryzyko '
     'ubezpieczeniowe) lub przez podmiot publiczny/prywatny świadczący usługi publiczne, deployer musi przeprowadzić '
     'ocenę wpływu na prawa podstawowe: opis procesów użycia, okres i częstotliwość użycia, kategorie osób dotkniętych, '
     'ryzyka szkody dla tych osób oraz środki nadzoru człowieka i mechanizmy odwoławcze.',
     140, 'major', 90, 'art27_fria')
) AS seed(risk_level, article_ref, requirement_title, requirement_text, sort_order, default_severity, default_deadline_days, decl_key)
WHERE NOT EXISTS (
    SELECT 1 FROM ai_act_requirements r
    WHERE r.risk_level = seed.risk_level AND r.article_ref = seed.article_ref
);

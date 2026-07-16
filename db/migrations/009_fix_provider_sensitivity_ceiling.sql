-- GovAI — Naprawa pułapu wrażliwości providerów chmurowych
-- Uruchomić: psql -U govai -d govai -f 009_fix_provider_sensitivity_ceiling.sql
--
-- Providery zewnętrzne z DPA (Anthropic, OpenAI, Google) miały ustawiony pułap
-- 'internal', mimo że ich własne notatki (003_providers.sql) mówią wprost:
-- "Wymaga DPA. Nie używać dla danych objętych tajemnicą adwokacką" — czyli
-- intencja projektu enuma (komentarz w 003_providers.sql) była taka, żeby
-- provider z DPA obsługiwał do poziomu 'confidential' (dane osobowe, NIP,
-- sygnatury — prywatna chmura (EU)), a dopiero 'privileged' (tajemnica
-- adwokacka) było zarezerwowane wyłącznie dla on-prem (Bielik).
--
-- Skutek błędnego seeda: KAŻDE zapytanie sklasyfikowane jako 'confidential'
-- (np. zawierające PESEL, numer dowodu, dane osobowe) do agenta na modelu
-- Claude/GPT/Gemini kończyło się twardym 503 "no_eligible_provider" — łącznie
-- ze scenariuszem demo "Klient podaje PESEL i numer konta (PII)", który
-- powinien kończyć się Dozwolone+PII, a nie błędem. DeepSeek (serwery poza UE)
-- zostaje na 'public' — to nie literówka, tak ma być (zakaz przetwarzania
-- danych klientów poza UE).

UPDATE providers SET max_data_sensitivity = 'confidential'
    WHERE name IN ('Anthropic Claude (Cloud)', 'OpenAI (Cloud)', 'Google Gemini (Cloud)');

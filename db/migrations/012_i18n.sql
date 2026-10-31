-- GovAI — Wielojęzyczność (wybór języka aplikacji)
-- Uruchomić: psql -U govai -d govai -f 012_i18n.sql
--
-- Języki: pl (źródłowy i zapasowy), en, de, it, es, fr, ro, ru, sl, hr.
-- Lista trzymana w synchronizacji z frontend/i18n/locales.ts, api/i18n/__init__.py
-- i gateway/i18n/__init__.py — przy dodaniu języka zmień też CHECK poniżej.
--
-- Idempotentna — deploy-remote.sh uruchamia wszystkie migracje przy każdym deployu.

-- ── Język użytkownika ─────────────────────────────────────────────────────────
-- NULL = "domyślny język instancji" (app_settings i18n.default_locale).
ALTER TABLE users ADD COLUMN IF NOT EXISTS locale VARCHAR(5);

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'users_locale_check') THEN
        ALTER TABLE users ADD CONSTRAINT users_locale_check
            CHECK (locale IS NULL OR locale IN ('pl','en','de','it','es','fr','ro','ru','sl','hr'));
    END IF;
END $$;

-- ── Tłumaczenia treści katalogowych w bazie ───────────────────────────────────
-- Kolumna bazowa (polski) zostaje bez zmian; *_i18n trzyma pozostałe języki
-- jako {"en": "...", "de": "...", ...}. API zwraca tekst w języku żądania,
-- z fallbackiem na kolumnę bazową (api/i18n.localized).
ALTER TABLE ai_act_requirements
    ADD COLUMN IF NOT EXISTS title_i18n JSONB NOT NULL DEFAULT '{}'::jsonb,
    ADD COLUMN IF NOT EXISTS text_i18n  JSONB NOT NULL DEFAULT '{}'::jsonb;

ALTER TABLE app_settings
    ADD COLUMN IF NOT EXISTS label_i18n       JSONB NOT NULL DEFAULT '{}'::jsonb,
    ADD COLUMN IF NOT EXISTS description_i18n JSONB NOT NULL DEFAULT '{}'::jsonb,
    ADD COLUMN IF NOT EXISTS unit_i18n        JSONB NOT NULL DEFAULT '{}'::jsonb;

ALTER TABLE providers
    ADD COLUMN IF NOT EXISTS notes_i18n JSONB NOT NULL DEFAULT '{}'::jsonb;

-- ── Domyślny język instancji (panel Parametry, edycja: it_admin) ─────────────
-- Każdy klient dostaje własną instancję — to odpowiednik "domyślnego języka
-- organizacji" z CRMtree. ON CONFLICT DO NOTHING: nie nadpisuj wyboru admina.
INSERT INTO app_settings (key, value, value_type, category, label, description, unit, min_value, max_value)
VALUES ('i18n.default_locale', '"pl"'::jsonb, 'string', 'i18n',
        'Domyślny język',
        'Język interfejsu, raportów i komunikatów dla użytkowników, którzy nie wybrali własnego. Kody: pl, en, de, it, es, fr, ro, ru, sl, hr.',
        NULL, NULL, NULL)
ON CONFLICT (key) DO NOTHING;

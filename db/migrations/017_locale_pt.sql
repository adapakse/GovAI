-- GovAI — Portugalski (pt, europejski) w aplikacji
-- Uruchomić: sh infra/scripts/migrate.sh
--
-- Języki: pl (źródłowy i zapasowy), en, de, it, es, fr, ro, ru, sl, hr, pt.
-- Lista trzymana w synchronizacji z frontend/i18n/locales.ts, api/i18n/__init__.py
-- i gateway/i18n/__init__.py. Tłumaczenia treści katalogowych dla pt:
-- 018_i18n_content_pt.sql (generowana przez scripts/gen-db-i18n.mjs).
--
-- Idempotentna.

-- ── Język użytkownika: CHECK users.locale z pt ─────────────────────────────────
-- Constraint z 012 jest odtwarzany tylko, gdy jeszcze nie dopuszcza 'pt'.
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'users_locale_check'
          AND conrelid = 'users'::regclass
          AND pg_get_constraintdef(oid) LIKE '%''pt''%'
    ) THEN
        ALTER TABLE users DROP CONSTRAINT IF EXISTS users_locale_check;
        ALTER TABLE users ADD CONSTRAINT users_locale_check
            CHECK (locale IS NULL OR locale IN ('pl','en','de','it','es','fr','ro','ru','sl','hr','pt'));
    END IF;
END $$;

-- ── Opis parametru i18n.default_locale: lista kodów z pt ──────────────────────
-- Opis we wszystkich językach kończy się listą kodów "…, sl, hr." — dopisujemy pt
-- (kolumna bazowa i *_i18n). Po zamianie wzorzec już nie występuje, więc ponowne
-- uruchomienie niczego nie zmienia; opis poprawiony ręcznie w UI zostaje, o ile
-- nie zawiera tej listy.
UPDATE app_settings
SET description = replace(description, ', sl, hr.', ', sl, hr, pt.'),
    description_i18n = (
        SELECT COALESCE(jsonb_object_agg(e.key, to_jsonb(replace(e.value, ', sl, hr.', ', sl, hr, pt.'))), '{}'::jsonb)
        FROM jsonb_each_text(COALESCE(app_settings.description_i18n, '{}'::jsonb)) AS e(key, value)
    )
WHERE key = 'i18n.default_locale'
  AND (description LIKE '%, sl, hr.%' OR description_i18n::text LIKE '%, sl, hr.%');

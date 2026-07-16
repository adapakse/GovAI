-- GovAI — Naprawa dryfu schematu: profil agenta (rejestr) + policies.policy_code
-- Uruchomić: psql -U govai -d govai -f 010_agent_profile_and_policy_code.sql
--
-- Wykryte przez `pg_dump --schema-only` na govai vs świeżo zmigrowanym
-- govai-int (16.07.2026) — te kolumny istniały w bazie govai ad-hoc, nigdy
-- nie trafiły do żadnej wersjonowanej migracji. Bez nich /demo/seed-fleet
-- pada z asyncpg.exceptions.UndefinedColumnError: column "compliance_decl"
-- does not exist, a silnik polityk (gateway/policy_engine.py) czyta
-- policy_code z wiersza reguły (etykiety G-001/G-002 w Symulatorze/Dzienniku).
--
-- Wszystko przez ADD COLUMN IF NOT EXISTS — bezpieczne do uruchomienia także
-- na bazie, gdzie kolumny już istnieją (no-op, zweryfikowane na govai).

ALTER TABLE agents
    ADD COLUMN IF NOT EXISTS version                   VARCHAR(20)    DEFAULT '1.0.0',
    ADD COLUMN IF NOT EXISTS last_reviewed_at           TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS next_review_date           DATE,
    ADD COLUMN IF NOT EXISTS compliance_decl            JSONB          DEFAULT '{}'::jsonb,
    ADD COLUMN IF NOT EXISTS processes_personal_data    BOOLEAN        DEFAULT false,
    ADD COLUMN IF NOT EXISTS gdpr_legal_basis           VARCHAR(100),
    ADD COLUMN IF NOT EXISTS data_retention_days        INTEGER,
    ADD COLUMN IF NOT EXISTS intended_purpose           TEXT,
    ADD COLUMN IF NOT EXISTS intended_users             VARCHAR(200),
    ADD COLUMN IF NOT EXISTS geographic_scope           VARCHAR(100)   DEFAULT 'PL',
    ADD COLUMN IF NOT EXISTS input_modalities           TEXT[]         DEFAULT '{text}'::text[],
    ADD COLUMN IF NOT EXISTS output_modalities          TEXT[]         DEFAULT '{text}'::text[],
    ADD COLUMN IF NOT EXISTS integration_points         TEXT[]         DEFAULT '{}'::text[],
    ADD COLUMN IF NOT EXISTS model_version               VARCHAR(50),
    ADD COLUMN IF NOT EXISTS technical_contact_email    VARCHAR(200),
    ADD COLUMN IF NOT EXISTS compliance_officer_email   VARCHAR(200),
    ADD COLUMN IF NOT EXISTS cost_alert_threshold_eur   NUMERIC(10,2)  DEFAULT 0;

ALTER TABLE policies
    ADD COLUMN IF NOT EXISTS policy_code VARCHAR(20);

-- Backfill dla dwóch reguł zasianych przez db/init.sql (G-001/G-002 — kody
-- widoczne w Symulatorze/Dzienniku/policy_engine.py). Dopasowanie po `name`,
-- bezpieczne do wielokrotnego uruchomienia. Inne, ręcznie utworzone polityki
-- (jeśli są) zachowują policy_code = NULL — nie zgadujemy za administratora.
UPDATE policies SET policy_code = 'G-001'
    WHERE name = 'Blokada modyfikacji danych finansowych' AND policy_code IS NULL;
UPDATE policies SET policy_code = 'G-002'
    WHERE name = 'Blokada wstrzyknięcia instrukcji' AND policy_code IS NULL;

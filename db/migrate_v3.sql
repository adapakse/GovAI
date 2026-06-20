-- GovAI — Migracja v3: Rozszerzony rejestr agentów
-- docker exec -i govai-postgres-1 psql -U govai -d govai < db/migrate_v3.sql

ALTER TABLE agents
    -- Wersjonowanie
    ADD COLUMN IF NOT EXISTS version                  VARCHAR(20)   DEFAULT '1.0.0',
    ADD COLUMN IF NOT EXISTS last_reviewed_at         TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS next_review_date         DATE,

    -- Deklaracje zgodności EU AI Act (JSONB — elastyczne, bez N kolejnych kolumn boolean)
    -- Każdy klucz: { "status": "yes|no|partial|na", "notes": "...", "updated_at": "..." }
    ADD COLUMN IF NOT EXISTS compliance_decl          JSONB         DEFAULT '{}',

    -- Dane i prywatność
    ADD COLUMN IF NOT EXISTS processes_personal_data  BOOLEAN       DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS gdpr_legal_basis         VARCHAR(100),
    ADD COLUMN IF NOT EXISTS data_retention_days      INTEGER,

    -- Przeznaczenie
    ADD COLUMN IF NOT EXISTS intended_purpose         TEXT,
    ADD COLUMN IF NOT EXISTS intended_users           VARCHAR(200),
    ADD COLUMN IF NOT EXISTS geographic_scope         VARCHAR(100)  DEFAULT 'PL',

    -- Techniczne
    ADD COLUMN IF NOT EXISTS input_modalities         TEXT[]        DEFAULT '{text}',
    ADD COLUMN IF NOT EXISTS output_modalities        TEXT[]        DEFAULT '{text}',
    ADD COLUMN IF NOT EXISTS integration_points       TEXT[]        DEFAULT '{}',
    ADD COLUMN IF NOT EXISTS model_version            VARCHAR(50),

    -- Kontakty
    ADD COLUMN IF NOT EXISTS technical_contact_email  VARCHAR(200),
    ADD COLUMN IF NOT EXISTS compliance_officer_email VARCHAR(200),

    -- Budżet
    ADD COLUMN IF NOT EXISTS cost_alert_threshold_eur DECIMAL(10,2) DEFAULT 0;

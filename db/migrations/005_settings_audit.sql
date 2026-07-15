-- GovAI — Historia zmian parametrów (panel "Parametry")
-- Uruchomić: psql -U govai -d govai -f 005_settings_audit.sql
--
-- Każdy PUT /settings/{key} dopisuje wiersz tutaj (stara i nowa wartość, kto, kiedy).

CREATE TABLE IF NOT EXISTS app_settings_audit (
    id           BIGSERIAL PRIMARY KEY,
    key          VARCHAR(120) NOT NULL,
    old_value    JSONB,
    new_value    JSONB        NOT NULL,
    updated_by   VARCHAR(200),
    updated_at   TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_app_settings_audit_key ON app_settings_audit (key, updated_at DESC);

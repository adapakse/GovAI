-- GovAI — Multitenancy (etap 1 planu: docs/multitenancy-plan.md)
-- Uruchomić: sh infra/scripts/migrate.sh (rejestr schema_migrations)
--
-- Model: wspólna baza, tenant_id we wszystkich tabelach danych klienta,
-- izolację wymusza Row Level Security (FORCE — także dla właściciela tabel,
-- czyli roli, którą łączy się aplikacja). Kontekst ustawia aplikacja w każdej
-- transakcji:
--   SET LOCAL app.tenant_id = '<uuid>'  — dane jednej organizacji
--   SET LOCAL app.platform  = 'on'      — operacje platformy (logowanie,
--                                         super-admin, zadania tła, migracje)
-- Kolumny tenant_id mają DEFAULT current_tenant_id(), więc INSERT w kontekście
-- organizacji sam wpisuje właściwą organizację, a WITH CHECK nie pozwala
-- zapisać wiersza obcej organizacji.
--
-- Istniejące dane → organizacja demonstracyjna "govai-demo".

-- ── Rola aplikacji ────────────────────────────────────────────────────────────
-- RLS nie działa dla superużytkownika (rola "govai" z obrazu Postgresa jest
-- superużytkownikiem i omija RLS nawet z FORCE). API i gateway łączą się rolą
-- govai_app: bez superużytkownika, bez BYPASSRLS, bez DDL. Hasło ustawia
-- infra/scripts/migrate.sh z DB_APP_PASSWORD (.env) — nie trzymamy go w repo.
-- Migracje dalej wykonuje "govai".
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'govai_app') THEN
        CREATE ROLE govai_app LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS;
    END IF;
    EXECUTE format('GRANT CONNECT ON DATABASE %I TO govai_app', current_database());
END $$;

GRANT USAGE ON SCHEMA public TO govai_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO govai_app;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO govai_app;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO govai_app;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT USAGE, SELECT ON SEQUENCES TO govai_app;
-- Rejestr migracji nie jest sprawą aplikacji.
REVOKE ALL ON schema_migrations FROM govai_app;

-- ── Funkcje kontekstu ─────────────────────────────────────────────────────────
CREATE OR REPLACE FUNCTION current_tenant_id() RETURNS uuid
LANGUAGE sql STABLE AS
$$ SELECT NULLIF(current_setting('app.tenant_id', true), '')::uuid $$;

CREATE OR REPLACE FUNCTION is_platform() RETURNS boolean
LANGUAGE sql STABLE AS
$$ SELECT coalesce(current_setting('app.platform', true), '') = 'on' $$;

-- ── Organizacje ───────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS tenants (
    id          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    slug        VARCHAR(63) NOT NULL
                CHECK (slug ~ '^[a-z0-9]([a-z0-9-]*[a-z0-9])?$'),
    name        TEXT NOT NULL,
    status      VARCHAR(16) NOT NULL DEFAULT 'active'
                CHECK (status IN ('active', 'suspended')),
    is_demo     BOOLEAN NOT NULL DEFAULT false,   -- symulator i reset danych demo
    deleted_at  TIMESTAMPTZ,                      -- miękkie usunięcie
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
-- Slug unikalny wśród nieusuniętych — po usunięciu można go użyć ponownie.
CREATE UNIQUE INDEX IF NOT EXISTS uq_tenants_slug ON tenants (slug) WHERE deleted_at IS NULL;

INSERT INTO tenants (id, slug, name, is_demo)
VALUES ('d0000000-0000-0000-0000-000000000001', 'govai-demo', 'GovAI Demo', true)
ON CONFLICT (id) DO NOTHING;

-- ── Super-admin platformy ─────────────────────────────────────────────────────
ALTER TABLE users ADD COLUMN IF NOT EXISTS is_super_admin BOOLEAN NOT NULL DEFAULT false;
UPDATE users SET is_super_admin = true WHERE id = '00000000-0000-0000-0000-000000000001';

-- ── tenant_id w tabelach danych klienta ───────────────────────────────────────
DO $$
DECLARE
    t text;
BEGIN
    FOREACH t IN ARRAY ARRAY['agents', 'policies', 'oversight_queue', 'audit_log',
                             'users', 'api_keys', 'refresh_tokens'] LOOP
        IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                       WHERE table_name = t AND column_name = 'tenant_id') THEN
            EXECUTE format('ALTER TABLE %I ADD COLUMN tenant_id UUID', t);
            EXECUTE format('UPDATE %I SET tenant_id = %L WHERE tenant_id IS NULL',
                           t, 'd0000000-0000-0000-0000-000000000001');
            EXECUTE format('ALTER TABLE %I ALTER COLUMN tenant_id SET NOT NULL', t);
            EXECUTE format('ALTER TABLE %I ALTER COLUMN tenant_id SET DEFAULT current_tenant_id()', t);
            EXECUTE format('ALTER TABLE %I ADD CONSTRAINT %I FOREIGN KEY (tenant_id) REFERENCES tenants(id)',
                           t, t || '_tenant_id_fkey');
        END IF;
    END LOOP;
END $$;

-- Katalogi: tenant_id NULL = wiersz platformy (wspólny, tylko do odczytu dla
-- organizacji), tenant_id ustawiony = własny wiersz organizacji.
ALTER TABLE providers           ADD COLUMN IF NOT EXISTS tenant_id UUID REFERENCES tenants(id);
ALTER TABLE ai_act_requirements ADD COLUMN IF NOT EXISTS tenant_id UUID REFERENCES tenants(id);
ALTER TABLE app_settings_audit  ADD COLUMN IF NOT EXISTS tenant_id UUID REFERENCES tenants(id);
ALTER TABLE providers           ALTER COLUMN tenant_id SET DEFAULT current_tenant_id();
ALTER TABLE ai_act_requirements ALTER COLUMN tenant_id SET DEFAULT current_tenant_id();
ALTER TABLE app_settings_audit  ALTER COLUMN tenant_id SET DEFAULT current_tenant_id();

-- Własny klucz API organizacji dla jej providera (szyfrowany po stronie
-- aplikacji; klucz szyfrujący poza bazą). Providerzy platformy używają api_key_env.
ALTER TABLE providers ADD COLUMN IF NOT EXISTS api_key_encrypted TEXT;

-- ── Unikalności per organizacja ───────────────────────────────────────────────
ALTER TABLE users DROP CONSTRAINT IF EXISTS users_email_key;
CREATE UNIQUE INDEX IF NOT EXISTS uq_users_tenant_email ON users (tenant_id, lower(email));
CREATE UNIQUE INDEX IF NOT EXISTS uq_policies_tenant_code
    ON policies (tenant_id, policy_code) WHERE policy_code IS NOT NULL;

-- ── Powiązania tylko w obrębie organizacji ─────────────────────────────────────
-- Klucze obce nie podlegają RLS — samo agent_id pozwalałoby wskazać agenta innej
-- organizacji (np. polityka albo klucz API przypięte do cudzego agenta). Złożone
-- klucze obce (tenant_id, agent_id) wymuszają to na poziomie bazy.
CREATE UNIQUE INDEX IF NOT EXISTS uq_agents_tenant_id ON agents (tenant_id, id);
DO $$
DECLARE
    t text;
BEGIN
    FOREACH t IN ARRAY ARRAY['policies', 'oversight_queue', 'api_keys'] LOOP
        IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = t || '_tenant_agent_fkey') THEN
            EXECUTE format('ALTER TABLE %I ADD CONSTRAINT %I FOREIGN KEY (tenant_id, agent_id) REFERENCES agents (tenant_id, id)',
                           t, t || '_tenant_agent_fkey');
        END IF;
    END LOOP;
END $$;

-- ── Indeksy z tenant_id na początku ───────────────────────────────────────────
CREATE INDEX IF NOT EXISTS idx_agents_tenant       ON agents (tenant_id);
CREATE INDEX IF NOT EXISTS idx_policies_tenant     ON policies (tenant_id);
CREATE INDEX IF NOT EXISTS idx_oversight_tenant    ON oversight_queue (tenant_id, status);
CREATE INDEX IF NOT EXISTS idx_audit_tenant_time   ON audit_log (tenant_id, time DESC);
CREATE INDEX IF NOT EXISTS idx_users_tenant        ON users (tenant_id);
CREATE INDEX IF NOT EXISTS idx_api_keys_tenant     ON api_keys (tenant_id);
CREATE INDEX IF NOT EXISTS idx_refresh_tenant      ON refresh_tokens (tenant_id);
CREATE INDEX IF NOT EXISTS idx_providers_tenant    ON providers (tenant_id);
CREATE INDEX IF NOT EXISTS idx_requirements_tenant ON ai_act_requirements (tenant_id);

-- ── Parametry: definicje globalne + wartości per organizacja ──────────────────
-- app_settings zostaje katalogiem definicji z wartością domyślną (platformy);
-- organizacja nadpisuje wartość w app_settings_values. Parametry techniczne
-- platformy (bezpieczeństwo, interwały, cennik, modele) edytuje tylko super-admin.
ALTER TABLE app_settings ADD COLUMN IF NOT EXISTS tenant_editable BOOLEAN NOT NULL DEFAULT true;
UPDATE app_settings SET tenant_editable = false
 WHERE category IN ('security', 'intervals', 'pricing', 'models');

CREATE TABLE IF NOT EXISTS app_settings_values (
    tenant_id   UUID NOT NULL DEFAULT current_tenant_id() REFERENCES tenants(id),
    key         VARCHAR(120) NOT NULL REFERENCES app_settings(key) ON DELETE CASCADE,
    value       JSONB NOT NULL,
    updated_by  VARCHAR(200),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (tenant_id, key)
);

-- ── Row Level Security ────────────────────────────────────────────────────────
DO $$
DECLARE
    t text;
BEGIN
    -- Dane organizacji: widoczne i zapisywalne tylko w jej kontekście.
    FOREACH t IN ARRAY ARRAY['agents', 'policies', 'oversight_queue', 'audit_log', 'users',
                             'api_keys', 'refresh_tokens', 'app_settings_values'] LOOP
        EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY', t);
        EXECUTE format('ALTER TABLE %I FORCE ROW LEVEL SECURITY', t);
        EXECUTE format('DROP POLICY IF EXISTS tenant_isolation ON %I', t);
        EXECUTE format($p$CREATE POLICY tenant_isolation ON %I
                          USING (tenant_id = current_tenant_id() OR is_platform())
                          WITH CHECK (tenant_id = current_tenant_id() OR is_platform())$p$, t);
    END LOOP;

    -- Katalogi: wiersze platformy (tenant_id NULL) widoczne dla wszystkich,
    -- ale INSERT/UPDATE/DELETE tylko własnych wierszy (albo w trybie platformy).
    -- Osobne polityki per polecenie — DELETE sprawdza wyłącznie USING, więc jedna
    -- wspólna polityka z "tenant_id IS NULL" w USING pozwalałaby usunąć wiersz platformy.
    FOREACH t IN ARRAY ARRAY['providers', 'ai_act_requirements', 'app_settings_audit'] LOOP
        EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY', t);
        EXECUTE format('ALTER TABLE %I FORCE ROW LEVEL SECURITY', t);
        EXECUTE format('DROP POLICY IF EXISTS tenant_isolation ON %I', t);
        EXECUTE format('DROP POLICY IF EXISTS catalog_read ON %I', t);
        EXECUTE format('DROP POLICY IF EXISTS catalog_insert ON %I', t);
        EXECUTE format('DROP POLICY IF EXISTS catalog_update ON %I', t);
        EXECUTE format('DROP POLICY IF EXISTS catalog_delete ON %I', t);
        EXECUTE format($p$CREATE POLICY catalog_read ON %I FOR SELECT
                          USING (tenant_id IS NULL OR tenant_id = current_tenant_id() OR is_platform())$p$, t);
        EXECUTE format($p$CREATE POLICY catalog_insert ON %I FOR INSERT
                          WITH CHECK (tenant_id = current_tenant_id() OR is_platform())$p$, t);
        EXECUTE format($p$CREATE POLICY catalog_update ON %I FOR UPDATE
                          USING (tenant_id = current_tenant_id() OR is_platform())
                          WITH CHECK (tenant_id = current_tenant_id() OR is_platform())$p$, t);
        EXECUTE format($p$CREATE POLICY catalog_delete ON %I FOR DELETE
                          USING (tenant_id = current_tenant_id() OR is_platform())$p$, t);
    END LOOP;
END $$;

-- Organizacje: każda widzi tylko siebie; zmiany wyłącznie w trybie platformy.
ALTER TABLE tenants ENABLE ROW LEVEL SECURITY;
ALTER TABLE tenants FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_self ON tenants;
CREATE POLICY tenant_self ON tenants
    USING (id = current_tenant_id() OR is_platform())
    WITH CHECK (is_platform());

-- ── Niezmienny dziennik audytowy ──────────────────────────────────────────────
-- UPDATE/DELETE zabronione; wyjątek: jawny reset danych demo (app.audit_purge)
-- w organizacji demonstracyjnej albo konserwacja w trybie platformy.
CREATE OR REPLACE FUNCTION audit_log_immutable() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF coalesce(current_setting('app.audit_purge', true), '') = 'on'
       AND (is_platform() OR EXISTS (SELECT 1 FROM tenants WHERE id = OLD.tenant_id AND is_demo)) THEN
        RETURN CASE WHEN TG_OP = 'DELETE' THEN OLD ELSE NEW END;
    END IF;
    RAISE EXCEPTION 'audit_log jest niezmienny (% zabronione)', TG_OP
        USING ERRCODE = 'insufficient_privilege';
END $$;

DROP TRIGGER IF EXISTS audit_log_no_update_delete ON audit_log;
CREATE TRIGGER audit_log_no_update_delete
    BEFORE UPDATE OR DELETE ON audit_log
    FOR EACH ROW EXECUTE FUNCTION audit_log_immutable();

-- GovAI — Panel super-admina i administracja organizacji (etap 4 planu multitenancy)
-- Uruchomić: sh infra/scripts/migrate.sh
--
-- Idempotentna.

-- ── Wymuszona zmiana hasła ────────────────────────────────────────────────────
-- Konto założone przez super-admina (pierwszy admin organizacji) albo po resecie
-- hasła przez administratora dostaje hasło tymczasowe — przy pierwszym logowaniu
-- użytkownik musi ustawić własne.
ALTER TABLE users ADD COLUMN IF NOT EXISTS must_change_password BOOLEAN NOT NULL DEFAULT false;

-- ── Dziennik operacji platformy ───────────────────────────────────────────────
-- Zakładanie / zawieszanie / usuwanie organizacji, wejście super-admina w kontekst
-- organizacji itp. Tylko tryb platformy (RLS) — organizacje go nie widzą.
CREATE TABLE IF NOT EXISTS platform_audit_log (
    id             BIGSERIAL PRIMARY KEY,
    time           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    actor_user_id  UUID,
    actor_email    TEXT NOT NULL,
    action         VARCHAR(64) NOT NULL,
    tenant_id      UUID REFERENCES tenants(id),
    details        JSONB NOT NULL DEFAULT '{}'::jsonb
);
CREATE INDEX IF NOT EXISTS idx_platform_audit_time   ON platform_audit_log (time DESC);
CREATE INDEX IF NOT EXISTS idx_platform_audit_tenant ON platform_audit_log (tenant_id, time DESC);

ALTER TABLE platform_audit_log ENABLE ROW LEVEL SECURITY;
ALTER TABLE platform_audit_log FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS platform_only ON platform_audit_log;
CREATE POLICY platform_only ON platform_audit_log
    USING (is_platform())
    WITH CHECK (is_platform());

-- Dopisywanie tylko przez aplikację; zmiany i usuwanie wpisów — nie.
REVOKE UPDATE, DELETE ON platform_audit_log FROM govai_app;

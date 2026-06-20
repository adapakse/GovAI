-- GovAI — Faza 1: Autentykacja i RBAC
-- Uruchomić na działającej bazie: psql -U govai -d govai -f 002_auth.sql

-- ── Typy ──────────────────────────────────────────────────────────────────────
CREATE TYPE user_role AS ENUM (
    'partner',              -- pełny dostęp; zarządza użytkownikami
    'associate',            -- dostęp do własnych spraw i agentów
    'compliance_officer',   -- pełny dostęp do audytu i raportów; read-only
    'it_admin',             -- konfiguracja systemu; brak dostępu do danych spraw
    'reviewer'              -- wyłącznie kolejka nadzoru człowieka
);

CREATE TYPE user_status AS ENUM ('active', 'suspended', 'pending');

-- ── Użytkownicy ───────────────────────────────────────────────────────────────
CREATE TABLE users (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    email           TEXT UNIQUE NOT NULL,
    full_name       TEXT NOT NULL,
    role            user_role NOT NULL,
    status          user_status NOT NULL DEFAULT 'active',
    password_hash   TEXT,                       -- NULL dla kont SSO/LDAP
    department      TEXT,
    phone           TEXT,
    last_login_at   TIMESTAMPTZ,
    created_by      UUID REFERENCES users(id),
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_users_email  ON users (email);
CREATE INDEX idx_users_role   ON users (role);
CREATE INDEX idx_users_status ON users (status);

-- ── Tokeny odświeżania ────────────────────────────────────────────────────────
CREATE TABLE refresh_tokens (
    id          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id     UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    token_hash  TEXT NOT NULL UNIQUE,   -- SHA-256 tokenu; surowy token wysyłany do klienta
    expires_at  TIMESTAMPTZ NOT NULL,
    revoked     BOOLEAN NOT NULL DEFAULT false,
    ip_address  TEXT,
    user_agent  TEXT,
    created_at  TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_refresh_user    ON refresh_tokens (user_id);
CREATE INDEX idx_refresh_expires ON refresh_tokens (expires_at) WHERE NOT revoked;

-- ── Klucze API (dla aplikacji wywołujących gateway) ───────────────────────────
CREATE TABLE api_keys (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name            TEXT NOT NULL,
    key_hash        TEXT NOT NULL UNIQUE,   -- SHA-256 klucza; surowy klucz wyświetlany raz
    key_prefix      TEXT NOT NULL,          -- pierwsze 8 znaków do identyfikacji w UI
    created_by      UUID REFERENCES users(id),
    agent_id        UUID REFERENCES agents(id) ON DELETE SET NULL,
    expires_at      TIMESTAMPTZ,
    last_used_at    TIMESTAMPTZ,
    active          BOOLEAN NOT NULL DEFAULT true,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_api_keys_hash    ON api_keys (key_hash);
CREATE INDEX idx_api_keys_agent   ON api_keys (agent_id);
CREATE INDEX idx_api_keys_creator ON api_keys (created_by);

-- ── Powiązanie agentów z właścicielem ────────────────────────────────────────
ALTER TABLE agents
    ADD COLUMN IF NOT EXISTS created_by UUID REFERENCES users(id),
    ADD COLUMN IF NOT EXISTS owner_user_id UUID REFERENCES users(id);

-- ── Użytkownik startowy — admin / partner ─────────────────────────────────────
-- Hasło startowe: GovAI_Admin_2026! — zmień po pierwszym logowaniu przez /auth/me/password
INSERT INTO users (id, email, full_name, role, status, password_hash, department)
VALUES (
    '00000000-0000-0000-0000-000000000001',
    'admin@kancelaria.local',
    'Administrator GovAI',
    'partner',
    'active',
    '$2b$12$iREXq.mve82rCSPFrneRRuyhly6iq4JedJk7sO4fOWT683u30MpR.',
    'IT / Compliance'
);

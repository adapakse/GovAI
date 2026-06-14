-- GovAI — inicjalizacja bazy danych
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS timescaledb CASCADE;

-- ──────────────────────────────────────────────
-- Typy wyliczeniowe
-- ──────────────────────────────────────────────
CREATE TYPE risk_level AS ENUM ('minimal', 'limited', 'high', 'unacceptable');
CREATE TYPE agent_status AS ENUM ('active', 'suspended', 'quarantined', 'retired');
CREATE TYPE policy_level AS ENUM ('org', 'team', 'agent');
CREATE TYPE policy_action AS ENUM ('allow', 'deny', 'require_oversight');
CREATE TYPE oversight_status AS ENUM ('pending', 'approved', 'rejected', 'escalated');
CREATE TYPE audit_result AS ENUM ('allowed', 'blocked', 'oversight_required');

-- ──────────────────────────────────────────────
-- Tabela agentów
-- ──────────────────────────────────────────────
CREATE TABLE agents (
    id                      UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name                    VARCHAR(200) NOT NULL,
    description             TEXT,
    owner_name              VARCHAR(200) NOT NULL,
    owner_email             VARCHAR(200) NOT NULL,
    team                    VARCHAR(200),
    risk_level              risk_level NOT NULL DEFAULT 'minimal',
    annex_iii_cat           VARCHAR(200),
    legal_basis             TEXT,
    status                  agent_status NOT NULL DEFAULT 'active',
    system_prompt_hash      VARCHAR(64),
    allowed_data_cats       TEXT[] DEFAULT '{}',
    allowed_tools           TEXT[] DEFAULT '{}',
    requires_oversight      BOOLEAN NOT NULL DEFAULT FALSE,
    model_id                VARCHAR(100) NOT NULL DEFAULT 'claude-haiku-4-5-20251001',
    monthly_budget_eur      DECIMAL(10,2) DEFAULT 0,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ──────────────────────────────────────────────
-- Tabela polityk
-- ──────────────────────────────────────────────
CREATE TABLE policies (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name            VARCHAR(200) NOT NULL,
    level           policy_level NOT NULL,
    agent_id        UUID REFERENCES agents(id) ON DELETE CASCADE,
    team            VARCHAR(200),
    rule_type       policy_action NOT NULL,
    condition_json  JSONB NOT NULL DEFAULT '{}',
    action_json     JSONB NOT NULL DEFAULT '{}',
    priority        INTEGER NOT NULL DEFAULT 100,
    active          BOOLEAN NOT NULL DEFAULT TRUE,
    version         INTEGER NOT NULL DEFAULT 1,
    created_by      VARCHAR(200),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ──────────────────────────────────────────────
-- Kolejka nadzoru człowieka
-- ──────────────────────────────────────────────
CREATE TABLE oversight_queue (
    id                  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    agent_id            UUID NOT NULL REFERENCES agents(id),
    task_id             VARCHAR(200) NOT NULL,
    decision_type       VARCHAR(200),
    agent_decision      TEXT NOT NULL,
    agent_reasoning     TEXT,
    input_hash          VARCHAR(64),
    confidence          DECIMAL(3,2),
    status              oversight_status NOT NULL DEFAULT 'pending',
    reviewer_id         VARCHAR(200),
    reviewer_decision   TEXT,
    review_start_at     TIMESTAMPTZ,
    reviewed_at         TIMESTAMPTZ,
    ttl_expires_at      TIMESTAMPTZ NOT NULL,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ──────────────────────────────────────────────
-- Dziennik audytowy — hypertable TimescaleDB
-- ──────────────────────────────────────────────
CREATE TABLE audit_log (
    time            TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    id              UUID NOT NULL DEFAULT uuid_generate_v4(),
    agent_id        UUID NOT NULL,
    agent_name      VARCHAR(200),
    task_id         VARCHAR(200),
    call_id         UUID NOT NULL DEFAULT uuid_generate_v4(),
    event_type      VARCHAR(50) NOT NULL,
    policy_result   audit_result NOT NULL,
    policy_id       VARCHAR(100),
    pii_categories  TEXT[] DEFAULT '{}',
    pii_count       INTEGER NOT NULL DEFAULT 0,
    input_hash      VARCHAR(64),
    output_hash     VARCHAR(64),
    model_used      VARCHAR(100),
    latency_ms      INTEGER,
    tokens_in       INTEGER,
    tokens_out      INTEGER,
    cost_eur        DECIMAL(10,6),
    block_reason    TEXT,
    metadata        JSONB DEFAULT '{}'
);

-- Konwersja na hypertable TimescaleDB (partycjonowanie po czasie)
SELECT create_hypertable('audit_log', 'time');

-- Indeksy dla typowych zapytań
CREATE INDEX idx_audit_agent_id ON audit_log (agent_id, time DESC);
CREATE INDEX idx_audit_event_type ON audit_log (event_type, time DESC);
CREATE INDEX idx_audit_policy_result ON audit_log (policy_result, time DESC);
CREATE INDEX idx_oversight_status ON oversight_queue (status, created_at);
CREATE INDEX idx_oversight_ttl ON oversight_queue (ttl_expires_at) WHERE status = 'pending';

-- ──────────────────────────────────────────────
-- Dane startowe — trzej agenci demo
-- ──────────────────────────────────────────────
INSERT INTO agents (id, name, description, owner_name, owner_email, team,
                    risk_level, annex_iii_cat, legal_basis, status,
                    requires_oversight, model_id, monthly_budget_eur,
                    allowed_data_cats)
VALUES
(
    'a1000000-0000-0000-0000-000000000001',
    'Asystent Obsługi Klienta',
    'Agent odpowiada na pytania klientów dotyczące produktów bankowych, harmonogramów rat i ogólnych informacji. Nie ma dostępu do danych finansowych ani możliwości modyfikacji kont.',
    'Anna Kowalska',
    'a.kowalska@bank.example.com',
    'Obsługa Klienta',
    'limited',
    NULL,
    'Art. 50 EU AI Act — obowiązek transparentności wobec użytkownika',
    'active',
    FALSE,
    'claude-haiku-4-5-20251001',
    50.00,
    ARRAY['customer_query', 'product_info', 'faq']
),
(
    'a2000000-0000-0000-0000-000000000002',
    'Agent Oceny Kredytowej',
    'Agent analizuje wnioski kredytowe i wydaje rekomendację creditworthiness na podstawie danych finansowych. Każda decyzja wymaga zatwierdzenia przez analityka kredytowego.',
    'Piotr Nowak',
    'p.nowak@bank.example.com',
    'Ryzyko Kredytowe',
    'high',
    'creditworthiness_assessment',
    'Aneks III pkt 5(b) EU AI Act — ocena zdolności kredytowej osób fizycznych',
    'active',
    TRUE,
    'claude-sonnet-4-6',
    200.00,
    ARRAY['financial_data', 'credit_history', 'income_data']
),
(
    'a3000000-0000-0000-0000-000000000003',
    'Agent Rekrutacji Wewnętrznej',
    'Agent wstępnie ocenia aplikacje kandydatów na podstawie wymagań stanowiska. Każda rekomendacja wymaga weryfikacji przez dział HR przed podjęciem działań.',
    'Maria Wiśniewska',
    'm.wisniewska@bank.example.com',
    'Zasoby Ludzkie',
    'high',
    'employment_recruitment',
    'Aneks III pkt 4(a) EU AI Act — systemy AI w rekrutacji i selekcji pracowników',
    'active',
    TRUE,
    'claude-sonnet-4-6',
    150.00,
    ARRAY['cv_content', 'job_requirements', 'competency_data']
);

-- Przykładowe polityki globalne
INSERT INTO policies (name, level, rule_type, condition_json, action_json, priority, created_by)
VALUES
(
    'Blokada modyfikacji danych finansowych',
    'org',
    'deny',
    '{"keywords": ["zmień saldo", "modify balance", "transfer funds", "delete account", "usuń konto"]}',
    '{"reason": "Modyfikacja danych finansowych poza zakresem agenta", "alert": true}',
    1,
    'system'
),
(
    'Blokada wstrzyknięcia instrukcji',
    'org',
    'deny',
    '{"keywords": ["ignore previous", "ignoruj poprzednie", "forget instructions", "zapomnij instrukcje"]}',
    '{"reason": "Wykryto próbę wstrzyknięcia instrukcji (prompt injection)", "alert": true}',
    2,
    'system'
);

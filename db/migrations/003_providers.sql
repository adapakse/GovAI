-- GovAI — Faza 2: Hybrydowy routing LLM
-- Uruchomić: psql -U govai -d govai -f 003_providers.sql

-- ── Poziomy wrażliwości danych ────────────────────────────────────────────────
CREATE TYPE data_sensitivity_level AS ENUM (
    'public',        -- pytania ogólne, informacje publiczne — dowolny provider
    'internal',      -- dane robocze bez identyfikatorów — provider z DPA
    'confidential',  -- dane osobowe, NIP, sygnatury — prywatna chmura (EU)
    'privileged'     -- tajemnica adwokacka / radcowska — wyłącznie on-prem
);

-- ── Dostawcy modeli LLM ───────────────────────────────────────────────────────
CREATE TABLE providers (
    id                   UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name                 TEXT NOT NULL,
    provider_type        TEXT NOT NULL,       -- openai | anthropic | deepseek | google | bielik | ollama | vllm | custom
    model_ids            TEXT[] NOT NULL DEFAULT '{}',  -- model_id obsługiwane przez tego providera
    base_url             TEXT,                -- dla on-prem / custom: http://host:port/v1
    api_key_env          TEXT,                -- nazwa zmiennej środowiskowej z kluczem API
    max_data_sensitivity data_sensitivity_level NOT NULL DEFAULT 'internal',
    active               BOOLEAN NOT NULL DEFAULT true,
    priority             INT NOT NULL DEFAULT 100,  -- niższy = preferowany
    is_healthy           BOOLEAN NOT NULL DEFAULT true,
    last_health_check_at TIMESTAMPTZ,
    notes                TEXT,
    created_by           UUID REFERENCES users(id),
    created_at           TIMESTAMPTZ DEFAULT NOW(),
    updated_at           TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_providers_active    ON providers (active) WHERE active = true;
CREATE INDEX idx_providers_sensitivity ON providers (max_data_sensitivity);

-- ── Rozszerzenie dziennika audytowego ─────────────────────────────────────────
ALTER TABLE audit_log
    ADD COLUMN IF NOT EXISTS data_sensitivity data_sensitivity_level,
    ADD COLUMN IF NOT EXISTS provider_id      UUID REFERENCES providers(id);

-- ── Domyślni dostawcy ─────────────────────────────────────────────────────────

-- Anthropic Claude — zewnętrzny, DPA dostępne, tylko EU-safe use-cases
INSERT INTO providers (name, provider_type, model_ids, api_key_env, max_data_sensitivity, priority, notes)
VALUES (
    'Anthropic Claude (Cloud)',
    'anthropic',
    ARRAY['claude-haiku-4-5-20251001', 'claude-sonnet-4-6', 'claude-opus-4-8'],
    'ANTHROPIC_API_KEY',
    'internal',
    10,
    'Provider zewnętrzny. Wymaga DPA. Nie używać dla danych objętych tajemnicą adwokacką.'
);

-- OpenAI — zewnętrzny, DPA dostępne
INSERT INTO providers (name, provider_type, model_ids, api_key_env, max_data_sensitivity, priority, notes)
VALUES (
    'OpenAI (Cloud)',
    'openai',
    ARRAY['gpt-4o', 'gpt-4o-mini', 'gpt-4-turbo', 'o1', 'o3-mini'],
    'OPENAI_API_KEY',
    'internal',
    20,
    'Provider zewnętrzny. Wymaga DPA Enterprise. Nie używać dla danych poufnych.'
);

-- DeepSeek — zewnętrzny, serwery w Chinach — TYLKO dane publiczne
INSERT INTO providers (name, provider_type, model_ids, api_key_env, max_data_sensitivity, priority, notes)
VALUES (
    'DeepSeek (Cloud)',
    'deepseek',
    ARRAY['deepseek-chat', 'deepseek-coder'],
    'DEEPSEEK_API_KEY',
    'public',
    30,
    'Serwery poza UE (Chiny). Wyłącznie dane publiczne — zakaz przetwarzania danych klientów.'
);

-- Google Gemini — zewnętrzny, EU Data Boundary dostępne
INSERT INTO providers (name, provider_type, model_ids, api_key_env, max_data_sensitivity, priority, notes)
VALUES (
    'Google Gemini (Cloud)',
    'google',
    ARRAY['gemini-1.5-pro', 'gemini-1.5-flash', 'gemini-2.0-flash'],
    'GOOGLE_API_KEY',
    'internal',
    25,
    'Provider zewnętrzny z EU Data Boundary. Wymaga DPA. Nie używać dla danych uprzywilejowanych.'
);

-- Bielik On-Prem — lokalny model, pełna kontrola — może obsługiwać PRIVILEGED
INSERT INTO providers (id, name, provider_type, model_ids, base_url, max_data_sensitivity, priority, active, notes)
VALUES (
    'b0000000-0000-0000-0000-000000000001',
    'Bielik On-Prem (Local)',
    'ollama',
    ARRAY['bielik-11b-v2.3-instruct', 'bielik-7b', 'llama3.1', 'mistral'],
    'http://ollama:11434',
    'privileged',
    1,
    false,  -- domyślnie wyłączony — aktywuj po skonfigurowaniu serwera
    'Model lokalny — tajemnica adwokacka OK. Aktywuj po uruchomieniu serwera Ollama.'
);

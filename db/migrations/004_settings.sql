-- GovAI — Faza 4: Parametryzacja (panel ustawień)
-- Uruchomić: psql -U govai -d govai -f 004_settings.sql
--
-- Tabela konfiguracji edytowalnej w locie (panel "Parametry", edycja: it_admin).
-- Gateway i API czytają z cache odświeżanego z tej tabeli — bez restartu.

CREATE TABLE IF NOT EXISTS app_settings (
    key          VARCHAR(120) PRIMARY KEY,
    value        JSONB        NOT NULL,
    value_type   VARCHAR(16)  NOT NULL,          -- number | int | bool | string | json
    category     VARCHAR(32)  NOT NULL,          -- pricing | oversight | intervals | security | models | budget | pagination | compliance
    label        VARCHAR(160) NOT NULL,
    description  TEXT,
    unit         VARCHAR(32),                    -- np. 'sekundy', 'dni', 'EUR', '%', 'tokeny'
    min_value    NUMERIC,                        -- walidacja (tylko number/int)
    max_value    NUMERIC,
    editable     BOOLEAN      NOT NULL DEFAULT true,
    updated_by   VARCHAR(200),
    updated_at   TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_app_settings_category ON app_settings (category);

-- ── Seed: bieżące wartości wyjęte z kodu ──────────────────────────────────────
INSERT INTO app_settings (key, value, value_type, category, label, description, unit, min_value, max_value) VALUES

-- PRICING (gateway/proxy.py:_estimate_cost)
('pricing.usd_to_eur', '0.93'::jsonb, 'number', 'pricing',
 'Kurs USD→EUR', 'Mnożnik konwersji kosztów modeli z USD na EUR.', 'mnożnik', 0.1, 5),
('pricing.model_rates',
 '{"claude-haiku-4-5-20251001":[0.00025,0.00125],"claude-sonnet-4-6":[0.003,0.015],"claude-opus-4-8":[0.015,0.075],"gpt-4o":[0.005,0.015],"gpt-4o-mini":[0.00015,0.0006],"deepseek-chat":[0.00014,0.00028]}'::jsonb,
 'json', 'pricing',
 'Stawki modeli (USD/1k tok.)', 'Mapa model → [wejście, wyjście] w USD za 1000 tokenów. Model spoza listy używa stawki domyślnej.', 'USD/1k', NULL, NULL),
('pricing.default_rate', '[0.003,0.015]'::jsonb, 'json', 'pricing',
 'Stawka domyślna (USD/1k tok.)', 'Stawka [wejście, wyjście] dla modeli spoza mapy.', 'USD/1k', NULL, NULL),

-- OVERSIGHT
('oversight.min_review_seconds', '10'::jsonb, 'int', 'oversight',
 'Min. czas przeglądu', 'Poniżej tej liczby sekund przegląd nadzoru oznaczany jest jako pozorny (rubber-stamp).', 'sekundy', 0, 3600),
('oversight.ttl_seconds', '3600'::jsonb, 'int', 'oversight',
 'TTL zadania nadzoru', 'Czas do eskalacji zadania w kolejce nadzoru.', 'sekundy', 60, 86400),
('oversight.history_max_days', '90'::jsonb, 'int', 'oversight',
 'Historia nadzoru — max dni', 'Maksymalny zakres dni dla GET /oversight/history.', 'dni', 1, 365),
('oversight.history_limit', '200'::jsonb, 'int', 'oversight',
 'Historia nadzoru — limit wierszy', 'Twardy limit liczby pozycji historii nadzoru.', 'wiersze', 1, 2000),

-- INTERVALS
('intervals.policy_refresh_seconds', '60'::jsonb, 'int', 'intervals',
 'Odświeżanie polityk', 'Co ile sekund gateway przeładowuje reguły polityk z bazy.', 'sekundy', 5, 3600),
('intervals.ttl_monitor_seconds', '60'::jsonb, 'int', 'intervals',
 'Monitor TTL nadzoru', 'Co ile sekund monitor eskaluje przeterminowane zadania nadzoru.', 'sekundy', 5, 3600),

-- SECURITY
('security.pii_confidence_threshold', '0.7'::jsonb, 'number', 'security',
 'Próg pewności PII', 'Minimalny poziom pewności Presidio do uznania wykrycia PII.', '0–1', 0, 1),
('security.access_token_expire_minutes', '60'::jsonb, 'int', 'security',
 'Ważność access tokenu', 'Czas życia JWT access token.', 'minuty', 5, 1440),
('security.refresh_token_expire_days', '7'::jsonb, 'int', 'security',
 'Ważność refresh tokenu', 'Czas życia refresh tokenu.', 'dni', 1, 90),
('security.bcrypt_rounds', '12'::jsonb, 'int', 'security',
 'Rundy bcrypt', 'Koszt hashowania haseł (wyższy = wolniej, bezpieczniej).', 'rundy', 4, 16),

-- MODELS
('models.default_agent_model', '"claude-haiku-4-5-20251001"'::jsonb, 'string', 'models',
 'Domyślny model agenta', 'Model przypisywany nowo rejestrowanym agentom.', NULL, NULL, NULL),
('models.classifier_model', '"claude-sonnet-4-6"'::jsonb, 'string', 'models',
 'Model klasyfikatora AI Act', 'Model używany do oceny poziomu ryzyka agenta.', NULL, NULL, NULL),
('models.default_temperature', '0.7'::jsonb, 'number', 'models',
 'Domyślna temperatura', 'Temperatura LLM, gdy klient jej nie poda.', '0–2', 0, 2),
('models.default_max_tokens', '1024'::jsonb, 'int', 'models',
 'Domyślny limit tokenów', 'Limit tokenów wyjścia, gdy klient go nie poda.', 'tokeny', 1, 16384),

-- BUDGET
('budget.default_monthly_eur', '0'::jsonb, 'number', 'budget',
 'Domyślny budżet miesięczny', 'Budżet przypisywany nowym agentom (0 = brak limitu).', 'EUR', 0, 1000000),
('budget.default_alert_threshold_eur', '0'::jsonb, 'number', 'budget',
 'Domyślny próg alertu', 'Próg alertu kosztowego dla nowych agentów (0 = wyłączony).', 'EUR', 0, 1000000),

-- PAGINATION
('pagination.audit_default_limit', '100'::jsonb, 'int', 'pagination',
 'Audyt — domyślny limit', 'Domyślna liczba wpisów w GET /audit.', 'wiersze', 1, 5000),
('pagination.audit_max_limit', '500'::jsonb, 'int', 'pagination',
 'Audyt — max limit', 'Maksymalna liczba wpisów w jednym zapytaniu audytu.', 'wiersze', 1, 10000),
('pagination.default_window_days', '7'::jsonb, 'int', 'pagination',
 'Domyślne okno (dni)', 'Domyślny zakres dni dla audytu i dashboardu.', 'dni', 1, 90),
('pagination.dashboard_top_agents', '5'::jsonb, 'int', 'pagination',
 'Dashboard — top agentów', 'Liczba najaktywniejszych agentów na pulpicie.', 'pozycje', 1, 50),
('pagination.dashboard_recent_blocks', '10'::jsonb, 'int', 'pagination',
 'Dashboard — ostatnie blokady', 'Liczba ostatnich blokad w alertach pulpitu.', 'pozycje', 1, 100),
('pagination.timeline_default_hours', '24'::jsonb, 'int', 'pagination',
 'Timeline — domyślne godziny', 'Domyślne okno wykresu timeline.', 'godziny', 1, 168),
('pagination.timeline_max_hours', '72'::jsonb, 'int', 'pagination',
 'Timeline — max godziny', 'Maksymalny zakres wykresu timeline.', 'godziny', 1, 720),
('pagination.stats_default_days', '30'::jsonb, 'int', 'pagination',
 'Statystyki agenta — domyślne dni', 'Domyślny zakres GET /agents/{id}/stats.', 'dni', 1, 365),
('pagination.stats_max_days', '90'::jsonb, 'int', 'pagination',
 'Statystyki agenta — max dni', 'Maksymalny zakres statystyk agenta.', 'dni', 1, 365),

-- COMPLIANCE
('compliance.deadline_days',
 '{"oversight":7,"legal_basis":14,"annex_iii_cat":14,"documentation":30,"conformity":30,"eu_database":60}'::jsonb,
 'json', 'compliance',
 'Terminy luk compliance (dni)', 'Liczba dni na usunięcie poszczególnych luk zgodności high-risk.', 'dni', NULL, NULL),
('compliance.enterprise_report_max_tokens', '500'::jsonb, 'int', 'compliance',
 'Raport enterprise — max tokenów', 'Limit tokenów narracji raportu korporacyjnego.', 'tokeny', 50, 4000),
('compliance.report_max_tokens', '280'::jsonb, 'int', 'compliance',
 'Raport agenta — max tokenów', 'Limit tokenów narracji raportu zgodności agenta.', 'tokeny', 50, 4000)

ON CONFLICT (key) DO NOTHING;

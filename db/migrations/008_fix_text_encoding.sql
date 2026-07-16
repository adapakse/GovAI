-- GovAI — Naprawa uszkodzonego kodowania polskich znaków
-- Uruchomić: psql -U govai -d govai -f 008_fix_text_encoding.sql
--
-- Migracje 003/004 zostały pierwotnie zastosowane przez
-- `Get-Content -Raw | docker compose exec -T postgres psql` w Windows
-- PowerShell 5.1 — pipe do procesu natywnego koduje tekst przez
-- $OutputEncoding (domyślnie kodowanie bez polskich znaków), więc każdy bajt
-- wielobajtowego znaku UTF-8 (ą, ć, ę, ł, ń, ó, ś, ź, ż, —, →) trafił do bazy
-- jako '?'. Kolumna `value` w app_settings (edytowalna przez UI) NIE jest
-- ruszana — nadprisujemy tylko label/description/unit (settings) i notes
-- (providers), czyli treści statyczne z seeda.
--
-- Bezpieczny sposób aplikowania (omija PowerShell stdin):
--   docker cp db/migrations/008_fix_text_encoding.sql govai-postgres-1:/tmp/008.sql
--   docker compose exec -T postgres psql -U govai -d govai -f /tmp/008.sql
-- Tą samą metodą aplikuj WSZYSTKIE przyszłe migracje z polskim tekstem —
-- nigdy przez `Get-Content -Raw | docker compose exec -T postgres psql`.

-- ── app_settings — poprawne label/description/unit z seeda (004_settings.sql) ──
INSERT INTO app_settings (key, value, value_type, category, label, description, unit, min_value, max_value) VALUES

('pricing.usd_to_eur', '0.93'::jsonb, 'number', 'pricing',
 'Kurs USD→EUR', 'Mnożnik konwersji kosztów modeli z USD na EUR.', 'mnożnik', 0.1, 5),
('pricing.model_rates',
 '{"claude-haiku-4-5-20251001":[0.00025,0.00125],"claude-sonnet-4-6":[0.003,0.015],"claude-opus-4-8":[0.015,0.075],"gpt-4o":[0.005,0.015],"gpt-4o-mini":[0.00015,0.0006],"deepseek-chat":[0.00014,0.00028]}'::jsonb,
 'json', 'pricing',
 'Stawki modeli (USD/1k tok.)', 'Mapa model → [wejście, wyjście] w USD za 1000 tokenów. Model spoza listy używa stawki domyślnej.', 'USD/1k', NULL, NULL),
('pricing.default_rate', '[0.003,0.015]'::jsonb, 'json', 'pricing',
 'Stawka domyślna (USD/1k tok.)', 'Stawka [wejście, wyjście] dla modeli spoza mapy.', 'USD/1k', NULL, NULL),

('oversight.min_review_seconds', '10'::jsonb, 'int', 'oversight',
 'Min. czas przeglądu', 'Poniżej tej liczby sekund przegląd nadzoru oznaczany jest jako pozorny (rubber-stamp).', 'sekundy', 0, 3600),
('oversight.ttl_seconds', '3600'::jsonb, 'int', 'oversight',
 'TTL zadania nadzoru', 'Czas do eskalacji zadania w kolejce nadzoru.', 'sekundy', 60, 86400),
('oversight.history_max_days', '90'::jsonb, 'int', 'oversight',
 'Historia nadzoru — max dni', 'Maksymalny zakres dni dla GET /oversight/history.', 'dni', 1, 365),
('oversight.history_limit', '200'::jsonb, 'int', 'oversight',
 'Historia nadzoru — limit wierszy', 'Twardy limit liczby pozycji historii nadzoru.', 'wiersze', 1, 2000),

('intervals.policy_refresh_seconds', '60'::jsonb, 'int', 'intervals',
 'Odświeżanie polityk', 'Co ile sekund gateway przeładowuje reguły polityk z bazy.', 'sekundy', 5, 3600),
('intervals.ttl_monitor_seconds', '60'::jsonb, 'int', 'intervals',
 'Monitor TTL nadzoru', 'Co ile sekund monitor eskaluje przeterminowane zadania nadzoru.', 'sekundy', 5, 3600),

('security.pii_confidence_threshold', '0.7'::jsonb, 'number', 'security',
 'Próg pewności PII', 'Minimalny poziom pewności Presidio do uznania wykrycia PII.', '0–1', 0, 1),
('security.access_token_expire_minutes', '60'::jsonb, 'int', 'security',
 'Ważność access tokenu', 'Czas życia JWT access token.', 'minuty', 5, 1440),
('security.refresh_token_expire_days', '7'::jsonb, 'int', 'security',
 'Ważność refresh tokenu', 'Czas życia refresh tokenu.', 'dni', 1, 90),
('security.bcrypt_rounds', '12'::jsonb, 'int', 'security',
 'Rundy bcrypt', 'Koszt hashowania haseł (wyższy = wolniej, bezpieczniej).', 'rundy', 4, 16),

('models.default_agent_model', '"claude-haiku-4-5-20251001"'::jsonb, 'string', 'models',
 'Domyślny model agenta', 'Model przypisywany nowo rejestrowanym agentom.', NULL, NULL, NULL),
('models.classifier_model', '"claude-sonnet-4-6"'::jsonb, 'string', 'models',
 'Model klasyfikatora AI Act', 'Model używany do oceny poziomu ryzyka agenta.', NULL, NULL, NULL),
('models.default_temperature', '0.7'::jsonb, 'number', 'models',
 'Domyślna temperatura', 'Temperatura LLM, gdy klient jej nie poda.', '0–2', 0, 2),
('models.default_max_tokens', '1024'::jsonb, 'int', 'models',
 'Domyślny limit tokenów', 'Limit tokenów wyjścia, gdy klient go nie poda.', 'tokeny', 1, 16384),

('budget.default_monthly_eur', '0'::jsonb, 'number', 'budget',
 'Domyślny budżet miesięczny', 'Budżet przypisywany nowym agentom (0 = brak limitu).', 'EUR', 0, 1000000),
('budget.default_alert_threshold_eur', '0'::jsonb, 'number', 'budget',
 'Domyślny próg alertu', 'Próg alertu kosztowego dla nowych agentów (0 = wyłączony).', 'EUR', 0, 1000000),

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

('compliance.deadline_days',
 '{"requires_oversight":7,"legal_basis":14,"annex_iii_cat":14,"_technical_doc":30,"_conformity":30,"_eu_db":60}'::jsonb,
 'json', 'compliance',
 'Terminy luk compliance (dni)', 'Liczba dni na usunięcie poszczególnych luk zgodności high-risk (klucz = pole kontroli).', 'dni', NULL, NULL),
('compliance.enterprise_report_max_tokens', '500'::jsonb, 'int', 'compliance',
 'Raport enterprise — max tokenów', 'Limit tokenów narracji raportu korporacyjnego.', 'tokeny', 50, 4000),
('compliance.report_max_tokens', '450'::jsonb, 'int', 'compliance',
 'Raport agenta — max tokenów', 'Limit tokenów narracji raportu zgodności agenta.', 'tokeny', 50, 4000)

ON CONFLICT (key) DO UPDATE SET
    label       = EXCLUDED.label,
    description = EXCLUDED.description,
    unit        = EXCLUDED.unit;
    -- `value`, `updated_by`, `updated_at` celowo nietknięte — to pole edytowalne przez it_admin.

-- ── providers.notes — poprawny tekst z seeda (003_providers.sql) ───────────────
UPDATE providers SET notes = 'Provider zewnętrzny. Wymaga DPA. Nie używać dla danych objętych tajemnicą adwokacką.'
    WHERE name = 'Anthropic Claude (Cloud)';
UPDATE providers SET notes = 'Provider zewnętrzny. Wymaga DPA Enterprise. Nie używać dla danych poufnych.'
    WHERE name = 'OpenAI (Cloud)';
UPDATE providers SET notes = 'Serwery poza UE (Chiny). Wyłącznie dane publiczne — zakaz przetwarzania danych klientów.'
    WHERE name = 'DeepSeek (Cloud)';
UPDATE providers SET notes = 'Provider zewnętrzny z EU Data Boundary. Wymaga DPA. Nie używać dla danych uprzywilejowanych.'
    WHERE name = 'Google Gemini (Cloud)';
UPDATE providers SET notes = 'Model lokalny — tajemnica adwokacka OK. Aktywuj po uruchomieniu serwera Ollama.'
    WHERE name = 'Bielik On-Prem (Local)';

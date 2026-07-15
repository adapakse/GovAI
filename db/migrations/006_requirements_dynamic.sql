-- GovAI — Dynamiczna walidacja rejestru vs wymagania EU AI Act
-- Uruchomić: psql -U govai -d govai -f 006_requirements_dynamic.sql
--
-- Rozszerza ai_act_requirements o dane potrzebne do automatycznego wyliczania
-- luk (severity/deadline) oraz klucz łączący wymaganie z samo-deklaracją
-- w agents.compliance_decl / automatycznym sprawdzeniem pola rejestru.
-- Dzięki temu cała logika "luka / spełnione / nie dotyczy" jest wyliczana
-- z danych (tabela + rejestr agenta), a nie z tekstu zaszytego w kodzie.

ALTER TABLE ai_act_requirements
    ADD COLUMN IF NOT EXISTS default_severity      VARCHAR(16)  NOT NULL DEFAULT 'major',
    ADD COLUMN IF NOT EXISTS default_deadline_days  INTEGER      NOT NULL DEFAULT 30,
    ADD COLUMN IF NOT EXISTS decl_key               VARCHAR(64);

COMMENT ON COLUMN ai_act_requirements.decl_key IS
    'Klucz w agents.compliance_decl (samo-deklaracja) lub w rejestrze automatycznych '
    'sprawdzeń pola agenta (zob. services/compliance.py:_AUTO_CHECKS). NULL = wymaga '
    'wyłącznie ręcznej samo-deklaracji.';

-- ── Backfill: severity/deadline/decl_key dla wymagań zasianych w migrate_v2.sql ──

UPDATE ai_act_requirements SET default_severity='critical', default_deadline_days=90, decl_key='art9_risk_management'   WHERE risk_level='high' AND article_ref='Art. 9';
UPDATE ai_act_requirements SET default_severity='major',    default_deadline_days=60, decl_key='art10_data_governance'  WHERE risk_level='high' AND article_ref='Art. 10';
UPDATE ai_act_requirements SET default_severity='critical', default_deadline_days=60, decl_key='art11_technical_docs'   WHERE risk_level='high' AND article_ref='Art. 11';
UPDATE ai_act_requirements SET default_severity='major',    default_deadline_days=60, decl_key='art13_transparency'    WHERE risk_level='high' AND article_ref='Art. 13';
UPDATE ai_act_requirements SET default_severity='critical', default_deadline_days=30, decl_key='art14_human_oversight' WHERE risk_level='high' AND article_ref='Art. 14';
UPDATE ai_act_requirements SET default_severity='major',    default_deadline_days=90, decl_key='art15_accuracy'        WHERE risk_level='high' AND article_ref='Art. 15';
UPDATE ai_act_requirements SET default_severity='major',    default_deadline_days=90, decl_key='art17_quality_mgmt'    WHERE risk_level='high' AND article_ref='Art. 17';

UPDATE ai_act_requirements SET default_severity='critical', default_deadline_days=0   WHERE risk_level='unacceptable' AND article_ref='Art. 5';

UPDATE ai_act_requirements SET default_severity='minor', default_deadline_days=180, decl_key='art50_1_transparency' WHERE risk_level='limited' AND article_ref='Art. 50 ust. 1';
UPDATE ai_act_requirements SET default_severity='minor', default_deadline_days=180, decl_key='art50_4_ai_labeling'  WHERE risk_level='limited' AND article_ref='Art. 50 ust. 4';

UPDATE ai_act_requirements SET default_severity='minor', default_deadline_days=365, decl_key='voluntary_code' WHERE risk_level='minimal' AND article_ref='Preambuła 46';

-- ── Brakujące pozycje wysokiego ryzyka (dawniej zaszyte na stałe w kodzie) ──────

INSERT INTO ai_act_requirements (risk_level, article_ref, requirement_title, requirement_text, sort_order, default_severity, default_deadline_days, decl_key)
SELECT 'high', 'Art. 43', 'Ocena zgodności',
       'Systemy wysokiego ryzyka z Aneksu III wymagają przeprowadzenia oceny zgodności '
       '(samoocena lub przez jednostkę notyfikowaną) przed wprowadzeniem do użytku.',
       80, 'critical', 30, 'conformity_assessment'
WHERE NOT EXISTS (SELECT 1 FROM ai_act_requirements WHERE risk_level='high' AND article_ref='Art. 43');

INSERT INTO ai_act_requirements (risk_level, article_ref, requirement_title, requirement_text, sort_order, default_severity, default_deadline_days, decl_key)
SELECT 'high', 'Art. 49', 'Rejestracja w unijnej bazie danych',
       'Systemy wysokiego ryzyka muszą być zarejestrowane w unijnej bazie danych AI '
       'przed wprowadzeniem do użytku.',
       90, 'major', 60, 'eu_database_registered'
WHERE NOT EXISTS (SELECT 1 FROM ai_act_requirements WHERE risk_level='high' AND article_ref='Art. 49');

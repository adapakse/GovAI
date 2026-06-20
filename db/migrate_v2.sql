-- GovAI — Migracja v2
-- Uruchom jednorazowo: docker exec -i govai-postgres-1 psql -U govai -d govai < db/migrate_v2.sql

-- Dodaj policy_code do tabeli policies
ALTER TABLE policies ADD COLUMN IF NOT EXISTS policy_code VARCHAR(20);

-- Ustaw kody dla istniejących polityk systemowych
UPDATE policies SET policy_code = 'G-001'
WHERE priority = 1 AND level = 'org' AND policy_code IS NULL;

UPDATE policies SET policy_code = 'G-002'
WHERE priority = 2 AND level = 'org' AND policy_code IS NULL;

-- Tabela wymagań EU AI Act
CREATE TABLE IF NOT EXISTS ai_act_requirements (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    risk_level      risk_level NOT NULL,
    article_ref     VARCHAR(50) NOT NULL,
    requirement_title   VARCHAR(200) NOT NULL,
    requirement_text    TEXT NOT NULL,
    active          BOOLEAN NOT NULL DEFAULT TRUE,
    sort_order      INTEGER NOT NULL DEFAULT 100,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Dane startowe — wymagania EU AI Act wg poziomu ryzyka
INSERT INTO ai_act_requirements (risk_level, article_ref, requirement_title, requirement_text, sort_order) VALUES

-- WYSOKIE RYZYKO
('high', 'Art. 9',  'System zarządzania ryzykiem',
 'Agent wysokiego ryzyka wymaga udokumentowanego systemu zarządzania ryzykiem przez cały cykl życia. Wymagana identyfikacja, analiza i ocena ryzyk oraz wdrożenie środków zaradczych.', 10),

('high', 'Art. 10', 'Wymagania dotyczące danych',
 'Dane treningowe, walidacyjne i testowe muszą spełniać kryteria jakości — właściwość, reprezentatywność, brak błędów i kompletność. Wymagana dokumentacja zbiorów danych.', 20),

('high', 'Art. 11', 'Dokumentacja techniczna',
 'Przed wprowadzeniem do użytku wymagana kompletna dokumentacja techniczna zgodna z Aneksem IV EU AI Act. Dokument musi być aktualizowany przez cały cykl życia systemu.', 30),

('high', 'Art. 13', 'Transparentność i informacja',
 'System AI musi zapewniać przejrzystość operacyjną. Użytkownicy muszą być informowani o interakcji z systemem AI i rozumieć jego działanie w stopniu niezbędnym do nadzoru.', 40),

('high', 'Art. 14', 'Nadzór człowieka',
 'Wdrożone środki umożliwiające rozumienie, monitorowanie i interwencję w działanie systemu AI przez człowieka. Możliwość zatrzymania lub cofnięcia każdej decyzji systemu.', 50),

('high', 'Art. 15', 'Dokładność i odporność',
 'System musi osiągać odpowiedni poziom dokładności przez cały cykl życia. Wymagane testy odporności na błędy, ataki i nieoczekiwane dane wejściowe.', 60),

('high', 'Art. 17', 'System zarządzania jakością',
 'Dostawca wdraża system zarządzania jakością obejmujący polityki, procedury i instrukcje dla zapewnienia zgodności z EU AI Act.', 70),

-- NIEDOPUSZCZALNE RYZYKO
('unacceptable', 'Art. 5', 'Bezwzględny zakaz stosowania',
 'Praktyki AI wymienione w Art. 5 są bezwzględnie zakazane w UE. Wymagana weryfikacja, czy system nie kwalifikuje się do żadnej z zakazanych kategorii (manipulacja podprogowa, scoring społeczny, identyfikacja biometryczna w czasie rzeczywistym).', 10),

-- OGRANICZONE RYZYKO
('limited', 'Art. 50 ust. 1', 'Obowiązek informowania o AI',
 'Systemy wchodzące w interakcję z ludźmi muszą informować użytkownika w jasny, czytelny i terminowy sposób o automatycznym charakterze systemu, chyba że jest to oczywiste.', 10),

('limited', 'Art. 50 ust. 4', 'Oznaczanie treści generowanych przez AI',
 'Treści tekstowe, audio i wideo generowane przez AI muszą być w sposób maszynowo czytelny oznaczone jako wygenerowane przez AI.', 20),

-- MINIMALNE RYZYKO
('minimal', 'Preambuła 46', 'Dobrowolne kodeksy postępowania',
 'Brak obowiązkowych wymogów prawnych dla systemów minimalnego ryzyka. Zalecane stosowanie dobrowolnych kodeksów postępowania i ogólnych zasad godnej zaufania AI (transparentność, sprawiedliwość, bezpieczeństwo).', 10);

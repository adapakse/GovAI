-- GovAI — Katalog wymagań EU AI Act (tabela + seed bazowy)
-- Uruchomić: psql -U govai -d govai -f 001_ai_act_requirements.sql
--
-- Ta tabela istniała już w bazie govai (ad-hoc, poza wersjonowanymi
-- migracjami) zanim zaczęto śledzić schemat w db/migrations/ — stąd
-- numer 001, mimo że dodana później niż 002-009. Rekonstrukcja 1:1 ze
-- struktury i danych z działającej instancji (16.07.2026), żeby środowisko
-- govai-int (świeży wolumen Postgresa) miało komplet schematu.
--
-- Kolumny default_severity/default_deadline_days/decl_key oraz dodatkowe
-- wiersze (Art. 43, Art. 49) dokłada migracja 006_requirements_dynamic.sql
-- — musi być aplikowana PO tej.

CREATE TABLE IF NOT EXISTS ai_act_requirements (
    id                 UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    risk_level         risk_level     NOT NULL,
    article_ref        VARCHAR(50)    NOT NULL,
    requirement_title  VARCHAR(200)   NOT NULL,
    requirement_text   TEXT           NOT NULL,
    active             BOOLEAN        NOT NULL DEFAULT true,
    sort_order         INTEGER        NOT NULL DEFAULT 100,
    created_at         TIMESTAMPTZ    NOT NULL DEFAULT NOW()
);

-- INSERT ... WHERE NOT EXISTS zamiast zwykłego INSERT — brak unikalnego
-- klucza na (risk_level, article_ref), a ta migracja musi być bezpieczna do
-- ponownego uruchomienia (np. na bazie, gdzie tabela już istniała wcześniej
-- ad-hoc, tak jak na środowisku govai).
INSERT INTO ai_act_requirements (risk_level, article_ref, requirement_title, requirement_text, sort_order)
SELECT * FROM (VALUES
    ('minimal'::risk_level, 'Preambuła 46', 'Dobrowolne kodeksy postępowania', 'Brak obowiązkowych wymogów prawnych dla systemów minimalnego ryzyka. Zalecane stosowanie dobrowolnych kodeksów postępowania i ogólnych zasad godnej zaufania AI (transparentność, sprawiedliwość, bezpieczeństwo).', 10),
    ('limited', 'Art. 50 ust. 1', 'Obowiązek informowania o AI', 'Systemy wchodzące w interakcję z ludźmi muszą informować użytkownika w jasny, czytelny i terminowy sposób o automatycznym charakterze systemu, chyba że jest to oczywiste.', 10),
    ('limited', 'Art. 50 ust. 4', 'Oznaczanie treści generowanych przez AI', 'Treści tekstowe, audio i wideo generowane przez AI muszą być w sposób maszynowo czytelny oznaczone jako wygenerowane przez AI.', 20),
    ('high', 'Art. 9', 'System zarządzania ryzykiem', 'Agent wysokiego ryzyka wymaga udokumentowanego systemu zarządzania ryzykiem przez cały cykl życia. Wymagana identyfikacja, analiza i ocena ryzyk oraz wdrożenie środków zaradczych.', 10),
    ('high', 'Art. 10', 'Wymagania dotyczące danych', 'Dane treningowe, walidacyjne i testowe muszą spełniać kryteria jakości — właściwość, reprezentatywność, brak błędów i kompletność. Wymagana dokumentacja zbiorów danych.', 20),
    ('high', 'Art. 11', 'Dokumentacja techniczna', 'Przed wprowadzeniem do użytku wymagana kompletna dokumentacja techniczna zgodna z Aneksem IV EU AI Act. Dokument musi być aktualizowany przez cały cykl życia systemu.', 30),
    ('high', 'Art. 13', 'Transparentność i informacja', 'System AI musi zapewniać przejrzystość operacyjną. Użytkownicy muszą być informowani o interakcji z systemem AI i rozumieć jego działanie w stopniu niezbędnym do nadzoru.', 40),
    ('high', 'Art. 14', 'Nadzór człowieka', 'Wdrożone środki umożliwiające rozumienie, monitorowanie i interwencję w działanie systemu AI przez człowieka. Możliwość zatrzymania lub cofnięcia każdej decyzji systemu.', 50),
    ('high', 'Art. 15', 'Dokładność i odporność', 'System musi osiągać odpowiedni poziom dokładności przez cały cykl życia. Wymagane testy odporności na błędy, ataki i nieoczekiwane dane wejściowe.', 60),
    ('high', 'Art. 17', 'System zarządzania jakością', 'Dostawca wdraża system zarządzania jakością obejmujący polityki, procedury i instrukcje dla zapewnienia zgodności z EU AI Act.', 70),
    ('unacceptable', 'Art. 5', 'Bezwzględny zakaz stosowania', 'Praktyki AI wymienione w Art. 5 są bezwzględnie zakazane w UE. Wymagana weryfikacja, czy system nie kwalifikuje się do żadnej z zakazanych kategorii (manipulacja podprogowa, scoring społeczny, identyfikacja biometryczna w czasie rzeczywistym).', 10)
) AS seed(risk_level, article_ref, requirement_title, requirement_text, sort_order)
WHERE NOT EXISTS (
    SELECT 1 FROM ai_act_requirements r
    WHERE r.risk_level = seed.risk_level AND r.article_ref = seed.article_ref
);

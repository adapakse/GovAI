-- GovAI — pełne pokrycie dziennika audytowego
-- Uruchomić: psql -U govai -d govai -f 007_audit_error_result.sql
--
-- Dotąd audit_result miał tylko allowed/blocked/oversight_required — awarie
-- infrastrukturalne (brak providera dla wymaganej wrażliwości, błąd wywołania
-- LLM u dostawcy) w ogóle nie trafiały do dziennika, bo nie pasowały do żadnej
-- z tych wartości i gateway po prostu rzucał wyjątek HTTP bez zapisu.
-- 'error' pozwala je logować bez fałszowania semantyki 'blocked' (to nie jest
-- decyzja polityki, tylko awaria/konfiguracja).

ALTER TYPE audit_result ADD VALUE IF NOT EXISTS 'error';

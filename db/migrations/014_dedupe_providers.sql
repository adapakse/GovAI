-- GovAI — Usunięcie zduplikowanych providerów
-- Uruchomić: psql -U govai -d govai -f 014_dedupe_providers.sql
--
-- 003_providers.sql nie była idempotentna, a deploy uruchamiał wszystkie migracje
-- przy każdym deployu — każdy deploy dodawał 4 providerów chmurowych ponownie
-- (na INT po 7 kopii). Zostawiamy najstarszy wiersz dla każdej nazwy; odwołania
-- z audit_log przepinamy na niego przed usunięciem kopii (FK provider_id).
-- Idempotentna: bez duplikatów nic nie robi.

WITH ranked AS (
    SELECT id, name,
           first_value(id) OVER (PARTITION BY name ORDER BY created_at, id) AS keep_id
    FROM providers
),
dupes AS (
    SELECT id, keep_id FROM ranked WHERE id <> keep_id
)
UPDATE audit_log a
   SET provider_id = d.keep_id
  FROM dupes d
 WHERE a.provider_id = d.id;

WITH ranked AS (
    SELECT id,
           first_value(id) OVER (PARTITION BY name ORDER BY created_at, id) AS keep_id
    FROM providers
)
DELETE FROM providers p
 USING ranked r
 WHERE p.id = r.id
   AND r.id <> r.keep_id;

"""
Repozytorium danych demo — JEDYNE miejsce z SQL dla seedera/resetu danych demo.

Routery i serwisy nigdy nie składają zapytań samodzielnie; wołają te funkcje.
Wszystkie wartości przekazywane jako parametry pozycyjne ($n) — brak interpolacji.
Router generuje krotki danych; repozytorium wyłącznie wykonuje SQL (asyncpg).
"""
from __future__ import annotations

from database import get_pool

# ── INSERT SQL ─────────────────────────────────────────────────────────────────

_AUDIT_INSERT = """
INSERT INTO audit_log (
    time, agent_id, agent_name, task_id, call_id, event_type,
    policy_result, policy_id, pii_categories, pii_count,
    input_hash, output_hash, model_used, latency_ms,
    tokens_in, tokens_out, cost_eur, block_reason, metadata
) VALUES (
    $1, $2::uuid, $3, $4, $5::uuid, $6,
    $7::audit_result, $8, $9::text[], $10,
    $11, $12, $13, $14,
    $15, $16, $17, $18, $19::jsonb
)
"""

_OVERSIGHT_INSERT = """
INSERT INTO oversight_queue (
    agent_id, task_id, decision_type, agent_decision, agent_reasoning,
    input_hash, confidence, status, reviewer_id, reviewer_decision,
    review_start_at, reviewed_at, ttl_expires_at, created_at
) VALUES (
    $1::uuid, $2, $3, $4, $5,
    $6, $7, $8::oversight_status, $9, $10,
    $11, $12, $13, $14
)
"""


# Kolejność MUSI zgadzać się z placeholderami $1.. w _FLEET_INSERT poniżej —
# jedyne miejsce, które zna to mapowanie (routery przekazują zwykłe dicty).
_FLEET_COLUMNS = [
    "id", "name", "description", "owner_name", "owner_email", "team",
    "risk_level", "annex_iii_cat", "legal_basis",
    "requires_oversight", "model_id", "monthly_budget_eur", "cost_alert_threshold_eur",
    "next_review_date", "last_reviewed_at", "processes_personal_data", "gdpr_legal_basis",
    "data_retention_days",
    "intended_purpose", "intended_users", "geographic_scope",
    "input_modalities", "output_modalities", "integration_points",
    "model_version", "technical_contact_email", "compliance_officer_email",
    "compliance_decl",
]

_FLEET_INSERT = """
INSERT INTO agents (
    id, name, description, owner_name, owner_email, team,
    risk_level, annex_iii_cat, legal_basis, status,
    requires_oversight, model_id, monthly_budget_eur, cost_alert_threshold_eur,
    next_review_date, last_reviewed_at, processes_personal_data, gdpr_legal_basis,
    data_retention_days,
    intended_purpose, intended_users, geographic_scope,
    input_modalities, output_modalities, integration_points,
    model_version, technical_contact_email, compliance_officer_email,
    compliance_decl
) VALUES (
    $1::uuid, $2, $3, $4, $5, $6,
    $7::risk_level, $8, $9, 'active'::agent_status,
    $10, $11, $12, $13,
    $14, $15, $16, $17,
    $18,
    $19, $20, $21,
    $22::text[], $23::text[], $24::text[],
    $25, $26, $27,
    $28
)
"""

# Predykat odporny na obie formy zapisu markera (natywny obiekt jsonb oraz —
# dla ewentualnych starych wierszy — podwójnie zakodowany string JSON).
_FLEET_PREDICATE = "compliance_decl::text LIKE '%seeded_fleet%'"


def _fleet_row_to_tuple(row: dict) -> tuple:
    return tuple(row[c] for c in _FLEET_COLUMNS)


async def seed_entries(audit_entries: list[tuple], oversight_entries: list[tuple]) -> None:
    """Wstawia wpisy audytowe i nadzoru w jednej transakcji."""
    pool = get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.executemany(_AUDIT_INSERT, audit_entries)
            await conn.executemany(_OVERSIGHT_INSERT, oversight_entries)


async def seed_fleet(agent_rows: list[dict]) -> int:
    """Wstawia flotę agentów demonstracyjnych (oznaczonych compliance_decl.seeded_fleet).

    agent_rows — lista dictów kluczowanych nazwami kolumn (zob. _FLEET_COLUMNS).
    Idempotentne: najpierw czyści poprzednią flotę, potem wstawia nową.
    Zwraca liczbę wstawionych agentów.
    """
    pool = get_pool()
    tuples = [_fleet_row_to_tuple(r) for r in agent_rows]
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute(f"DELETE FROM agents WHERE {_FLEET_PREDICATE}")
            await conn.executemany(_FLEET_INSERT, tuples)
    return len(tuples)


async def reset_fleet() -> int:
    """Usuwa flotę demonstracyjną. Zwraca liczbę usuniętych agentów."""
    pool = get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            n = await conn.fetchval(f"SELECT COUNT(*) FROM agents WHERE {_FLEET_PREDICATE}")
            await conn.execute(f"DELETE FROM agents WHERE {_FLEET_PREDICATE}")
    return n


async def fleet_count() -> int:
    """Liczba agentów należących do floty demonstracyjnej."""
    pool = get_pool()
    return await pool.fetchval(f"SELECT COUNT(*) FROM agents WHERE {_FLEET_PREDICATE}")


async def reset_demo(ids: list[str]) -> tuple[int, int]:
    """Usuwa dane audit_log i oversight_queue dla podanych agentów. Zwraca (n_audit, n_oq)."""
    pool = get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            n_audit = await conn.fetchval(
                "SELECT COUNT(*) FROM audit_log WHERE agent_id = ANY($1::uuid[])", ids
            )
            await conn.execute(
                "DELETE FROM audit_log WHERE agent_id = ANY($1::uuid[])", ids
            )
            n_oq = await conn.fetchval(
                "SELECT COUNT(*) FROM oversight_queue WHERE agent_id = ANY($1::uuid[])", ids
            )
            await conn.execute(
                "DELETE FROM oversight_queue WHERE agent_id = ANY($1::uuid[])", ids
            )
    return n_audit, n_oq


async def seed_status(ids: list[str]) -> tuple[int, int]:
    """Zwraca liczbę wpisów (n_audit, n_oq) dla podanych agentów."""
    pool = get_pool()
    n_audit = await pool.fetchval(
        "SELECT COUNT(*) FROM audit_log WHERE agent_id = ANY($1::uuid[])", ids
    )
    n_oq = await pool.fetchval(
        "SELECT COUNT(*) FROM oversight_queue WHERE agent_id = ANY($1::uuid[])", ids
    )
    return n_audit, n_oq

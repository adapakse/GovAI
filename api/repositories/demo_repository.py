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


async def seed_entries(audit_entries: list[tuple], oversight_entries: list[tuple]) -> None:
    """Wstawia wpisy audytowe i nadzoru w jednej transakcji."""
    pool = get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.executemany(_AUDIT_INSERT, audit_entries)
            await conn.executemany(_OVERSIGHT_INSERT, oversight_entries)


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

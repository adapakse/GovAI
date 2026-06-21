"""
Repozytorium dziennika audytowego — JEDYNE miejsce z SQL dla tabeli audit_log.

Routery i serwisy nigdy nie składają zapytań samodzielnie; wołają te funkcje.
Wszystkie wartości przekazywane jako parametry pozycyjne ($n) — brak interpolacji.
Funkcje zwracają surowy wynik asyncpg (Record / list[Record]) — konwersję
na dict wykonuje router.
"""
from __future__ import annotations

from typing import Optional


from database import get_pool


async def list_audit(
    days: int,
    limit: int,
    offset: int,
    agent_id: Optional[str] = None,
    event_type: Optional[str] = None,
    policy_result: Optional[str] = None,
    has_pii: Optional[bool] = None,
):
    pool = get_pool()
    conditions = ["time > NOW() - ($1 || ' days')::INTERVAL"]
    params = [str(days)]
    idx = 2

    if agent_id:
        conditions.append(f"agent_id = ${idx}"); params.append(agent_id); idx += 1
    if event_type:
        conditions.append(f"event_type = ${idx}"); params.append(event_type); idx += 1
    if policy_result:
        conditions.append(f"policy_result = ${idx}::audit_result"); params.append(policy_result); idx += 1
    if has_pii is True:
        conditions.append("pii_count > 0")
    elif has_pii is False:
        conditions.append("pii_count = 0")

    where = " AND ".join(conditions)
    return await pool.fetch(
        f"""SELECT time, id, agent_id, agent_name, task_id, call_id,
                   event_type, policy_result, policy_id,
                   pii_categories, pii_count,
                   input_hash, output_hash, model_used,
                   latency_ms, tokens_in, tokens_out, cost_eur, block_reason
            FROM audit_log
            WHERE {where}
            ORDER BY time DESC
            LIMIT ${idx} OFFSET ${idx+1}""",
        *params, limit, offset,
    )


async def summary(days: int):
    pool = get_pool()
    return await pool.fetchrow(
        """SELECT
               COUNT(*)                                              AS total_calls,
               COUNT(DISTINCT agent_id)                             AS unique_agents,
               COUNT(*) FILTER (WHERE policy_result = 'blocked')    AS blocked,
               COUNT(*) FILTER (WHERE policy_result = 'oversight_required') AS oversight,
               COUNT(*) FILTER (WHERE pii_count > 0)                AS pii_detected,
               COALESCE(SUM(cost_eur), 0)                           AS total_cost_eur,
               ROUND(AVG(latency_ms))                               AS avg_latency_ms
           FROM audit_log
           WHERE time > NOW() - ($1 || ' days')::INTERVAL""",
        str(days),
    )


async def get_call(call_id: str):
    pool = get_pool()
    return await pool.fetchrow(
        "SELECT * FROM audit_log WHERE call_id = $1 ORDER BY time DESC LIMIT 1",
        call_id,
    )

"""
Repozytorium pulpitu — JEDYNE miejsce z SQL dla endpointów dashboardu.

Routery nigdy nie składają zapytań samodzielnie; wołają te funkcje.
Funkcje zwracają surowy wynik asyncpg (.fetch/.fetchrow/.fetchval) — bez konwersji.
Wszystkie wartości przekazywane jako parametry pozycyjne ($n) — brak interpolacji.
"""
from __future__ import annotations

from database import get_pool


async def agents_stats():
    pool = get_pool()
    return await pool.fetchrow(
        """SELECT
               COUNT(*)                                    AS total,
               COUNT(*) FILTER (WHERE status = 'active')  AS active,
               COUNT(*) FILTER (WHERE status = 'suspended' OR status = 'quarantined') AS suspended,
               COUNT(*) FILTER (WHERE risk_level = 'high' OR risk_level = 'unacceptable') AS high_risk
           FROM agents"""
    )


async def call_stats(days: int):
    pool = get_pool()
    return await pool.fetchrow(
        """SELECT
               COUNT(*)                                              AS total_calls,
               COUNT(*) FILTER (WHERE policy_result = 'blocked')    AS blocked,
               COUNT(*) FILTER (WHERE policy_result = 'oversight_required') AS oversight_required,
               COUNT(*) FILTER (WHERE policy_result = 'error')      AS errors,
               COUNT(*) FILTER (WHERE pii_count > 0)                AS pii_calls,
               COALESCE(SUM(cost_eur), 0)                           AS total_cost_eur,
               ROUND(AVG(latency_ms))                               AS avg_latency_ms
           FROM audit_log
           WHERE time > NOW() - ($1 || ' days')::INTERVAL""",
        str(days),
    )


async def pending_oversight_count():
    pool = get_pool()
    return await pool.fetchval(
        "SELECT COUNT(*) FROM oversight_queue WHERE status = 'pending' AND ttl_expires_at > NOW()"
    )


async def top_agents(days: int, top_n: int):
    pool = get_pool()
    return await pool.fetch(
        """SELECT agent_name, COUNT(*) AS calls,
                  COUNT(*) FILTER (WHERE policy_result = 'blocked') AS blocked,
                  COALESCE(SUM(cost_eur), 0) AS cost_eur
           FROM audit_log
           WHERE time > NOW() - ($1 || ' days')::INTERVAL
           GROUP BY agent_name
           ORDER BY calls DESC
           LIMIT $2""",
        str(days), top_n,
    )


async def recent_blocks(days: int, recent_n: int):
    pool = get_pool()
    return await pool.fetch(
        """SELECT time, agent_name, event_type, policy_result,
                  pii_categories, block_reason
           FROM audit_log
           WHERE policy_result IN ('blocked', 'oversight_required', 'error')
             AND time > NOW() - ($1 || ' days')::INTERVAL
           ORDER BY time DESC
           LIMIT $2""",
        str(days), recent_n,
    )


async def timeline(hours: int):
    pool = get_pool()
    return await pool.fetch(
        """
        SELECT
            date_trunc('hour', time)                                        AS hour,
            COUNT(*)                                                         AS total,
            COUNT(*) FILTER (WHERE policy_result = 'blocked')               AS blocked,
            COUNT(*) FILTER (WHERE policy_result = 'oversight_required')    AS oversight
        FROM audit_log
        WHERE time > NOW() - ($1 * INTERVAL '1 hour')
        GROUP BY hour
        ORDER BY hour
        """,
        hours,
    )

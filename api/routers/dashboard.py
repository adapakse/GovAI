import asyncio
import json
import logging

from fastapi import APIRouter, Depends, Query, WebSocket, WebSocketDisconnect
from database import get_pool
from dependencies.auth import CurrentUser, get_current_user

logger = logging.getLogger(__name__)
router = APIRouter(tags=["dashboard"])

_redis = None


def set_redis(r) -> None:
    global _redis
    _redis = r


@router.get("/dashboard/summary")
async def dashboard_summary(
    days: int = Query(7, ge=1, le=30),
    user: CurrentUser = Depends(get_current_user),
):
    """
    Agregaty dla pulpitu operacyjnego.
    Jeden endpoint zamiast N osobnych zapytań z frontendu.
    """
    pool = get_pool()

    agents_stats = await pool.fetchrow(
        """SELECT
               COUNT(*)                                    AS total,
               COUNT(*) FILTER (WHERE status = 'active')  AS active,
               COUNT(*) FILTER (WHERE status = 'suspended' OR status = 'quarantined') AS suspended,
               COUNT(*) FILTER (WHERE risk_level = 'high' OR risk_level = 'unacceptable') AS high_risk
           FROM agents"""
    )

    call_stats = await pool.fetchrow(
        """SELECT
               COUNT(*)                                              AS total_calls,
               COUNT(*) FILTER (WHERE policy_result = 'blocked')    AS blocked,
               COUNT(*) FILTER (WHERE policy_result = 'oversight_required') AS oversight_required,
               COUNT(*) FILTER (WHERE pii_count > 0)                AS pii_calls,
               COALESCE(SUM(cost_eur), 0)                           AS total_cost_eur,
               ROUND(AVG(latency_ms))                               AS avg_latency_ms
           FROM audit_log
           WHERE time > NOW() - ($1 || ' days')::INTERVAL""",
        str(days),
    )

    pending_oversight = await pool.fetchval(
        "SELECT COUNT(*) FROM oversight_queue WHERE status = 'pending' AND ttl_expires_at > NOW()"
    )

    top_agents = await pool.fetch(
        """SELECT agent_name, COUNT(*) AS calls,
                  COUNT(*) FILTER (WHERE policy_result = 'blocked') AS blocked,
                  COALESCE(SUM(cost_eur), 0) AS cost_eur
           FROM audit_log
           WHERE time > NOW() - ($1 || ' days')::INTERVAL
           GROUP BY agent_name
           ORDER BY calls DESC
           LIMIT 5""",
        str(days),
    )

    recent_blocks = await pool.fetch(
        """SELECT time, agent_name, event_type, policy_result,
                  pii_categories, block_reason
           FROM audit_log
           WHERE policy_result IN ('blocked', 'oversight_required')
             AND time > NOW() - ($1 || ' days')::INTERVAL
           ORDER BY time DESC
           LIMIT 10""",
        str(days),
    )

    return {
        "period_days": days,
        "agents": dict(agents_stats),
        "calls": dict(call_stats),
        "pending_oversight": pending_oversight,
        "top_agents": [dict(r) for r in top_agents],
        "recent_alerts": [_row_to_dict(r) for r in recent_blocks],
    }


@router.get("/dashboard/timeline")
async def dashboard_timeline(
    hours: int = Query(24, ge=1, le=72),
    user: CurrentUser = Depends(get_current_user),
):
    """Godzinowe zestawienie wywołań agentów (ostatnie N godzin)."""
    pool = get_pool()
    rows = await pool.fetch(
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
    return [
        {
            "hour":     row["hour"].strftime("%H:%M"),
            "total":    row["total"],
            "blocked":  row["blocked"],
            "oversight": row["oversight"],
        }
        for row in rows
    ]


@router.websocket("/ws/live-feed")
async def live_feed(websocket: WebSocket):
    """
    WebSocket stream zdarzeń real-time dla pulpitu operacyjnego.
    Subskrybuje kanały Redis: audit:new_call, audit:blocked, oversight:pending.
    """
    await websocket.accept()

    if _redis is None:
        await websocket.send_json({"type": "error", "message": "Redis niedostępny"})
        await websocket.close()
        return

    pubsub = _redis.pubsub()
    await pubsub.subscribe("audit:new_call", "audit:blocked", "oversight:pending", "oversight:escalated")

    try:
        async for message in pubsub.listen():
            if message["type"] == "message":
                try:
                    payload = json.loads(message["data"])
                except Exception:
                    payload = {"raw": message["data"]}

                await websocket.send_json({
                    "type": message["channel"],
                    "payload": payload,
                })
    except WebSocketDisconnect:
        pass
    finally:
        await pubsub.unsubscribe()
        await pubsub.aclose()


def _row_to_dict(row) -> dict:
    d = dict(row)
    for k, v in d.items():
        if hasattr(v, 'isoformat'):
            d[k] = v.isoformat()
        elif hasattr(v, '__iter__') and not isinstance(v, (str, bytes, dict)):
            d[k] = list(v)
    return d

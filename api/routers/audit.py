import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from database import get_pool
from dependencies.auth import CurrentUser, get_current_user, require_role

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/audit", tags=["audit"])

_AUDIT_ROLES = require_role("partner", "it_admin", "compliance_officer", "associate")


@router.get("")
async def list_audit(
    agent_id: Optional[str] = Query(None),
    event_type: Optional[str] = Query(None),
    policy_result: Optional[str] = Query(None),
    has_pii: Optional[bool] = Query(None),
    days: int = Query(7, ge=1, le=90),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    user: CurrentUser = Depends(_AUDIT_ROLES),
):
    """Dziennik audytowy z filtrowaniem."""
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
    rows = await pool.fetch(
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
    return [_row_to_dict(r) for r in rows]


@router.get("/summary")
async def get_summary(
    days: int = Query(7, ge=1, le=90),
    user: CurrentUser = Depends(_AUDIT_ROLES),
):
    """Podsumowanie dziennika audytowego."""
    pool = get_pool()
    row = await pool.fetchrow(
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
    return {**dict(row), "period_days": days}


@router.get("/{call_id}")
async def get_call(call_id: str, user: CurrentUser = Depends(_AUDIT_ROLES)):
    """Szczegóły pojedynczego wywołania."""
    pool = get_pool()
    row = await pool.fetchrow(
        "SELECT * FROM audit_log WHERE call_id = $1 ORDER BY time DESC LIMIT 1",
        call_id,
    )
    if not row:
        raise HTTPException(404, f"Wywołanie '{call_id}' nie znalezione w dzienniku")
    return _row_to_dict(row)


def _row_to_dict(row) -> dict:
    d = dict(row)
    for k, v in d.items():
        if hasattr(v, 'isoformat'):
            d[k] = v.isoformat()
        elif hasattr(v, '__iter__') and not isinstance(v, (str, bytes, dict)):
            d[k] = list(v)
    for f in ("id", "agent_id", "call_id"):
        if d.get(f):
            d[f] = str(d[f])
    return d

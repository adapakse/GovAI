import logging
from typing import Optional
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, EmailStr, field_validator

from database import get_pool
from services.ai_act_classifier import classify_risk
from services.compliance import assess_compliance

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/agents", tags=["agents"])


# ── Schematy ──────────────────────────────────────────────────────────────────

class AgentCreate(BaseModel):
    name: str
    description: str
    owner_name: str
    owner_email: str
    team: Optional[str] = None
    model_id: str = "claude-haiku-4-5-20251001"
    monthly_budget_eur: float = 0.0
    allowed_data_cats: list[str] = []
    allowed_tools: list[str] = []

    @field_validator("name")
    @classmethod
    def name_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Nazwa agenta nie może być pusta")
        return v.strip()


class AgentStatusUpdate(BaseModel):
    status: str

    @field_validator("status")
    @classmethod
    def valid_status(cls, v: str) -> str:
        allowed = {"active", "suspended", "quarantined", "retired"}
        if v not in allowed:
            raise ValueError(f"Nieprawidłowy status. Dozwolone: {allowed}")
        return v


# ── Endpointy ─────────────────────────────────────────────────────────────────

@router.get("")
async def list_agents(
    risk_level: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    team: Optional[str] = Query(None),
):
    """Lista wszystkich agentów z opcjonalnym filtrowaniem."""
    pool = get_pool()

    conditions = ["1=1"]
    params = []
    idx = 1

    if risk_level:
        conditions.append(f"risk_level = ${idx}::risk_level")
        params.append(risk_level); idx += 1
    if status:
        conditions.append(f"status = ${idx}::agent_status")
        params.append(status); idx += 1
    if team:
        conditions.append(f"team ILIKE ${idx}")
        params.append(f"%{team}%"); idx += 1

    where = " AND ".join(conditions)
    rows = await pool.fetch(
        f"""SELECT id, name, description, owner_name, owner_email, team,
                   risk_level, annex_iii_cat, legal_basis, status,
                   requires_oversight, model_id, monthly_budget_eur,
                   allowed_data_cats, created_at, updated_at
            FROM agents
            WHERE {where}
            ORDER BY name""",
        *params,
    )
    return [_row_to_dict(r) for r in rows]


@router.post("", status_code=201)
async def register_agent(data: AgentCreate):
    """
    Rejestracja nowego agenta z automatyczną klasyfikacją AI Act.
    Claude analizuje opis i przypisuje poziom ryzyka, kategorię i podstawę prawną.
    """
    pool = get_pool()

    logger.info("Klasyfikuję agenta: %s", data.name)
    classification = await classify_risk(data.description)
    logger.info(
        "Klasyfikacja: risk=%s cat=%s oversight=%s",
        classification.risk_level, classification.annex_iii_cat, classification.requires_oversight,
    )

    agent_id = str(uuid4())
    await pool.execute(
        """INSERT INTO agents (
               id, name, description, owner_name, owner_email, team,
               risk_level, annex_iii_cat, legal_basis, status,
               requires_oversight, model_id, monthly_budget_eur,
               allowed_data_cats, allowed_tools
           ) VALUES (
               $1, $2, $3, $4, $5, $6,
               $7::risk_level, $8, $9, 'active'::agent_status,
               $10, $11, $12,
               $13, $14
           )""",
        agent_id, data.name, data.description, data.owner_name, data.owner_email, data.team,
        classification.risk_level, classification.annex_iii_cat, classification.legal_basis,
        classification.requires_oversight, data.model_id, data.monthly_budget_eur,
        data.allowed_data_cats, data.allowed_tools,
    )

    row = await pool.fetchrow("SELECT * FROM agents WHERE id = $1", agent_id)
    result = _row_to_dict(row)
    result["classification_details"] = {
        "key_obligations": classification.key_obligations,
        "auto_classified": True,
    }
    return result


@router.get("/{agent_id}")
async def get_agent(agent_id: str):
    """Szczegóły agenta."""
    pool = get_pool()
    row = await pool.fetchrow("SELECT * FROM agents WHERE id = $1", agent_id)
    if not row:
        raise HTTPException(404, f"Agent '{agent_id}' nie istnieje")
    return _row_to_dict(row)


@router.patch("/{agent_id}/status")
async def update_status(agent_id: str, body: AgentStatusUpdate):
    """
    Zmiana statusu agenta (active / suspended / quarantined / retired).
    Natychmiastowy efekt — bramka weryfikuje status przy każdym wywołaniu.
    """
    pool = get_pool()
    row = await pool.fetchrow("SELECT id, name, status FROM agents WHERE id = $1", agent_id)
    if not row:
        raise HTTPException(404, f"Agent '{agent_id}' nie istnieje")

    await pool.execute(
        "UPDATE agents SET status = $1::agent_status, updated_at = NOW() WHERE id = $2",
        body.status, agent_id,
    )
    logger.info("Status agenta %s zmieniony: %s → %s", row["name"], row["status"], body.status)
    return {"agent_id": agent_id, "name": row["name"], "old_status": row["status"], "new_status": body.status}


@router.get("/{agent_id}/compliance")
async def get_compliance(agent_id: str):
    """
    Pełna ocena zgodności agenta z EU AI Act.
    Identyfikuje luki i zwraca plan naprawczy z terminami.
    """
    pool = get_pool()
    row = await pool.fetchrow("SELECT * FROM agents WHERE id = $1", agent_id)
    if not row:
        raise HTTPException(404, f"Agent '{agent_id}' nie istnieje")

    report = assess_compliance(dict(row))

    return {
        "agent_id": agent_id,
        "agent_name": report.agent_name,
        "risk_level": report.risk_level,
        "status": report.status,
        "gaps_count": len(report.gaps),
        "gaps": [
            {
                "article": g.article,
                "title": g.title,
                "description": g.description,
                "severity": g.severity,
                "action": g.action,
                "deadline_days": g.deadline_days,
            }
            for g in report.gaps
        ],
        "obligations": report.obligations,
        "summary": _compliance_summary(report),
    }


@router.get("/{agent_id}/stats")
async def get_stats(agent_id: str, days: int = Query(30, ge=1, le=90)):
    """Statystyki wywołań agenta z dziennika audytowego (ostatnie N dni)."""
    pool = get_pool()

    agent = await pool.fetchrow("SELECT id, name FROM agents WHERE id = $1", agent_id)
    if not agent:
        raise HTTPException(404, f"Agent '{agent_id}' nie istnieje")

    stats = await pool.fetchrow(
        """SELECT
               COUNT(*)                                              AS total_calls,
               COUNT(*) FILTER (WHERE policy_result = 'blocked')    AS blocked_calls,
               COUNT(*) FILTER (WHERE policy_result = 'oversight_required') AS oversight_calls,
               COUNT(*) FILTER (WHERE pii_count > 0)                AS pii_calls,
               ROUND(AVG(latency_ms))                               AS avg_latency_ms,
               MAX(latency_ms)                                       AS max_latency_ms,
               COALESCE(SUM(cost_eur), 0)                           AS total_cost_eur,
               COALESCE(SUM(tokens_in), 0)                          AS total_tokens_in,
               COALESCE(SUM(tokens_out), 0)                         AS total_tokens_out,
               COALESCE(SUM(pii_count), 0)                          AS total_pii_detected
           FROM audit_log
           WHERE agent_id = $1
             AND time > NOW() - ($2 || ' days')::INTERVAL""",
        agent_id, str(days),
    )

    daily = await pool.fetch(
        """SELECT
               DATE_TRUNC('day', time) AS day,
               COUNT(*)                AS calls,
               COUNT(*) FILTER (WHERE policy_result = 'blocked') AS blocked,
               COALESCE(SUM(cost_eur), 0) AS cost_eur
           FROM audit_log
           WHERE agent_id = $1
             AND time > NOW() - ($2 || ' days')::INTERVAL
           GROUP BY 1
           ORDER BY 1""",
        agent_id, str(days),
    )

    return {
        "agent_id": agent_id,
        "agent_name": agent["name"],
        "period_days": days,
        "totals": dict(stats),
        "daily": [dict(r) for r in daily],
    }


# ── Helpers ───────────────────────────────────────────────────────────────────

def _row_to_dict(row) -> dict:
    d = dict(row)
    for k, v in d.items():
        if hasattr(v, 'isoformat'):
            d[k] = v.isoformat()
        elif hasattr(v, '__iter__') and not isinstance(v, (str, bytes, dict)):
            d[k] = list(v)
    d["id"] = str(d["id"])
    return d


def _compliance_summary(report) -> str:
    if report.status == "compliant":
        return f"Agent '{report.name}' spełnia wymagania EU AI Act."
    critical = [g for g in report.gaps if g.severity == "critical"]
    major = [g for g in report.gaps if g.severity == "major"]
    parts = []
    if critical:
        parts.append(f"{len(critical)} krytyczne luki wymagają natychmiastowego działania")
    if major:
        parts.append(f"{len(major)} ważnych luk do uzupełnienia")
    return f"Agent '{report.agent_name}' wymaga działań: " + ", ".join(parts) + "."

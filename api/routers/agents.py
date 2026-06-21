import logging
from typing import Optional
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, field_validator

from database import get_pool
from dependencies.auth import CurrentUser, get_current_user, require_role
from services import settings_service
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
    model_id: Optional[str] = None          # domyślny z parametrów (models.default_agent_model)
    monthly_budget_eur: Optional[float] = None  # domyślny z parametrów (budget.default_monthly_eur)
    allowed_data_cats: list[str] = []
    allowed_tools: list[str] = []

    @field_validator("name")
    @classmethod
    def name_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Nazwa agenta nie może być pusta")
        return v.strip()


class AgentRegistryUpdate(BaseModel):
    """Pola rejestru — wszystkie opcjonalne, zapisujemy tylko to co podano."""
    # Wersjonowanie
    version:                  Optional[str]   = None
    last_reviewed_at:         Optional[str]   = None   # ISO datetime
    next_review_date:         Optional[str]   = None   # ISO date

    # Deklaracje AI Act
    compliance_decl:          Optional[dict]  = None

    # Dane i prywatność
    processes_personal_data:  Optional[bool]  = None
    gdpr_legal_basis:         Optional[str]   = None
    data_retention_days:      Optional[int]   = None

    # Przeznaczenie
    intended_purpose:         Optional[str]   = None
    intended_users:           Optional[str]   = None
    geographic_scope:         Optional[str]   = None

    # Techniczne
    input_modalities:         Optional[list[str]] = None
    output_modalities:        Optional[list[str]] = None
    integration_points:       Optional[list[str]] = None
    model_version:            Optional[str]   = None

    # Kontakty
    technical_contact_email:  Optional[str]   = None
    compliance_officer_email: Optional[str]   = None

    # Budżet
    monthly_budget_eur:       Optional[float] = None
    cost_alert_threshold_eur: Optional[float] = None


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
    user: CurrentUser = Depends(get_current_user),
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
async def register_agent(
    data: AgentCreate,
    user: CurrentUser = Depends(require_role("partner", "it_admin", "associate")),
):
    """
    Rejestracja nowego agenta z automatyczną klasyfikacją AI Act.
    Claude analizuje opis i przypisuje poziom ryzyka, kategorię i podstawę prawną.
    """
    pool = get_pool()

    model_id = data.model_id or settings_service.get_str(
        "models.default_agent_model", "claude-haiku-4-5-20251001")
    monthly_budget = (
        data.monthly_budget_eur if data.monthly_budget_eur is not None
        else settings_service.get_number("budget.default_monthly_eur", 0.0)
    )

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
        classification.requires_oversight, model_id, monthly_budget,
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
async def get_agent(agent_id: str, user: CurrentUser = Depends(get_current_user)):
    """Szczegóły agenta."""
    pool = get_pool()
    row = await pool.fetchrow("SELECT * FROM agents WHERE id = $1", agent_id)
    if not row:
        raise HTTPException(404, f"Agent '{agent_id}' nie istnieje")
    return _row_to_dict(row)


@router.patch("/{agent_id}/status")
async def update_status(
    agent_id: str,
    body: AgentStatusUpdate,
    user: CurrentUser = Depends(require_role("partner", "it_admin")),
):
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


@router.patch("/{agent_id}/registry")
async def update_registry(
    agent_id: str,
    data: AgentRegistryUpdate,
    user: CurrentUser = Depends(require_role("partner", "it_admin", "associate")),
):
    """
    Aktualizacja danych rejestru agenta — deklaracje compliance, wersja,
    dane osobowe, kontakty, budżet. Partial update — tylko podane pola.
    """
    import json as _json
    pool = get_pool()
    row = await pool.fetchrow("SELECT id FROM agents WHERE id = $1", agent_id)
    if not row:
        raise HTTPException(404, f"Agent '{agent_id}' nie istnieje")

    updates, params = [], []
    idx = 1

    simple_fields = [
        "version", "last_reviewed_at", "next_review_date",
        "processes_personal_data", "gdpr_legal_basis", "data_retention_days",
        "intended_purpose", "intended_users", "geographic_scope",
        "model_version", "technical_contact_email", "compliance_officer_email",
        "monthly_budget_eur", "cost_alert_threshold_eur",
    ]
    array_fields = ["input_modalities", "output_modalities", "integration_points"]

    for field in simple_fields:
        val = getattr(data, field)
        if val is not None:
            updates.append(f"{field} = ${idx}")
            params.append(val); idx += 1

    for field in array_fields:
        val = getattr(data, field)
        if val is not None:
            updates.append(f"{field} = ${idx}::text[]")
            params.append(val); idx += 1

    if data.compliance_decl is not None:
        updates.append(f"compliance_decl = ${idx}::jsonb")
        params.append(_json.dumps(data.compliance_decl)); idx += 1

    if not updates:
        raise HTTPException(400, "Brak pól do aktualizacji")

    updates.append("updated_at = NOW()")
    params.append(agent_id)
    await pool.execute(
        f"UPDATE agents SET {', '.join(updates)} WHERE id = ${idx}",
        *params,
    )
    row = await pool.fetchrow("SELECT * FROM agents WHERE id = $1", agent_id)
    return _row_to_dict(row)


@router.get("/{agent_id}/compliance")
async def get_compliance(agent_id: str, user: CurrentUser = Depends(get_current_user)):
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
async def get_stats(
    agent_id: str,
    days: Optional[int] = Query(None, ge=1),
    user: CurrentUser = Depends(get_current_user),
):
    """Statystyki wywołań agenta z dziennika audytowego (ostatnie N dni)."""
    max_days = settings_service.get_int("pagination.stats_max_days", 90)
    days = min(days or settings_service.get_int("pagination.stats_default_days", 30), max_days)
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
    import json as _json
    d = dict(row)
    for k, v in d.items():
        if hasattr(v, 'isoformat'):
            d[k] = v.isoformat()
        elif hasattr(v, '__iter__') and not isinstance(v, (str, bytes, dict)):
            d[k] = list(v)
    d["id"] = str(d["id"])
    # asyncpg zwraca JSONB jako string — odkoduj
    if isinstance(d.get("compliance_decl"), str):
        try:
            d["compliance_decl"] = _json.loads(d["compliance_decl"])
        except Exception:
            d["compliance_decl"] = {}
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

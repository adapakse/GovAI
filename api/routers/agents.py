import logging
from typing import Optional
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, field_validator

from dependencies.auth import CurrentUser, get_current_user, require_role
from repositories import agents_repository as agents_repo
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
    rows = await agents_repo.list_agents(risk_level, status, team)
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
    await agents_repo.insert_agent(
        agent_id, data.name, data.description, data.owner_name, data.owner_email, data.team,
        classification.risk_level, classification.annex_iii_cat, classification.legal_basis,
        classification.requires_oversight, model_id, monthly_budget,
        data.allowed_data_cats, data.allowed_tools,
    )

    row = await agents_repo.get_agent_by_id(agent_id)
    result = _row_to_dict(row)
    result["classification_details"] = {
        "key_obligations": classification.key_obligations,
        "auto_classified": True,
    }
    return result


@router.get("/{agent_id}")
async def get_agent(agent_id: str, user: CurrentUser = Depends(get_current_user)):
    """Szczegóły agenta."""
    row = await agents_repo.get_agent_by_id(agent_id)
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
    row = await agents_repo.get_agent_status(agent_id)
    if not row:
        raise HTTPException(404, f"Agent '{agent_id}' nie istnieje")

    await agents_repo.update_status(agent_id, body.status)
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
    row = await agents_repo.get_agent_id_only(agent_id)
    if not row:
        raise HTTPException(404, f"Agent '{agent_id}' nie istnieje")

    simple_fields = [
        "version", "last_reviewed_at", "next_review_date",
        "processes_personal_data", "gdpr_legal_basis", "data_retention_days",
        "intended_purpose", "intended_users", "geographic_scope",
        "model_version", "technical_contact_email", "compliance_officer_email",
        "monthly_budget_eur", "cost_alert_threshold_eur",
    ]
    array_fields = ["input_modalities", "output_modalities", "integration_points"]

    simple_values = {}
    for field in simple_fields:
        val = getattr(data, field)
        if val is not None:
            simple_values[field] = val

    array_values = {}
    for field in array_fields:
        val = getattr(data, field)
        if val is not None:
            array_values[field] = val

    compliance_decl_json = (
        _json.dumps(data.compliance_decl) if data.compliance_decl is not None else None
    )

    if not simple_values and not array_values and compliance_decl_json is None:
        raise HTTPException(400, "Brak pól do aktualizacji")

    await agents_repo.update_registry(
        agent_id, simple_values, array_values, compliance_decl_json,
    )
    row = await agents_repo.get_agent_by_id(agent_id)
    return _row_to_dict(row)


@router.get("/{agent_id}/compliance")
async def get_compliance(agent_id: str, user: CurrentUser = Depends(get_current_user)):
    """
    Pełna ocena zgodności agenta z EU AI Act.
    Identyfikuje luki i zwraca plan naprawczy z terminami.
    """
    row = await agents_repo.get_agent_by_id(agent_id)
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

    agent = await agents_repo.get_agent_name(agent_id)
    if not agent:
        raise HTTPException(404, f"Agent '{agent_id}' nie istnieje")

    stats = await agents_repo.fetch_stats_totals(agent_id, str(days))

    daily = await agents_repo.fetch_stats_daily(agent_id, str(days))

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

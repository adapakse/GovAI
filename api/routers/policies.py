import logging
from typing import Optional
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, field_validator

from dependencies.auth import CurrentUser, get_current_user, require_role
from repositories import policies_repository as policies_repo

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/policies", tags=["policies"])

_WRITE_ROLES = require_role("partner", "it_admin")


class PolicyCreate(BaseModel):
    name: str
    policy_code: Optional[str] = None
    level: str
    agent_id: Optional[str] = None
    team: Optional[str] = None
    rule_type: str
    condition_json: dict
    action_json: dict
    priority: int = 100
    created_by: Optional[str] = None

    @field_validator("level")
    @classmethod
    def valid_level(cls, v: str) -> str:
        if v not in {"org", "team", "agent"}:
            raise ValueError("Poziom musi być: org, team lub agent")
        return v

    @field_validator("rule_type")
    @classmethod
    def valid_rule_type(cls, v: str) -> str:
        if v not in {"allow", "deny", "require_oversight"}:
            raise ValueError("Typ reguły musi być: allow, deny lub require_oversight")
        return v


class PolicyUpdate(BaseModel):
    name: Optional[str] = None
    condition_json: Optional[dict] = None
    action_json: Optional[dict] = None
    priority: Optional[int] = None
    active: Optional[bool] = None


@router.get("")
async def list_policies(
    level: Optional[str] = Query(None),
    agent_id: Optional[str] = Query(None),
    active_only: bool = Query(True),
    user: CurrentUser = Depends(get_current_user),
):
    """Lista polityk z filtrowaniem."""
    rows = await policies_repo.list_policies(level, agent_id, active_only)
    return [_row_to_dict(r) for r in rows]


@router.post("", status_code=201)
async def create_policy(data: PolicyCreate, user: CurrentUser = Depends(_WRITE_ROLES)):
    """Dodanie nowej polityki."""
    if data.level == "agent" and not data.agent_id:
        raise HTTPException(400, "Polityka agentowa wymaga agent_id")
    if data.level == "team" and not data.team:
        raise HTTPException(400, "Polityka zespołu wymaga pola team")

    policy_id = str(uuid4())
    await policies_repo.insert_policy(
        policy_id, data.name, data.policy_code, data.level, data.agent_id, data.team,
        data.rule_type, data.condition_json, data.action_json,
        data.priority, data.created_by,
    )
    row = await policies_repo.get_policy_by_id(policy_id)
    return _row_to_dict(row)


@router.put("/{policy_id}")
async def update_policy(policy_id: str, data: PolicyUpdate, user: CurrentUser = Depends(_WRITE_ROLES)):
    """Aktualizacja polityki (wersjonowanie automatyczne)."""
    row = await policies_repo.get_policy_by_id(policy_id)
    if not row:
        raise HTTPException(404, f"Polityka '{policy_id}' nie istnieje")

    result = await policies_repo.update_policy(
        policy_id,
        name=data.name,
        condition_json=data.condition_json,
        action_json=data.action_json,
        priority=data.priority,
        active=data.active,
    )
    if result is None:
        raise HTTPException(400, "Brak pól do aktualizacji")

    row = await policies_repo.get_policy_by_id(policy_id)
    return _row_to_dict(row)


@router.patch("/{policy_id}/keywords")
async def update_keywords(policy_id: str, body: dict, user: CurrentUser = Depends(_WRITE_ROLES)):
    """
    Zastępuje listę słów kluczowych w condition_json.keywords.
    Body: {"keywords": ["słowo1", "słowo2", ...]}
    """
    row = await policies_repo.get_policy_condition(policy_id)
    if not row:
        raise HTTPException(404, f"Polityka '{policy_id}' nie istnieje")

    keywords = body.get("keywords")
    if not isinstance(keywords, list):
        raise HTTPException(400, "Pole 'keywords' musi być listą")

    existing = dict(row["condition_json"]) if row["condition_json"] else {}
    existing["keywords"] = [str(k).strip() for k in keywords if str(k).strip()]

    await policies_repo.update_keywords(policy_id, existing)
    row = await policies_repo.get_policy_by_id(policy_id)
    return _row_to_dict(row)


@router.patch("/{policy_id}/toggle")
async def toggle_policy(policy_id: str, user: CurrentUser = Depends(_WRITE_ROLES)):
    """Przełącza active ↔ inactive."""
    row = await policies_repo.get_policy_active(policy_id)
    if not row:
        raise HTTPException(404, f"Polityka '{policy_id}' nie istnieje")
    new_active = not row["active"]
    await policies_repo.toggle_policy(policy_id, new_active)
    return {"policy_id": policy_id, "name": row["name"], "active": new_active}


@router.delete("/{policy_id}")
async def deactivate_policy(policy_id: str, user: CurrentUser = Depends(_WRITE_ROLES)):
    """Dezaktywacja polityki (soft delete — nie usuwa z historii)."""
    row = await policies_repo.get_policy_active(policy_id)
    if not row:
        raise HTTPException(404, f"Polityka '{policy_id}' nie istnieje")
    await policies_repo.deactivate_policy(policy_id)
    return {"policy_id": policy_id, "name": row["name"], "status": "deactivated"}


def _row_to_dict(row) -> dict:
    d = dict(row)
    for k, v in d.items():
        if hasattr(v, 'isoformat'):
            d[k] = v.isoformat()
    for f in ("id", "agent_id"):
        if d.get(f):
            d[f] = str(d[f])
    return d

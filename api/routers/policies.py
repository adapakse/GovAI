import logging
from typing import Optional
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, field_validator

from database import get_pool
from dependencies.auth import CurrentUser, get_current_user, require_role

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
    pool = get_pool()
    conditions = ["1=1"]
    params = []
    idx = 1

    if level:
        conditions.append(f"level = ${idx}::policy_level")
        params.append(level); idx += 1
    if agent_id:
        conditions.append(f"agent_id = ${idx}")
        params.append(agent_id); idx += 1
    if active_only:
        conditions.append("active = true")

    where = " AND ".join(conditions)
    rows = await pool.fetch(
        f"""SELECT id, name, policy_code, level, agent_id, team, rule_type,
                   condition_json, action_json, priority, active, version,
                   created_by, created_at
            FROM policies
            WHERE {where}
            ORDER BY priority ASC, created_at DESC""",
        *params,
    )
    return [_row_to_dict(r) for r in rows]


@router.post("", status_code=201)
async def create_policy(data: PolicyCreate, user: CurrentUser = Depends(_WRITE_ROLES)):
    """Dodanie nowej polityki."""
    pool = get_pool()

    if data.level == "agent" and not data.agent_id:
        raise HTTPException(400, "Polityka agentowa wymaga agent_id")
    if data.level == "team" and not data.team:
        raise HTTPException(400, "Polityka zespołu wymaga pola team")

    policy_id = str(uuid4())
    await pool.execute(
        """INSERT INTO policies (
               id, name, policy_code, level, agent_id, team, rule_type,
               condition_json, action_json, priority, created_by
           ) VALUES ($1, $2, $3, $4::policy_level, $5, $6, $7::policy_action, $8, $9, $10, $11)""",
        policy_id, data.name, data.policy_code, data.level, data.agent_id, data.team,
        data.rule_type, data.condition_json, data.action_json,
        data.priority, data.created_by,
    )
    row = await pool.fetchrow("SELECT * FROM policies WHERE id = $1", policy_id)
    return _row_to_dict(row)


@router.put("/{policy_id}")
async def update_policy(policy_id: str, data: PolicyUpdate, user: CurrentUser = Depends(_WRITE_ROLES)):
    """Aktualizacja polityki (wersjonowanie automatyczne)."""
    pool = get_pool()
    row = await pool.fetchrow("SELECT * FROM policies WHERE id = $1", policy_id)
    if not row:
        raise HTTPException(404, f"Polityka '{policy_id}' nie istnieje")

    updates = []
    params = []
    idx = 1

    if data.name is not None:
        updates.append(f"name = ${idx}"); params.append(data.name); idx += 1
    if data.condition_json is not None:
        updates.append(f"condition_json = ${idx}"); params.append(data.condition_json); idx += 1
    if data.action_json is not None:
        updates.append(f"action_json = ${idx}"); params.append(data.action_json); idx += 1
    if data.priority is not None:
        updates.append(f"priority = ${idx}"); params.append(data.priority); idx += 1
    if data.active is not None:
        updates.append(f"active = ${idx}"); params.append(data.active); idx += 1

    if not updates:
        raise HTTPException(400, "Brak pól do aktualizacji")

    updates.append(f"version = version + 1")
    params.append(policy_id)
    await pool.execute(
        f"UPDATE policies SET {', '.join(updates)} WHERE id = ${idx}",
        *params,
    )
    row = await pool.fetchrow("SELECT * FROM policies WHERE id = $1", policy_id)
    return _row_to_dict(row)


@router.patch("/{policy_id}/keywords")
async def update_keywords(policy_id: str, body: dict, user: CurrentUser = Depends(_WRITE_ROLES)):
    """
    Zastępuje listę słów kluczowych w condition_json.keywords.
    Body: {"keywords": ["słowo1", "słowo2", ...]}
    """
    pool = get_pool()
    row = await pool.fetchrow(
        "SELECT id, condition_json FROM policies WHERE id = $1", policy_id
    )
    if not row:
        raise HTTPException(404, f"Polityka '{policy_id}' nie istnieje")

    keywords = body.get("keywords")
    if not isinstance(keywords, list):
        raise HTTPException(400, "Pole 'keywords' musi być listą")

    existing = dict(row["condition_json"]) if row["condition_json"] else {}
    existing["keywords"] = [str(k).strip() for k in keywords if str(k).strip()]

    await pool.execute(
        "UPDATE policies SET condition_json = $1, version = version + 1 WHERE id = $2",
        existing, policy_id,
    )
    row = await pool.fetchrow("SELECT * FROM policies WHERE id = $1", policy_id)
    return _row_to_dict(row)


@router.patch("/{policy_id}/toggle")
async def toggle_policy(policy_id: str, user: CurrentUser = Depends(_WRITE_ROLES)):
    """Przełącza active ↔ inactive."""
    pool = get_pool()
    row = await pool.fetchrow("SELECT id, name, active FROM policies WHERE id = $1", policy_id)
    if not row:
        raise HTTPException(404, f"Polityka '{policy_id}' nie istnieje")
    new_active = not row["active"]
    await pool.execute(
        "UPDATE policies SET active = $1, version = version + 1 WHERE id = $2",
        new_active, policy_id,
    )
    return {"policy_id": policy_id, "name": row["name"], "active": new_active}


@router.delete("/{policy_id}")
async def deactivate_policy(policy_id: str, user: CurrentUser = Depends(_WRITE_ROLES)):
    """Dezaktywacja polityki (soft delete — nie usuwa z historii)."""
    pool = get_pool()
    row = await pool.fetchrow("SELECT id, name, active FROM policies WHERE id = $1", policy_id)
    if not row:
        raise HTTPException(404, f"Polityka '{policy_id}' nie istnieje")
    await pool.execute("UPDATE policies SET active = false WHERE id = $1", policy_id)
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

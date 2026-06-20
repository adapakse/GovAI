"""
Wymagania EU AI Act — CRUD zarządzany przez konsultanta z UI.
"""
from typing import Optional
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from database import get_pool
from dependencies.auth import CurrentUser, get_current_user, require_role

router = APIRouter(prefix="/compliance", tags=["compliance"])

_WRITE_ROLES = require_role("partner", "it_admin")


class RequirementCreate(BaseModel):
    risk_level: str
    article_ref: str
    requirement_title: str
    requirement_text: str
    sort_order: int = 100

    def validate_risk_level(self) -> None:
        if self.risk_level not in {"minimal", "limited", "high", "unacceptable"}:
            raise ValueError("risk_level musi być: minimal, limited, high lub unacceptable")


class RequirementUpdate(BaseModel):
    article_ref: Optional[str] = None
    requirement_title: Optional[str] = None
    requirement_text: Optional[str] = None
    sort_order: Optional[int] = None
    active: Optional[bool] = None


@router.get("")
async def list_requirements(
    risk_level: Optional[str] = Query(None),
    active_only: bool = Query(False),
    user: CurrentUser = Depends(get_current_user),
):
    """Lista wymagań EU AI Act — opcjonalnie filtrowana wg risk_level."""
    pool = get_pool()
    conditions = ["1=1"]
    params: list = []
    idx = 1

    if risk_level:
        conditions.append(f"risk_level = ${idx}::risk_level")
        params.append(risk_level); idx += 1
    if active_only:
        conditions.append("active = true")

    rows = await pool.fetch(
        f"""SELECT id, risk_level, article_ref, requirement_title,
                   requirement_text, active, sort_order, created_at
            FROM ai_act_requirements
            WHERE {' AND '.join(conditions)}
            ORDER BY
                CASE risk_level
                    WHEN 'unacceptable' THEN 1
                    WHEN 'high'         THEN 2
                    WHEN 'limited'      THEN 3
                    WHEN 'minimal'      THEN 4
                END,
                sort_order ASC""",
        *params,
    )
    return [_to_dict(r) for r in rows]


@router.post("", status_code=201)
async def create_requirement(data: RequirementCreate, user: CurrentUser = Depends(_WRITE_ROLES)):
    """Dodanie nowego wymagania EU AI Act."""
    pool = get_pool()
    req_id = str(uuid4())
    await pool.execute(
        """INSERT INTO ai_act_requirements
               (id, risk_level, article_ref, requirement_title, requirement_text, sort_order)
           VALUES ($1, $2::risk_level, $3, $4, $5, $6)""",
        req_id, data.risk_level, data.article_ref,
        data.requirement_title, data.requirement_text, data.sort_order,
    )
    row = await pool.fetchrow(
        "SELECT * FROM ai_act_requirements WHERE id = $1", req_id
    )
    return _to_dict(row)


@router.put("/{req_id}")
async def update_requirement(req_id: str, data: RequirementUpdate, user: CurrentUser = Depends(_WRITE_ROLES)):
    """Aktualizacja wymagania."""
    pool = get_pool()
    row = await pool.fetchrow(
        "SELECT id FROM ai_act_requirements WHERE id = $1", req_id
    )
    if not row:
        raise HTTPException(404, f"Wymaganie '{req_id}' nie istnieje")

    updates, params = [], []
    idx = 1
    for field, val in {
        "article_ref":        data.article_ref,
        "requirement_title":  data.requirement_title,
        "requirement_text":   data.requirement_text,
        "sort_order":         data.sort_order,
        "active":             data.active,
    }.items():
        if val is not None:
            updates.append(f"{field} = ${idx}"); params.append(val); idx += 1

    if not updates:
        raise HTTPException(400, "Brak pól do aktualizacji")

    params.append(req_id)
    await pool.execute(
        f"UPDATE ai_act_requirements SET {', '.join(updates)} WHERE id = ${idx}",
        *params,
    )
    row = await pool.fetchrow("SELECT * FROM ai_act_requirements WHERE id = $1", req_id)
    return _to_dict(row)


@router.delete("/{req_id}")
async def delete_requirement(req_id: str, user: CurrentUser = Depends(require_role("partner"))):
    """Trwałe usunięcie wymagania."""
    pool = get_pool()
    row = await pool.fetchrow(
        "SELECT id, requirement_title FROM ai_act_requirements WHERE id = $1", req_id
    )
    if not row:
        raise HTTPException(404, f"Wymaganie '{req_id}' nie istnieje")
    await pool.execute("DELETE FROM ai_act_requirements WHERE id = $1", req_id)
    return {"deleted": req_id, "title": row["requirement_title"]}


def _to_dict(row) -> dict:
    d = dict(row)
    d["id"] = str(d["id"])
    if hasattr(d.get("created_at"), "isoformat"):
        d["created_at"] = d["created_at"].isoformat()
    return d

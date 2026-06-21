"""
Wymagania EU AI Act — CRUD zarządzany przez konsultanta z UI.
"""
from typing import Optional
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from dependencies.auth import CurrentUser, get_current_user, require_role
from repositories import compliance_repository as compliance_repo

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
    rows = await compliance_repo.list_requirements(risk_level=risk_level, active_only=active_only)
    return [_to_dict(r) for r in rows]


@router.post("", status_code=201)
async def create_requirement(data: RequirementCreate, user: CurrentUser = Depends(_WRITE_ROLES)):
    """Dodanie nowego wymagania EU AI Act."""
    req_id = str(uuid4())
    row = await compliance_repo.insert_requirement(
        req_id, data.risk_level, data.article_ref,
        data.requirement_title, data.requirement_text, data.sort_order,
    )
    return _to_dict(row)


@router.put("/{req_id}")
async def update_requirement(req_id: str, data: RequirementUpdate, user: CurrentUser = Depends(_WRITE_ROLES)):
    """Aktualizacja wymagania."""
    row = await compliance_repo.get_requirement(req_id, columns="id")
    if not row:
        raise HTTPException(404, f"Wymaganie '{req_id}' nie istnieje")

    fields = {
        "article_ref":        data.article_ref,
        "requirement_title":  data.requirement_title,
        "requirement_text":   data.requirement_text,
        "sort_order":         data.sort_order,
        "active":             data.active,
    }
    if all(v is None for v in fields.values()):
        raise HTTPException(400, "Brak pól do aktualizacji")

    row = await compliance_repo.update_requirement(req_id, fields)
    return _to_dict(row)


@router.delete("/{req_id}")
async def delete_requirement(req_id: str, user: CurrentUser = Depends(require_role("partner"))):
    """Trwałe usunięcie wymagania."""
    row = await compliance_repo.get_requirement(req_id, columns="id, requirement_title")
    if not row:
        raise HTTPException(404, f"Wymaganie '{req_id}' nie istnieje")
    await compliance_repo.delete_requirement(req_id)
    return {"deleted": req_id, "title": row["requirement_title"]}


def _to_dict(row) -> dict:
    d = dict(row)
    d["id"] = str(d["id"])
    if hasattr(d.get("created_at"), "isoformat"):
        d["created_at"] = d["created_at"].isoformat()
    return d

"""
Wymagania EU AI Act — CRUD zarządzany przez konsultanta z UI.
"""
from typing import Optional
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from dependencies.auth import CurrentUser, get_current_user, require_role
from i18n import DEFAULT_LOCALE, get_locale, localized, t
from repositories import compliance_repository as compliance_repo

router = APIRouter(prefix="/compliance", tags=["compliance"])

_WRITE_ROLES = require_role("partner", "it_admin")


class RequirementCreate(BaseModel):
    risk_level: str
    article_ref: str
    requirement_title: str
    requirement_text: str
    sort_order: int = 100
    default_severity: str = "major"           # critical | major | minor
    default_deadline_days: int = 30
    decl_key: Optional[str] = None            # klucz w agents.compliance_decl / auto-check

    def validate_risk_level(self) -> None:
        if self.risk_level not in {"minimal", "limited", "high", "unacceptable"}:
            raise ValueError(t("compliance.errors.invalid_risk_level"))


class RequirementUpdate(BaseModel):
    article_ref: Optional[str] = None
    requirement_title: Optional[str] = None
    requirement_text: Optional[str] = None
    sort_order: Optional[int] = None
    active: Optional[bool] = None
    default_severity: Optional[str] = None
    default_deadline_days: Optional[int] = None
    decl_key: Optional[str] = None


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
        data.default_severity, data.default_deadline_days, data.decl_key,
    )
    # Kolumna bazowa wymaga tekstu — w innym języku niż polski zapisujemy go
    # w niej (fallback) oraz jako tłumaczenie dla języka żądania.
    locale = get_locale()
    if locale != DEFAULT_LOCALE:
        row = await compliance_repo.set_requirement_translation(
            req_id, locale, data.requirement_title, data.requirement_text,
        )
    return _to_dict(row)


@router.put("/{req_id}")
async def update_requirement(req_id: str, data: RequirementUpdate, user: CurrentUser = Depends(_WRITE_ROLES)):
    """Aktualizacja wymagania."""
    row = await compliance_repo.get_requirement(req_id, columns="id")
    if not row:
        raise HTTPException(404, t("compliance.errors.requirement_not_found", req_id=req_id))

    # Tytuł/treść edytowane w innym języku niż polski trafiają do *_i18n[locale],
    # kolumna bazowa (polski) zostaje nietknięta.
    locale = get_locale()
    translated = locale != DEFAULT_LOCALE
    fields = {
        "article_ref":            data.article_ref,
        "requirement_title":      None if translated else data.requirement_title,
        "requirement_text":       None if translated else data.requirement_text,
        "sort_order":             data.sort_order,
        "active":                 data.active,
        "default_severity":       data.default_severity,
        "default_deadline_days":  data.default_deadline_days,
        "decl_key":               data.decl_key,
    }
    has_translation = translated and (
        data.requirement_title is not None or data.requirement_text is not None
    )
    if all(v is None for v in fields.values()) and not has_translation:
        raise HTTPException(400, t("common.errors.no_fields_to_update"))

    if any(v is not None for v in fields.values()):
        row = await compliance_repo.update_requirement(req_id, fields)
    if has_translation:
        row = await compliance_repo.set_requirement_translation(
            req_id, locale, data.requirement_title, data.requirement_text,
        )
    return _to_dict(row)


@router.delete("/{req_id}")
async def delete_requirement(req_id: str, user: CurrentUser = Depends(require_role("partner"))):
    """Trwałe usunięcie wymagania."""
    row = await compliance_repo.get_requirement(req_id, columns="id, requirement_title, title_i18n")
    if not row:
        raise HTTPException(404, t("compliance.errors.requirement_not_found", req_id=req_id))
    await compliance_repo.delete_requirement(req_id)
    return {"deleted": req_id, "title": localized(row["title_i18n"], row["requirement_title"])}


def _to_dict(row) -> dict:
    d = dict(row)
    # Tytuł/treść w języku żądania; surowe kolumny tłumaczeń nie trafiają do klienta
    d["requirement_title"] = localized(d.pop("title_i18n", None), d.get("requirement_title"))
    d["requirement_text"] = localized(d.pop("text_i18n", None), d.get("requirement_text"))
    d["id"] = str(d["id"])
    if hasattr(d.get("created_at"), "isoformat"):
        d["created_at"] = d["created_at"].isoformat()
    return d

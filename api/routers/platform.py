"""
Router /platform — panel super-admina platformy (zarządzanie organizacjami).

Dostęp: tylko super-admin (users.is_super_admin). Dane ponad organizacjami,
więc każda operacja działa w trybie platformy (database.platform_db).
Każda zmiana (create/patch/delete/reset/enter) trafia do platform_audit_log.

  GET    /platform/tenants
  POST   /platform/tenants
  PATCH  /platform/tenants/{id}
  DELETE /platform/tenants/{id}
  GET    /platform/tenants/{id}/users
  POST   /platform/tenants/{id}/users/{user_id}/reset-password
  POST   /platform/tenants/{id}/enter
  GET    /platform/audit?limit=
"""
from __future__ import annotations

import logging
import uuid
from typing import Literal, Optional

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, field_validator

from database import platform_db
from dependencies.auth import CurrentUser, require_super_admin
from i18n import LOCALES, is_locale, t
from repositories import platform_repository as platform_repo
from services import settings_service
from services.auth_service import (
    ACT_TOKEN_MINUTES, change_password, create_access_token, create_user,
    generate_temporary_password,
)
from services.tenant_host import is_valid_slug

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/platform", tags=["platform"])

FIRST_ADMIN_ROLE = "partner"


# ── Schematy ───────────────────────────────────────────────────────────────────

class TenantCreate(BaseModel):
    slug: str
    name: str
    default_locale: Optional[str] = None
    admin_email: str
    admin_full_name: str

    @field_validator("slug")
    @classmethod
    def normalize_slug(cls, v: str) -> str:
        return v.strip().lower()

    @field_validator("name", "admin_full_name")
    @classmethod
    def not_blank(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError(t("platform.errors.field_required"))
        return v

    @field_validator("admin_email")
    @classmethod
    def valid_email(cls, v: str) -> str:
        v = v.strip().lower()
        if "@" not in v or v.startswith("@") or v.endswith("@"):
            raise ValueError(t("platform.errors.invalid_email"))
        return v

    @field_validator("default_locale")
    @classmethod
    def valid_locale(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and not is_locale(v):
            raise ValueError(t("auth.errors.invalid_locale", allowed=", ".join(LOCALES)))
        return v


class TenantUpdate(BaseModel):
    name: Optional[str] = None
    status: Optional[Literal["active", "suspended"]] = None

    @field_validator("name")
    @classmethod
    def not_blank(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            v = v.strip()
            if not v:
                raise ValueError(t("platform.errors.field_required"))
        return v


# ── Helpers ────────────────────────────────────────────────────────────────────

def _jsonable(row) -> dict:
    d = dict(row)
    for k, v in d.items():
        if isinstance(v, uuid.UUID):
            d[k] = str(v)
        elif hasattr(v, "isoformat"):
            d[k] = v.isoformat()
    return d


def _tenant_dict(row) -> dict:
    d = _jsonable(row)
    for k in ("users_count", "agents_count"):
        if k in d:
            d[k] = int(d[k] or 0)
    return d


def _valid_uuid(value: str) -> str:
    try:
        return str(uuid.UUID(value))
    except (ValueError, TypeError):
        raise HTTPException(404, t("platform.errors.tenant_not_found"))


async def _audit(user: CurrentUser, action: str, tenant_id: Optional[str], details: dict) -> None:
    await platform_repo.insert_audit(user.id, user.email, action, tenant_id, details)


async def _existing_tenant(tenant_id: str):
    row = await platform_repo.tenant_by_id(_valid_uuid(tenant_id))
    if not row:
        raise HTTPException(404, t("platform.errors.tenant_not_found"))
    return row


# ── Organizacje ────────────────────────────────────────────────────────────────

@router.get("/tenants")
async def list_tenants(user: CurrentUser = Depends(require_super_admin)):
    async with platform_db():
        rows = await platform_repo.list_tenants()
    return [_tenant_dict(r) for r in rows]


@router.post("/tenants", status_code=201)
async def create_tenant(body: TenantCreate, user: CurrentUser = Depends(require_super_admin)):
    """Zakłada organizację z pierwszym adminem (hasło tymczasowe — tylko w tej
    odpowiedzi), opcjonalnym domyślnym językiem i kopią polityk szablonu (govai-demo).
    Wszystko w jednej transakcji."""
    if not is_valid_slug(body.slug):
        raise HTTPException(400, t("platform.errors.invalid_slug"))

    temporary_password = generate_temporary_password()
    try:
        async with platform_db():
            if await platform_repo.slug_taken(body.slug):
                raise HTTPException(409, t("platform.errors.slug_taken", slug=body.slug))
            tenant = await platform_repo.insert_tenant(body.slug, body.name)
            tenant_id = str(tenant["id"])
            admin = await create_user(
                email=body.admin_email,
                full_name=body.admin_full_name,
                role=FIRST_ADMIN_ROLE,
                password=temporary_password,
                department=None,
                phone=None,
                created_by=None,          # super-admin jest w innej organizacji
                must_change_password=True,
                tenant_id=tenant_id,
            )
            if body.default_locale:
                await platform_repo.set_tenant_setting(
                    tenant_id, "i18n.default_locale", body.default_locale, user.email,
                )
            policies_copied = await platform_repo.copy_template_policies(tenant_id, user.email)
            await _audit(user, "tenant.create", tenant_id, {
                "slug": body.slug, "name": body.name, "admin_email": body.admin_email,
                "default_locale": body.default_locale, "policies_copied": policies_copied,
            })
    except asyncpg.UniqueViolationError:
        # Wyścig dwóch równoległych zakładań z tym samym slugiem
        raise HTTPException(409, t("platform.errors.slug_taken", slug=body.slug))

    if body.default_locale:
        await settings_service.load()   # nadpisanie widoczne od razu (cache parametrów)

    logger.info("Organizacja '%s' założona przez %s (polityki: %s)", body.slug, user.email, policies_copied)
    return {
        "tenant": {**_tenant_dict(tenant), "users_count": 1, "agents_count": 0},
        "admin": {"id": admin["id"], "email": admin["email"]},
        "temporary_password": temporary_password,
    }


@router.patch("/tenants/{tenant_id}")
async def update_tenant(tenant_id: str, body: TenantUpdate, user: CurrentUser = Depends(require_super_admin)):
    async with platform_db():
        existing = await _existing_tenant(tenant_id)
        if existing["deleted_at"] is not None:
            raise HTTPException(400, t("platform.errors.tenant_deleted"))
        if body.status == "suspended" and str(existing["id"]) == user.home_tenant_id:
            raise HTTPException(400, t("platform.errors.cannot_suspend_own"))
        if body.name is None and body.status is None:
            return _tenant_dict(existing)
        row = await platform_repo.update_tenant(str(existing["id"]), body.name, body.status)
        changes = {k: v for k, v in (("name", body.name), ("status", body.status)) if v is not None}
        await _audit(user, "tenant.update", str(existing["id"]), {
            "slug": existing["slug"], "changes": changes,
            "previous": {k: existing[k] for k in changes},
        })
    logger.info("Organizacja '%s' zmieniona przez %s: %s", existing["slug"], user.email, changes)
    return _tenant_dict(row)


@router.delete("/tenants/{tenant_id}")
async def delete_tenant(tenant_id: str, user: CurrentUser = Depends(require_super_admin)):
    """Miękkie usunięcie (deleted_at) — dane zostają, logowanie i dostęp zablokowane."""
    async with platform_db():
        existing = await _existing_tenant(tenant_id)
        if existing["deleted_at"] is not None:
            raise HTTPException(400, t("platform.errors.tenant_deleted"))
        if existing["is_demo"]:
            raise HTTPException(400, t("platform.errors.cannot_delete_demo"))
        if str(existing["id"]) == user.home_tenant_id:
            raise HTTPException(400, t("platform.errors.cannot_delete_own"))
        row = await platform_repo.soft_delete_tenant(str(existing["id"]))
        await _audit(user, "tenant.delete", str(existing["id"]), {"slug": existing["slug"], "name": existing["name"]})
    logger.info("Organizacja '%s' usunięta przez %s", existing["slug"], user.email)
    return _tenant_dict(row)


# ── Użytkownicy organizacji ────────────────────────────────────────────────────

@router.get("/tenants/{tenant_id}/users")
async def list_tenant_users(tenant_id: str, user: CurrentUser = Depends(require_super_admin)):
    async with platform_db():
        existing = await _existing_tenant(tenant_id)
        rows = await platform_repo.list_tenant_users(str(existing["id"]))
    return [_jsonable(r) for r in rows]


@router.post("/tenants/{tenant_id}/users/{user_id}/reset-password")
async def reset_tenant_user_password(
    tenant_id: str, user_id: str, user: CurrentUser = Depends(require_super_admin),
):
    """Hasło tymczasowe dla użytkownika organizacji (tylko w tej odpowiedzi);
    wymuszona zmiana przy logowaniu, wszystkie sesje unieważnione."""
    temporary_password = generate_temporary_password()
    async with platform_db():
        existing = await _existing_tenant(tenant_id)
        try:
            uuid.UUID(user_id)
        except ValueError:
            raise HTTPException(404, t("auth.errors.user_not_found"))
        target = await platform_repo.tenant_user(str(existing["id"]), user_id)
        if not target:
            raise HTTPException(404, t("auth.errors.user_not_found"))
        await change_password(user_id, temporary_password, must_change=True)
        await _audit(user, "user.reset_password", str(existing["id"]), {
            "slug": existing["slug"], "user_id": user_id, "email": target["email"],
        })
    logger.info("Reset hasła %s (%s) przez %s", target["email"], existing["slug"], user.email)
    return {"temporary_password": temporary_password}


# ── Wejście w kontekst organizacji ─────────────────────────────────────────────

@router.post("/tenants/{tenant_id}/enter")
async def enter_tenant(tenant_id: str, user: CurrentUser = Depends(require_super_admin)):
    """Token super-admina działającego w kontekście organizacji (claim act_tenant_id,
    ważny 60 min). Organizacja musi być aktywna i nieusunięta."""
    async with platform_db():
        existing = await _existing_tenant(tenant_id)
        if existing["deleted_at"] is not None:
            raise HTTPException(400, t("platform.errors.tenant_deleted"))
        if existing["status"] != "active":
            raise HTTPException(400, t("platform.errors.tenant_suspended"))
        await _audit(user, "tenant.enter", str(existing["id"]), {"slug": existing["slug"]})

    token = create_access_token(
        user.id, user.email, user.role, user.home_tenant_id, act_tenant_id=str(existing["id"]),
    )
    logger.info("Super-admin %s wszedł w kontekst organizacji '%s'", user.email, existing["slug"])
    return {
        "access_token": token,
        "token_type": "bearer",
        "expires_in": ACT_TOKEN_MINUTES * 60,
        "tenant": {"id": str(existing["id"]), "slug": existing["slug"], "name": existing["name"],
                   "is_demo": bool(existing["is_demo"])},
    }


# ── Dziennik operacji platformy ────────────────────────────────────────────────

@router.get("/audit")
async def platform_audit(
    limit: int = Query(100, ge=1, le=1000),
    user: CurrentUser = Depends(require_super_admin),
):
    async with platform_db():
        rows = await platform_repo.list_audit(limit)
    return [_jsonable(r) for r in rows]

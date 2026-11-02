"""
Router autentykacji i zarządzania użytkownikami.

Endpointy publiczne (bez JWT):
  POST /auth/login
  POST /auth/refresh

Endpointy wymagające JWT (dowolna rola):
  POST /auth/logout
  GET  /auth/me
  PUT  /auth/me/locale

Endpointy wymagające roli partner lub it_admin:
  GET    /auth/users
  POST   /auth/users
  PATCH  /auth/users/{id}
  POST   /auth/users/{id}/password

Endpointy wymagające roli it_admin:
  GET  /auth/api-keys
  POST /auth/api-keys
  DELETE /auth/api-keys/{id}
"""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, field_validator

from database import platform_db, tenant_db
from dependencies.auth import CurrentUser, get_current_user, require_role
from i18n import DEFAULT_LOCALE, LOCALES, is_locale, t
from repositories import agents_repository as agents_repo
from repositories import auth_repository as auth_repo
from services import settings_service
from services.tenant_host import slug_from_host
from services.auth_service import (
    change_password, create_api_key, create_refresh_token, create_user,
    find_login_identities, get_identity,
    get_user_by_email, get_user_by_id, list_users, revoke_refresh_token,
    update_last_login, update_user, update_user_locale, verify_api_key,
    verify_refresh_token, create_access_token,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/auth", tags=["auth"])

# ── Schematy wejściowe ─────────────────────────────────────────────────────────

class LoginRequest(BaseModel):
    email: str
    password: str

class RefreshRequest(BaseModel):
    refresh_token: str

class UserCreate(BaseModel):
    email: str
    full_name: str
    role: str
    password: str
    department: Optional[str] = None
    phone: Optional[str] = None

    @field_validator("role")
    @classmethod
    def valid_role(cls, v: str) -> str:
        allowed = {"partner", "associate", "compliance_officer", "it_admin", "reviewer"}
        if v not in allowed:
            raise ValueError(t("auth.errors.invalid_role", allowed=allowed))
        return v

    @field_validator("password")
    @classmethod
    def password_strength(cls, v: str) -> str:
        if len(v) < 12:
            raise ValueError(t("auth.errors.password_too_short", min=12))
        return v

class UserUpdate(BaseModel):
    full_name: Optional[str] = None
    role: Optional[str] = None
    status: Optional[str] = None
    department: Optional[str] = None
    phone: Optional[str] = None

    @field_validator("role")
    @classmethod
    def valid_role(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            allowed = {"partner", "associate", "compliance_officer", "it_admin", "reviewer"}
            if v not in allowed:
                raise ValueError(t("auth.errors.invalid_role", allowed=allowed))
        return v

    @field_validator("status")
    @classmethod
    def valid_status(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and v not in {"active", "suspended", "pending"}:
            raise ValueError(t("auth.errors.invalid_status"))
        return v

class PasswordChange(BaseModel):
    new_password: str

    @field_validator("new_password")
    @classmethod
    def password_strength(cls, v: str) -> str:
        if len(v) < 12:
            raise ValueError(t("auth.errors.password_too_short", min=12))
        return v

class ApiKeyCreate(BaseModel):
    name: str
    agent_id: Optional[str] = None
    expires_days: Optional[int] = None

class LocaleUpdate(BaseModel):
    locale: Optional[str] = None      # None = domyślny język instancji

    @field_validator("locale")
    @classmethod
    def valid_locale(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and not is_locale(v):
            raise ValueError(t("auth.errors.invalid_locale", allowed=", ".join(LOCALES)))
        return v


def _locale_fields(user: dict) -> dict:
    """Język z profilu + domyślny instancji — frontend wylicza z nich język UI."""
    return {
        "locale": user.get("locale"),
        "default_locale": settings_service.get_str("i18n.default_locale", DEFAULT_LOCALE),
    }

# ── Endpointy publiczne ────────────────────────────────────────────────────────

def _tenant_fields(identity: dict) -> dict:
    return {
        "is_super_admin": bool(identity.get("is_super_admin")),
        "tenant": {
            "id": str(identity["tenant_id"]),
            "slug": identity["tenant_slug"],
            "name": identity["tenant_name"],
            "is_demo": bool(identity["tenant_is_demo"]),
        },
    }


def _ensure_active(identity: dict) -> None:
    if identity["tenant_deleted_at"] is not None or identity["tenant_status"] != "active":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=t("auth.errors.tenant_inactive"))
    if identity["status"] != "active":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                            detail=t("auth.errors.account_status", status=identity["status"]))


@router.post("/login")
async def login(body: LoginRequest, request: Request):
    """
    Logowanie — zwraca access_token (JWT, 60 min) i refresh_token (7 dni).
    Refresh token należy przechowywać bezpiecznie i używać do odnowienia sesji.

    Organizacja: na subdomenie {slug}.<domena> — tylko konta tej organizacji;
    na adresie uniwersalnym (app.<domena>) — konto o danym e-mailu i haśle
    w dowolnej organizacji (gdy pasuje kilka — trzeba użyć adresu organizacji).
    """
    host_slug = slug_from_host(request.headers.get("host"))
    async with platform_db():
        tenant_id = None
        if host_slug:
            tenant_id = await auth_repo.tenant_id_by_slug(host_slug)
            if tenant_id is None:
                raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                                    detail=t("auth.errors.invalid_credentials"))
        candidates = await find_login_identities(str(body.email), tenant_id)

    from services.auth_service import verify_password
    matches = [c for c in candidates
               if c.get("password_hash") and verify_password(body.password, c["password_hash"])]
    if not matches:
        logger.warning("Nieudane logowanie dla: %s (IP: %s)", body.email,
                       request.client.host if request.client else "unknown")
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                            detail=t("auth.errors.invalid_credentials"))
    if len(matches) > 1:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=t("auth.errors.ambiguous_login"))

    user = matches[0]
    _ensure_active(user)

    user_id = str(user["id"])
    tenant_id = str(user["tenant_id"])
    access_token = create_access_token(user_id, user["email"], str(user["role"]), tenant_id)
    async with tenant_db(tenant_id):
        refresh_token = await create_refresh_token(
            user_id,
            tenant_id,
            ip_address=request.client.host if request.client else None,
            user_agent=request.headers.get("User-Agent"),
        )
        await update_last_login(user_id)
        locale_fields = _locale_fields(user)

    logger.info("Zalogowano: %s (%s, organizacja %s)", body.email, user["role"], user["tenant_slug"])
    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer",
        "expires_in": 3600,
        "user": {
            "id": user_id,
            "email": user["email"],
            "full_name": user["full_name"],
            "role": user["role"],
            **locale_fields,
            **_tenant_fields(user),
        },
    }


@router.post("/refresh")
async def refresh(body: RefreshRequest, request: Request):
    """Odnawia access_token na podstawie refresh_token."""
    async with platform_db():
        token_data = await verify_refresh_token(body.refresh_token)
        user = await get_identity(token_data["user_id"]) if token_data else None
    if not token_data:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                            detail=t("auth.errors.invalid_refresh_token"))
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                            detail=t("auth.errors.account_inactive"))
    _ensure_active(user)
    host_slug = slug_from_host(request.headers.get("host"))
    if host_slug is not None and host_slug != user["tenant_slug"]:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=t("auth.errors.tenant_host_mismatch"))

    access_token = create_access_token(str(user["id"]), user["email"], user["role"], str(user["tenant_id"]))
    return {"access_token": access_token, "token_type": "bearer", "expires_in": 3600}

# ── Endpointy wymagające JWT ───────────────────────────────────────────────────

@router.post("/logout")
async def logout(body: RefreshRequest, user: CurrentUser = Depends(get_current_user)):
    """Unieważnia refresh token (wylogowanie)."""
    await revoke_refresh_token(body.refresh_token)
    logger.info("Wylogowano: %s", user.email)
    return {"message": t("auth.messages.logged_out")}


@router.get("/me")
async def me(user: CurrentUser = Depends(get_current_user)):
    """Dane aktualnie zalogowanego użytkownika."""
    full = await get_user_by_id(user.id)
    if not full:
        return full
    return {
        **full, **_locale_fields(full),
        "is_super_admin": user.is_super_admin,
        "tenant": {"id": user.tenant_id, "slug": user.tenant_slug, "name": user.tenant_name,
                   "is_demo": user.tenant_is_demo},
    }


@router.put("/me/locale")
async def set_my_locale(body: LocaleUpdate, user: CurrentUser = Depends(get_current_user)):
    """Zmiana języka interfejsu zalogowanego użytkownika (null = domyślny instancji)."""
    await update_user_locale(user.id, body.locale)
    full = await get_user_by_id(user.id)
    return {
        "id": str(full["id"]),
        "email": full["email"],
        "full_name": full["full_name"],
        "role": full["role"],
        **_locale_fields(full),
    }

# ── Zarządzanie użytkownikami (partner / it_admin) ────────────────────────────

@router.get("/users")
async def list_all_users(
    user: CurrentUser = Depends(require_role("partner", "it_admin", "compliance_officer")),
):
    """Lista wszystkich użytkowników systemu."""
    return await list_users()


@router.post("/users", status_code=201)
async def create_new_user(
    body: UserCreate,
    user: CurrentUser = Depends(require_role("partner", "it_admin")),
):
    """Tworzy nowe konto użytkownika. Tylko partner lub it_admin."""
    existing = await get_user_by_email(str(body.email))
    if existing:
        raise HTTPException(status_code=409, detail=t("auth.errors.user_exists", email=body.email))

    # it_admin nie może tworzyć kont partner
    if user.role == "it_admin" and body.role == "partner":
        raise HTTPException(status_code=403, detail=t("auth.errors.it_admin_cannot_create_partner"))

    new_user = await create_user(
        email=str(body.email),
        full_name=body.full_name,
        role=body.role,
        password=body.password,
        department=body.department,
        phone=body.phone,
        created_by=user.id,
    )
    logger.info("Nowy użytkownik: %s (%s) — utworzył: %s", body.email, body.role, user.email)
    return new_user


@router.patch("/users/{target_id}")
async def update_existing_user(
    target_id: str,
    body: UserUpdate,
    user: CurrentUser = Depends(require_role("partner", "it_admin")),
):
    """Aktualizuje dane użytkownika."""
    # it_admin nie może edytować partnerów
    target = await get_user_by_id(target_id)
    if not target:
        raise HTTPException(404, t("auth.errors.user_not_found"))
    if user.role == "it_admin" and target.get("role") == "partner":
        raise HTTPException(403, t("auth.errors.it_admin_cannot_edit_partner"))

    updated = await update_user(
        target_id, body.full_name, body.role, body.status, body.department, body.phone,
    )
    return updated


@router.post("/users/{target_id}/password")
async def reset_password(
    target_id: str,
    body: PasswordChange,
    user: CurrentUser = Depends(require_role("partner", "it_admin")),
):
    """Zmienia hasło użytkownika i unieważnia wszystkie jego sesje."""
    target = await get_user_by_id(target_id)
    if not target:
        raise HTTPException(404, t("auth.errors.user_not_found"))
    if user.role == "it_admin" and target.get("role") == "partner":
        raise HTTPException(403, t("auth.errors.it_admin_cannot_change_partner_password"))

    await change_password(target_id, body.new_password)
    logger.info("Zmieniono hasło dla %s — zmienił: %s", target["email"], user.email)
    return {"message": t("auth.messages.password_changed_sessions_revoked")}


@router.post("/me/password")
async def change_own_password(
    body: PasswordChange,
    user: CurrentUser = Depends(get_current_user),
):
    """Zmiana własnego hasła przez zalogowanego użytkownika."""
    await change_password(user.id, body.new_password)
    return {"message": t("auth.messages.password_changed_relogin")}

# ── Klucze API (it_admin) ─────────────────────────────────────────────────────

@router.get("/api-keys")
async def list_api_keys(
    user: CurrentUser = Depends(require_role("partner", "it_admin")),
):
    """Lista kluczy API (bez surowych wartości)."""
    rows = await auth_repo.list_api_keys()
    return [_key_row(r) for r in rows]


@router.post("/api-keys", status_code=201)
async def new_api_key(
    body: ApiKeyCreate,
    user: CurrentUser = Depends(require_role("partner", "it_admin")),
):
    """
    Tworzy nowy klucz API. Surowy klucz widoczny TYLKO w tej odpowiedzi —
    zapisz go natychmiast, nie jest przechowywany w czytelnej formie.
    """
    # Klucz obcy api_keys.agent_id nie podlega RLS — bez tej kontroli dałoby się
    # przypiąć klucz do agenta innej organizacji (RLS ukrywa cudzych agentów).
    if body.agent_id and not await agents_repo.get_agent_id_only(body.agent_id):
        raise HTTPException(status_code=404, detail=t("agents.errors.not_found", agent_id=body.agent_id))
    result = await create_api_key(
        name=body.name,
        created_by=user.id,
        agent_id=body.agent_id,
        expires_days=body.expires_days,
    )
    logger.info("Nowy klucz API '%s' — utworzył: %s", body.name, user.email)
    return result


@router.delete("/api-keys/{key_id}")
async def revoke_api_key(
    key_id: str,
    user: CurrentUser = Depends(require_role("partner", "it_admin")),
):
    """Dezaktywuje klucz API."""
    result = await auth_repo.deactivate_api_key(key_id)
    if result == "UPDATE 0":
        raise HTTPException(404, t("auth.errors.api_key_not_found"))
    return {"message": t("auth.messages.api_key_deactivated", key_id=key_id)}

# ── Helper ────────────────────────────────────────────────────────────────────

def _key_row(row) -> dict:
    d = dict(row)
    d["id"] = str(d["id"])
    if d.get("agent_id"):
        d["agent_id"] = str(d["agent_id"])
    for k, v in d.items():
        if hasattr(v, "isoformat"):
            d[k] = v.isoformat()
    return d

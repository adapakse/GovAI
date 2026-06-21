"""
Router autentykacji i zarządzania użytkownikami.

Endpointy publiczne (bez JWT):
  POST /auth/login
  POST /auth/refresh

Endpointy wymagające JWT (dowolna rola):
  POST /auth/logout
  GET  /auth/me

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

from dependencies.auth import CurrentUser, get_current_user, require_role
from repositories import auth_repository as auth_repo
from services.auth_service import (
    change_password, create_api_key, create_refresh_token, create_user,
    get_user_by_email, get_user_by_id, list_users, revoke_refresh_token,
    update_last_login, update_user, verify_api_key, verify_refresh_token,
    create_access_token,
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
            raise ValueError(f"Nieprawidłowa rola. Dozwolone: {allowed}")
        return v

    @field_validator("password")
    @classmethod
    def password_strength(cls, v: str) -> str:
        if len(v) < 12:
            raise ValueError("Hasło musi mieć co najmniej 12 znaków")
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
                raise ValueError(f"Nieprawidłowa rola. Dozwolone: {allowed}")
        return v

    @field_validator("status")
    @classmethod
    def valid_status(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and v not in {"active", "suspended", "pending"}:
            raise ValueError("Nieprawidłowy status")
        return v

class PasswordChange(BaseModel):
    new_password: str

    @field_validator("new_password")
    @classmethod
    def password_strength(cls, v: str) -> str:
        if len(v) < 12:
            raise ValueError("Hasło musi mieć co najmniej 12 znaków")
        return v

class ApiKeyCreate(BaseModel):
    name: str
    agent_id: Optional[str] = None
    expires_days: Optional[int] = None

# ── Endpointy publiczne ────────────────────────────────────────────────────────

@router.post("/login")
async def login(body: LoginRequest, request: Request):
    """
    Logowanie — zwraca access_token (JWT, 60 min) i refresh_token (7 dni).
    Refresh token należy przechowywać bezpiecznie i używać do odnowienia sesji.
    """
    user = await get_user_by_email(str(body.email))

    if not user or not user.get("password_hash"):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                            detail="Nieprawidłowy email lub hasło.")

    from services.auth_service import verify_password
    if not verify_password(body.password, user["password_hash"]):
        logger.warning("Nieudane logowanie dla: %s (IP: %s)", body.email,
                       request.client.host if request.client else "unknown")
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                            detail="Nieprawidłowy email lub hasło.")

    if user["status"] != "active":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                            detail=f"Konto jest {user['status']}.")

    user_id = str(user["id"])
    access_token = create_access_token(user_id, str(body.email), str(user["role"]))
    refresh_token = await create_refresh_token(
        user_id,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("User-Agent"),
    )
    await update_last_login(user_id)

    logger.info("Zalogowano: %s (%s)", body.email, user["role"])
    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer",
        "expires_in": 3600,
        "user": {
            "id": user_id,
            "email": str(body.email),
            "full_name": user["full_name"],
            "role": user["role"],
        },
    }


@router.post("/refresh")
async def refresh(body: RefreshRequest):
    """Odnawia access_token na podstawie refresh_token."""
    token_data = await verify_refresh_token(body.refresh_token)
    if not token_data:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                            detail="Refresh token nieprawidłowy lub wygasły.")

    user = await get_user_by_id(token_data["user_id"])
    if not user or user["status"] != "active":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                            detail="Konto nieaktywne.")

    access_token = create_access_token(user["id"], user["email"], user["role"])
    return {"access_token": access_token, "token_type": "bearer", "expires_in": 3600}

# ── Endpointy wymagające JWT ───────────────────────────────────────────────────

@router.post("/logout")
async def logout(body: RefreshRequest, user: CurrentUser = Depends(get_current_user)):
    """Unieważnia refresh token (wylogowanie)."""
    await revoke_refresh_token(body.refresh_token)
    logger.info("Wylogowano: %s", user.email)
    return {"message": "Wylogowano pomyślnie."}


@router.get("/me")
async def me(user: CurrentUser = Depends(get_current_user)):
    """Dane aktualnie zalogowanego użytkownika."""
    full = await get_user_by_id(user.id)
    return full

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
        raise HTTPException(status_code=409, detail=f"Użytkownik '{body.email}' już istnieje.")

    # it_admin nie może tworzyć kont partner
    if user.role == "it_admin" and body.role == "partner":
        raise HTTPException(status_code=403, detail="it_admin nie może tworzyć kont partner.")

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
        raise HTTPException(404, "Użytkownik nie znaleziony.")
    if user.role == "it_admin" and target.get("role") == "partner":
        raise HTTPException(403, "it_admin nie może edytować kont partner.")

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
        raise HTTPException(404, "Użytkownik nie znaleziony.")
    if user.role == "it_admin" and target.get("role") == "partner":
        raise HTTPException(403, "it_admin nie może zmieniać hasła partner.")

    await change_password(target_id, body.new_password)
    logger.info("Zmieniono hasło dla %s — zmienił: %s", target["email"], user.email)
    return {"message": "Hasło zmienione. Wszystkie sesje użytkownika zostały unieważnione."}


@router.post("/me/password")
async def change_own_password(
    body: PasswordChange,
    user: CurrentUser = Depends(get_current_user),
):
    """Zmiana własnego hasła przez zalogowanego użytkownika."""
    await change_password(user.id, body.new_password)
    return {"message": "Hasło zmienione. Zaloguj się ponownie."}

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
        raise HTTPException(404, "Klucz API nie znaleziony.")
    return {"message": f"Klucz API {key_id} dezaktywowany."}

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

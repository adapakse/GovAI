"""
FastAPI Depends dla autentykacji, RBAC i kontekstu organizacji (multitenancy).

Użycie w routerach:
    from dependencies.auth import get_current_user, require_role, CurrentUser

    @router.get("/")
    async def list_items(user: CurrentUser = Depends(get_current_user)):
        ...

    @router.post("/")
    async def create_item(user: CurrentUser = Depends(require_role("partner", "it_admin"))):
        ...

get_current_user otwiera transakcję w kontekście organizacji użytkownika
(database.tenant_db) na czas całego żądania — każde zapytanie w endpoincie
widzi wyłącznie dane tej organizacji (Row Level Security).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import AsyncIterator, Callable, Optional

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError

from database import platform_db, tenant_db
from i18n import match_locale, set_locale, t
from services import settings_service
from services.auth_service import decode_access_token, get_identity
from services.tenant_host import slug_from_host

_bearer = HTTPBearer(auto_error=False)

ROLE_HIERARCHY = {
    "partner":            5,
    "it_admin":           4,
    "compliance_officer": 3,
    "associate":          2,
    "reviewer":           1,
}


@dataclass
class CurrentUser:
    id: str
    email: str
    role: str
    full_name: str
    tenant_id: str
    tenant_slug: str
    tenant_name: str
    tenant_is_demo: bool = False
    is_super_admin: bool = False

    def has_role(self, *roles: str) -> bool:
        return self.role in roles

    def has_min_level(self, min_role: str) -> bool:
        return ROLE_HIERARCHY.get(self.role, 0) >= ROLE_HIERARCHY.get(min_role, 0)


def _unauthorized(detail: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )


async def authenticate_token(token: str, host: Optional[str] = None) -> CurrentUser:
    """Weryfikuje access token (JWT), aktywność konta i organizacji oraz zgodność
    subdomeny z organizacją. Wspólne dla HTTP (Bearer) i WebSocket (token
    w query string — przeglądarka nie wyśle nagłówka).

    Organizacja zawsze z rekordu użytkownika w bazie (nie z JWT), więc
    zawieszenie lub usunięcie organizacji działa natychmiast."""
    try:
        payload = decode_access_token(token)
    except JWTError as exc:
        raise _unauthorized(t("auth.errors.invalid_token", error=exc)) from exc

    async with platform_db():
        user = await get_identity(payload.get("sub", ""))

    if not user:
        raise _unauthorized(t("auth.errors.user_does_not_exist"))
    if user["tenant_deleted_at"] is not None or user["tenant_status"] != "active":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=t("auth.errors.tenant_inactive"))
    if user["status"] != "active":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=t("auth.errors.account_status_contact_admin", status=user["status"]),
        )

    # Sesja organizacji A na subdomenie organizacji B — odrzucamy (blokada
    # pomyłek i podszywania się pod adres; dane i tak wynikają z rekordu).
    host_slug = slug_from_host(host)
    if host_slug is not None and host_slug != user["tenant_slug"]:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=t("auth.errors.tenant_host_mismatch"))

    return CurrentUser(
        id=str(user["id"]),
        email=user["email"],
        role=user["role"],
        full_name=user.get("full_name") or "",
        tenant_id=str(user["tenant_id"]),
        tenant_slug=user["tenant_slug"],
        tenant_name=user["tenant_name"],
        tenant_is_demo=bool(user["tenant_is_demo"]),
        is_super_admin=bool(user["is_super_admin"]),
    )


async def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> AsyncIterator[CurrentUser]:
    """
    Weryfikuje JWT Bearer token i na czas żądania otwiera transakcję
    w kontekście organizacji użytkownika. Rzuca 401 gdy token brak,
    nieprawidłowy lub wygasły; 403 gdy konto/organizacja nieaktywne.
    """
    if not credentials:
        raise _unauthorized(t("auth.errors.missing_token"))
    user = await authenticate_token(credentials.credentials, request.headers.get("host"))

    async with tenant_db(user.tenant_id):
        # Bez obsługiwanego Accept-Language — domyślny język organizacji
        # (LocaleMiddleware zna tylko domyślny język platformy).
        if not match_locale(request.headers.get("accept-language")):
            set_locale(settings_service.get_str("i18n.default_locale", "pl"))
        yield user


def require_role(*roles: str) -> Callable:
    """
    Dependency factory sprawdzające rolę.

    Przykład: Depends(require_role("partner", "it_admin"))
    """
    async def _check(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
        if user.role not in roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=t("auth.errors.role_forbidden", role=user.role, required=", ".join(roles)),
            )
        return user
    return _check


def require_min_level(min_role: str) -> Callable:
    """
    Dependency sprawdzające minimalny poziom roli w hierarchii.
    Przydatne gdy chcemy „partner lub wyżej".
    """
    async def _check(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
        if not user.has_min_level(min_role):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=t("auth.errors.min_role_required", role=min_role),
            )
        return user
    return _check


async def require_super_admin(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
    """Super-admin platformy (zarządzanie organizacjami, parametry platformy)."""
    if not user.is_super_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=t("auth.errors.super_admin_required"))
    return user

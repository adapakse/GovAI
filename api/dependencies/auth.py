"""
FastAPI Depends dla autentykacji i RBAC.

Użycie w routerach:
    from dependencies.auth import get_current_user, require_role, CurrentUser

    @router.get("/")
    async def list_items(user: CurrentUser = Depends(get_current_user)):
        ...

    @router.post("/")
    async def create_item(user: CurrentUser = Depends(require_role("partner", "it_admin"))):
        ...
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError

from services.auth_service import decode_access_token, get_user_by_id

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

    def has_role(self, *roles: str) -> bool:
        return self.role in roles

    def has_min_level(self, min_role: str) -> bool:
        return ROLE_HIERARCHY.get(self.role, 0) >= ROLE_HIERARCHY.get(min_role, 0)


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> CurrentUser:
    """
    Weryfikuje JWT Bearer token i zwraca CurrentUser.
    Rzuca 401 gdy token brak, nieprawidłowy lub wygasły.
    """
    if not credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Brak tokenu autoryzacyjnego. Zaloguj się i podaj nagłówek Authorization: Bearer <token>.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        payload = decode_access_token(credentials.credentials)
    except JWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Token nieprawidłowy lub wygasły: {exc}",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc

    user_id: str = payload.get("sub", "")
    user = await get_user_by_id(user_id)

    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Użytkownik nie istnieje.")
    if user["status"] != "active":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Konto jest {user['status']}. Skontaktuj się z administratorem.",
        )

    return CurrentUser(
        id=user_id,
        email=payload.get("email", ""),
        role=payload.get("role", ""),
        full_name=user.get("full_name", ""),
    )


def require_role(*roles: str) -> Callable:
    """
    Dependency factory sprawdzające rolę.

    Przykład: Depends(require_role("partner", "it_admin"))
    """
    async def _check(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
        if user.role not in roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(
                    f"Twoja rola '{user.role}' nie ma uprawnień do tej operacji. "
                    f"Wymagane: {', '.join(roles)}."
                ),
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
                detail=f"Wymagana rola co najmniej '{min_role}'.",
            )
        return user
    return _check

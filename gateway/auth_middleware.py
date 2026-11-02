"""
Middleware autoryzacji Gateway — weryfikuje JWT Bearer lub X-API-Key
i ustala organizację żądania (multitenancy).

Ścieżki publiczne (bez autoryzacji): /health, /
Wszystkie pozostałe wymagają tokenu.

Przepływ:
  1. Authorization: Bearer <jwt>  → weryfikacja JWT, user_id + role + organizacja (claim tenant_id;
                                     token bez tenant_id → 401). Konto z "sub" sprawdzane w bazie
                                     (tryb platformy, cache ~30 s): istnieje, należy do organizacji
                                     z tokenu, status active (inaczej 401), bez wymuszonej zmiany
                                     hasła (inaczej 403). Claim "act_tenant_id" (super-admin
                                     w kontekście organizacji) → wymaga is_super_admin (inaczej 403;
                                     przynależność do organizacji nie jest wtedy sprawdzana),
                                     organizacją żądania jest act_tenant_id.
  2. X-API-Key: <key>             → wyszukanie hash w DB (tryb platformy) → agent_id + organizacja klucza
  3. Brak obu                     → 401
Następnie: organizacja musi być aktywna (status='active', nieusunięta) — inaczej 403.
Wynik: request.state.tenant_id + contextvar database.request_tenant_id (parametry per organizacja).
"""
from __future__ import annotations

import hashlib
import logging
import time
from typing import Optional

from fastapi import Request
from fastapi.responses import JSONResponse
from jose import JWTError, jwt
from starlette.middleware.base import BaseHTTPMiddleware

import app_settings
from config import settings
from database import fetch_tenant_status, fetch_user_auth, is_uuid, platform_conn, set_request_tenant
from i18n import DEFAULT_LOCALE, match_locale, set_locale, t

logger = logging.getLogger(__name__)

_PUBLIC_PATHS = {"/", "/health", "/docs", "/openapi.json"}

# Cache werdyktu konta: (user_id, tenant_id z tokenu, act_tenant_id) → (ważny_do, werdykt).
# Zablokowanie konta działa najpóźniej po _USER_CACHE_TTL sekundach.
_USER_CACHE_TTL = 30.0
_USER_CACHE_MAX = 10_000
_user_cache: dict[tuple, tuple[float, Optional[str]]] = {}

# Werdykty (None = dostęp dozwolony) → (status HTTP, klucz i18n).
_USER_REJECTIONS = {
    "inactive":        (401, "errors.auth.userInactive"),
    "wrong_tenant":    (401, "errors.auth.invalidToken"),
    "acting_denied":   (403, "errors.auth.actingNotAllowed"),
    "password_change": (403, "errors.auth.passwordChangeRequired"),
}


async def _check_user(user_id: str, token_tenant_id: str, act_tenant_id: Optional[str]) -> Optional[str]:
    """Werdykt dla konta z tokenu (z cache). Błąd bazy → wyjątek (bez zapisu w cache)."""
    key = (user_id, token_tenant_id, act_tenant_id)
    now = time.monotonic()
    cached = _user_cache.get(key)
    if cached and cached[0] > now:
        return cached[1]

    user = await fetch_user_auth(user_id)
    if user is None or user["status"] != "active":
        verdict: Optional[str] = "inactive"
    elif act_tenant_id:
        # Token "enter" (API: tenant_id = act_tenant_id = organizacja docelowa) —
        # konto należy do innej organizacji, wymagany super-admin.
        verdict = None if user["is_super_admin"] else "acting_denied"
    elif user["tenant_id"] != token_tenant_id:
        verdict = "wrong_tenant"
    else:
        verdict = None
    if verdict is None and user is not None and user["must_change_password"]:
        verdict = "password_change"

    if len(_user_cache) >= _USER_CACHE_MAX:
        _user_cache.clear()
    _user_cache[key] = (now + _USER_CACHE_TTL, verdict)
    return verdict


def _hash_key(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


class AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if request.url.path in _PUBLIC_PATHS:
            return await call_next(request)

        auth_header = request.headers.get("Authorization", "")
        api_key_header = request.headers.get("X-API-Key", "")

        if auth_header.startswith("Bearer "):
            token = auth_header[7:]
            try:
                payload = jwt.decode(
                    token,
                    settings.jwt_secret,
                    algorithms=[settings.jwt_algorithm],
                )
                if payload.get("type") != "access":
                    raise JWTError("Nieprawidłowy typ tokenu")
                # Tokeny sprzed multitenancy (bez organizacji) są odrzucane.
                if not is_uuid(payload.get("tenant_id")):
                    raise JWTError("Brak organizacji (tenant_id) w tokenie")
                if not is_uuid(payload.get("sub")):
                    raise JWTError("Brak użytkownika (sub) w tokenie")
                act_tenant_id = payload.get("act_tenant_id")
                if act_tenant_id is not None and not is_uuid(act_tenant_id):
                    raise JWTError("Nieprawidłowy act_tenant_id w tokenie")
            except JWTError as exc:
                logger.warning("Gateway: odrzucono JWT: %s", exc)
                return JSONResponse(
                    status_code=401,
                    content={"error": t("errors.auth.invalidToken"), "detail": str(exc)},
                )

            user_id = str(payload["sub"])
            token_tenant_id = str(payload["tenant_id"])
            act_tenant_id = str(act_tenant_id) if act_tenant_id else None
            try:
                verdict = await _check_user(user_id, token_tenant_id, act_tenant_id)
            except Exception as exc:
                # Fail closed — bez potwierdzenia konta nie wpuszczamy.
                logger.error("Gateway: błąd weryfikacji konta %s: %s", user_id, exc)
                verdict = "inactive"
            if verdict is not None:
                status, msg_key = _USER_REJECTIONS[verdict]
                logger.warning("Gateway: odrzucono JWT użytkownika %s (%s)", user_id, verdict)
                headers = {"X-GovAI-Error": "password_change_required"} if verdict == "password_change" else None
                return JSONResponse(status_code=status, content={"error": t(msg_key)}, headers=headers)

            request.state.auth_user_id = user_id
            request.state.auth_role = payload.get("role")
            request.state.auth_via = "jwt"
            request.state.auth_acting_as = act_tenant_id is not None
            tenant_id = act_tenant_id or token_tenant_id

        elif api_key_header:
            key_data = await _verify_api_key(api_key_header)
            if not key_data:
                logger.warning("Gateway: odrzucono X-API-Key (nieznany lub wygasły)")
                return JSONResponse(
                    status_code=401,
                    content={"error": t("errors.auth.invalidApiKey")},
                )
            request.state.auth_api_key_id = key_data["key_id"]
            request.state.auth_agent_id = key_data["agent_id"]
            request.state.auth_via = "api_key"
            tenant_id = key_data["tenant_id"]

        else:
            return JSONResponse(
                status_code=401,
                content={
                    "error": t("errors.auth.missing"),
                    "detail": t("errors.auth.missingDetail"),
                },
            )

        # ── Organizacja: musi istnieć i być aktywna ─────────────────────────────
        try:
            tenant = await fetch_tenant_status(tenant_id)
        except Exception as exc:
            logger.error("Gateway: błąd odczytu organizacji %s: %s", tenant_id, exc)
            tenant = None
        if tenant is None or tenant["status"] != "active" or tenant["deleted"]:
            logger.warning("Gateway: organizacja %s nieaktywna lub nieistniejąca — odrzucono", tenant_id)
            return JSONResponse(
                status_code=403,
                content={"error": t("errors.auth.tenantInactive")},
            )

        request.state.tenant_id = tenant_id
        set_request_tenant(tenant_id)
        # Bez Accept-Language — domyślny język organizacji (LocaleMiddleware znał
        # tylko domyślny język platformy, bo organizacja nie była jeszcze ustalona).
        if not match_locale(request.headers.get("accept-language")):
            set_locale(app_settings.get_str("i18n.default_locale", DEFAULT_LOCALE))

        return await call_next(request)


async def _verify_api_key(raw: str) -> dict | None:
    """Wyszukuje klucz po hashu w trybie platformy (organizacja nie jest jeszcze
    znana) — zwraca też organizację, do której klucz należy."""
    key_hash = _hash_key(raw)
    try:
        async with platform_conn() as conn:
            row = await conn.fetchrow(
                """SELECT id, name, agent_id, tenant_id FROM api_keys
                   WHERE key_hash = $1
                     AND active = true
                     AND (expires_at IS NULL OR expires_at > NOW())""",
                key_hash,
            )
            if not row:
                return None
            await conn.execute(
                "UPDATE api_keys SET last_used_at = NOW() WHERE id = $1", row["id"]
            )
        return {
            "key_id": str(row["id"]),
            "agent_id": str(row["agent_id"]) if row["agent_id"] else None,
            "tenant_id": str(row["tenant_id"]),
            "name": row["name"],
        }
    except Exception as exc:
        logger.error("Gateway: błąd weryfikacji klucza API: %s", exc)
        return None

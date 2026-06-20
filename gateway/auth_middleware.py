"""
Middleware autoryzacji Gateway — weryfikuje JWT Bearer lub X-API-Key.

Ścieżki publiczne (bez autoryzacji): /health, /
Wszystkie pozostałe wymagają tokenu.

Przepływ:
  1. Authorization: Bearer <jwt>  → weryfikacja JWT, ekstrahuje user_id + role
  2. X-API-Key: <key>             → weryfikacja hash w DB, ekstrahuje agent_id
  3. Brak obu                     → 401
"""
from __future__ import annotations

import hashlib
import logging

from fastapi import Request
from fastapi.responses import JSONResponse
from jose import JWTError, jwt
from starlette.middleware.base import BaseHTTPMiddleware

from config import settings
from database import get_pool

logger = logging.getLogger(__name__)

_PUBLIC_PATHS = {"/", "/health", "/docs", "/openapi.json"}


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
                request.state.auth_user_id = payload.get("sub")
                request.state.auth_role = payload.get("role")
                request.state.auth_via = "jwt"
            except JWTError as exc:
                logger.warning("Gateway: odrzucono JWT: %s", exc)
                return JSONResponse(
                    status_code=401,
                    content={"error": "Token nieprawidłowy lub wygasły", "detail": str(exc)},
                )

        elif api_key_header:
            key_data = await _verify_api_key(api_key_header)
            if not key_data:
                logger.warning("Gateway: odrzucono X-API-Key (nieznany lub wygasły)")
                return JSONResponse(
                    status_code=401,
                    content={"error": "Klucz API nieprawidłowy lub wygasły"},
                )
            request.state.auth_api_key_id = key_data["key_id"]
            request.state.auth_agent_id = key_data["agent_id"]
            request.state.auth_via = "api_key"

        else:
            return JSONResponse(
                status_code=401,
                content={
                    "error": "Brak autoryzacji",
                    "detail": "Wymagany nagłówek Authorization: Bearer <token> lub X-API-Key: <key>",
                },
            )

        return await call_next(request)


async def _verify_api_key(raw: str) -> dict | None:
    key_hash = _hash_key(raw)
    try:
        pool = get_pool()
        row = await pool.fetchrow(
            """SELECT id, name, agent_id FROM api_keys
               WHERE key_hash = $1
                 AND active = true
                 AND (expires_at IS NULL OR expires_at > NOW())""",
            key_hash,
        )
        if not row:
            return None
        await pool.execute(
            "UPDATE api_keys SET last_used_at = NOW() WHERE id = $1", row["id"]
        )
        return {
            "key_id": str(row["id"]),
            "agent_id": str(row["agent_id"]) if row["agent_id"] else None,
            "name": row["name"],
        }
    except Exception as exc:
        logger.error("Gateway: błąd weryfikacji klucza API: %s", exc)
        return None

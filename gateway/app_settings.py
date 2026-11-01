"""
Magazyn parametrów bramki — czyta app_settings (wartości domyślne platformy)
i app_settings_values (nadpisania per organizacja) do cache. Wspólne z API.

Odczyt (get_*) bierze organizację bieżącego żądania (database.request_tenant_id,
ustawia AuthMiddleware); poza żądaniem — wartości domyślne platformy.

Uwaga: pula asyncpg bramki NIE ma kodeka jsonb (zob. database.py), więc kolumnę
value pobieramy jako ::text i parsujemy json.loads. Konsumenci wołają get_* z
wartością domyślną — działa też zanim cache się załaduje (fallback do hardcodów).
"""
from __future__ import annotations

import json
import logging
from typing import Any

from database import platform_conn, request_tenant_id

logger = logging.getLogger(__name__)

_defaults: dict[str, Any] = {}
_overrides: dict[str, dict[str, Any]] = {}


async def load() -> None:
    """Ładuje wartości domyślne i nadpisania wszystkich organizacji (start + odświeżanie)."""
    global _defaults, _overrides
    try:
        async with platform_conn() as conn:
            rows = await conn.fetch("SELECT key, value::text AS value FROM app_settings")
            override_rows = await conn.fetch(
                "SELECT tenant_id, key, value::text AS value FROM app_settings_values"
            )
        defaults = {r["key"]: json.loads(r["value"]) for r in rows}
        overrides: dict[str, dict[str, Any]] = {}
        for r in override_rows:
            overrides.setdefault(str(r["tenant_id"]), {})[r["key"]] = json.loads(r["value"])
        _defaults, _overrides = defaults, overrides
    except Exception as exc:
        logger.error("Bramka: błąd ładowania parametrów z DB: %s", exc)


def _get(key: str, default: Any) -> Any:
    tenant = request_tenant_id()
    if tenant is not None:
        tenant_values = _overrides.get(tenant)
        if tenant_values and key in tenant_values:
            return tenant_values[key]
    return _defaults.get(key, default)


def get_int(key: str, default: int) -> int:
    try:
        return int(_get(key, default))
    except (TypeError, ValueError):
        return default


def get_number(key: str, default: float) -> float:
    try:
        return float(_get(key, default))
    except (TypeError, ValueError):
        return default


def get_str(key: str, default: str) -> str:
    val = _get(key, default)
    return str(val) if val is not None else default


def get_json(key: str, default: Any) -> Any:
    return _get(key, default)

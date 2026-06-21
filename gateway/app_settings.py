"""
Magazyn parametrów bramki — czyta tabelę app_settings (wspólną z API) do cache.

Uwaga: pula asyncpg bramki NIE ma kodeka jsonb (zob. database.py), więc kolumnę
value pobieramy jako ::text i parsujemy json.loads. Konsumenci wołają get_* z
wartością domyślną — działa też zanim cache się załaduje (fallback do hardcodów).
"""
from __future__ import annotations

import json
import logging
from typing import Any

from database import get_pool

logger = logging.getLogger(__name__)

_cache: dict[str, Any] = {}


async def load() -> None:
    """Ładuje wszystkie parametry do cache (start + cykliczne odświeżanie)."""
    global _cache
    try:
        rows = await get_pool().fetch("SELECT key, value::text AS value FROM app_settings")
        _cache = {r["key"]: json.loads(r["value"]) for r in rows}
    except Exception as exc:
        logger.error("Bramka: błąd ładowania parametrów z DB: %s", exc)


def get_int(key: str, default: int) -> int:
    try:
        return int(_cache[key])
    except (KeyError, TypeError, ValueError):
        return default


def get_number(key: str, default: float) -> float:
    try:
        return float(_cache[key])
    except (KeyError, TypeError, ValueError):
        return default


def get_str(key: str, default: str) -> str:
    val = _cache.get(key, default)
    return str(val) if val is not None else default


def get_json(key: str, default: Any) -> Any:
    return _cache.get(key, default)

"""
Serwis ustawień — typowany dostęp do parametrów z cache odświeżanym z bazy.

Wzorzec jak pętla polityk: wartości w pamięci, odświeżane co N sekund oraz
natychmiast po zapisie (PUT). Konsumenci wołają get_int/get_number/... z
wartością domyślną jako fallback — działa nawet zanim cache się załaduje.
"""
from __future__ import annotations

import logging
from typing import Any

from repositories import settings_repository as repo

logger = logging.getLogger(__name__)

_cache: dict[str, Any] = {}


async def load() -> None:
    """Ładuje wszystkie wartości do cache (start + odświeżanie)."""
    global _cache
    try:
        _cache = await repo.fetch_values()
    except Exception as exc:
        logger.error("Błąd ładowania ustawień z DB: %s", exc)


def _get(key: str, default: Any) -> Any:
    return _cache.get(key, default)


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


def get_bool(key: str, default: bool) -> bool:
    val = _get(key, default)
    return bool(val)


def get_str(key: str, default: str) -> str:
    val = _get(key, default)
    return str(val) if val is not None else default


def get_json(key: str, default: Any) -> Any:
    return _get(key, default)


def coerce(value_type: str, raw: Any) -> Any:
    """Rzutuje wartość z żądania PUT na właściwy typ przed walidacją/zapisem."""
    if value_type == "int":
        return int(raw)
    if value_type == "number":
        return float(raw)
    if value_type == "bool":
        if isinstance(raw, str):
            return raw.lower() in ("true", "1", "yes")
        return bool(raw)
    if value_type == "string":
        return str(raw)
    # json — przekazujemy jak jest (dict/list)
    return raw


def validate(meta: dict, value: Any) -> None:
    """Waliduje typ i zakres min/max. Rzuca ValueError z komunikatem PL."""
    vt = meta["value_type"]
    if vt in ("int", "number"):
        num = float(value)
        lo, hi = meta.get("min_value"), meta.get("max_value")
        if lo is not None and num < float(lo):
            raise ValueError(f"Wartość {num} poniżej minimum {lo}")
        if hi is not None and num > float(hi):
            raise ValueError(f"Wartość {num} powyżej maksimum {hi}")
    elif vt == "bool":
        if not isinstance(value, bool):
            raise ValueError("Oczekiwano wartości logicznej")
    elif vt == "string":
        if not isinstance(value, str):
            raise ValueError("Oczekiwano tekstu")
    elif vt == "json":
        if not isinstance(value, (dict, list)):
            raise ValueError("Oczekiwano obiektu lub listy JSON")


async def set_value(key: str, raw_value: Any, meta: dict, updated_by: str) -> dict:
    """Rzutuje, waliduje, zapisuje przez repozytorium i odświeża cache."""
    value = coerce(meta["value_type"], raw_value)
    validate(meta, value)
    row = await repo.update_value(key, value, updated_by)
    if row is None:
        raise KeyError(key)
    _cache[key] = value
    return row

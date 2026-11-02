"""
Serwis ustawień — typowany dostęp do parametrów z cache odświeżanym z bazy.

Wzorzec jak pętla polityk: wartości w pamięci, odświeżane co N sekund oraz
natychmiast po zapisie (PUT). Konsumenci wołają get_int/get_number/... z
wartością domyślną jako fallback — działa nawet zanim cache się załaduje.
"""
from __future__ import annotations

import logging
from typing import Any

from database import current_tenant_id, platform_db
from i18n import LOCALES, is_locale, t
from repositories import settings_repository as repo

logger = logging.getLogger(__name__)

# Multitenancy: wartości domyślne platformy + nadpisania per organizacja.
# Odczyt (get_*) bierze organizację z kontekstu bazy (database.current_tenant_id);
# poza kontekstem organizacji — wartości domyślne platformy.
_defaults: dict[str, Any] = {}
_overrides: dict[str, dict[str, Any]] = {}


async def load() -> None:
    """Ładuje wartości domyślne i nadpisania wszystkich organizacji (start + odświeżanie)."""
    global _defaults, _overrides
    try:
        async with platform_db():
            defaults = await repo.fetch_defaults()
            overrides = await repo.fetch_overrides()
        _defaults, _overrides = defaults, overrides
    except Exception as exc:
        logger.error("Błąd ładowania ustawień z DB: %s", exc)


def _get(key: str, default: Any) -> Any:
    tenant = current_tenant_id()
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
    """Waliduje typ i zakres min/max. Rzuca ValueError z komunikatem w języku żądania."""
    vt = meta["value_type"]
    if vt in ("int", "number"):
        num = float(value)
        lo, hi = meta.get("min_value"), meta.get("max_value")
        if lo is not None and num < float(lo):
            raise ValueError(t("settings.errors.below_min", value=num, min=lo))
        if hi is not None and num > float(hi):
            raise ValueError(t("settings.errors.above_max", value=num, max=hi))
    elif vt == "bool":
        if not isinstance(value, bool):
            raise ValueError(t("settings.errors.expected_bool"))
    elif vt == "string":
        if not isinstance(value, str):
            raise ValueError(t("settings.errors.expected_string"))
    elif vt == "json":
        if not isinstance(value, (dict, list)):
            raise ValueError(t("settings.errors.expected_json"))

    # Reguły per klucz (poza typem i zakresem)
    if meta.get("key") == "i18n.default_locale" and not is_locale(value):
        raise ValueError(t("settings.errors.invalid_locale", allowed=", ".join(LOCALES)))


async def set_value(key: str, raw_value: Any, meta: dict, updated_by: str) -> dict:
    """Rzutuje, waliduje i zapisuje nadpisanie organizacji bieżącego kontekstu; odświeża cache."""
    value = coerce(meta["value_type"], raw_value)
    validate(meta, value)
    row = await repo.update_value(key, value, updated_by)
    if row is None:
        raise KeyError(key)
    tenant = current_tenant_id()
    if tenant is not None:
        _overrides.setdefault(tenant, {})[key] = value
    return row


async def set_default(key: str, raw_value: Any, meta: dict, updated_by: str) -> dict:
    """Zmienia wartość domyślną platformy (super-admin) — w osobnej transakcji platformy."""
    value = coerce(meta["value_type"], raw_value)
    validate(meta, value)
    async with platform_db():
        row = await repo.update_default(key, value, updated_by)
    if row is None:
        raise KeyError(key)
    _defaults[key] = value
    return row

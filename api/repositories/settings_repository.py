"""
Repozytorium ustawień — JEDYNE miejsce z SQL dla tabeli app_settings.

Routery i serwisy nigdy nie składają zapytań samodzielnie; wołają te funkcje.
Wszystkie wartości przekazywane jako parametry pozycyjne ($n) — brak interpolacji.
"""
from __future__ import annotations

from typing import Any, Optional

from database import get_pool

_SELECT_COLS = """
    key, value, value_type, category, label, description, unit,
    min_value, max_value, editable, updated_by, updated_at
"""


async def fetch_all() -> list[dict]:
    pool = get_pool()
    rows = await pool.fetch(f"SELECT {_SELECT_COLS} FROM app_settings ORDER BY category, key")
    return [dict(r) for r in rows]


async def fetch_one(key: str) -> Optional[dict]:
    pool = get_pool()
    row = await pool.fetchrow(f"SELECT {_SELECT_COLS} FROM app_settings WHERE key = $1", key)
    return dict(row) if row else None


async def fetch_values() -> dict[str, Any]:
    """Zwraca wyłącznie {key: value} — do zasilenia cache."""
    pool = get_pool()
    rows = await pool.fetch("SELECT key, value FROM app_settings")
    return {r["key"]: r["value"] for r in rows}


async def update_value(key: str, value: Any, updated_by: str) -> Optional[dict]:
    """Nadpisuje wartość (kodek jsonb serializuje natywny obiekt Pythona)."""
    pool = get_pool()
    row = await pool.fetchrow(
        f"""UPDATE app_settings
            SET value = $1, updated_by = $2, updated_at = NOW()
            WHERE key = $3
            RETURNING {_SELECT_COLS}""",
        value, updated_by, key,
    )
    return dict(row) if row else None

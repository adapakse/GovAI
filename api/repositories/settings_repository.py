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
    """Nadpisuje wartość (kodek jsonb serializuje natywny obiekt Pythona) i loguje zmianę do historii."""
    pool = get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            old = await conn.fetchrow("SELECT value FROM app_settings WHERE key = $1", key)
            if old is None:
                return None
            row = await conn.fetchrow(
                f"""UPDATE app_settings
                    SET value = $1, updated_by = $2, updated_at = NOW()
                    WHERE key = $3
                    RETURNING {_SELECT_COLS}""",
                value, updated_by, key,
            )
            await conn.execute(
                """INSERT INTO app_settings_audit (key, old_value, new_value, updated_by)
                   VALUES ($1, $2, $3, $4)""",
                key, old["value"], value, updated_by,
            )
    return dict(row) if row else None


async def fetch_history(key: str, limit: int = 20) -> list[dict]:
    pool = get_pool()
    rows = await pool.fetch(
        """SELECT id, key, old_value, new_value, updated_by, updated_at
           FROM app_settings_audit
           WHERE key = $1
           ORDER BY updated_at DESC
           LIMIT $2""",
        key, limit,
    )
    return [dict(r) for r in rows]

"""
Repozytorium ustawień — JEDYNE miejsce z SQL dla tabel app_settings,
app_settings_values i app_settings_audit.

Multitenancy (migracja 015): app_settings = definicje + wartość domyślna platformy,
app_settings_values = nadpisania organizacji (RLS). Odczyt w kontekście
organizacji zwraca wartość efektywną (nadpisanie albo domyślna).

Routery i serwisy nigdy nie składają zapytań samodzielnie; wołają te funkcje.
Wszystkie wartości przekazywane jako parametry pozycyjne ($n) — brak interpolacji.
"""
from __future__ import annotations

from typing import Any, Optional

from database import get_pool

# Wartość efektywna: nadpisanie organizacji (jeśli jest) albo domyślna platformy.
# W trybie platformy current_tenant_id() jest NULL — zwraca wartości domyślne.
_SELECT_EFFECTIVE = """
    SELECT s.key, COALESCE(v.value, s.value) AS value, s.value AS default_value,
           s.value_type, s.category, s.label, s.description, s.unit,
           s.min_value, s.max_value, s.editable, s.tenant_editable,
           COALESCE(v.updated_by, s.updated_by) AS updated_by,
           COALESCE(v.updated_at, s.updated_at) AS updated_at,
           (v.key IS NOT NULL) AS overridden,
           s.label_i18n, s.description_i18n, s.unit_i18n
    FROM app_settings s
    LEFT JOIN app_settings_values v ON v.key = s.key AND v.tenant_id = current_tenant_id()
"""


async def fetch_all() -> list[dict]:
    pool = get_pool()
    rows = await pool.fetch(_SELECT_EFFECTIVE + " ORDER BY s.category, s.key")
    return [dict(r) for r in rows]


async def fetch_one(key: str) -> Optional[dict]:
    pool = get_pool()
    row = await pool.fetchrow(_SELECT_EFFECTIVE + " WHERE s.key = $1", key)
    return dict(row) if row else None


async def fetch_defaults() -> dict[str, Any]:
    """{key: wartość domyślna platformy} — do zasilenia cache."""
    pool = get_pool()
    rows = await pool.fetch("SELECT key, value FROM app_settings")
    return {r["key"]: r["value"] for r in rows}


async def fetch_overrides() -> dict[str, dict[str, Any]]:
    """{tenant_id: {key: value}} — nadpisania wszystkich organizacji (tryb platformy)."""
    pool = get_pool()
    rows = await pool.fetch("SELECT tenant_id, key, value FROM app_settings_values")
    out: dict[str, dict[str, Any]] = {}
    for r in rows:
        out.setdefault(str(r["tenant_id"]), {})[r["key"]] = r["value"]
    return out


async def update_value(key: str, value: Any, updated_by: str) -> Optional[dict]:
    """Zapisuje nadpisanie organizacji bieżącego kontekstu (kodek jsonb serializuje
    natywny obiekt Pythona) i loguje zmianę do historii organizacji."""
    pool = get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            old = await conn.fetchrow(_SELECT_EFFECTIVE + " WHERE s.key = $1", key)
            if old is None:
                return None
            await conn.execute(
                """INSERT INTO app_settings_values (key, value, updated_by)
                   VALUES ($1, $2, $3)
                   ON CONFLICT (tenant_id, key)
                   DO UPDATE SET value = EXCLUDED.value, updated_by = EXCLUDED.updated_by, updated_at = NOW()""",
                key, value, updated_by,
            )
            await conn.execute(
                """INSERT INTO app_settings_audit (key, old_value, new_value, updated_by)
                   VALUES ($1, $2, $3, $4)""",
                key, old["value"], value, updated_by,
            )
            row = await conn.fetchrow(_SELECT_EFFECTIVE + " WHERE s.key = $1", key)
    return dict(row) if row else None


async def update_default(key: str, value: Any, updated_by: str) -> Optional[dict]:
    """Zmienia wartość domyślną platformy (super-admin, tryb platformy)."""
    pool = get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            old = await conn.fetchrow("SELECT value FROM app_settings WHERE key = $1", key)
            if old is None:
                return None
            await conn.execute(
                "UPDATE app_settings SET value = $1, updated_by = $2, updated_at = NOW() WHERE key = $3",
                value, updated_by, key,
            )
            await conn.execute(
                """INSERT INTO app_settings_audit (key, old_value, new_value, updated_by, tenant_id)
                   VALUES ($1, $2, $3, $4, NULL)""",
                key, old["value"], value, updated_by,
            )
            row = await conn.fetchrow(_SELECT_EFFECTIVE + " WHERE s.key = $1", key)
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

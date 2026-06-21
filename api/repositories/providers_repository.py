"""
Repozytorium providerów — JEDYNE miejsce z SQL dla tabeli providers.

Routery nigdy nie składają zapytań samodzielnie; wołają te funkcje.
Wszystkie wartości przekazywane jako parametry pozycyjne ($n) — brak interpolacji
poza dynamicznym budowaniem klauzul (WHERE active, SET pól opcjonalnych).
Funkcje zwracają surowy wynik asyncpg (.fetch/.fetchrow/.execute).
"""
from __future__ import annotations

from typing import Any, Optional

from database import get_pool

_SELECT_COLS = """id, name, provider_type, model_ids, base_url, api_key_env,
                  max_data_sensitivity, active, priority, is_healthy,
                  last_health_check_at, notes, created_by, created_at, updated_at"""


async def list_providers(active_only: bool = False):
    pool = get_pool()
    where = "WHERE active = true" if active_only else ""
    return await pool.fetch(
        f"""SELECT id, name, provider_type, model_ids, base_url, api_key_env,
                   max_data_sensitivity, active, priority, is_healthy,
                   last_health_check_at, notes, created_by, created_at, updated_at
            FROM providers
            {where}
            ORDER BY priority ASC, name ASC"""
    )


async def get_provider(provider_id: str):
    pool = get_pool()
    return await pool.fetchrow(
        """SELECT id, name, provider_type, model_ids, base_url, api_key_env,
                  max_data_sensitivity, active, priority, is_healthy,
                  last_health_check_at, notes, created_by, created_at, updated_at
           FROM providers WHERE id = $1""",
        provider_id,
    )


async def insert_provider(
    name: str,
    provider_type: str,
    model_ids: list[str],
    base_url: Optional[str],
    api_key_env: Optional[str],
    max_data_sensitivity: str,
    priority: int,
    notes: Optional[str],
    created_by: Any,
):
    pool = get_pool()
    return await pool.fetchrow(
        """INSERT INTO providers
               (name, provider_type, model_ids, base_url, api_key_env,
                max_data_sensitivity, priority, notes, created_by)
           VALUES ($1, $2, $3, $4, $5, $6::data_sensitivity_level, $7, $8, $9)
           RETURNING id, name, provider_type, model_ids, base_url, api_key_env,
                     max_data_sensitivity, active, priority, is_healthy,
                     last_health_check_at, notes, created_by, created_at, updated_at""",
        name,
        provider_type,
        model_ids,
        base_url,
        api_key_env,
        max_data_sensitivity,
        priority,
        notes,
        created_by,
    )


async def get_provider_id(provider_id: str):
    pool = get_pool()
    return await pool.fetchrow("SELECT id FROM providers WHERE id = $1", provider_id)


async def update_provider(
    provider_id: str,
    *,
    name: Optional[str] = None,
    base_url: Optional[str] = None,
    api_key_env: Optional[str] = None,
    priority: Optional[int] = None,
    active: Optional[bool] = None,
    is_healthy: Optional[bool] = None,
    notes: Optional[str] = None,
    model_ids: Optional[list[str]] = None,
    max_data_sensitivity: Optional[str] = None,
):
    """Dynamiczny UPDATE pól opcjonalnych. Zwraca None gdy brak pól do zmiany."""
    pool = get_pool()
    updates, params = [], []
    idx = 1

    simple_fields = [
        ("name", name),
        ("base_url", base_url),
        ("api_key_env", api_key_env),
        ("priority", priority),
        ("active", active),
        ("is_healthy", is_healthy),
        ("notes", notes),
    ]
    for field, val in simple_fields:
        if val is not None:
            updates.append(f"{field} = ${idx}")
            params.append(val)
            idx += 1

    if model_ids is not None:
        updates.append(f"model_ids = ${idx}")
        params.append(model_ids)
        idx += 1

    if max_data_sensitivity is not None:
        updates.append(f"max_data_sensitivity = ${idx}::data_sensitivity_level")
        params.append(max_data_sensitivity)
        idx += 1

    if not updates:
        return None

    updates.append("updated_at = NOW()")
    params.append(provider_id)

    return await pool.fetchrow(
        f"""UPDATE providers SET {', '.join(updates)} WHERE id = ${idx}
            RETURNING id, name, provider_type, model_ids, base_url, api_key_env,
                      max_data_sensitivity, active, priority, is_healthy,
                      last_health_check_at, notes, created_by, created_at, updated_at""",
        *params,
    )


async def delete_provider(provider_id: str):
    pool = get_pool()
    return await pool.fetchrow(
        "DELETE FROM providers WHERE id = $1 RETURNING id, name", provider_id
    )


async def set_health(provider_id: str, healthy: bool):
    pool = get_pool()
    return await pool.fetchrow(
        """UPDATE providers
           SET is_healthy = $1, last_health_check_at = NOW(), updated_at = NOW()
           WHERE id = $2
           RETURNING id, name, is_healthy, last_health_check_at""",
        healthy, provider_id,
    )

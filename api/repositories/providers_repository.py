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
from i18n import DEFAULT_LOCALE, get_locale


def _notes_col() -> str:
    """notes w języku żądania (notes_i18n), fallback na kolumnę bazową (polski).
    Locale pochodzi z białej listy i18n.LOCALES — bezpieczne do wstawienia w SQL."""
    loc = get_locale()
    if loc == DEFAULT_LOCALE:
        return "notes"
    return f"COALESCE(NULLIF(notes_i18n ->> '{loc}', ''), notes) AS notes"


def _columns() -> str:
    """Kolumny zwracane do API. is_platform = wiersz platformy (tenant_id NULL),
    dla organizacji tylko do odczytu. api_key_encrypted nigdy nie wychodzi z bazy."""
    return f"""id, name, provider_type, model_ids, base_url, api_key_env,
               max_data_sensitivity, active, priority, is_healthy,
               last_health_check_at, {_notes_col()}, created_by, created_at, updated_at,
               (tenant_id IS NULL) AS is_platform"""


async def list_providers(active_only: bool = False):
    pool = get_pool()
    where = "WHERE active = true" if active_only else ""
    return await pool.fetch(
        f"""SELECT {_columns()}
            FROM providers
            {where}
            ORDER BY priority ASC, name ASC"""
    )


async def get_provider(provider_id: str):
    pool = get_pool()
    return await pool.fetchrow(
        f"""SELECT {_columns()}
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
        f"""INSERT INTO providers
               (name, provider_type, model_ids, base_url, api_key_env,
                max_data_sensitivity, priority, notes, created_by)
           VALUES ($1, $2, $3, $4, $5, $6::data_sensitivity_level, $7, $8, $9)
           RETURNING {_columns()}""",
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
    ]
    # Notatka w języku innym niż polski trafia do notes_i18n[locale] — kolumna
    # bazowa (polski, źródło tłumaczeń) zostaje nietknięta.
    if notes is not None and get_locale() != DEFAULT_LOCALE:
        updates.append(f"notes_i18n = COALESCE(notes_i18n, '{{}}'::jsonb) || ${idx}::jsonb")
        params.append({get_locale(): notes})
        idx += 1
        notes = None
    simple_fields.append(("notes", notes))
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
            RETURNING {_columns()}""",
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
           RETURNING id, name, is_healthy, last_health_check_at,
                     (tenant_id IS NULL) AS is_platform""",
        healthy, provider_id,
    )

"""
Repozytorium wymagań EU AI Act — JEDYNE miejsce z SQL dla tabeli ai_act_requirements.

Routery nigdy nie składają zapytań samodzielnie; wołają te funkcje.
Funkcje zwracają surowy wynik asyncpg (Record / list[Record]) — bez konwersji na dict.
Wszystkie wartości przekazywane jako parametry pozycyjne ($n) — brak interpolacji.
"""
from __future__ import annotations

from typing import Any, Optional

from database import get_pool


async def list_requirements(
    risk_level: Optional[str] = None,
    active_only: bool = False,
):
    """Lista wymagań — opcjonalnie filtrowana wg risk_level / active."""
    pool = get_pool()
    conditions = ["1=1"]
    params: list = []
    idx = 1

    if risk_level:
        conditions.append(f"risk_level = ${idx}::risk_level")
        params.append(risk_level); idx += 1
    if active_only:
        conditions.append("active = true")

    return await pool.fetch(
        f"""SELECT id, risk_level, article_ref, requirement_title,
                   requirement_text, active, sort_order, created_at,
                   default_severity, default_deadline_days, decl_key
            FROM ai_act_requirements
            WHERE {' AND '.join(conditions)}
            ORDER BY
                CASE risk_level
                    WHEN 'unacceptable' THEN 1
                    WHEN 'high'         THEN 2
                    WHEN 'limited'      THEN 3
                    WHEN 'minimal'      THEN 4
                END,
                sort_order ASC""",
        *params,
    )


async def insert_requirement(
    req_id: str,
    risk_level: str,
    article_ref: str,
    requirement_title: str,
    requirement_text: str,
    sort_order: int,
    default_severity: str = "major",
    default_deadline_days: int = 30,
    decl_key: Optional[str] = None,
):
    """Wstawia nowe wymaganie i zwraca pełny wiersz."""
    pool = get_pool()
    await pool.execute(
        """INSERT INTO ai_act_requirements
               (id, risk_level, article_ref, requirement_title, requirement_text, sort_order,
                default_severity, default_deadline_days, decl_key)
           VALUES ($1, $2::risk_level, $3, $4, $5, $6, $7, $8, $9)""",
        req_id, risk_level, article_ref,
        requirement_title, requirement_text, sort_order,
        default_severity, default_deadline_days, decl_key,
    )
    return await pool.fetchrow(
        "SELECT * FROM ai_act_requirements WHERE id = $1", req_id
    )


async def get_requirement(req_id: str, columns: str = "*"):
    """Pobiera pojedyncze wymaganie po id (wybór kolumn sterowany przez wołającego)."""
    pool = get_pool()
    return await pool.fetchrow(
        f"SELECT {columns} FROM ai_act_requirements WHERE id = $1", req_id
    )


async def update_requirement(req_id: str, fields: dict[str, Any]):
    """Aktualizuje przekazane (nie-None) pola i zwraca pełny wiersz.

    `fields` to mapa {kolumna: wartość} — wartości None są pomijane.
    Zachowuje kolejność iteracji słownika z routera.
    """
    pool = get_pool()
    updates, params = [], []
    idx = 1
    for field, val in fields.items():
        if val is not None:
            updates.append(f"{field} = ${idx}"); params.append(val); idx += 1

    if not updates:
        return None

    params.append(req_id)
    await pool.execute(
        f"UPDATE ai_act_requirements SET {', '.join(updates)} WHERE id = ${idx}",
        *params,
    )
    return await pool.fetchrow("SELECT * FROM ai_act_requirements WHERE id = $1", req_id)


async def delete_requirement(req_id: str):
    """Usuwa wymaganie po id."""
    pool = get_pool()
    await pool.execute("DELETE FROM ai_act_requirements WHERE id = $1", req_id)

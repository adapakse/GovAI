"""
Repozytorium polityk — JEDYNE miejsce z SQL dla tabeli policies.

Routery wołają te funkcje; nie składają zapytań samodzielnie.
Funkcje zwracają surowy wynik asyncpg (Record / list[Record] / str) — bez konwersji.

UWAGA: pula API ma zarejestrowany kodek jsonb — do kolumn condition_json / action_json
przekazujemy surowe dict-y (kodek serializuje), bez json.dumps.
"""
from __future__ import annotations

from typing import Any, Optional

from database import get_pool


async def list_policies(
    level: Optional[str],
    agent_id: Optional[str],
    active_only: bool,
) -> list:
    """Lista polityk z dynamicznym filtrowaniem. Zwraca list[Record]."""
    pool = get_pool()
    conditions = ["1=1"]
    params: list = []
    idx = 1

    if level:
        conditions.append(f"level = ${idx}::policy_level")
        params.append(level); idx += 1
    if agent_id:
        conditions.append(f"agent_id = ${idx}")
        params.append(agent_id); idx += 1
    if active_only:
        conditions.append("active = true")

    where = " AND ".join(conditions)
    return await pool.fetch(
        f"""SELECT id, name, policy_code, level, agent_id, team, rule_type,
                   condition_json, action_json, priority, active, version,
                   created_by, created_at
            FROM policies
            WHERE {where}
            ORDER BY priority ASC, created_at DESC""",
        *params,
    )


async def insert_policy(
    policy_id: str,
    name: str,
    policy_code: Optional[str],
    level: str,
    agent_id: Optional[str],
    team: Optional[str],
    rule_type: str,
    condition_json: dict,
    action_json: dict,
    priority: int,
    created_by: Optional[str],
) -> str:
    """Wstawia nową politykę. Zwraca status string z .execute."""
    pool = get_pool()
    return await pool.execute(
        """INSERT INTO policies (
               id, name, policy_code, level, agent_id, team, rule_type,
               condition_json, action_json, priority, created_by
           ) VALUES ($1, $2, $3, $4::policy_level, $5, $6, $7::policy_action, $8, $9, $10, $11)""",
        policy_id, name, policy_code, level, agent_id, team,
        rule_type, condition_json, action_json,
        priority, created_by,
    )


async def get_policy_by_id(policy_id: str):
    """Pełny wiersz polityki. Zwraca Record|None."""
    pool = get_pool()
    return await pool.fetchrow("SELECT * FROM policies WHERE id = $1", policy_id)


async def update_policy(
    policy_id: str,
    name: Optional[str] = None,
    condition_json: Optional[dict] = None,
    action_json: Optional[dict] = None,
    priority: Optional[int] = None,
    active: Optional[bool] = None,
) -> Optional[str]:
    """
    Dynamiczna aktualizacja polityki (tylko przekazane pola) + inkrementacja version.
    Zwraca status string z .execute, lub None gdy nie ma żadnego pola do aktualizacji.
    """
    pool = get_pool()
    updates: list = []
    params: list = []
    idx = 1

    if name is not None:
        updates.append(f"name = ${idx}"); params.append(name); idx += 1
    if condition_json is not None:
        updates.append(f"condition_json = ${idx}"); params.append(condition_json); idx += 1
    if action_json is not None:
        updates.append(f"action_json = ${idx}"); params.append(action_json); idx += 1
    if priority is not None:
        updates.append(f"priority = ${idx}"); params.append(priority); idx += 1
    if active is not None:
        updates.append(f"active = ${idx}"); params.append(active); idx += 1

    if not updates:
        return None

    updates.append(f"version = version + 1")
    params.append(policy_id)
    return await pool.execute(
        f"UPDATE policies SET {', '.join(updates)} WHERE id = ${idx}",
        *params,
    )


async def get_policy_condition(policy_id: str):
    """Zwraca id + condition_json. Record|None."""
    pool = get_pool()
    return await pool.fetchrow(
        "SELECT id, condition_json FROM policies WHERE id = $1", policy_id
    )


async def update_keywords(policy_id: str, condition_json: dict) -> str:
    """Nadpisuje condition_json + inkrementuje version. Zwraca status string."""
    pool = get_pool()
    return await pool.execute(
        "UPDATE policies SET condition_json = $1, version = version + 1 WHERE id = $2",
        condition_json, policy_id,
    )


async def get_policy_active(policy_id: str):
    """Zwraca id, name, active. Record|None."""
    pool = get_pool()
    return await pool.fetchrow(
        "SELECT id, name, active FROM policies WHERE id = $1", policy_id
    )


async def toggle_policy(policy_id: str, new_active: bool) -> str:
    """Ustawia active + inkrementuje version. Zwraca status string."""
    pool = get_pool()
    return await pool.execute(
        "UPDATE policies SET active = $1, version = version + 1 WHERE id = $2",
        new_active, policy_id,
    )


async def deactivate_policy(policy_id: str) -> str:
    """Soft delete — ustawia active = false. Zwraca status string."""
    pool = get_pool()
    return await pool.execute(
        "UPDATE policies SET active = false WHERE id = $1", policy_id
    )

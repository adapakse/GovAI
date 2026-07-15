"""
Repozytorium agentów — JEDYNE miejsce z SQL dla tabeli agents (oraz audit_log w zakresie statystyk agenta).

Routery i serwisy nigdy nie składają zapytań samodzielnie; wołają te funkcje.
Wszystkie wartości przekazywane jako parametry pozycyjne ($n) — brak interpolacji wartości.

Funkcje zwracają surowy wynik asyncpg (Record / list[Record] / scalar / str) —
formatowanie odpowiedzi pozostaje po stronie routera.
"""
from __future__ import annotations

from typing import Any, Optional


from database import get_pool


async def list_agents(
    risk_level: Optional[str],
    status: Optional[str],
    team: Optional[str],
) -> list:
    """Lista agentów z opcjonalnym filtrowaniem po risk_level / status / team."""
    pool = get_pool()

    conditions = ["1=1"]
    params: list = []
    idx = 1

    if risk_level:
        conditions.append(f"risk_level = ${idx}::risk_level")
        params.append(risk_level); idx += 1
    if status:
        conditions.append(f"status = ${idx}::agent_status")
        params.append(status); idx += 1
    if team:
        conditions.append(f"team ILIKE ${idx}")
        params.append(f"%{team}%"); idx += 1

    where = " AND ".join(conditions)
    return await pool.fetch(
        f"""SELECT id, name, description, owner_name, owner_email, team,
                   risk_level, annex_iii_cat, legal_basis, status,
                   requires_oversight, model_id, monthly_budget_eur,
                   allowed_data_cats, created_at, updated_at
            FROM agents
            WHERE {where}
            ORDER BY name""",
        *params,
    )


async def insert_agent(
    agent_id: str,
    name: str,
    description: str,
    owner_name: str,
    owner_email: str,
    team: Optional[str],
    risk_level: str,
    annex_iii_cat: Any,
    legal_basis: Any,
    requires_oversight: Any,
    model_id: str,
    monthly_budget: Any,
    allowed_data_cats: list,
    allowed_tools: list,
) -> str:
    """Wstawia nowego agenta (status 'active'). Zwraca status z asyncpg.execute."""
    pool = get_pool()
    return await pool.execute(
        """INSERT INTO agents (
               id, name, description, owner_name, owner_email, team,
               risk_level, annex_iii_cat, legal_basis, status,
               requires_oversight, model_id, monthly_budget_eur,
               allowed_data_cats, allowed_tools
           ) VALUES (
               $1, $2, $3, $4, $5, $6,
               $7::risk_level, $8, $9, 'active'::agent_status,
               $10, $11, $12,
               $13, $14
           )""",
        agent_id, name, description, owner_name, owner_email, team,
        risk_level, annex_iii_cat, legal_basis,
        requires_oversight, model_id, monthly_budget,
        allowed_data_cats, allowed_tools,
    )


async def get_agent_by_id(agent_id: str):
    """Pełny wiersz agenta po id (SELECT *). Record|None."""
    pool = get_pool()
    return await pool.fetchrow("SELECT * FROM agents WHERE id = $1", agent_id)


async def get_agent_status(agent_id: str):
    """Zwraca id, name, status agenta. Record|None."""
    pool = get_pool()
    return await pool.fetchrow("SELECT id, name, status FROM agents WHERE id = $1", agent_id)


async def update_status(agent_id: str, status: str) -> str:
    """Zmienia status agenta (cast ::agent_status). Zwraca status z asyncpg.execute."""
    pool = get_pool()
    return await pool.execute(
        "UPDATE agents SET status = $1::agent_status, updated_at = NOW() WHERE id = $2",
        status, agent_id,
    )


async def get_agent_id_only(agent_id: str):
    """Zwraca wyłącznie id agenta (sprawdzenie istnienia). Record|None."""
    pool = get_pool()
    return await pool.fetchrow("SELECT id FROM agents WHERE id = $1", agent_id)


# Pola tekstowe (ISO string z frontendu), które muszą trafić do kolumn
# date/timestamptz — bez jawnego castu asyncpg odmawia zakodowania str jako
# datetime (TypeError: expected a datetime.date or datetime.datetime instance).
_SIMPLE_CASTS = {
    "last_reviewed_at": "::timestamptz",
    "next_review_date": "::date",
}


async def update_registry(
    agent_id: str,
    simple_values: dict,
    array_values: dict,
    compliance_decl: Optional[dict],
) -> str:
    """
    Partial update danych rejestru agenta.

    simple_values   — {kolumna: wartość} dla pól skalarnych (przypisanie bez castu,
                      poza polami dat — zob. _SIMPLE_CASTS),
    array_values    — {kolumna: wartość} dla pól tablicowych (cast ::text[]),
    compliance_decl — natywny dict deklaracji lub None (kodek jsonb puli, cast ::jsonb).

    Buduje dynamiczny SET w tej samej kolejności co dotychczas:
    pola skalarne -> pola tablicowe -> compliance_decl -> updated_at.
    Zwraca status z asyncpg.execute.
    """
    pool = get_pool()

    updates: list = []
    params: list = []
    idx = 1

    for field, val in simple_values.items():
        cast = _SIMPLE_CASTS.get(field, "")
        updates.append(f"{field} = ${idx}{cast}")
        params.append(val); idx += 1

    for field, val in array_values.items():
        updates.append(f"{field} = ${idx}::text[]")
        params.append(val); idx += 1

    if compliance_decl is not None:
        updates.append(f"compliance_decl = ${idx}::jsonb")
        params.append(compliance_decl); idx += 1

    updates.append("updated_at = NOW()")
    params.append(agent_id)
    return await pool.execute(
        f"UPDATE agents SET {', '.join(updates)} WHERE id = ${idx}",
        *params,
    )


async def get_agent_name(agent_id: str):
    """Zwraca id, name agenta. Record|None."""
    pool = get_pool()
    return await pool.fetchrow("SELECT id, name FROM agents WHERE id = $1", agent_id)


async def fetch_stats_totals(agent_id: str, days: str):
    """Agregaty wywołań agenta z audit_log za ostatnie N dni. Record."""
    pool = get_pool()
    return await pool.fetchrow(
        """SELECT
               COUNT(*)                                              AS total_calls,
               COUNT(*) FILTER (WHERE policy_result = 'blocked')    AS blocked_calls,
               COUNT(*) FILTER (WHERE policy_result = 'oversight_required') AS oversight_calls,
               COUNT(*) FILTER (WHERE pii_count > 0)                AS pii_calls,
               ROUND(AVG(latency_ms))                               AS avg_latency_ms,
               MAX(latency_ms)                                       AS max_latency_ms,
               COALESCE(SUM(cost_eur), 0)                           AS total_cost_eur,
               COALESCE(SUM(tokens_in), 0)                          AS total_tokens_in,
               COALESCE(SUM(tokens_out), 0)                         AS total_tokens_out,
               COALESCE(SUM(pii_count), 0)                          AS total_pii_detected
           FROM audit_log
           WHERE agent_id = $1
             AND time > NOW() - ($2 || ' days')::INTERVAL""",
        agent_id, days,
    )


async def fetch_stats_daily(agent_id: str, days: str) -> list:
    """Dzienny rozkład wywołań agenta z audit_log za ostatnie N dni. list[Record]."""
    pool = get_pool()
    return await pool.fetch(
        """SELECT
               DATE_TRUNC('day', time) AS day,
               COUNT(*)                AS calls,
               COUNT(*) FILTER (WHERE policy_result = 'blocked') AS blocked,
               COALESCE(SUM(cost_eur), 0) AS cost_eur
           FROM audit_log
           WHERE agent_id = $1
             AND time > NOW() - ($2 || ' days')::INTERVAL
           GROUP BY 1
           ORDER BY 1""",
        agent_id, days,
    )

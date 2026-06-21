"""
Repozytorium nadzoru — JEDYNE miejsce z SQL dla tabeli oversight_queue.

Routery i serwisy nigdy nie składają zapytań samodzielnie; wołają te funkcje.
Funkcje zwracają surowy wynik asyncpg (Record / list[Record]) — bez konwersji.
Wszystkie wartości przekazywane jako parametry pozycyjne ($n) — brak interpolacji.
"""
from __future__ import annotations

from typing import Optional

from database import get_pool


async def fetch_pending():
    """Zadania oczekujące na decyzję recenzenta (status pending, TTL aktywny)."""
    pool = get_pool()
    return await pool.fetch(
        """SELECT oq.id, oq.agent_id, a.name AS agent_name, a.risk_level,
                  oq.task_id, oq.decision_type, oq.agent_decision,
                  oq.confidence, oq.status, oq.ttl_expires_at, oq.created_at
           FROM oversight_queue oq
           JOIN agents a ON a.id = oq.agent_id
           WHERE oq.status = 'pending'
             AND oq.ttl_expires_at > NOW()
           ORDER BY oq.created_at ASC"""
    )


async def fetch_status(oversight_id: str):
    """Pobiera id i status pojedynczego zadania nadzoru."""
    pool = get_pool()
    return await pool.fetchrow(
        "SELECT id, status FROM oversight_queue WHERE id = $1", oversight_id
    )


async def mark_review_start(oversight_id: str):
    """Zapisuje moment otwarcia zadania przez recenzenta."""
    pool = get_pool()
    return await pool.execute(
        "UPDATE oversight_queue SET review_start_at = NOW() WHERE id = $1",
        oversight_id,
    )


async def fetch_with_agent(oversight_id: str):
    """Pobiera pełny rekord zadania nadzoru wraz z nazwą agenta."""
    pool = get_pool()
    return await pool.fetchrow(
        """SELECT oq.*, a.name AS agent_name
           FROM oversight_queue oq
           JOIN agents a ON a.id = oq.agent_id
           WHERE oq.id = $1""",
        oversight_id,
    )


async def update_review_decision(
    oversight_id: str, action: str, reviewer_id, comment: Optional[str]
):
    """Zapisuje decyzję recenzenta (status/reviewer/komentarz/czas)."""
    pool = get_pool()
    return await pool.execute(
        """UPDATE oversight_queue
           SET status           = $1::oversight_status,
               reviewer_id      = $2,
               reviewer_decision= $3,
               reviewed_at      = NOW()
           WHERE id = $4""",
        action, reviewer_id, comment, oversight_id,
    )


async def fetch_history(
    days: int,
    hist_limit: int,
    status: Optional[str] = None,
    agent_id: Optional[str] = None,
):
    """
    Historia decyzji nadzorczych z filtrami.

    Buduje dynamiczne WHERE z opcjonalnych filtrów status/agent_id,
    interwał dni oraz LIMIT przekazany przez wywołującego.
    """
    pool = get_pool()
    conditions = ["oq.created_at > NOW() - ($1 || ' days')::INTERVAL"]
    params = [str(days)]
    idx = 2

    if status:
        conditions.append(f"oq.status = ${idx}::oversight_status")
        params.append(status); idx += 1
    if agent_id:
        conditions.append(f"oq.agent_id = ${idx}")
        params.append(agent_id); idx += 1

    where = " AND ".join(conditions)
    return await pool.fetch(
        f"""SELECT oq.id, oq.agent_id, a.name AS agent_name, a.risk_level,
                   oq.task_id, oq.agent_decision, oq.status,
                   oq.reviewer_id, oq.reviewer_decision,
                   oq.review_start_at, oq.reviewed_at, oq.created_at,
                   EXTRACT(EPOCH FROM (oq.reviewed_at - oq.review_start_at)) AS review_duration_s
            FROM oversight_queue oq
            JOIN agents a ON a.id = oq.agent_id
            WHERE {where}
            ORDER BY oq.created_at DESC
            LIMIT ${idx}""",
        *params, hist_limit,
    )

import json
import logging
from datetime import datetime, timezone
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from database import get_pool
from dependencies.auth import CurrentUser, get_current_user, require_role
from services import settings_service

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/oversight", tags=["oversight"])

_REVIEW_ROLES = require_role("reviewer", "partner", "associate")


class ReviewSubmit(BaseModel):
    action: Literal["approved", "rejected", "escalated"]
    comment: Optional[str] = None


@router.get("/pending")
async def list_pending(user: CurrentUser = Depends(get_current_user)):
    """Zadania oczekujące na decyzję recenzenta."""
    pool = get_pool()
    rows = await pool.fetch(
        """SELECT oq.id, oq.agent_id, a.name AS agent_name, a.risk_level,
                  oq.task_id, oq.decision_type, oq.agent_decision,
                  oq.confidence, oq.status, oq.ttl_expires_at, oq.created_at
           FROM oversight_queue oq
           JOIN agents a ON a.id = oq.agent_id
           WHERE oq.status = 'pending'
             AND oq.ttl_expires_at > NOW()
           ORDER BY oq.created_at ASC"""
    )
    return [_row_to_dict(r) for r in rows]


@router.post("/{oversight_id}/start-review")
async def start_review(oversight_id: str, user: CurrentUser = Depends(_REVIEW_ROLES)):
    """
    Oznacza moment otwarcia zadania przez recenzenta.
    Czas od tego momentu do zatwierdzenia jest mierzony
    w celu wykrycia pozornego nadzoru (< 10 sekund).
    """
    pool = get_pool()
    row = await pool.fetchrow(
        "SELECT id, status FROM oversight_queue WHERE id = $1", oversight_id
    )
    if not row:
        raise HTTPException(404, "Zadanie nadzoru nie istnieje")
    if row["status"] != "pending":
        raise HTTPException(409, f"Zadanie ma status '{row['status']}' — nie można rozpocząć przeglądu")

    await pool.execute(
        "UPDATE oversight_queue SET review_start_at = NOW() WHERE id = $1",
        oversight_id,
    )
    return {"oversight_id": oversight_id, "review_started_at": datetime.now(timezone.utc).isoformat()}


@router.post("/{oversight_id}/review")
async def submit_review(
    oversight_id: str,
    body: ReviewSubmit,
    user: CurrentUser = Depends(_REVIEW_ROLES),
):
    """
    Zatwierdź / odrzuć / eskaluj decyzję agenta.

    Mierzy czas przeglądu. Jeśli recenzent zatwierdził w mniej niż 10 sekund
    — loguje alert o potencjalnym pozornym nadzorze.
    """
    pool = get_pool()
    row = await pool.fetchrow(
        """SELECT oq.*, a.name AS agent_name
           FROM oversight_queue oq
           JOIN agents a ON a.id = oq.agent_id
           WHERE oq.id = $1""",
        oversight_id,
    )
    if not row:
        raise HTTPException(404, "Zadanie nadzoru nie istnieje")
    if row["status"] != "pending":
        raise HTTPException(409, f"Zadanie już rozpatrzone — status: {row['status']}")

    # Pomiar czasu przeglądu
    review_duration_s = None
    rubber_stamp_alert = False
    if row["review_start_at"]:
        review_duration_s = (
            datetime.now(timezone.utc) - row["review_start_at"].replace(tzinfo=timezone.utc)
        ).total_seconds()

        min_review_seconds = settings_service.get_int("oversight.min_review_seconds", 10)
        if review_duration_s < min_review_seconds and body.action == "approved":
            rubber_stamp_alert = True
            logger.warning(
                "ALERT: Pozorny nadzór wykryty! Recenzent %s zatwierdził w %.1fs (min %ds) — agent: %s",
                user.id, review_duration_s, min_review_seconds, row["agent_name"],
            )

    await pool.execute(
        """UPDATE oversight_queue
           SET status           = $1::oversight_status,
               reviewer_id      = $2,
               reviewer_decision= $3,
               reviewed_at      = NOW()
           WHERE id = $4""",
        body.action, user.id, body.comment, oversight_id,
    )

    result = {
        "oversight_id": oversight_id,
        "agent_name": row["agent_name"],
        "action": body.action,
        "reviewer_id": user.id,
        "review_duration_seconds": review_duration_s,
    }
    if rubber_stamp_alert:
        result["alert"] = (
            f"Pozorny nadzór — przegląd krótszy niż {min_review_seconds} sekund. "
            "Zdarzenie zalogowane."
        )

    return result


@router.get("/history")
async def list_history(
    days: Optional[int] = Query(None, ge=1),
    status: Optional[str] = Query(None),
    agent_id: Optional[str] = Query(None),
    user: CurrentUser = Depends(get_current_user),
):
    """Historia wszystkich decyzji nadzorczych."""
    max_days = settings_service.get_int("oversight.history_max_days", 90)
    days = min(days or max_days, max_days)
    hist_limit = settings_service.get_int("oversight.history_limit", 200)
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
    rows = await pool.fetch(
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
    return [_row_to_dict(r) for r in rows]


def _row_to_dict(row) -> dict:
    d = dict(row)
    for k, v in d.items():
        if hasattr(v, 'isoformat'):
            d[k] = v.isoformat()
    for f in ("id", "agent_id"):
        if d.get(f):
            d[f] = str(d[f])
    return d

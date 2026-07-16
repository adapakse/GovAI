import asyncio
import json
import logging

from typing import Optional

from fastapi import APIRouter, Depends, Query, WebSocket, WebSocketDisconnect
from dependencies.auth import CurrentUser, get_current_user
from repositories import dashboard_repository as dashboard_repo
from services import settings_service

logger = logging.getLogger(__name__)
router = APIRouter(tags=["dashboard"])

_redis = None


def set_redis(r) -> None:
    global _redis
    _redis = r


@router.get("/dashboard/summary")
async def dashboard_summary(
    days: Optional[int] = Query(None, ge=1),
    user: CurrentUser = Depends(get_current_user),
):
    """
    Agregaty dla pulpitu operacyjnego.
    Jeden endpoint zamiast N osobnych zapytań z frontendu.
    """
    days = days or settings_service.get_int("pagination.default_window_days", 7)
    top_n = settings_service.get_int("pagination.dashboard_top_agents", 5)
    recent_n = settings_service.get_int("pagination.dashboard_recent_blocks", 10)

    agents_stats = await dashboard_repo.agents_stats()
    call_stats = await dashboard_repo.call_stats(days)
    pending_oversight = await dashboard_repo.pending_oversight_count()
    top_agents = await dashboard_repo.top_agents(days, top_n)
    recent_blocks = await dashboard_repo.recent_blocks(days, recent_n)

    return {
        "period_days": days,
        "agents": dict(agents_stats),
        "calls": dict(call_stats),
        "pending_oversight": pending_oversight,
        "top_agents": [dict(r) for r in top_agents],
        "recent_alerts": [_row_to_dict(r) for r in recent_blocks],
    }


@router.get("/dashboard/timeline")
async def dashboard_timeline(
    hours: Optional[int] = Query(None, ge=1),
    user: CurrentUser = Depends(get_current_user),
):
    """Godzinowe zestawienie wywołań agentów (ostatnie N godzin)."""
    max_hours = settings_service.get_int("pagination.timeline_max_hours", 72)
    hours = min(hours or settings_service.get_int("pagination.timeline_default_hours", 24), max_hours)
    rows = await dashboard_repo.timeline(hours)
    return [
        {
            "hour":     row["hour"].strftime("%H:%M"),
            "total":    row["total"],
            "blocked":  row["blocked"],
            "oversight": row["oversight"],
        }
        for row in rows
    ]


@router.websocket("/ws/live-feed")
async def live_feed(websocket: WebSocket):
    """
    WebSocket stream zdarzeń real-time dla pulpitu operacyjnego.
    Subskrybuje kanały Redis: audit:new_call, audit:blocked, audit:error,
    oversight:pending, oversight:escalated.
    """
    await websocket.accept()

    if _redis is None:
        await websocket.send_json({"type": "error", "message": "Redis niedostępny"})
        await websocket.close()
        return

    pubsub = _redis.pubsub()
    await pubsub.subscribe(
        "audit:new_call", "audit:blocked", "audit:error",
        "oversight:pending", "oversight:escalated",
    )

    try:
        async for message in pubsub.listen():
            if message["type"] == "message":
                try:
                    payload = json.loads(message["data"])
                except Exception:
                    payload = {"raw": message["data"]}

                await websocket.send_json({
                    "type": message["channel"],
                    "payload": payload,
                })
    except WebSocketDisconnect:
        pass
    finally:
        await pubsub.unsubscribe()
        await pubsub.aclose()


def _row_to_dict(row) -> dict:
    d = dict(row)
    for k, v in d.items():
        if hasattr(v, 'isoformat'):
            d[k] = v.isoformat()
        elif hasattr(v, '__iter__') and not isinstance(v, (str, bytes, dict)):
            d[k] = list(v)
    return d

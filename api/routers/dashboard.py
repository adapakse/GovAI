import asyncio
import json
import logging

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, WebSocket, WebSocketDisconnect, status
from dependencies.auth import CurrentUser, authenticate_token, get_current_user
from i18n import t
from repositories import dashboard_repository as dashboard_repo
from services import settings_service
from services.block_reasons import localize_block_reason

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

    Wymaga access tokenu w query string (?token=...) — przeglądarkowy WebSocket
    nie pozwala ustawić nagłówka Authorization. Bez ważnego tokenu połączenie
    jest odrzucane przed accept (HTTP 403 przy handshake).
    """
    token = websocket.query_params.get("token")
    try:
        if not token:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
        await authenticate_token(token)
    except HTTPException:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    await websocket.accept()

    if _redis is None:
        await websocket.send_json({"type": "error", "message": t("dashboard.errors.redis_unavailable")})
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

                # Powód blokady w języku klienta WS — kod i parametry gateway
                # publikuje w payloadzie (block_reason_code / block_reason_params).
                if isinstance(payload, dict) and "block_reason" in payload:
                    payload["block_reason"] = localize_block_reason(payload.get("block_reason"), payload)

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
    metadata = d.pop("metadata", None)
    if "block_reason" in d:
        d["block_reason"] = localize_block_reason(
            d["block_reason"], metadata if isinstance(metadata, dict) else None,
        )
    for k, v in d.items():
        if hasattr(v, 'isoformat'):
            d[k] = v.isoformat()
        elif hasattr(v, '__iter__') and not isinstance(v, (str, bytes, dict)):
            d[k] = list(v)
    return d

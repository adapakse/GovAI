import asyncio
import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional
from uuid import uuid4

import redis.asyncio as aioredis

import app_settings
from config import settings
from database import platform_conn, tenant_conn
from i18n import t
from models import AgentRecord

logger = logging.getLogger(__name__)

_redis: Optional[aioredis.Redis] = None


async def init_redis() -> None:
    global _redis
    _redis = await aioredis.from_url(settings.redis_url, decode_responses=True)
    logger.info("Połączenie z Redis zainicjalizowane")


async def close_redis() -> None:
    global _redis
    if _redis:
        await _redis.aclose()


def get_redis() -> aioredis.Redis:
    if _redis is None:
        raise RuntimeError("Redis nie został zainicjalizowany")
    return _redis


def tenant_channel(tenant_id: str, channel: str) -> str:
    """Kanał Redis organizacji (subskrybuje go WebSocket API: api/routers/dashboard.py)."""
    return f"tenant:{tenant_id}:{channel}"


async def push_oversight_task(
    agent: AgentRecord,
    messages: list[dict],
    task_id: str,
    input_hash: str,
) -> str:
    """
    Tworzy zadanie nadzoru w bazie danych i publikuje zdarzenie w Redis.
    Zwraca oversight_id.
    """
    oversight_id = str(uuid4())
    ttl_seconds = app_settings.get_int("oversight.ttl_seconds", settings.oversight_ttl_seconds)
    ttl_expires_at = datetime.now(timezone.utc) + timedelta(seconds=ttl_seconds)

    # Rekonstrukcja kontekstu decyzji — ostatnia wiadomość agenta/użytkownika
    user_content = ""
    for msg in reversed(messages):
        if msg.get("role") in ("user", "human"):
            user_content = msg.get("content", "")[:500]
            break

    agent_decision = t("oversight.agentDecision", agent=agent.name, content=user_content[:200])

    if not agent.tenant_id:
        raise RuntimeError("push_oversight_task: agent bez tenant_id")
    async with tenant_conn(agent.tenant_id) as conn:
        await conn.execute(
            """
            INSERT INTO oversight_queue (
                id, agent_id, task_id, decision_type, agent_decision,
                input_hash, status, ttl_expires_at, tenant_id
            ) VALUES ($1, $2, $3, $4, $5, $6, 'pending', $7, $8)
            """,
            oversight_id,
            agent.id,
            task_id,
            t("oversight.decisionType", risk=agent.risk_level.upper()),
            agent_decision,
            input_hash,
            ttl_expires_at,
            agent.tenant_id,
        )

    # Powiadomienie dla pulpitu organizacji przez Redis pub/sub
    redis = get_redis()
    await redis.publish(
        tenant_channel(agent.tenant_id, "oversight:pending"),
        json.dumps({
            "oversight_id": oversight_id,
            "agent_id": agent.id,
            "agent_name": agent.name,
            "risk_level": agent.risk_level,
            "task_id": task_id,
            "ttl_expires_at": ttl_expires_at.isoformat(),
        }),
    )

    logger.info(
        "Zadanie nadzoru utworzone: oversight_id=%s agent=%s",
        oversight_id, agent.name,
    )
    return oversight_id


async def ttl_monitor_loop() -> None:
    """
    Pętla działająca w tle — co minutę eskaluje przeterminowane zadania.
    Uruchamiana jako asyncio.Task przy starcie aplikacji.
    """
    redis = get_redis()

    while True:
        try:
            # Zadanie platformy — ponad organizacjami; zdarzenie trafia na kanał
            # organizacji, do której należy zadanie.
            async with platform_conn() as conn:
                rows = await conn.fetch(
                    """
                    UPDATE oversight_queue
                    SET status = 'escalated'
                    WHERE status = 'pending' AND ttl_expires_at < NOW()
                    RETURNING id, agent_id, task_id, tenant_id
                    """
                )
            for row in rows:
                logger.warning(
                    "Zadanie nadzoru przeterminowane i eskalowane: id=%s tenant=%s",
                    row["id"], row["tenant_id"],
                )
                await redis.publish(
                    tenant_channel(str(row["tenant_id"]), "oversight:escalated"),
                    json.dumps({
                        "oversight_id": str(row["id"]),
                        "agent_id": str(row["agent_id"]),
                        "task_id": row["task_id"],
                    }),
                )
        except Exception:
            logger.exception("Błąd pętli monitorowania TTL")

        await asyncio.sleep(app_settings.get_int("intervals.ttl_monitor_seconds", 60))

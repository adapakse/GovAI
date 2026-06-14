import asyncpg
import logging
from contextlib import asynccontextmanager
from typing import Optional

from config import settings
from models import AgentRecord

logger = logging.getLogger(__name__)

_pool: Optional[asyncpg.Pool] = None


async def init_pool() -> None:
    global _pool
    _pool = await asyncpg.create_pool(
        dsn=settings.database_url,
        min_size=2,
        max_size=10,
        command_timeout=5,
    )
    logger.info("Pula połączeń z bazą danych zainicjalizowana")


async def close_pool() -> None:
    global _pool
    if _pool:
        await _pool.close()
        logger.info("Pula połączeń z bazą danych zamknięta")


def get_pool() -> asyncpg.Pool:
    if _pool is None:
        raise RuntimeError("Pula połączeń nie została zainicjalizowana")
    return _pool


async def get_agent(agent_id: str) -> Optional[AgentRecord]:
    pool = get_pool()
    row = await pool.fetchrow(
        """
        SELECT id, name, status, risk_level, requires_oversight, model_id,
               allowed_data_cats, owner_email, team, monthly_budget_eur, annex_iii_cat
        FROM agents
        WHERE id = $1
        """,
        agent_id,
    )
    if row is None:
        return None
    return AgentRecord(
        id=str(row["id"]),
        name=row["name"],
        status=row["status"],
        risk_level=row["risk_level"],
        requires_oversight=row["requires_oversight"],
        model_id=row["model_id"],
        allowed_data_cats=list(row["allowed_data_cats"] or []),
        owner_email=row["owner_email"],
        team=row["team"],
        monthly_budget_eur=float(row["monthly_budget_eur"] or 0),
        annex_iii_cat=row["annex_iii_cat"],
    )

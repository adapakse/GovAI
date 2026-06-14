import asyncpg
import logging
from typing import Optional

from config import settings

logger = logging.getLogger(__name__)
_pool: Optional[asyncpg.Pool] = None


async def init_pool() -> None:
    global _pool
    _pool = await asyncpg.create_pool(
        dsn=settings.database_url,
        min_size=2,
        max_size=15,
        command_timeout=10,
    )
    logger.info("Pula połączeń API zainicjalizowana")


async def close_pool() -> None:
    global _pool
    if _pool:
        await _pool.close()


def get_pool() -> asyncpg.Pool:
    if _pool is None:
        raise RuntimeError("Pula połączeń nie została zainicjalizowana")
    return _pool

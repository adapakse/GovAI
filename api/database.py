import asyncpg
import json as _json
import logging
from typing import Optional

from config import settings

logger = logging.getLogger(__name__)
_pool: Optional[asyncpg.Pool] = None


async def _init_connection(conn: asyncpg.Connection) -> None:
    """Rejestruje kodeki JSON/JSONB — asyncpg domyślnie zwraca je jako string."""
    await conn.set_type_codec('json',  encoder=_json.dumps, decoder=_json.loads, schema='pg_catalog')
    await conn.set_type_codec('jsonb', encoder=_json.dumps, decoder=_json.loads, schema='pg_catalog')


async def init_pool() -> None:
    global _pool
    _pool = await asyncpg.create_pool(
        dsn=settings.database_url,
        min_size=2,
        max_size=15,
        command_timeout=10,
        init=_init_connection,
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

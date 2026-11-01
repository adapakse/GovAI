"""
Dostęp do bazy z izolacją organizacji (multitenancy, migracja 015).

Każde zapytanie aplikacji idzie przez połączenie z ustawionym kontekstem —
Row Level Security w Postgresie sam ogranicza dane do jednej organizacji
i sam wpisuje tenant_id przy INSERT (DEFAULT current_tenant_id()):

    async with tenant_db(tenant_id):   # dane jednej organizacji
        ...
    async with platform_db():          # logowanie, super-admin, zadania tła
        ...

W żądaniach HTTP kontekst organizacji otwiera zależność uwierzytelniania
(dependencies/auth.py: get_current_user) — transakcja na całe żądanie.

get_pool() zwraca obiekt z tym samym interfejsem co asyncpg.Pool (fetch,
fetchrow, fetchval, execute, executemany, acquire), ale działający na połączeniu
bieżącego kontekstu. Poza kontekstem rzuca błąd — brak kontekstu nigdy nie
oznacza "wszystkie organizacje" (fail closed).
"""
from __future__ import annotations

import json as _json
import logging
from contextlib import asynccontextmanager
from contextvars import ContextVar
from typing import AsyncIterator, Optional

import asyncpg

from config import settings

logger = logging.getLogger(__name__)
_pool: Optional[asyncpg.Pool] = None
_current_conn: ContextVar[Optional[asyncpg.Connection]] = ContextVar("govai_db_conn", default=None)
_current_tenant: ContextVar[Optional[str]] = ContextVar("govai_tenant_id", default=None)


async def _init_connection(conn: asyncpg.Connection) -> None:
    """Rejestruje kodeki JSON/JSONB — asyncpg domyślnie zwraca je jako string."""
    await conn.set_type_codec('json',  encoder=_json.dumps, decoder=_json.loads, schema='pg_catalog')
    await conn.set_type_codec('jsonb', encoder=_json.dumps, decoder=_json.loads, schema='pg_catalog')


async def init_pool() -> None:
    global _pool
    _pool = await asyncpg.create_pool(
        dsn=settings.database_url,
        min_size=2,
        max_size=20,
        # Raporty z narracją LLM trzymają połączenie (transakcja żądania) dłużej
        # niż zwykłe zapytanie — limit dotyczy pojedynczego polecenia SQL.
        command_timeout=30,
        init=_init_connection,
    )
    logger.info("Pula połączeń API zainicjalizowana")


async def close_pool() -> None:
    global _pool
    if _pool:
        await _pool.close()


def raw_pool() -> asyncpg.Pool:
    """Surowa pula — tylko do health checku (SELECT 1). Dane: tenant_db/platform_db."""
    if _pool is None:
        raise RuntimeError("Pula połączeń nie została zainicjalizowana")
    return _pool


def current_tenant_id() -> Optional[str]:
    """Organizacja bieżącego kontekstu (None w trybie platformy / poza kontekstem)."""
    return _current_tenant.get()


@asynccontextmanager
async def _context(setting: str, value: str, tenant_id: Optional[str]) -> AsyncIterator[asyncpg.Connection]:
    # Zawsze osobne połączenie i transakcja — także przy zagnieżdżeniu (np.
    # platform_db wewnątrz żądania organizacji), żeby nie mieszać kontekstów RLS.
    async with raw_pool().acquire() as conn:
        async with conn.transaction():
            await conn.execute("SELECT set_config($1, $2, true)", setting, value)
            conn_token = _current_conn.set(conn)
            tenant_token = _current_tenant.set(tenant_id)
            try:
                yield conn
            finally:
                _current_conn.reset(conn_token)
                _current_tenant.reset(tenant_token)


def tenant_db(tenant_id: str):
    """Transakcja w kontekście jednej organizacji (RLS: app.tenant_id)."""
    return _context("app.tenant_id", str(tenant_id), str(tenant_id))


def platform_db():
    """Transakcja w trybie platformy (RLS: app.platform) — ponad organizacjami.
    Tylko dla logowania, panelu super-admina i zadań tła."""
    return _context("app.platform", "on", None)


class _ContextPool:
    """Interfejs asyncpg.Pool na połączeniu bieżącego kontekstu."""

    @staticmethod
    def _conn() -> asyncpg.Connection:
        conn = _current_conn.get()
        if conn is None:
            raise RuntimeError("Zapytanie poza kontekstem organizacji/platformy (tenant_db/platform_db)")
        return conn

    async def fetch(self, *args, **kwargs):
        return await self._conn().fetch(*args, **kwargs)

    async def fetchrow(self, *args, **kwargs):
        return await self._conn().fetchrow(*args, **kwargs)

    async def fetchval(self, *args, **kwargs):
        return await self._conn().fetchval(*args, **kwargs)

    async def execute(self, *args, **kwargs):
        return await self._conn().execute(*args, **kwargs)

    async def executemany(self, *args, **kwargs):
        return await self._conn().executemany(*args, **kwargs)

    @asynccontextmanager
    async def acquire(self) -> AsyncIterator[asyncpg.Connection]:
        # Repozytoria robią `async with pool.acquire() as conn: async with
        # conn.transaction()` — w kontekście to samo połączenie, a transakcja
        # staje się savepointem w transakcji żądania.
        yield self._conn()


_context_pool = _ContextPool()


def get_pool() -> _ContextPool:
    if _pool is None:
        raise RuntimeError("Pula połączeń nie została zainicjalizowana")
    return _context_pool

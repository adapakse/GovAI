"""
Dostęp do bazy bramki z izolacją organizacji (multitenancy, migracja 015).

Bramka łączy się jako govai_app (bez BYPASSRLS) — bez kontekstu RLS nie widzi
żadnych danych organizacji. Każda operacja idzie przez krótki kontekst:
    async with tenant_conn(tenant_id) as conn:   # dane jednej organizacji
        ...
    async with platform_conn() as conn:          # wyszukanie klucza API, pętla TTL, cache
        ...
Konteksty są celowo krótkie (pojedyncza operacja) — bramka nie trzyma połączenia
przez wywołanie modelu LLM, a zapisy w tle (audit_logger) otwierają własny kontekst
z jawnym tenant_id.
"""
from __future__ import annotations

import json as _json
import logging
from contextlib import asynccontextmanager
from contextvars import ContextVar
from typing import AsyncIterator, Optional
from uuid import UUID

import asyncpg

from config import settings
from models import AgentRecord, ProviderRecord

logger = logging.getLogger(__name__)

_pool: Optional[asyncpg.Pool] = None

# Organizacja bieżącego żądania (ustawia AuthMiddleware) — dla parametrów per
# organizacja (app_settings). Poza żądaniem None → wartości domyślne platformy.
_request_tenant: ContextVar[Optional[str]] = ContextVar("govai_gateway_tenant_id", default=None)


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


def raw_pool() -> asyncpg.Pool:
    """Surowa pula — tylko do health checku (SELECT 1). Dane: tenant_conn/platform_conn."""
    if _pool is None:
        raise RuntimeError("Pula połączeń nie została zainicjalizowana")
    return _pool


def set_request_tenant(tenant_id: Optional[str]) -> None:
    _request_tenant.set(tenant_id)


def request_tenant_id() -> Optional[str]:
    """Organizacja bieżącego żądania (None poza żądaniem)."""
    return _request_tenant.get()


def is_uuid(value: object) -> bool:
    try:
        UUID(str(value))
        return True
    except (TypeError, ValueError):
        return False


@asynccontextmanager
async def _context(setting: str, value: str) -> AsyncIterator[asyncpg.Connection]:
    async with raw_pool().acquire() as conn:
        async with conn.transaction():
            await conn.execute("SELECT set_config($1, $2, true)", setting, value)
            yield conn


def tenant_conn(tenant_id: str):
    """Połączenie + transakcja w kontekście jednej organizacji (RLS: app.tenant_id)."""
    if not tenant_id or not is_uuid(tenant_id):
        # Fail closed — brak organizacji nigdy nie oznacza "wszystkie organizacje".
        raise RuntimeError(f"tenant_conn: nieprawidłowy tenant_id {tenant_id!r}")
    return _context("app.tenant_id", str(tenant_id))


def platform_conn():
    """Połączenie + transakcja w trybie platformy (RLS: app.platform) — ponad
    organizacjami. Tylko: wyszukanie klucza API, ładowanie cache, pętla TTL."""
    return _context("app.platform", "on")


async def fetch_tenant_status(tenant_id: str) -> Optional[dict]:
    """Status organizacji (None = nie istnieje). Organizacja widzi samą siebie."""
    async with tenant_conn(tenant_id) as conn:
        row = await conn.fetchrow(
            "SELECT status, deleted_at FROM tenants WHERE id = $1", tenant_id,
        )
    if row is None:
        return None
    return {"status": row["status"], "deleted": row["deleted_at"] is not None}


async def fetch_active_policies(tenant_id: str) -> list[dict]:
    """Aktywne reguły polityk JEDNEJ organizacji (filtr + RLS)."""
    async with tenant_conn(tenant_id) as conn:
        rows = await conn.fetch(
            """SELECT policy_code, rule_type, condition_json::text, action_json::text, priority, name
               FROM policies
               WHERE active = true AND tenant_id = $1
               ORDER BY priority ASC""",
            tenant_id,
        )
    return [
        {
            "policy_code":    row["policy_code"],
            "rule_type":      row["rule_type"],
            "condition_json": _json.loads(row["condition_json"]) if row["condition_json"] else {},
            "action_json":    _json.loads(row["action_json"])    if row["action_json"]    else {},
            "priority":       row["priority"],
            "name":           row["name"],
        }
        for row in rows
    ]


_SENSITIVITY_ORDER = {
    'public':       0,
    'internal':     1,
    'confidential': 2,
    'privileged':   3,
}


async def get_providers_for_sensitivity(tenant_id: str, sensitivity_level: str) -> list[ProviderRecord]:
    """Zwraca aktywnych, zdrowych providerów (platformy + własnych organizacji)
    obsługujących wymagany poziom wrażliwości."""
    required_order = _SENSITIVITY_ORDER.get(sensitivity_level, 0)
    # TODO(etap 4): providerzy organizacji z własnym kluczem (providers.api_key_encrypted)
    # — odszyfrowanie kluczem z Key Vault i przekazanie do LiteLLM. Na razie klucze
    # wyłącznie z api_key_env (biała lista kluczy platformy, zob. models.ProviderRecord).
    async with tenant_conn(tenant_id) as conn:
        rows = await conn.fetch(
            """
            SELECT id, name, provider_type, model_ids, base_url,
                   api_key_env, max_data_sensitivity, priority
            FROM providers
            WHERE active = true AND is_healthy = true
              AND (tenant_id IS NULL OR tenant_id = $1)
            ORDER BY priority ASC
            """,
            tenant_id,
        )
    result = []
    for row in rows:
        provider_max = row['max_data_sensitivity']
        if _SENSITIVITY_ORDER.get(provider_max, -1) >= required_order:
            result.append(ProviderRecord(
                id=str(row['id']),
                name=row['name'],
                provider_type=row['provider_type'],
                model_ids=list(row['model_ids'] or []),
                base_url=row['base_url'],
                api_key_env=row['api_key_env'],
                max_data_sensitivity=provider_max,
                priority=row['priority'],
            ))
    return result


async def get_agent(tenant_id: str, agent_id: str) -> Optional[AgentRecord]:
    """Agent z rejestru organizacji — agent innej organizacji = None (nieznany)."""
    if not is_uuid(agent_id):
        return None
    async with tenant_conn(tenant_id) as conn:
        row = await conn.fetchrow(
            """
            SELECT id, name, status, risk_level, requires_oversight, model_id,
                   allowed_data_cats, owner_email, team, monthly_budget_eur, annex_iii_cat,
                   tenant_id
            FROM agents
            WHERE id = $1 AND tenant_id = $2
            """,
            agent_id,
            tenant_id,
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
        tenant_id=str(row["tenant_id"]),
    )

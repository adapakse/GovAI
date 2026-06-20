import asyncpg
import logging
from contextlib import asynccontextmanager
from typing import Optional

from config import settings
from models import AgentRecord, ProviderRecord

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


async def fetch_active_policies() -> list[dict]:
    """Pobiera aktywne reguły blokujące z DB dla silnika polityk."""
    import json as _json
    pool = get_pool()
    rows = await pool.fetch(
        """SELECT policy_code, rule_type, condition_json::text, action_json::text, priority, name
           FROM policies
           WHERE active = true
           ORDER BY priority ASC"""
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


async def get_providers_for_sensitivity(sensitivity_level: str) -> list[ProviderRecord]:
    """Zwraca aktywnych, zdrowych providerów obsługujących wymagany poziom wrażliwości."""
    required_order = _SENSITIVITY_ORDER.get(sensitivity_level, 0)
    pool = get_pool()
    rows = await pool.fetch(
        """
        SELECT id, name, provider_type, model_ids, base_url,
               api_key_env, max_data_sensitivity, priority
        FROM providers
        WHERE active = true AND is_healthy = true
        ORDER BY priority ASC
        """
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

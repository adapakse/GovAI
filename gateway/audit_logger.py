import asyncio
import json
import logging
from typing import Optional

from database import get_pool
from models import AuditEntry
from oversight import get_redis

logger = logging.getLogger(__name__)

# policy_result → kanał Redis pub/sub, którego słucha dashboard (GET /ws/live-feed).
# Mapowane po policy_result (allowed/blocked/error), NIE po event_type — event_type ma
# kilka wariantów per wynik (np. "blocked" to zarówno naruszenie polityki, jak i
# unknown_agent/agent_inactive; "error" to zarówno no_eligible_provider, jak i llm_error)
# i osobne mapowanie po event_type po cichu gubiło nowe warianty w live-feedzie.
# 'oversight_required' pomijamy — to zdarzenie publikuje już push_oversight_task
# na kanale 'oversight:pending', drugi wpis byłby duplikatem w live-feedzie.
_LIVE_FEED_CHANNEL = {
    "allowed": "audit:new_call",
    "blocked": "audit:blocked",
    "error":   "audit:error",
}

_INSERT_SQL = """
INSERT INTO audit_log (
    time, agent_id, agent_name, task_id, call_id, event_type,
    policy_result, policy_id, pii_categories, pii_count,
    input_hash, output_hash, model_used, latency_ms,
    tokens_in, tokens_out, cost_eur, block_reason, metadata,
    data_sensitivity, provider_id
) VALUES (
    NOW(), $1, $2, $3, $4, $5,
    $6, $7, $8, $9,
    $10, $11, $12, $13,
    $14, $15, $16, $17, $18,
    $19::data_sensitivity_level, $20
)
"""


async def write_audit(entry: AuditEntry) -> None:
    """Zapisuje wpis do dziennika audytowego asynchronicznie."""
    try:
        pool = get_pool()
        await pool.execute(
            _INSERT_SQL,
            entry.agent_id,
            entry.agent_name,
            entry.task_id,
            entry.call_id,
            entry.event_type,
            entry.policy_result,
            entry.policy_id,
            entry.pii_categories,
            entry.pii_count,
            entry.input_hash,
            entry.output_hash,
            entry.model_used,
            entry.latency_ms,
            entry.tokens_in,
            entry.tokens_out,
            entry.cost_eur,
            entry.block_reason,
            json.dumps(entry.metadata) if entry.metadata is not None else None,
            entry.data_sensitivity,
            entry.provider_id,
        )

        channel = _LIVE_FEED_CHANNEL.get(entry.policy_result)
        if channel:
            await get_redis().publish(
                channel,
                json.dumps({
                    "agent_id": entry.agent_id,
                    "agent_name": entry.agent_name,
                    "task_id": entry.task_id,
                    "call_id": entry.call_id,
                    "policy_id": entry.policy_id,
                    "block_reason": entry.block_reason,
                    "model_used": entry.model_used,
                    "cost_eur": entry.cost_eur,
                    "latency_ms": entry.latency_ms,
                }),
            )
    except Exception:
        # Błąd audytu nie może blokować odpowiedzi — logujemy i kontynuujemy
        logger.exception("Błąd zapisu do dziennika audytowego dla call_id=%s", entry.call_id)


def write_audit_fire_and_forget(entry: AuditEntry) -> None:
    """Uruchamia zapis audytu w tle — nie blokuje ścieżki odpowiedzi."""
    asyncio.create_task(write_audit(entry))

import asyncio
import json
import logging

from database import tenant_conn
from models import AuditEntry
from oversight import get_redis, tenant_channel

logger = logging.getLogger(__name__)

# policy_result → kanał Redis pub/sub, którego słucha dashboard (GET /ws/live-feed).
# Mapowane po policy_result (allowed/blocked/error), NIE po event_type — event_type ma
# kilka wariantów per wynik (np. "blocked" to zarówno naruszenie polityki, jak i
# unknown_agent/agent_inactive; "error" to zarówno no_eligible_provider, jak i llm_error)
# i osobne mapowanie po event_type po cichu gubiło nowe warianty w live-feedzie.
# 'oversight_required' pomijamy — to zdarzenie publikuje już push_oversight_task
# na kanale 'oversight:pending', drugi wpis byłby duplikatem w live-feedzie.
# Kanały są per organizacja: tenant:{tenant_id}:<kanał> (oversight.tenant_channel).
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
    data_sensitivity, provider_id, tenant_id
) VALUES (
    NOW(), $1, $2, $3, $4, $5,
    $6, $7, $8, $9,
    $10, $11, $12, $13,
    $14, $15, $16, $17, $18,
    $19::data_sensitivity_level, $20, $21
)
"""


async def write_audit(entry: AuditEntry) -> None:
    """Zapisuje wpis do dziennika audytowego organizacji entry.tenant_id.
    Własny, krótki kontekst bazy — bezpieczne także jako zadanie w tle."""
    if not entry.tenant_id:
        # Fail closed: wpis bez organizacji nie trafia do żadnej (ani do "wspólnej") puli.
        logger.error("Wpis audytu bez tenant_id — pominięty (call_id=%s)", entry.call_id)
        return
    try:
        metadata = dict(entry.metadata) if entry.metadata is not None else {}
        if entry.block_reason_code:
            metadata["block_reason_code"] = entry.block_reason_code
            metadata["block_reason_params"] = entry.block_reason_params or {}

        async with tenant_conn(entry.tenant_id) as conn:
            await conn.execute(
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
                # Pula bramki nie ma kodeka jsonb (zob. app_settings.py) — tu tekst JSON.
                json.dumps(metadata),
                entry.data_sensitivity,
                entry.provider_id,
                entry.tenant_id,
            )

        channel = _LIVE_FEED_CHANNEL.get(entry.policy_result)
        if channel:
            await get_redis().publish(
                tenant_channel(entry.tenant_id, channel),
                json.dumps({
                    "agent_id": entry.agent_id,
                    "agent_name": entry.agent_name,
                    "task_id": entry.task_id,
                    "call_id": entry.call_id,
                    "policy_id": entry.policy_id,
                    "block_reason": entry.block_reason,
                    "block_reason_code": entry.block_reason_code,
                    "block_reason_params": entry.block_reason_params or {},
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

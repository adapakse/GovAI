import asyncio
import logging
from typing import Optional

from database import get_pool
from models import AuditEntry

logger = logging.getLogger(__name__)

_INSERT_SQL = """
INSERT INTO audit_log (
    time, agent_id, agent_name, task_id, call_id, event_type,
    policy_result, policy_id, pii_categories, pii_count,
    input_hash, output_hash, model_used, latency_ms,
    tokens_in, tokens_out, cost_eur, block_reason, metadata
) VALUES (
    NOW(), $1, $2, $3, $4, $5,
    $6, $7, $8, $9,
    $10, $11, $12, $13,
    $14, $15, $16, $17, $18
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
            str(entry.metadata),
        )
    except Exception:
        # Błąd audytu nie może blokować odpowiedzi — logujemy i kontynuujemy
        logger.exception("Błąd zapisu do dziennika audytowego dla call_id=%s", entry.call_id)


def write_audit_fire_and_forget(entry: AuditEntry) -> None:
    """Uruchamia zapis audytu w tle — nie blokuje ścieżki odpowiedzi."""
    asyncio.create_task(write_audit(entry))

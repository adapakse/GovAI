import hashlib
import logging
import time
from typing import Any
from uuid import uuid4

import litellm
from fastapi import HTTPException, Request

from audit_logger import write_audit_fire_and_forget
from database import get_agent
from models import AgentRecord, AuditEntry, PIIScanResult, PolicyDecision
from oversight import push_oversight_task
from pii_scanner import PIIScanner
from policy_engine import PolicyEngine

logger = logging.getLogger(__name__)

_pii_scanner: PIIScanner | None = None
_policy_engine: PolicyEngine | None = None


def init_components(pii: PIIScanner, policy: PolicyEngine) -> None:
    global _pii_scanner, _policy_engine
    _pii_scanner = pii
    _policy_engine = policy


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:16]


def _estimate_cost(model: str, tokens_in: int, tokens_out: int) -> float:
    """Przybliżony koszt w EUR na podstawie liczby tokenów."""
    rates = {
        "claude-haiku-4-5-20251001": (0.00025, 0.00125),
        "claude-sonnet-4-6": (0.003, 0.015),
        "claude-opus-4-8": (0.015, 0.075),
    }
    rate_in, rate_out = rates.get(model, (0.003, 0.015))
    usd = (tokens_in / 1000) * rate_in + (tokens_out / 1000) * rate_out
    return round(usd * 0.93, 8)  # przeliczenie USD → EUR (kurs uproszczony)


async def handle_chat_completion(request: Request) -> dict[str, Any]:
    """
    Główna ścieżka bramki — każde wywołanie agenta przechodzi tu.

    Kolejność sprawdzeń:
    1. Weryfikacja agenta (rejestr)
    2. Skan PII wejścia (Presidio)
    3. Ocena polityk (reguły)
    4. Wywołanie modelu LLM (LiteLLM) lub kolejka nadzoru
    5. Skan PII wyjścia
    6. Zapis do dziennika audytowego (asynchroniczny)
    """
    call_id = str(uuid4())
    task_id = request.headers.get("X-Task-ID", str(uuid4()))
    agent_id = request.headers.get("X-Agent-ID", "")

    if not agent_id:
        raise HTTPException(status_code=400, detail="Brak nagłówka X-Agent-ID")

    body = await request.json()
    messages = body.get("messages", [])

    if not messages:
        raise HTTPException(status_code=400, detail="Brak wiadomości w żądaniu")

    # ── 1. Weryfikacja agenta ──────────────────────────────────────────────
    agent = await get_agent(agent_id)

    if agent is None:
        logger.warning("Nieznany agent: %s", agent_id)
        raise HTTPException(
            status_code=403,
            detail=f"Agent '{agent_id}' nie jest zarejestrowany w GovAI. "
                   "Zarejestruj agenta przed użyciem bramki.",
        )

    if agent.status != "active":
        logger.warning("Agent %s ma status: %s", agent.name, agent.status)
        raise HTTPException(
            status_code=403,
            detail=f"Agent '{agent.name}' ma status '{agent.status}' i nie może wykonywać wywołań.",
        )

    # ── 2. Skan PII ────────────────────────────────────────────────────────
    pii_result: PIIScanResult = _pii_scanner.scan(messages)
    input_hash = _hash(str(messages))

    if pii_result.has_pii:
        logger.info(
            "PII wykryte dla agenta %s: %s (%d encji)",
            agent.name, pii_result.pii_categories, pii_result.pii_count,
        )

    # Używamy oczyszczonych wiadomości w dalszym potoku
    clean_messages = pii_result.redacted_messages

    # ── 3. Ocena polityk ───────────────────────────────────────────────────
    decision: PolicyDecision = _policy_engine.evaluate(agent, clean_messages, pii_result)

    if decision.result == "blocked":
        write_audit_fire_and_forget(AuditEntry(
            agent_id=agent.id,
            agent_name=agent.name,
            task_id=task_id,
            call_id=call_id,
            event_type="blocked",
            policy_result="blocked",
            policy_id=decision.policy_id,
            pii_categories=pii_result.pii_categories,
            pii_count=pii_result.pii_count,
            input_hash=input_hash,
            model_used=agent.model_id,
            block_reason=decision.reason,
        ))
        raise HTTPException(
            status_code=403,
            detail={
                "error": "call_blocked",
                "reason": decision.reason,
                "policy_id": decision.policy_id,
                "agent": agent.name,
                "call_id": call_id,
            },
        )

    if decision.result == "oversight_required":
        oversight_id = await push_oversight_task(agent, clean_messages, task_id, input_hash)

        write_audit_fire_and_forget(AuditEntry(
            agent_id=agent.id,
            agent_name=agent.name,
            task_id=task_id,
            call_id=call_id,
            event_type="oversight_required",
            policy_result="oversight_required",
            policy_id=decision.policy_id,
            pii_categories=pii_result.pii_categories,
            pii_count=pii_result.pii_count,
            input_hash=input_hash,
            model_used=agent.model_id,
            metadata={"oversight_id": oversight_id},
        ))

        return {
            "status": "awaiting_oversight",
            "oversight_id": oversight_id,
            "message": (
                f"Wywołanie agenta '{agent.name}' zostało wstrzymane — "
                "wymagane zatwierdzenie przez recenzenta zgodnie z EU AI Act."
            ),
            "call_id": call_id,
            "task_id": task_id,
        }

    # ── 4. Wywołanie modelu LLM ────────────────────────────────────────────
    t0 = time.monotonic()

    try:
        response = await litellm.acompletion(
            model=agent.model_id,
            messages=clean_messages,
            temperature=body.get("temperature", 0.7),
            max_tokens=body.get("max_tokens", 1024),
        )
    except Exception as exc:
        logger.exception("Błąd wywołania LLM dla agenta %s", agent.name)
        raise HTTPException(status_code=502, detail=f"Błąd modelu językowego: {exc}") from exc

    latency_ms = int((time.monotonic() - t0) * 1000)

    # ── 5. Skan PII w odpowiedzi ───────────────────────────────────────────
    response_text = response.choices[0].message.content or ""
    output_pii = _pii_scanner.scan_text(response_text)
    output_hash = _hash(response_text)

    if output_pii:
        logger.warning(
            "PII wykryte w ODPOWIEDZI agenta %s: %s — odpowiedź wymaga przeglądu",
            agent.name, output_pii,
        )

    usage = getattr(response, "usage", None)
    tokens_in = getattr(usage, "prompt_tokens", None)
    tokens_out = getattr(usage, "completion_tokens", None)
    cost_eur = _estimate_cost(agent.model_id, tokens_in or 0, tokens_out or 0)

    # ── 6. Dziennik audytowy ───────────────────────────────────────────────
    write_audit_fire_and_forget(AuditEntry(
        agent_id=agent.id,
        agent_name=agent.name,
        task_id=task_id,
        call_id=call_id,
        event_type="call_completed",
        policy_result="allowed",
        pii_categories=pii_result.pii_categories,
        pii_count=pii_result.pii_count,
        input_hash=input_hash,
        output_hash=output_hash,
        model_used=agent.model_id,
        latency_ms=latency_ms,
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        cost_eur=cost_eur,
        metadata={"output_pii": output_pii},
    ))

    return response.model_dump()

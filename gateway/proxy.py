import hashlib
import logging
import time
from typing import Any, Optional
from uuid import uuid4

import litellm
from fastapi import HTTPException, Request

import app_settings
from audit_logger import write_audit_fire_and_forget
from config import settings
from database import get_agent
from i18n import t
from models import AgentRecord, AuditEntry, PIIScanResult, PolicyDecision, ProviderRecord
from oversight import push_oversight_task
from pii_scanner import PIIScanner
from policy_engine import PolicyEngine
from services.data_sensitivity import DataSensitivityClassifier
from services.provider_selector import select_provider

logger = logging.getLogger(__name__)

_pii_scanner: PIIScanner | None = None
_policy_engine: PolicyEngine | None = None
_sensitivity_classifier: DataSensitivityClassifier = DataSensitivityClassifier()

# ── Tryb demo — gotowe odpowiedzi bez wywoływania Anthropic ───────────────────
# agent_id → klucz tekstu w gateway/i18n/locales/<locale>/demo.json
_DEMO_RESPONSE_KEYS: dict[str, str] = {
    "a1000000-0000-0000-0000-000000000001": "demo.responses.customerService",  # Obsługa Klienta
    "a2000000-0000-0000-0000-000000000002": "demo.responses.creditScoring",    # Ocena Kredytowa
    "a3000000-0000-0000-0000-000000000003": "demo.responses.recruitment",      # Rekrutacja
}


def _demo_response(agent_id: str, messages: list[dict]) -> str:
    """Zwraca gotową odpowiedź dla trybu demo (w języku żądania)."""
    if agent_id in _DEMO_RESPONSE_KEYS:
        return t(_DEMO_RESPONSE_KEYS[agent_id])
    system = next((m.get("content", "") for m in messages if m.get("role") == "system"), "")
    if any(k in system.lower() for k in ["kredyt", "ocena", "wniosek"]):
        return t("demo.responses.creditScoring")
    if any(k in system.lower() for k in ["cv", "rekrut", "kandydat"]):
        return t("demo.responses.recruitment")
    return t("demo.responses.generic")


def init_components(pii: PIIScanner, policy: PolicyEngine) -> None:
    global _pii_scanner, _policy_engine
    _pii_scanner = pii
    _policy_engine = policy


def _block_reason(code: str, **params: Any) -> dict[str, Any]:
    """Pola AuditEntry dla powodu blokady/błędu: tekst (block_reason, dla zgodności
    wstecznej, w języku żądania) + kod i parametry, z których API tłumaczy powód
    na język czytającego (api/services/block_reasons.py)."""
    params = {k: str(v) for k, v in params.items()}
    return {
        "block_reason": t(f"blockReasons.{code}", **params),
        "block_reason_code": code,
        "block_reason_params": params,
    }


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:16]


_DEFAULT_RATES = {
    "claude-haiku-4-5-20251001": [0.00025, 0.00125],
    "claude-sonnet-4-6":         [0.003,   0.015],
    "claude-opus-4-8":           [0.015,   0.075],
    "gpt-4o":                    [0.005,   0.015],
    "gpt-4o-mini":               [0.00015, 0.0006],
    "deepseek-chat":             [0.00014, 0.00028],
}


def _estimate_cost(model: str, tokens_in: int, tokens_out: int) -> float:
    """Przybliżony koszt w EUR — stawki i kurs z parametrów (app_settings)."""
    rates = app_settings.get_json("pricing.model_rates", _DEFAULT_RATES)
    default_rate = app_settings.get_json("pricing.default_rate", [0.003, 0.015])
    usd_to_eur = app_settings.get_number("pricing.usd_to_eur", 0.93)

    rate_in, rate_out = rates.get(model, default_rate)
    usd = (tokens_in / 1000) * rate_in + (tokens_out / 1000) * rate_out
    return round(usd * usd_to_eur, 8)



# provider_type → prefiks wymagany przez LiteLLM (custom_llm_provider), żeby
# jawnie wskazać dostawcę zamiast polegać na jego statycznym rejestrze nazw
# modeli — ten rejestr NIE zna np. "claude-haiku-4-5-20251001"/"claude-sonnet-4-6"
# (modele nowsze niż wydanie zainstalowanej wersji litellm), więc bez prefiksu
# rzuca "LLM Provider NOT provided".
_LITELLM_PREFIX = {
    "anthropic": "anthropic",
    "openai":    "openai",
    "deepseek":  "deepseek",
    "google":    "gemini",
    "bielik":    "ollama",
}


def _build_litellm_model(provider: ProviderRecord, preferred_model: str) -> str:
    """
    Buduje identyfikator modelu dla LiteLLM z uwzględnieniem providera.
    Zawsze jawny prefiks custom_llm_provider — nigdy bez, nawet dla dostawców
    "standardowych" (Anthropic/OpenAI/DeepSeek/Google), bo LiteLLM inaczej
    próbuje zgadywać dostawcę po nazwie modelu z własnego statycznego rejestru.
    """
    model_name = preferred_model if preferred_model in provider.model_ids else (
        provider.model_ids[0] if provider.model_ids else preferred_model
    )
    if provider.provider_type in ('ollama', 'bielik'):
        return f"ollama/{model_name}"
    if provider.provider_type in ('vllm', 'custom') and provider.base_url:
        return f"openai/{model_name}"
    prefix = _LITELLM_PREFIX.get(provider.provider_type)
    return f"{prefix}/{model_name}" if prefix else model_name


async def handle_chat_completion(request: Request) -> dict[str, Any]:
    """
    Główna ścieżka bramki — każde wywołanie agenta przechodzi tu.

    Kolejność sprawdzeń:
    1. Weryfikacja agenta (rejestr)
    2. Skan PII wejścia (Presidio)
    3. Ocena polityk (reguły) — blocked/oversight_required kończą tu, PRZED wyborem
       providera (decyzja polityki musi wygrywać z awarią routingu, nie odwrotnie)
    3.5. Klasyfikacja wrażliwości danych
    3.6. Wybór providera LLM — tylko dla zapytań "allowed"
    4. Wywołanie modelu LLM (LiteLLM) lub kolejka nadzoru
    5. Skan PII wyjścia
    6. Zapis do dziennika audytowego (asynchroniczny)
    """
    call_id = str(uuid4())
    task_id = request.headers.get("X-Task-ID", str(uuid4()))
    agent_id = request.headers.get("X-Agent-ID", "")

    if not agent_id:
        raise HTTPException(status_code=400, detail=t("errors.missingAgentId"))

    body = await request.json()
    messages = body.get("messages", [])

    if not messages:
        raise HTTPException(status_code=400, detail=t("errors.missingMessages"))

    # ── 1. Weryfikacja agenta ──────────────────────────────────────────────────
    agent = await get_agent(agent_id)

    if agent is None:
        logger.warning("Nieznany agent: %s", agent_id)
        write_audit_fire_and_forget(AuditEntry(
            agent_id=agent_id,
            agent_name=t("audit.unknownAgentName"),
            task_id=task_id,
            call_id=call_id,
            event_type="unknown_agent",
            policy_result="blocked",
            pii_categories=[],
            pii_count=0,
            input_hash=None,
            model_used=None,
            **_block_reason("unknown_agent", agent_id=agent_id),
        ))
        raise HTTPException(
            status_code=403,
            detail=t("errors.agentNotRegistered", agent_id=agent_id),
        )

    if agent.status != "active":
        logger.warning("Agent %s ma status: %s", agent.name, agent.status)
        write_audit_fire_and_forget(AuditEntry(
            agent_id=agent.id,
            agent_name=agent.name,
            task_id=task_id,
            call_id=call_id,
            event_type="agent_inactive",
            policy_result="blocked",
            pii_categories=[],
            pii_count=0,
            input_hash=None,
            model_used=agent.model_id,
            **_block_reason("agent_inactive", status=agent.status),
        ))
        raise HTTPException(
            status_code=403,
            detail=t("errors.agentInactive", agent=agent.name, status=agent.status),
        )

    # ── 2. Skan PII ────────────────────────────────────────────────────────────
    pii_result: PIIScanResult = _pii_scanner.scan(messages)
    input_hash = _hash(str(messages))

    if pii_result.has_pii:
        logger.info(
            "PII wykryte dla agenta %s: %s (%d encji)",
            agent.name, pii_result.pii_categories, pii_result.pii_count,
        )

    clean_messages = pii_result.redacted_messages

    # ── 3. Ocena polityk ────────────────────────────────────────────────────────
    decision: PolicyDecision = _policy_engine.evaluate(agent, clean_messages, pii_result)

    # ── 3.5. Klasyfikacja wrażliwości danych ────────────────────────────────────
    sensitivity = _sensitivity_classifier.classify(clean_messages)
    logger.info(
        "Wrażliwość danych dla agenta %s: %s (powody: %s)",
        agent.name, sensitivity.level,
        ', '.join(sensitivity.reasons[:3]) if sensitivity.reasons else 'brak',
    )

    # ── Obsługa zablokowania ─────────────────────────────────────────────────────
    # Sprawdzane PRZED wyborem providera (3.6) celowo: decyzja polityki musi zawsze
    # wygrywać z awarią routingu. Wcześniej wybór providera wykonywał się jako pierwszy
    # i przy braku providera dla danego poziomu wrażliwości rzucał 503 ZANIM w ogóle
    # sprawdzono decision.result — więc zapytanie, które powinno dostać 403 "Zablokowane",
    # czasem kończyło się myląco jako 503 "brak providera" (albo, dla zapytań które nie
    # trafiały w żadną regułę, w ogóle nie było zatrzymywane). Blokada/nadzór nie
    # potrzebują wybranego providera, więc provider_id w audycie zostaje puste — do
    # tego etapu bramka nawet nie próbowała szukać providera.
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
            block_reason_code=decision.reason_code,
            block_reason_params=decision.reason_params,
            data_sensitivity=sensitivity.level,
            provider_id=None,
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
            data_sensitivity=sensitivity.level,
            provider_id=None,
            metadata={"oversight_id": oversight_id},
        ))

        return {
            "status": "awaiting_oversight",
            "oversight_id": oversight_id,
            "message": t("oversight.awaitingMessage", agent=agent.name),
            "call_id": call_id,
            "task_id": task_id,
        }

    # ── 3.6. Wybór providera (tylko dla zapytań "allowed") ──────────────────────
    selected_provider: Optional[ProviderRecord] = None
    if not settings.demo_mode:
        selected_provider = await select_provider(agent.model_id, sensitivity.level)
        if selected_provider is None:
            block = _block_reason(
                "no_eligible_provider", model=agent.model_id, sensitivity=sensitivity.level,
            )
            reason = block["block_reason"]
            write_audit_fire_and_forget(AuditEntry(
                agent_id=agent.id,
                agent_name=agent.name,
                task_id=task_id,
                call_id=call_id,
                event_type="no_eligible_provider",
                policy_result="error",
                pii_categories=pii_result.pii_categories,
                pii_count=pii_result.pii_count,
                input_hash=input_hash,
                model_used=agent.model_id,
                **block,
                data_sensitivity=sensitivity.level,
            ))
            raise HTTPException(
                status_code=503,
                detail={
                    "error": "no_eligible_provider",
                    "sensitivity_level": sensitivity.level,
                    "requested_model": agent.model_id,
                    "message": reason,
                },
            )
        logger.info(
            "Wybrany provider: %s (max_sensitivity=%s, priority=%d)",
            selected_provider.name, selected_provider.max_data_sensitivity, selected_provider.priority,
        )

    # ── 4. Wywołanie modelu LLM ─────────────────────────────────────────────────
    t0 = time.monotonic()

    if settings.demo_mode:
        response_text = _demo_response(agent.id, clean_messages)
        latency_ms = 120
        tokens_in  = sum(len(str(m.get("content", ""))) // 4 for m in clean_messages)
        tokens_out = len(response_text) // 4
        cost_eur   = _estimate_cost(agent.model_id, tokens_in, tokens_out)
        output_hash = _hash(response_text)

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
            data_sensitivity=sensitivity.level,
            metadata={"demo_mode": True},
        ))

        return {
            "id": f"demo-{call_id}",
            "object": "chat.completion",
            "model": f"{agent.model_id}-demo",
            "choices": [{
                "index": 0,
                "message": {"role": "assistant", "content": response_text},
                "finish_reason": "stop",
            }],
            "usage": {
                "prompt_tokens": tokens_in,
                "completion_tokens": tokens_out,
                "total_tokens": tokens_in + tokens_out,
            },
        }

    # Zbuduj kwargs dla LiteLLM na podstawie wybranego providera
    model_to_call = _build_litellm_model(selected_provider, agent.model_id)
    extra_kwargs: dict = {}

    if selected_provider.base_url:
        extra_kwargs["api_base"] = selected_provider.base_url

    api_key = selected_provider.api_key_from_env()
    if api_key:
        extra_kwargs["api_key"] = api_key
    elif selected_provider.provider_type == "anthropic" and settings.anthropic_api_key:
        extra_kwargs["api_key"] = settings.anthropic_api_key
    elif selected_provider.provider_type == "deepseek" and settings.deepseek_api_key:
        extra_kwargs["api_key"] = settings.deepseek_api_key

    try:
        response = await litellm.acompletion(
            model=model_to_call,
            messages=clean_messages,
            temperature=body.get("temperature", app_settings.get_number("models.default_temperature", 0.7)),
            max_tokens=body.get("max_tokens", app_settings.get_int("models.default_max_tokens", 1024)),
            **extra_kwargs,
        )
    except Exception as exc:
        logger.exception("Błąd wywołania LLM dla agenta %s (provider: %s)", agent.name, selected_provider.name)
        write_audit_fire_and_forget(AuditEntry(
            agent_id=agent.id,
            agent_name=agent.name,
            task_id=task_id,
            call_id=call_id,
            event_type="llm_error",
            policy_result="error",
            pii_categories=pii_result.pii_categories,
            pii_count=pii_result.pii_count,
            input_hash=input_hash,
            model_used=model_to_call,
            **_block_reason("llm_error", provider=selected_provider.name, error=str(exc)),
            data_sensitivity=sensitivity.level,
            provider_id=selected_provider.id,
        ))
        raise HTTPException(status_code=502, detail=t("errors.llmError", error=exc)) from exc

    latency_ms = int((time.monotonic() - t0) * 1000)

    # ── 5. Skan PII w odpowiedzi ────────────────────────────────────────────────
    response_text = response.choices[0].message.content or ""
    output_pii = _pii_scanner.scan_text(response_text)
    output_hash = _hash(response_text)

    if output_pii:
        logger.warning(
            "PII wykryte w ODPOWIEDZI agenta %s: %s — odpowiedź wymaga przeglądu",
            agent.name, output_pii,
        )

    usage = getattr(response, "usage", None)
    tokens_in  = getattr(usage, "prompt_tokens", None)
    tokens_out = getattr(usage, "completion_tokens", None)
    cost_eur   = _estimate_cost(agent.model_id, tokens_in or 0, tokens_out or 0)

    # ── 6. Dziennik audytowy ────────────────────────────────────────────────────
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
        data_sensitivity=sensitivity.level,
        provider_id=selected_provider.id,
        metadata={"output_pii": output_pii},
    ))

    return response.model_dump()

import hashlib
import logging
import time
from typing import Any, Optional
from uuid import uuid4

import litellm
from fastapi import HTTPException, Request

from audit_logger import write_audit_fire_and_forget
from config import settings
from database import get_agent
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
_DEMO_RESPONSES: dict[str, str] = {
    # Agent 1 — Obsługa Klienta
    "a1000000-0000-0000-0000-000000000001": (
        "Dziękuję za pytanie!\n\n"
        "Ubezpieczenie od utraty pracy (UOP) to produkt chroniący kredytobiorcę "
        "w razie niedobrowolnej utraty zatrudnienia. Dla kredytu hipotecznego 450 000 zł "
        "typowa składka miesięczna wynosi 0,05–0,10% salda kredytu (225–450 zł/mies.). "
        "Składka wliczana jest w ratę kredytu.\n\n"
        "Oferujemy dwa warianty:\n"
        "• Wariant STANDARD — spłata rat przez 6 miesięcy (maks. 12 000 zł)\n"
        "• Wariant PREMIUM — spłata rat przez 12 miesięcy + ochrona na wypadek niezdolności do pracy\n\n"
        "Zachęcam do wizyty w oddziale lub kontaktu z doradcą: 800 123 456 (pon.–pt., 8:00–18:00).\n\n"
        "[TRYB DEMO — odpowiedź symulowana przez GovAI Gateway]"
    ),
    # Agent 2 — Ocena Kredytowa
    "a2000000-0000-0000-0000-000000000002": (
        "OCENA KREDYTOWA — WYNIK WSTĘPNY [TRYB DEMO]\n\n"
        "OCENA: WARUNKOWA AKCEPTACJA\n\n"
        "UZASADNIENIE:\n"
        "Na podstawie przedstawionych danych zdolność kredytowa wnioskodawcy jest "
        "wystarczająca. Wskaźnik DTI wynosi ok. 31% (poniżej progu 45%). "
        "Stabilne zatrudnienie i pozytywna historia kredytowa (BIK 820/1000) "
        "stanowią mocne punkty profilu.\n\n"
        "WARUNKI:\n"
        "• Obowiązkowa polisa na życie jako zabezpieczenie kredytu\n"
        "• Weryfikacja dochodów: wyciąg z konta za 6 ostatnich miesięcy\n"
        "• Wkład własny 26% spełnia wymóg minimalny 20%\n\n"
        "REKOMENDACJA: Przekazać do analityka kredytowego w celu ostatecznej decyzji.\n\n"
        "⚠ Ta decyzja wymaga zatwierdzenia przez człowieka zgodnie z EU AI Act art. 14.\n"
        "[TRYB DEMO — decyzja symulowana, niewiążąca prawnie]"
    ),
    # Agent 3 — Rekrutacja
    "a3000000-0000-0000-0000-000000000003": (
        "ANALIZA CV — WYNIK WSTĘPNY [TRYB DEMO]\n\n"
        "DOPASOWANIE: 85%\n\n"
        "MOCNE STRONY:\n"
        "• Solidne doświadczenie techniczne (Java/Spring Boot — 7 lat)\n"
        "• Certyfikaty branżowe: AWS Solutions Architect, Oracle Java SE 17\n"
        "• Doświadczenie w środowisku bankowym (PKO BP — systemy transakcyjne)\n"
        "• Praca zespołowa: Lead Developer (3 lata)\n\n"
        "BRAKI:\n"
        "• Brak doświadczenia z systemami mainframe (wymaganie dodatkowe)\n"
        "• Brak certyfikacji Kubernetes\n\n"
        "REKOMENDACJA: Kandydat spełnia kluczowe wymagania — "
        "zaproponować rozmowę techniczną z Lead Developerem i test architektoniczny.\n\n"
        "⚠ Ta rekomendacja wymaga akceptacji HR zgodnie z EU AI Act art. 14.\n"
        "[TRYB DEMO — analiza symulowana, wymaga weryfikacji przez człowieka]"
    ),
}


def _demo_response(agent_id: str, messages: list[dict]) -> str:
    """Zwraca gotową odpowiedź dla trybu demo."""
    if agent_id in _DEMO_RESPONSES:
        return _DEMO_RESPONSES[agent_id]
    system = next((m.get("content", "") for m in messages if m.get("role") == "system"), "")
    if any(k in system.lower() for k in ["kredyt", "ocena", "wniosek"]):
        return _DEMO_RESPONSES["a2000000-0000-0000-0000-000000000002"]
    if any(k in system.lower() for k in ["cv", "rekrut", "kandydat"]):
        return _DEMO_RESPONSES["a3000000-0000-0000-0000-000000000003"]
    return (
        "Dziękuję za zapytanie. Przetwarzam Twoją prośbę i przygotowuję odpowiedź.\n\n"
        "[TRYB DEMO — odpowiedź symulowana przez GovAI Gateway]"
    )


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
        "claude-sonnet-4-6":         (0.003,   0.015),
        "claude-opus-4-8":           (0.015,   0.075),
        "gpt-4o":                    (0.005,   0.015),
        "gpt-4o-mini":               (0.00015, 0.0006),
        "deepseek-chat":             (0.00014, 0.00028),
    }
    rate_in, rate_out = rates.get(model, (0.003, 0.015))
    usd = (tokens_in / 1000) * rate_in + (tokens_out / 1000) * rate_out
    return round(usd * 0.93, 8)  # USD → EUR (kurs uproszczony)


def _build_litellm_model(provider: ProviderRecord, preferred_model: str) -> str:
    """
    Buduje identyfikator modelu dla LiteLLM z uwzględnieniem providera.
    LiteLLM wymaga prefiksu dla niestandardowych providerów:
    - ollama: "ollama/model-name"
    - openai-compat (vllm, custom): "openai/model-name"
    """
    if provider.provider_type in ('ollama',):
        model_name = preferred_model if preferred_model in provider.model_ids else (provider.model_ids[0] if provider.model_ids else preferred_model)
        return f"ollama/{model_name}"
    if provider.provider_type in ('vllm', 'custom') and provider.base_url:
        model_name = preferred_model if preferred_model in provider.model_ids else (provider.model_ids[0] if provider.model_ids else preferred_model)
        return f"openai/{model_name}"
    # Dla Anthropic, OpenAI, DeepSeek, Google — LiteLLM rozumie model_id bezpośrednio
    if preferred_model in provider.model_ids:
        return preferred_model
    return provider.model_ids[0] if provider.model_ids else preferred_model


async def handle_chat_completion(request: Request) -> dict[str, Any]:
    """
    Główna ścieżka bramki — każde wywołanie agenta przechodzi tu.

    Kolejność sprawdzeń:
    1. Weryfikacja agenta (rejestr)
    2. Skan PII wejścia (Presidio)
    3. Ocena polityk (reguły)
    3.5. Klasyfikacja wrażliwości danych
    3.6. Wybór providera LLM
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

    # ── 1. Weryfikacja agenta ──────────────────────────────────────────────────
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

    # ── 3.6. Wybór providera ────────────────────────────────────────────────────
    selected_provider: Optional[ProviderRecord] = None
    if not settings.demo_mode:
        selected_provider = await select_provider(agent.model_id, sensitivity.level)
        if selected_provider is None:
            raise HTTPException(
                status_code=503,
                detail={
                    "error": "no_eligible_provider",
                    "sensitivity_level": sensitivity.level,
                    "message": (
                        f"Brak aktywnego providera zdolnego obsłużyć dane o poziomie "
                        f"wrażliwości '{sensitivity.level}'. "
                        "Skontaktuj się z administratorem — aktywuj odpowiedniego providera "
                        "lub obniż poziom wrażliwości danych w zapytaniu."
                    ),
                },
            )
        logger.info(
            "Wybrany provider: %s (max_sensitivity=%s, priority=%d)",
            selected_provider.name, selected_provider.max_data_sensitivity, selected_provider.priority,
        )

    # ── Obsługa zablokowania ────────────────────────────────────────────────────
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
            data_sensitivity=sensitivity.level,
            provider_id=selected_provider.id if selected_provider else None,
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
            provider_id=selected_provider.id if selected_provider else None,
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
            temperature=body.get("temperature", 0.7),
            max_tokens=body.get("max_tokens", 1024),
            **extra_kwargs,
        )
    except Exception as exc:
        logger.exception("Błąd wywołania LLM dla agenta %s (provider: %s)", agent.name, selected_provider.name)
        raise HTTPException(status_code=502, detail=f"Błąd modelu językowego: {exc}") from exc

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
    cost_eur   = _estimate_cost(model_to_call, tokens_in or 0, tokens_out or 0)

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
        model_used=model_to_call,
        latency_ms=latency_ms,
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        cost_eur=cost_eur,
        data_sensitivity=sensitivity.level,
        provider_id=selected_provider.id,
        metadata={"output_pii": output_pii},
    ))

    return response.model_dump()

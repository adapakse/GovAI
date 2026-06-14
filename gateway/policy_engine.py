import logging
from typing import Any

from models import AgentRecord, PIIScanResult, PolicyDecision

logger = logging.getLogger(__name__)

# Słowa kluczowe wykrywające próbę modyfikacji danych finansowych
_FINANCIAL_MUTATION_KEYWORDS = [
    "zmień saldo", "zmien saldo",
    "modify balance", "transfer funds",
    "delete account", "usuń konto", "usun konto",
    "przelej środki", "przelej srodki",
    "zablokuj kartę", "zablokuj karte",
]

# Frazy charakterystyczne dla prompt injection
_INJECTION_PATTERNS = [
    "ignore previous instructions",
    "ignoruj poprzednie instrukcje",
    "forget your instructions",
    "zapomnij swoje instrukcje",
    "you are now", "jesteś teraz",
    "act as if", "udawaj że",
    "new system prompt",
    "override your",
    "\\n\\nHuman:", "\\n\\nAssistant:",
]


def _text_from_messages(messages: list[dict]) -> str:
    return " ".join(
        m.get("content", "")
        for m in messages
        if isinstance(m.get("content"), str)
    ).lower()


class PolicyEngine:
    """
    Trzypoziomowy silnik polityk: globalne → agentowe → domyślne.

    Reguły globalne mają najwyższy priorytet i zawsze są sprawdzane pierwsze.
    Reguły agentowe wynikają z konfiguracji agenta w rejestrze.
    Domyślnie: wywołanie dozwolone.
    """

    def evaluate(
        self,
        agent: AgentRecord,
        messages: list[dict],
        pii_result: PIIScanResult,
    ) -> PolicyDecision:

        text = _text_from_messages(messages)

        # ── Reguła G-001: Blokada modyfikacji finansowych ──────────────────
        for kw in _FINANCIAL_MUTATION_KEYWORDS:
            if kw in text:
                logger.warning("Polityka G-001 aktywowana dla agenta %s", agent.id)
                return PolicyDecision(
                    result="blocked",
                    reason="Wykryto próbę modyfikacji danych finansowych poza zakresem agenta",
                    policy_id="G-001",
                )

        # ── Reguła G-002: Blokada wstrzyknięcia instrukcji ────────────────
        for pattern in _INJECTION_PATTERNS:
            if pattern.lower() in text:
                logger.warning("Polityka G-002 aktywowana dla agenta %s", agent.id)
                return PolicyDecision(
                    result="blocked",
                    reason="Wykryto próbę wstrzyknięcia instrukcji (prompt injection)",
                    policy_id="G-002",
                )

        # ── Reguła A-001: Agent wysokiego ryzyka wymaga nadzoru ───────────
        if agent.requires_oversight:
            logger.info("Agent %s wymaga nadzoru człowieka (ryzyko: %s)", agent.id, agent.risk_level)
            return PolicyDecision(
                result="oversight_required",
                reason=(
                    f"Agent '{agent.name}' jest klasyfikowany jako ryzyko {agent.risk_level.upper()} "
                    f"zgodnie z EU AI Act — każda decyzja wymaga zatwierdzenia przez człowieka"
                ),
                policy_id="A-001",
            )

        # ── Domyślnie: dozwolone ───────────────────────────────────────────
        return PolicyDecision(result="allowed", reason="OK")

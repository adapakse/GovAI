import logging
import time

from models import AgentRecord, PIIScanResult, PolicyDecision

logger = logging.getLogger(__name__)


def _text_from_messages(messages: list[dict]) -> str:
    return " ".join(
        m.get("content", "")
        for m in messages
        if isinstance(m.get("content"), str)
    ).lower()


class PolicyEngine:
    """
    Silnik polityk ładujący reguły z bazy danych.

    Reguły są trzymane w pamięci i odświeżane co 60s przez background task
    w main.py — bez restartu gateway. Ocena każdego żądania jest synchroniczna.

    Kolejność: deny rules (wg priorytetu) → oversight_required (flaga agenta) → allowed.
    """

    def __init__(self) -> None:
        self._deny_rules: list[dict] = []
        self._loaded_at: float = 0.0

    def load_rules(self, rules: list[dict]) -> None:
        """Ładuje reguły z DB. Wywoływane przy starcie i przez background task."""
        self._deny_rules = [r for r in rules if r.get("rule_type") == "deny"]
        self._loaded_at = time.time()
        logger.info(
            "Polityki załadowane z DB: %d reguł blokujących [%s]",
            len(self._deny_rules),
            time.strftime("%H:%M:%S", time.localtime(self._loaded_at)),
        )

    def rules_loaded_at(self) -> float:
        return self._loaded_at

    def evaluate(
        self,
        agent: AgentRecord,
        messages: list[dict],
        pii_result: PIIScanResult,
    ) -> PolicyDecision:

        text = _text_from_messages(messages)

        # ── Reguły blokujące (z DB, posortowane wg priorytetu) ────────────────
        for rule in self._deny_rules:
            keywords: list[str] = rule.get("condition_json", {}).get("keywords", [])
            for kw in keywords:
                if kw.lower() in text:
                    policy_code = rule.get("policy_code") or "POLICY"
                    reason = rule.get("action_json", {}).get(
                        "reason", "Zablokowane przez politykę bezpieczeństwa"
                    )
                    logger.warning(
                        "Polityka %s aktywowana dla agenta %s (słowo kluczowe: '%s')",
                        policy_code, agent.id, kw,
                    )
                    return PolicyDecision(
                        result="blocked",
                        reason=reason,
                        policy_id=policy_code,
                    )

        # ── Nadzór człowieka (flaga agenta z rejestru) ────────────────────────
        if agent.requires_oversight:
            logger.info(
                "Agent %s wymaga nadzoru człowieka (ryzyko: %s)", agent.id, agent.risk_level
            )
            return PolicyDecision(
                result="oversight_required",
                reason=(
                    f"Agent '{agent.name}' klasyfikowany jako ryzyko {agent.risk_level.upper()} "
                    "zgodnie z EU AI Act — każda decyzja wymaga zatwierdzenia przez człowieka"
                ),
                policy_id="A-001",
            )

        # ── Domyślnie: dozwolone ──────────────────────────────────────────────
        return PolicyDecision(result="allowed", reason="OK")

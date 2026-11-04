import asyncio
import logging
import time
from typing import Awaitable, Callable, Optional

from i18n import t
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
    Silnik polityk ładujący reguły z bazy danych — osobny zestaw reguł PER ORGANIZACJA.

    Cache: tenant_id → reguły blokujące. Reguły organizacji ładowane leniwie przy
    pierwszym żądaniu (ensure_loaded) i odświeżane przez background task w main.py
    (refresh_all, co intervals.policy_refresh_seconds) — bez restartu gateway.
    Ocena żądania (evaluate) jest synchroniczna i używa wyłącznie reguł organizacji
    agenta (agent.tenant_id) — reguły jednej organizacji nigdy nie trafiają do innej.

    Kolejność: deny rules (wg priorytetu) → oversight_required (flaga agenta) → allowed.
    """

    def __init__(self) -> None:
        # Klucz None — tylko testy jednostkowe (agent bez organizacji).
        self._deny_rules: dict[Optional[str], list[dict]] = {}
        self._loaded_at: dict[Optional[str], float] = {}
        self._locks: dict[str, asyncio.Lock] = {}

    def load_rules(self, rules: list[dict], tenant_id: Optional[str] = None) -> None:
        """Ustawia reguły organizacji (z DB lub w testach ręcznie)."""
        self._deny_rules[tenant_id] = [r for r in rules if r.get("rule_type") == "deny"]
        self._loaded_at[tenant_id] = time.time()
        logger.info(
            "Polityki organizacji %s załadowane z DB: %d reguł blokujących",
            tenant_id, len(self._deny_rules[tenant_id]),
        )

    def rules_loaded_at(self, tenant_id: Optional[str] = None) -> float:
        return self._loaded_at.get(tenant_id, 0.0)

    def loaded_tenants(self) -> list[str]:
        return [t_id for t_id in self._deny_rules if t_id is not None]

    async def ensure_loaded(self, tenant_id: str, fetch: Callable[[str], Awaitable[list[dict]]]) -> None:
        """Leniwe ładowanie reguł organizacji przy jej pierwszym żądaniu.
        Błąd odczytu propaguje się (fail closed — bez reguł nie oceniamy)."""
        if tenant_id in self._deny_rules:
            return
        lock = self._locks.setdefault(tenant_id, asyncio.Lock())
        async with lock:
            if tenant_id not in self._deny_rules:
                self.load_rules(await fetch(tenant_id), tenant_id)

    async def refresh_all(self, fetch: Callable[[str], Awaitable[list[dict]]]) -> None:
        """Odświeża reguły wszystkich organizacji obecnych w cache. Przy błędzie
        zostają poprzednie reguły danej organizacji."""
        for tenant_id in self.loaded_tenants():
            try:
                self.load_rules(await fetch(tenant_id), tenant_id)
            except Exception as exc:
                logger.error("Błąd odświeżania polityk organizacji %s: %s", tenant_id, exc)

    def evaluate(
        self,
        agent: AgentRecord,
        messages: list[dict],
        pii_result: PIIScanResult,
    ) -> PolicyDecision:

        text = _text_from_messages(messages)

        # ── Reguły blokujące organizacji agenta (posortowane wg priorytetu) ───
        for rule in self._deny_rules.get(agent.tenant_id, []):
            keywords: list[str] = rule.get("condition_json", {}).get("keywords", [])
            for kw in keywords:
                if kw.lower() in text:
                    policy_code = rule.get("policy_code") or "POLICY"
                    # Powód z polityki to treść wpisana przez użytkownika — bez tłumaczenia.
                    custom_reason = rule.get("action_json", {}).get("reason")
                    if custom_reason:
                        reason_code, reason_params = "policy_custom", {"reason": str(custom_reason)}
                    else:
                        reason_code, reason_params = "policy_default", {}
                    reason = t(f"blockReasons.{reason_code}", **reason_params)
                    logger.warning(
                        "Polityka %s aktywowana dla agenta %s (słowo kluczowe: '%s')",
                        policy_code, agent.id, kw,
                    )
                    return PolicyDecision(
                        result="blocked",
                        reason=reason,
                        policy_id=policy_code,
                        reason_code=reason_code,
                        reason_params=reason_params,
                    )

        # ── Nadzór człowieka (flaga agenta z rejestru) ────────────────────────
        if agent.requires_oversight:
            logger.info(
                "Agent %s wymaga nadzoru człowieka (ryzyko: %s)", agent.id, agent.risk_level
            )
            return PolicyDecision(
                result="oversight_required",
                reason=t(
                    "policy.oversightRequired",
                    agent=agent.name, risk=agent.risk_level.upper(),
                ),
                policy_id="A-001",
            )

        # ── Domyślnie: dozwolone ──────────────────────────────────────────────
        return PolicyDecision(result="allowed", reason="OK")

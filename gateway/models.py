from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Literal, Optional
from uuid import UUID

# Zmienne środowiskowe z kluczami platformy, do których może się odwołać provider
# (providers.api_key_env). Trzymaj w synchronizacji z api/routers/providers.py.
PLATFORM_KEY_ENVS = frozenset({"ANTHROPIC_API_KEY", "OPENAI_API_KEY", "DEEPSEEK_API_KEY", "GOOGLE_API_KEY"})


@dataclass
class AgentRecord:
    id: str
    name: str
    status: str
    risk_level: str
    requires_oversight: bool
    model_id: str
    allowed_data_cats: list[str]
    owner_email: str
    team: str
    monthly_budget_eur: float
    annex_iii_cat: Optional[str] = None


@dataclass
class PIIScanResult:
    has_pii: bool
    pii_categories: list[str] = field(default_factory=list)
    pii_count: int = 0
    redacted_messages: list[dict] = field(default_factory=list)


@dataclass
class PolicyDecision:
    result: Literal["allowed", "blocked", "oversight_required"]
    reason: str
    policy_id: Optional[str] = None
    # Kod i parametry powodu (blockReasons.<code>) — do tłumaczenia w API.
    reason_code: Optional[str] = None
    reason_params: dict[str, Any] = field(default_factory=dict)


@dataclass
class ProviderRecord:
    id: str
    name: str
    provider_type: str
    model_ids: list[str]
    max_data_sensitivity: str
    priority: int
    base_url: Optional[str] = None
    api_key_env: Optional[str] = None

    def api_key_from_env(self) -> Optional[str]:
        """Klucz platformy z env — tylko zmienna z białej listy i tylko dla
        providera bez własnego base_url (API waliduje to samo przy zapisie;
        tu druga linia obrony dla wierszy sprzed walidacji)."""
        if not self.api_key_env or self.base_url:
            return None
        if self.api_key_env not in PLATFORM_KEY_ENVS:
            return None
        return os.environ.get(self.api_key_env)


@dataclass
class AuditEntry:
    agent_id: str
    agent_name: str
    task_id: str
    call_id: str
    event_type: str
    policy_result: str
    pii_categories: list[str]
    pii_count: int
    input_hash: str
    model_used: str
    latency_ms: Optional[int] = None
    tokens_in: Optional[int] = None
    tokens_out: Optional[int] = None
    cost_eur: Optional[float] = None
    output_hash: Optional[str] = None
    block_reason: Optional[str] = None
    # Kod powodu (blockReasons.<code>) + parametry — zapisywane w metadata
    # (block_reason_code / block_reason_params), API tłumaczy z nich block_reason.
    block_reason_code: Optional[str] = None
    block_reason_params: dict[str, Any] = field(default_factory=dict)
    policy_id: Optional[str] = None
    data_sensitivity: Optional[str] = None
    provider_id: Optional[str] = None
    metadata: dict = field(default_factory=dict)

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Optional
from uuid import UUID


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
    policy_id: Optional[str] = None
    metadata: dict = field(default_factory=dict)

"""
Ocena zgodności agenta z EU AI Act — silnik w pełni dynamiczny.

Brak jakiejkolwiek zaszytej w kodzie listy wymagań, wag czy terminów.
Wszystko pochodzi z dwóch źródeł danych:

  1. Katalog wymagań — tabela `ai_act_requirements` (edytowalna w UI:
     Polityki → Wymagania EU AI Act), filtrowana wg risk_level agenta.
  2. Rejestr agenta — `agents.requires_oversight` (fakt systemowy) oraz
     `agents.compliance_decl` (samo-deklaracja per wymaganie, zakładka Rejestr).

Dla każdego wymagania silnik sprawdza najpierw, czy istnieje obiektywny
automatyczny check (pole rejestru, nie oświadczenie) — obecnie tylko nadzór
człowieka (art. 14). W przeciwnym razie czyta samo-deklarację po `decl_key`.
Brak jednego i drugiego = wymaganie nieocenione ("undeclared") — realna luka,
nie fikcyjna wartość domyślna.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

# decl_key → funkcja sprawdzająca fakt w rejestrze agenta (nie samo-deklarację).
# To JEDYNE miejsce z "twardą" regułą — bo to obiektywny stan systemu, a nie
# oświadczenie, które mogłoby być błędne lub aspiracyjne.
_AUTO_CHECKS = {
    "art14_human_oversight": lambda agent: "yes" if agent.get("requires_oversight") else "no",
}


@dataclass
class RequirementStatus:
    article: str
    title: str
    description: str
    status: str            # "yes" | "no" | "partial" | "na" | "undeclared"
    severity: str           # critical | major | minor (z ai_act_requirements.default_severity)
    deadline_days: int
    source: str              # "auto" | "declared" | "undeclared"
    notes: str = ""

    @property
    def is_gap(self) -> bool:
        return self.status in ("no", "partial", "undeclared")


@dataclass
class ComplianceReport:
    agent_id: str
    agent_name: str
    risk_level: str
    status: str  # "compliant" | "gaps_found" | "critical"
    requirements: list[RequirementStatus] = field(default_factory=list)

    @property
    def gaps(self) -> list[RequirementStatus]:
        return [r for r in self.requirements if r.is_gap]


def assess_compliance(agent: dict, requirements: list[dict]) -> ComplianceReport:
    """
    Konfrontuje katalog wymagań (requirements, już przefiltrowany wg risk_level
    agenta przez wołającego) z danymi rejestru agenta.
    """
    decl: dict = agent.get("compliance_decl") or {}
    items: list[RequirementStatus] = []

    for req in requirements:
        key = req.get("decl_key")
        auto_check = _AUTO_CHECKS.get(key) if key else None

        if auto_check is not None:
            status, source, notes = auto_check(agent), "auto", ""
        else:
            entry = decl.get(key) or {} if key else {}
            declared_status = entry.get("status")
            if declared_status:
                status, source, notes = declared_status, "declared", entry.get("notes", "")
            else:
                status, source, notes = "undeclared", "undeclared", ""

        items.append(RequirementStatus(
            article=req["article_ref"],
            title=req["requirement_title"],
            description=req["requirement_text"],
            status=status,
            severity=req["default_severity"],
            deadline_days=req["default_deadline_days"],
            source=source,
            notes=notes,
        ))

    gaps = [i for i in items if i.is_gap]
    if not gaps:
        overall = "compliant"
    elif any(i.severity == "critical" for i in gaps):
        overall = "critical"
    else:
        overall = "gaps_found"

    return ComplianceReport(
        agent_id=str(agent.get("id", "")),
        agent_name=agent.get("name", ""),
        risk_level=agent.get("risk_level", "minimal"),
        status=overall,
        requirements=items,
    )

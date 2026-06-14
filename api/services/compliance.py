"""
Ocena zgodności agenta z EU AI Act.
Identyfikuje luki i generuje plan naprawczy.
"""
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ComplianceGap:
    article: str
    title: str
    description: str
    severity: str  # "critical" | "major" | "minor"
    action: str
    deadline_days: int


@dataclass
class ComplianceReport:
    agent_id: str
    agent_name: str
    risk_level: str
    status: str  # "compliant" | "gaps_found" | "critical"
    gaps: list[ComplianceGap] = field(default_factory=list)
    obligations: list[str] = field(default_factory=list)


# Wymagania dla agentów wysokiego ryzyka (Aneks III)
_HIGH_RISK_CHECKS = [
    {
        "field": "requires_oversight",
        "check": lambda v: v is True,
        "gap": ComplianceGap(
            article="Art. 14",
            title="Brak nadzoru człowieka",
            description=(
                "Systemy AI wysokiego ryzyka muszą umożliwiać skuteczny nadzór człowieka. "
                "Agent nie ma włączonego wymogu zatwierdzenia przez recenzenta."
            ),
            severity="critical",
            action="Włącz flagę requires_oversight i wyznacz recenzenta odpowiedzialnego za zatwierdzanie decyzji",
            deadline_days=7,
        ),
    },
    {
        "field": "legal_basis",
        "check": lambda v: bool(v),
        "gap": ComplianceGap(
            article="Art. 10",
            title="Brak podstawy prawnej klasyfikacji",
            description=(
                "Agent nie ma udokumentowanej podstawy prawnej klasyfikacji ryzyka. "
                "Wymagane dla wszystkich systemów wysokiego ryzyka."
            ),
            severity="major",
            action="Uzupełnij pole legal_basis z numerem artykułu i kategorii Aneksu III",
            deadline_days=14,
        ),
    },
    {
        "field": "annex_iii_cat",
        "check": lambda v: bool(v),
        "gap": ComplianceGap(
            article="Aneks III",
            title="Brak kategorii Aneksu III",
            description=(
                "Agent nie ma przypisanej kategorii z Aneksu III EU AI Act. "
                "Wymagane dla wszystkich systemów wysokiego ryzyka."
            ),
            severity="major",
            action="Przypisz właściwą kategorię z Aneksu III podczas rejestracji lub edycji agenta",
            deadline_days=14,
        ),
    },
    {
        "field": "_technical_doc",
        "check": lambda v: False,  # Zawsze luka — brak pola w DB w prototypie
        "gap": ComplianceGap(
            article="Art. 11",
            title="Brak dokumentacji technicznej",
            description=(
                "Systemy wysokiego ryzyka wymagają kompletnej dokumentacji technicznej "
                "przed wprowadzeniem na rynek lub do użytku."
            ),
            severity="critical",
            action="Przygotuj dokumentację techniczną zgodną z Aneksem IV EU AI Act",
            deadline_days=30,
        ),
    },
    {
        "field": "_conformity",
        "check": lambda v: False,  # Zawsze luka — brak pola w DB w prototypie
        "gap": ComplianceGap(
            article="Art. 43",
            title="Brak oceny zgodności",
            description=(
                "Systemy wysokiego ryzyka z Aneksu III wymagają przeprowadzenia "
                "oceny zgodności przed wdrożeniem."
            ),
            severity="critical",
            action="Przeprowadź ocenę zgodności — dla większości kategorii możliwa samoocena (art. 43 ust. 2)",
            deadline_days=30,
        ),
    },
    {
        "field": "_eu_db",
        "check": lambda v: False,  # Zawsze luka — brak pola w DB w prototypie
        "gap": ComplianceGap(
            article="Art. 49",
            title="Brak rejestracji w EU AI Database",
            description=(
                "Systemy wysokiego ryzyka muszą być zarejestrowane w unijnej bazie danych AI "
                "przed wprowadzeniem do użytku (eu.ai.database)."
            ),
            severity="major",
            action="Zarejestruj system w EU AI Database pod adresem ec.europa.eu/digital-strategy/ai-database",
            deadline_days=60,
        ),
    },
]

# Obowiązki dla agentów o ograniczonym ryzyku
_LIMITED_RISK_OBLIGATIONS = [
    "Poinformuj użytkownika, że komunikuje się z systemem AI (art. 50 ust. 1)",
    "Oznacz treści generowane przez AI jeśli mogą być mylone z treściami ludzkimi (art. 50 ust. 2)",
]


def assess_compliance(agent: dict) -> ComplianceReport:
    """
    Ocenia stan zgodności agenta z EU AI Act.
    Zwraca raport z listą luk i obowiązków.
    """
    risk = agent.get("risk_level", "minimal")
    gaps: list[ComplianceGap] = []
    obligations: list[str] = []

    if risk == "unacceptable":
        gaps.append(ComplianceGap(
            article="Art. 5",
            title="System zakazany — niedopuszczalne ryzyko",
            description="Agent sklasyfikowany jako niedopuszczalne ryzyko. Stosowanie zabronione przez EU AI Act.",
            severity="critical",
            action="Natychmiast wyłącz agenta i przeprowadź przegląd prawny",
            deadline_days=0,
        ))

    elif risk == "high":
        for check in _HIGH_RISK_CHECKS:
            field_val = agent.get(check["field"])
            if not check["check"](field_val):
                gaps.append(check["gap"])
        obligations.extend([
            "Wdrożenie systemu zarządzania ryzykiem (art. 9)",
            "Zapewnienie jakości danych treningowych (art. 10)",
            "Prowadzenie dziennika logów przez co najmniej 6 miesięcy (art. 12)",
            "Przejrzystość wobec użytkowników (art. 13)",
            "Nadzór człowieka przy każdej decyzji (art. 14)",
            "Zgłaszanie poważnych incydentów do organu nadzorczego (art. 73)",
        ])

    elif risk == "limited":
        obligations.extend(_LIMITED_RISK_OBLIGATIONS)

    else:
        obligations.append("Brak szczególnych obowiązków (ryzyko minimalne)")

    if not gaps:
        status = "compliant"
    elif any(g.severity == "critical" for g in gaps):
        status = "critical"
    else:
        status = "gaps_found"

    return ComplianceReport(
        agent_id=str(agent.get("id", "")),
        agent_name=agent.get("name", ""),
        risk_level=risk,
        status=status,
        gaps=gaps,
        obligations=obligations,
    )

"""
Klasyfikator ryzyka AI Act — używa Claude do analizy opisu agenta
i zwraca poziom ryzyka, kategorię z Aneksu III i podstawę prawną.
"""
import json
import logging
import re
from dataclasses import dataclass, field

import anthropic

from config import settings

logger = logging.getLogger(__name__)

CLASSIFICATION_PROMPT = """Jesteś ekspertem prawnym specjalizującym się w Europejskiej Ustawie o Sztucznej Inteligencji (EU AI Act, Rozporządzenie UE 2024/1689).

Na podstawie opisu systemu AI oceń go i zwróć klasyfikację WYŁĄCZNIE w formacie JSON, bez żadnego dodatkowego tekstu.

Poziomy ryzyka:
- "unacceptable" — systemy zakazane (art. 5): manipulacja podprogowa, scoring społeczny, biometryczna identyfikacja w czasie rzeczywistym w przestrzeni publicznej
- "high" — systemy wysokiego ryzyka z Aneksu III: infrastruktura krytyczna, edukacja, zatrudnienie, dostęp do usług, egzekwowanie prawa, wymiar sprawiedliwości, zarządzanie migracją, ocena zdolności kredytowej
- "limited" — systemy z ograniczonymi obowiązkami (art. 50): chatboty, systemy generujące deepfake, systemy emocji
- "minimal" — pozostałe systemy: filtry spamu, gry, systemy rekomendacji bez znaczącego wpływu

Kategorie Aneksu III (tylko dla high risk):
- "critical_infrastructure" — pkt 2: zarządzanie infrastrukturą krytyczną
- "education" — pkt 3: edukacja i szkolenia zawodowe
- "employment_recruitment" — pkt 4(a): rekrutacja i selekcja pracowników
- "employment_decisions" — pkt 4(b): decyzje dotyczące warunków zatrudnienia
- "essential_services" — pkt 5(a): dostęp do usług publicznych i prywatnych
- "creditworthiness_assessment" — pkt 5(b): ocena zdolności kredytowej
- "law_enforcement" — pkt 6: egzekwowanie prawa
- "migration_asylum" — pkt 7: zarządzanie migracją i azylem
- "justice" — pkt 8: wymiar sprawiedliwości

Odpowiedz TYLKO w formacie JSON (bez markdown, bez komentarzy):
{
  "risk_level": "minimal|limited|high|unacceptable",
  "annex_iii_cat": "kategoria lub null jeśli nie high risk",
  "legal_basis": "Artykuł i punkt EU AI Act z krótkim uzasadnieniem",
  "requires_oversight": true/false,
  "key_obligations": ["obowiązek 1", "obowiązek 2", "obowiązek 3"]
}"""


@dataclass
class ClassificationResult:
    risk_level: str
    annex_iii_cat: str | None
    legal_basis: str
    requires_oversight: bool
    key_obligations: list[str] = field(default_factory=list)


async def classify_risk(description: str) -> ClassificationResult:
    """
    Klasyfikuje agenta AI według EU AI Act na podstawie opisu.
    Używa claude-sonnet-4-6 jako eksperta prawnego.
    """
    client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)

    try:
        response = await client.messages.create(
            model=settings.classifier_model,
            max_tokens=600,
            system=CLASSIFICATION_PROMPT,
            messages=[{
                "role": "user",
                "content": f"Opisz i sklasyfikuj następujący system AI:\n\n{description}",
            }],
        )

        raw = response.content[0].text.strip()

        # Wyciągnij JSON z odpowiedzi (zabezpieczenie na wypadek dodatkowego tekstu)
        json_match = re.search(r'\{.*\}', raw, re.DOTALL)
        if not json_match:
            raise ValueError(f"Brak JSON w odpowiedzi klasyfikatora: {raw[:200]}")

        data = json.loads(json_match.group())
        return ClassificationResult(
            risk_level=data.get("risk_level", "minimal"),
            annex_iii_cat=data.get("annex_iii_cat") or None,
            legal_basis=data.get("legal_basis", ""),
            requires_oversight=bool(data.get("requires_oversight", False)),
            key_obligations=data.get("key_obligations", []),
        )

    except Exception:
        logger.exception("Błąd klasyfikatora AI Act — domyślnie 'minimal'")
        return ClassificationResult(
            risk_level="minimal",
            annex_iii_cat=None,
            legal_basis="Błąd klasyfikacji — wymagana ręczna weryfikacja",
            requires_oversight=False,
            key_obligations=["Ręczna weryfikacja klasyfikacji wymagana"],
        )

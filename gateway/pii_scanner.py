import hashlib
import logging
import re
from typing import Optional

from presidio_analyzer import AnalyzerEngine, Pattern, PatternRecognizer, RecognizerResult
from presidio_analyzer.nlp_engine import NlpEngineProvider
from presidio_anonymizer import AnonymizerEngine
from presidio_anonymizer.entities import OperatorConfig

from config import settings
from models import PIIScanResult

logger = logging.getLogger(__name__)


def _make_pl_pesel_recognizer() -> PatternRecognizer:
    """PESEL — 11-cyfrowy numer identyfikacyjny obywatela polskiego."""
    pattern = Pattern(
        name="PESEL",
        regex=r"\b[0-9]{2}(?:0[1-9]|1[0-2]|2[1-9]|3[0-2])(?:0[1-9]|[12][0-9]|3[01])[0-9]{5}\b",
        score=0.85,
    )
    return PatternRecognizer(
        supported_entity="PL_PESEL",
        patterns=[pattern],
        supported_language="pl",
    )


def _make_pl_nip_recognizer() -> PatternRecognizer:
    """NIP — 10-cyfrowy numer identyfikacji podatkowej."""
    pattern = Pattern(
        name="NIP",
        regex=r"\b\d{3}[-\s]?\d{3}[-\s]?\d{2}[-\s]?\d{2}\b",
        score=0.75,
    )
    return PatternRecognizer(
        supported_entity="PL_NIP",
        patterns=[pattern],
        supported_language="pl",
    )


def _make_pl_phone_recognizer() -> PatternRecognizer:
    """Polskie numery telefonów."""
    pattern = Pattern(
        name="PL_PHONE",
        regex=r"\b(?:\+48[\s-]?)?(?:\d{3}[\s-]?\d{3}[\s-]?\d{3}|\d{2}[\s-]?\d{3}[\s-]?\d{2}[\s-]?\d{2})\b",
        score=0.65,
    )
    return PatternRecognizer(
        supported_entity="PHONE_NUMBER",
        patterns=[pattern],
        supported_language="pl",
    )


class PIIScanner:
    """Wykrywanie i anonimizacja danych osobowych z obsługą języka polskiego."""

    SUPPORTED_ENTITIES = [
        "PERSON", "EMAIL_ADDRESS", "PHONE_NUMBER", "LOCATION",
        "CREDIT_CARD", "IBAN_CODE", "DATE_TIME",
        "PL_PESEL", "PL_NIP",
    ]

    def __init__(self) -> None:
        config = {
            "nlp_engine_name": "spacy",
            "models": [
                {"lang_code": "pl", "model_name": "pl_core_news_sm"},
                {"lang_code": "en", "model_name": "en_core_web_sm"},
            ],
        }
        provider = NlpEngineProvider(nlp_configuration=config)
        nlp_engine = provider.create_engine()

        self._analyzer = AnalyzerEngine(
            nlp_engine=nlp_engine,
            supported_languages=["pl", "en"],
        )
        self._analyzer.registry.add_recognizer(_make_pl_pesel_recognizer())
        self._analyzer.registry.add_recognizer(_make_pl_nip_recognizer())
        self._analyzer.registry.add_recognizer(_make_pl_phone_recognizer())

        self._anonymizer = AnonymizerEngine()
        logger.info("PIIScanner zainicjalizowany (pl + en)")

    def scan(self, messages: list[dict], lang: str = "pl") -> PIIScanResult:
        """Skanuje wiadomości i zwraca wynik z oczyszczonymi wiadomościami."""
        all_texts = [m.get("content", "") for m in messages if isinstance(m.get("content"), str)]
        combined = " ".join(all_texts)

        if not combined.strip():
            return PIIScanResult(has_pii=False, redacted_messages=messages)

        findings = self._analyzer.analyze(
            text=combined,
            language=lang,
            entities=self.SUPPORTED_ENTITIES,
            score_threshold=settings.pii_confidence_threshold,
        )

        if not findings:
            return PIIScanResult(has_pii=False, redacted_messages=messages)

        categories = list({f.entity_type for f in findings})

        # Anonimizacja każdej wiadomości z osobna
        redacted_messages = []
        for msg in messages:
            content = msg.get("content", "")
            if not isinstance(content, str) or not content.strip():
                redacted_messages.append(msg)
                continue

            msg_findings = self._analyzer.analyze(
                text=content,
                language=lang,
                entities=self.SUPPORTED_ENTITIES,
                score_threshold=settings.pii_confidence_threshold,
            )
            if msg_findings:
                anonymized = self._anonymizer.anonymize(
                    text=content,
                    analyzer_results=msg_findings,
                    operators={
                        entity: OperatorConfig("replace", {"new_value": f"[{entity}]"})
                        for entity in self.SUPPORTED_ENTITIES
                    },
                )
                redacted_messages.append({**msg, "content": anonymized.text})
            else:
                redacted_messages.append(msg)

        return PIIScanResult(
            has_pii=True,
            pii_categories=categories,
            pii_count=len(findings),
            redacted_messages=redacted_messages,
        )

    def scan_text(self, text: str, lang: str = "pl") -> list[str]:
        """Skanuje pojedynczy tekst — zwraca listę wykrytych kategorii."""
        findings = self._analyzer.analyze(
            text=text,
            language=lang,
            entities=self.SUPPORTED_ENTITIES,
            score_threshold=settings.pii_confidence_threshold,
        )
        return list({f.entity_type for f in findings})

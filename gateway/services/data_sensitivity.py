"""
Klasyfikator wrażliwości danych — reguły dla kontekstu kancelarii prawnej.

Hierarchia poziomów (rosnąca wrażliwość):
  public → internal → confidential → privileged

Działanie:
  1. Łączy treść wszystkich wiadomości w jednym buforze.
  2. Sprawdza wzorce regex i słowa kluczowe dla każdego poziomu.
  3. Zwraca najwyższy wykryty poziom i listę powodów (do audytu).

Brak zewnętrznych wywołań — wyłącznie logika lokalna.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

# ── Hierarchia ─────────────────────────────────────────────────────────────────
LEVELS = ['public', 'internal', 'confidential', 'privileged']


@dataclass
class SensitivityResult:
    level: str
    reasons: list[str] = field(default_factory=list)


# ── PRIVILEGED — tajemnica adwokacka / radcowska ───────────────────────────────

_PRIV_KW = [
    "tajemnica adwokacka",
    "tajemnica radcy",
    "tajemnica zawodowa",
    "tajemnica kanclerska",
    "objęte tajemnicą",
    "klient kancelarii",
    "klientka kancelarii",
    "mocodawca",
    "pełnomocnictwo substytucyjne",
    "konferencja z klientem",
    "poufne zlecenie",
    "sprawy klienta",
    "zlecenie klienta",
]

_PRIV_RE = [
    re.compile(r'\bsygn(?:atura)?\.?\s*akt\b', re.IGNORECASE | re.UNICODE),
    re.compile(r'\b[IVX]{1,4}\s+[CKP]{1,3}\s+\d+/\d{2,4}\b', re.UNICODE),
    re.compile(r'\b(?:mój|nasz[ae]?go?|jej|jego|ich)\s+klient(?:a|ów|ce|em)?\b', re.IGNORECASE | re.UNICODE),
    re.compile(r'\bsprawa\s+(?:nr|numer|o\s+sygn)\s*[:.]?\s*\d+', re.IGNORECASE | re.UNICODE),
]

# ── CONFIDENTIAL — dane osobowe, dokumenty procesowe ──────────────────────────

_CONF_KW = [
    "pesel",
    " nip ",
    " regon ",
    " krs ",
    "wyrok sądu",
    "wyrok nakazowy",
    "wyrok łączny",
    "orzeczenie sądu",
    "postanowienie sądu",
    "nakaz zapłaty",
    "pozew",
    "apelacja",
    "skarga kasacyjna",
    "skarga do sądu",
    "data urodzenia",
    "adres zamieszkania",
    "adres zameldowania",
    "numer dowodu",
    "dowód osobisty",
    "numer paszportu",
    "numer rachunku",
    "karta kredytowa",
    " cvv ",
    "wynagrodzenie",
    "zarobki",
    "wysokość dochodu",
    "kwota kredytu",
    "saldo konta",
    "diagnoza",
    "schorzenie",
    "choroba przewlekła",
    "dane osobowe",
    "przetwarzanie danych osobowych",
    "umowa o pracę",
]

_CONF_RE = [
    re.compile(r'\bPESEL\s*[:=]?\s*\d{11}\b', re.IGNORECASE),
    re.compile(r'\bNIP\s*[:=]?\s*\d{3}[-\s]?\d{3}[-\s]?\d{2}[-\s]?\d{2}\b', re.IGNORECASE),
    re.compile(r'\bREGON\s*[:=]?\s*\d{9}(?:\d{5})?\b', re.IGNORECASE),
    re.compile(r'\b\d{2}[01]\d[0-3]\d\d{5}\b'),  # PESEL-like 11-digit sequence
]

# ── INTERNAL — dokumenty robocze kancelarii ────────────────────────────────────

_INT_KW = [
    "analiza prawna",
    "opinia prawna",
    "interpretacja prawna",
    "wykładnia prawa",
    "projekt umowy",
    "wzór umowy",
    "szablon dokumentu",
    "ustawa",
    "kodeks",
    "rozporządzenie",
    "dyrektywa unijna",
    "przepis prawa",
    "artykuł ustawy",
    "kancelaria",
    "radca prawny",
    "adwokat",
    "notariusz",
    "procedura wewnętrzna",
    "regulamin kancelarii",
    "wytyczne",
    "polityka kancelarii",
    "metodologia",
    "due diligence",
    "memorandum prawne",
    "legal memo",
    "prokurent",
    "pełnomocnik procesowy",
]


class DataSensitivityClassifier:
    """Klasyfikuje wrażliwość danych na podstawie reguł (bez zewnętrznych wywołań)."""

    def classify(self, messages: list[dict]) -> SensitivityResult:
        combined = ' '.join(
            str(m.get('content') or '') for m in messages
        )
        combined_lower = combined.lower()

        reasons: list[str] = []
        level = 'public'

        # Sprawdzaj od najwyższego poziomu

        priv_hit = self._check(combined, combined_lower, _PRIV_KW, _PRIV_RE)
        if priv_hit:
            reasons.extend(priv_hit)
            level = 'privileged'
            return SensitivityResult(level=level, reasons=reasons)

        conf_hit = self._check(combined, combined_lower, _CONF_KW, _CONF_RE)
        if conf_hit:
            reasons.extend(conf_hit)
            level = 'confidential'
            return SensitivityResult(level=level, reasons=reasons)

        int_hit = self._check(combined, combined_lower, _INT_KW, [])
        if int_hit:
            reasons.extend(int_hit)
            level = 'internal'
            return SensitivityResult(level=level, reasons=reasons)

        return SensitivityResult(level='public', reasons=['Brak wskaźników poufności'])

    @staticmethod
    def _check(text: str, text_lower: str, keywords: list[str], patterns: list[re.Pattern]) -> list[str]:
        hits: list[str] = []
        for kw in keywords:
            if kw in text_lower:
                hits.append(f'słowo kluczowe: „{kw.strip()}"')
        for pat in patterns:
            m = pat.search(text)
            if m:
                hits.append(f'wzorzec: {pat.pattern[:40]}')
        return hits

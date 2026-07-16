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


# ── PRIVILEGED — tajemnica adwokacka / radcowska, strategia i poufność klienta ─

_PRIV_KW = [
    "tajemnica adwokacka",
    "tajemnica radcy",
    "tajemnica zawodowa",
    "tajemnica kanclerska",
    "tajemnica przedsiębiorstwa",
    "tajemnica przedsiębiorcy",
    "objęte tajemnicą",
    "klient kancelarii",
    "klientka kancelarii",
    "mocodawca",
    "pełnomocnictwo substytucyjne",
    "konferencja z klientem",
    "poufne zlecenie",
    "poufna ugoda",
    "ugoda poufna",
    "klauzula poufności",
    "umowa o zachowaniu poufności",
    "sprawy klienta",
    "zlecenie klienta",
    "strategia procesowa",
    "taktyka procesowa",
    "linia obrony",
    "akta sprawy klienta",
    "korespondencja z klientem",
    "opinia prawna dla klienta",
    # ── prawo rodzinne — sprawy o wysokiej wrażliwości osobistej ──────────────
    "sprawa rozwodowa",
    "opieka nad dzieckiem",
    "władza rodzicielska",
    "kontakty z dzieckiem",
    "przemoc domowa",
    # ── prawo karne — obrona i toczące się postępowanie ───────────────────────
    "linia obrony oskarżonego",
    "wyjaśnienia podejrzanego",
    "immunitet",
    "tymczasowe aresztowanie",
]

_PRIV_RE = [
    re.compile(r'\bsygn(?:atura)?\.?\s*akt\b', re.IGNORECASE | re.UNICODE),
    re.compile(r'\b[IVX]{1,4}\s+[CKP]{1,3}\s+\d+/\d{2,4}\b', re.UNICODE),
    re.compile(r'\b(?:mój|nasz[ae]?go?|jej|jego|ich)\s+klient(?:a|ów|ce|em)?\b', re.IGNORECASE | re.UNICODE),
    re.compile(r'\bsprawa\s+(?:nr|numer|o\s+sygn)\s*[:.]?\s*\d+', re.IGNORECASE | re.UNICODE),
    re.compile(r'\bNDA\b'),
    # Warianty odmiany — dopasowują też "tajemnicę adwokacką", "tajemnicy zawodowej" itd.
    re.compile(r'\btajemnic\w*\s+(?:adwokack\w*|radc\w*|zawodow\w*|kancelarsk\w*)\b', re.IGNORECASE | re.UNICODE),
    re.compile(r'\bklient\w*\s+kancelari\w*\b', re.IGNORECASE | re.UNICODE),
    re.compile(r'\bspraw\w*\s+rozwodow\w*\b', re.IGNORECASE | re.UNICODE),
    re.compile(r'\bopiek\w*\s+nad\s+dzieck\w*\b', re.IGNORECASE | re.UNICODE),
]

# ── CONFIDENTIAL — dane osobowe, dokumenty procesowe, dane finansowe spółek ───

_CONF_KW = [
    "pesel",
    "wyrok sądu",
    "wyrok nakazowy",
    "wyrok łączny",
    "wyrok skazujący",
    "orzeczenie sądu",
    "postanowienie sądu",
    "nakaz zapłaty",
    "akt oskarżenia",
    "pozew",
    "apelacja",
    "skarga kasacyjna",
    "skarga do sądu",
    "kara pozbawienia wolności",
    "data urodzenia",
    "adres zamieszkania",
    "adres zameldowania",
    "numer dowodu",
    "nr dowodu",
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
    "dane wrażliwe",
    "dane szczególnej kategorii",
    "przetwarzanie danych osobowych",
    "naruszenie ochrony danych",
    "rodo",
    "umowa o pracę",
    # ── prawo spółek / M&A ─────────────────────────────────────────────────────
    "wycena spółki",
    "sprawozdanie finansowe",
    "bilans spółki",
    "rozwód",
    "alimenty",
]

_CONF_RE = [
    re.compile(r'\bPESEL\s*[:=]?\s*\d{11}\b', re.IGNORECASE),
    re.compile(r'\bNIP\s*[:=]?\s*\d{3}[-\s]?\d{3}[-\s]?\d{2}[-\s]?\d{2}\b', re.IGNORECASE),
    re.compile(r'\bREGON\s*[:=]?\s*\d{9}(?:\d{5})?\b', re.IGNORECASE),
    re.compile(r'\bKRS\s*[:=]?\s*\d{10}\b', re.IGNORECASE),
    re.compile(r'\b(?:NIP|REGON|KRS)\b', re.IGNORECASE),  # sama wzmianka o identyfikatorze spółki
    re.compile(r'\b\d{2}[01]\d[0-3]\d\d{5}\b'),  # PESEL-like 11-digit sequence
    re.compile(r'\b[A-Z]{3}\d{6}\b'),  # numer dowodu osobistego (seria + 6 cyfr), przed maskowaniem PII
    re.compile(r'\[PL_ID_CARD\]', re.IGNORECASE),  # ten sam numer po maskowaniu przez PIIScanner
]

# ── INTERNAL — dokumenty robocze kancelarii, wiedza ogólna ────────────────────

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
    "compliance",
    "audyt prawny",
    "know-how kancelarii",
    "szkolenie wewnętrzne",
]

_INT_RE = [
    # Warianty odmiany — dopasowują też "analizę prawną", "opinii prawnej", "dyrektywy unijnej" itd.
    re.compile(r'\b(?:analiz\w*|opini\w*|interpretacj\w*)\s+prawn\w*\b', re.IGNORECASE | re.UNICODE),
    re.compile(r'\bwyk[łl]adni\w*\s+praw\w*\b', re.IGNORECASE | re.UNICODE),
    re.compile(r'\bdyrektyw\w*\s+unijn\w*\b', re.IGNORECASE | re.UNICODE),
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

        int_hit = self._check(combined, combined_lower, _INT_KW, _INT_RE)
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

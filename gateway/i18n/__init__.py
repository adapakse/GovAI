"""
Tłumaczenia tekstów zwracanych przez bramkę (błędy HTTP, powody blokad w audycie).

Odpowiednik api/i18n/__init__.py — bramka to osobny obraz Dockera i nie importuje
kodu z api/, więc logika jest skopiowana. Trzymaj obie wersje (LOCALES, t, match_locale)
w synchronizacji, a także z frontend/i18n/locales.ts i CHECK users.locale
w db/migrations/012_i18n.sql.

Pliki: gateway/i18n/locales/<locale>/<namespace>.json — zagnieżdżony JSON, parametry
w pojedynczych klamrach ({name}, str.format). Polski jest językiem źródłowym
i zapasowym. Język żądania ustawia LocaleMiddleware (main.py) z nagłówka
Accept-Language, a gdy go brak — z app_settings i18n.default_locale.
"""
from __future__ import annotations

import json
import logging
from contextvars import ContextVar
from functools import lru_cache
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

LOCALES: tuple[str, ...] = ("pl", "en", "de", "it", "es", "fr", "ro", "ru", "sl", "hr")
DEFAULT_LOCALE = "pl"

# Nazwy języków po angielsku — do promptów LLM ("Respond in {language}").
LANGUAGE_NAMES_EN: dict[str, str] = {
    "pl": "Polish", "en": "English", "de": "German", "it": "Italian", "es": "Spanish",
    "fr": "French", "ro": "Romanian", "ru": "Russian", "sl": "Slovenian", "hr": "Croatian",
}

_LOCALES_DIR = Path(__file__).parent / "locales"
_current_locale: ContextVar[str] = ContextVar("govai_gateway_locale", default=DEFAULT_LOCALE)


def is_locale(value: Any) -> bool:
    return isinstance(value, str) and value in LOCALES


def match_locale(header: Optional[str]) -> Optional[str]:
    """Pierwszy obsługiwany język z nagłówka Accept-Language (bez wag q)."""
    if not header:
        return None
    for part in header.split(","):
        code = part.split(";")[0].strip()[:2].lower()
        if code in LOCALES:
            return code
    return None


def set_locale(locale: str) -> None:
    _current_locale.set(locale if is_locale(locale) else DEFAULT_LOCALE)


def get_locale() -> str:
    return _current_locale.get()


def language_name_en(locale: Optional[str] = None) -> str:
    return LANGUAGE_NAMES_EN[locale or get_locale()]


@lru_cache(maxsize=None)
def _catalog(locale: str) -> dict[str, Any]:
    merged: dict[str, Any] = {}
    folder = _LOCALES_DIR / locale
    if not folder.is_dir():
        return merged
    for path in sorted(folder.glob("*.json")):
        try:
            merged[path.stem] = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            logger.error("Błąd wczytywania tłumaczeń %s: %s", path, exc)
    return merged


def _lookup(catalog: dict[str, Any], key: str) -> Optional[Any]:
    node: Any = catalog
    for part in key.split("."):
        if not isinstance(node, dict) or part not in node:
            return None
        node = node[part]
    return node


def t(key: str, /, locale: Optional[str] = None, **params: Any) -> str:
    """Tekst dla klucza "<namespace>.<ścieżka>" w języku żądania (lub podanym)."""
    loc = locale if is_locale(locale) else get_locale()
    value = _lookup(_catalog(loc), key)
    if not isinstance(value, str):
        value = _lookup(_catalog(DEFAULT_LOCALE), key)
    if not isinstance(value, str):
        logger.warning("Brak tłumaczenia: %s", key)
        return key
    if not params:
        return value
    try:
        return value.format(**params)
    except (KeyError, IndexError, ValueError):
        logger.warning("Błędne parametry tłumaczenia %s: %s", key, sorted(params))
        return value

"""
Selector providera LLM — wybiera optymalnego dostawcę na podstawie:
  - wymaganego poziomu wrażliwości danych
  - obsługiwanego model_id agenta (miękkie dopasowanie)
  - priorytetu (niższy = preferowany)
  - aktywności i stanu zdrowia providera

Hierarchia wrażliwości (provider z higher max obsługuje wszystko poniżej):
  public(0) < internal(1) < confidential(2) < privileged(3)
"""
from __future__ import annotations

import logging
import os
from typing import Optional

from models import ProviderRecord

logger = logging.getLogger(__name__)

_SENSITIVITY_ORDER = {
    'public':       0,
    'internal':     1,
    'confidential': 2,
    'privileged':   3,
}


def _can_handle(provider_max: str, required: str) -> bool:
    """Sprawdza, czy provider może obsłużyć wymagany poziom wrażliwości."""
    return _SENSITIVITY_ORDER.get(provider_max, -1) >= _SENSITIVITY_ORDER.get(required, 0)


async def select_provider(
    model_id: str,
    sensitivity_level: str,
) -> Optional[ProviderRecord]:
    """
    Zwraca najlepszego providera dla danego model_id i poziomu wrażliwości.

    Kolejność preferencji:
    1. Aktywny, zdrowy provider obsługujący wymagany poziom wrażliwości
    2. Preferowany ten, który ma model_id agenta w swojej liście
    3. Przy remisie — niższy priorytet wygrywa
    """
    from database import get_providers_for_sensitivity
    providers = await get_providers_for_sensitivity(sensitivity_level)

    if not providers:
        logger.warning(
            "Brak aktywnych providerów dla poziomu wrażliwości '%s'", sensitivity_level
        )
        return None

    # Preferuj providera, który wprost obsługuje model_id agenta
    primary = [p for p in providers if model_id in p.model_ids]
    if primary:
        return primary[0]  # już posortowane wg priority

    # Żaden kwalifikujący się provider nie obsługuje zadeklarowanego modelu agenta.
    # Świadomie NIE podmieniamy po cichu na inny model innego providera — agent
    # zadeklarował konkretny model, a cicha podmiana dawałaby nieprzewidywalną
    # jakość odpowiedzi bez żadnego śladu poza polem model_used w audycie.
    logger.warning(
        "Model '%s' nieobsługiwany przez żadnego providera zdolnego obsłużyć "
        "wrażliwość '%s' (kandydaci: %s) — odmawiam cichej podmiany modelu.",
        model_id, sensitivity_level, ', '.join(p.name for p in providers),
    )
    return None

"""
Tłumaczenie powodów blokad z dziennika audytowego (audit_log.block_reason).

Bramka zapisuje w block_reason tekst w języku żądania (zgodność wsteczna),
a w metadata dodatkowo block_reason_code + block_reason_params (gateway/proxy.py,
gateway/policy_engine.py). Kody i polskie teksty: gateway/i18n/locales/pl/blockReasons.json
oraz api/i18n/locales/pl/blockReasons.json — trzymaj je w synchronizacji.
Stare wiersze (bez kodu) i nieznane kody zwracają oryginalny block_reason.
"""
from __future__ import annotations

import json
from typing import Any, Optional

from i18n import t_dict, t


def localize_block_reason(block_reason: Optional[str], metadata: Any) -> Optional[str]:
    """block_reason w języku żądania API, jeśli metadata niesie znany kod powodu."""
    if isinstance(metadata, str):
        # Na wypadek puli/zapytania bez kodeka jsonb (metadata jako tekst JSON).
        try:
            metadata = json.loads(metadata)
        except (TypeError, ValueError):
            return block_reason
    if not isinstance(metadata, dict):
        return block_reason

    code = metadata.get("block_reason_code")
    if not isinstance(code, str) or code not in t_dict("blockReasons"):
        return block_reason

    params = metadata.get("block_reason_params")
    params = {str(k): v for k, v in params.items()} if isinstance(params, dict) else {}
    try:
        return t(f"blockReasons.{code}", **params)
    except TypeError:
        # Parametr o nazwie kolidującej z argumentem t() (np. "locale") — zostaw oryginał.
        return block_reason

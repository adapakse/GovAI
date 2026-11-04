"""
Klient Anthropic dla raportów i klasyfikatora AI Act.

Organizacja z aktywnym własnym providerem typu anthropic z własnym kluczem
(providers.api_key_encrypted) — jej klucz (i base_url, jeśli podany);
w przeciwnym razie klucz platformy (ANTHROPIC_API_KEY).
Organizacja z kontekstu bazy (tenant_db) — poza nim zawsze klucz platformy.
"""
from __future__ import annotations

import logging

import anthropic

from config import settings
from database import current_tenant_id, get_pool
from services import secret_box

logger = logging.getLogger(__name__)


async def _tenant_anthropic_provider():
    if current_tenant_id() is None:
        return None
    return await get_pool().fetchrow(
        """SELECT id, base_url, api_key_encrypted FROM providers
           WHERE tenant_id = current_tenant_id()
             AND provider_type = 'anthropic' AND active
             AND api_key_encrypted IS NOT NULL
           ORDER BY priority ASC, created_at ASC
           LIMIT 1""",
    )


async def anthropic_client() -> anthropic.AsyncAnthropic:
    try:
        row = await _tenant_anthropic_provider()
    except Exception:
        logger.exception("Nie udało się odczytać providera organizacji — klucz platformy")
        row = None
    if row:
        try:
            key = secret_box.decrypt(row["api_key_encrypted"])
            kwargs = {"api_key": key}
            if row["base_url"]:
                kwargs["base_url"] = row["base_url"]
            return anthropic.AsyncAnthropic(**kwargs)
        except secret_box.SecretBoxError:
            logger.error("Nie udało się odszyfrować klucza providera %s — klucz platformy", row["id"])
    return anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)

"""GovAIConfig i GovAIClient — rdzeń SDK."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

import httpx


@dataclass
class GovAIConfig:
    """Konfiguracja połączenia z GovAI.

    gateway_url  — adres bramki (domyślnie localhost:8001)
    api_url      — adres API panelu (domyślnie localhost:8000)
    agent_id     — UUID agenta zarejestrowanego w GovAI (wymagany)
    api_token    — JWT do API panelu (potrzebny do pollingu oversight)
    """
    gateway_url: str = "http://localhost:8001"
    api_url: str = "http://localhost:8000"
    agent_id: str = ""
    api_token: str = ""

    @property
    def gateway_v1(self) -> str:
        return f"{self.gateway_url}/v1"

    @property
    def default_headers(self) -> dict[str, str]:
        h = {"X-Agent-ID": self.agent_id}
        if self.api_token:
            h["Authorization"] = f"Bearer {self.api_token}"
        return h


class GovAIClient:
    """Klient HTTP do API panelu GovAI (nie do bramki)."""

    def __init__(self, config: GovAIConfig) -> None:
        self.config = config

    async def get_oversight(self, oversight_id: str) -> dict:
        """Pobiera aktualny status zadania nadzoru."""
        async with httpx.AsyncClient() as client:
            r = await client.get(
                f"{self.config.api_url}/oversight/{oversight_id}",
                headers=self.config.default_headers,
                timeout=10.0,
            )
            r.raise_for_status()
            return r.json()

    async def wait_for_oversight(
        self,
        oversight_id: str,
        *,
        poll_interval: float = 5.0,
        timeout: float = 3600.0,
    ) -> dict:
        """Czeka (polling) na decyzję recenzenta.

        Zwraca rekord oversight gdy status != 'pending'.
        Rzuca TimeoutError po przekroczeniu timeout.
        """
        elapsed = 0.0
        while elapsed < timeout:
            record = await self.get_oversight(oversight_id)
            if record.get("status") != "pending":
                return record
            await asyncio.sleep(poll_interval)
            elapsed += poll_interval
        raise TimeoutError(
            f"Oversight {oversight_id} nie został rozstrzygnięty w ciągu {timeout:.0f}s"
        )

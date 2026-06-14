"""Bazowa klasa agenta — wysyła wywołania przez bramkę GovAI."""
import os
import uuid
from typing import Any

import httpx

GATEWAY_URL = os.getenv("GATEWAY_URL", "http://localhost:8001")


class BaseAgent:
    def __init__(self, agent_id: str, name: str, system_prompt: str) -> None:
        self.agent_id = agent_id
        self.name = name
        self.system_prompt = system_prompt

    def _headers(self, task_id: str) -> dict:
        return {
            "X-Agent-ID": self.agent_id,
            "X-Task-ID": task_id,
            "Content-Type": "application/json",
        }

    async def call(self, user_message: str, task_id: str | None = None) -> dict[str, Any]:
        task_id = task_id or str(uuid.uuid4())
        payload = {
            "messages": [
                {"role": "system", "content": self.system_prompt},
                {"role": "user", "content": user_message},
            ],
            "max_tokens": 512,
        }
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                f"{GATEWAY_URL}/v1/chat/completions",
                json=payload,
                headers=self._headers(task_id),
            )
        return resp.json()

"""Integracja GovAI z LangChain.

Dwa mechanizmy (można stosować razem):

1. create_govai_llm() — przekierowuje base_url do bramki GovAI.
   Bramka wykonuje PII, polityki, routing i audyt transparentnie.
   Zero zmian w logice łańcucha — wystarczy podmienić instancję LLM.

2. GovAICallbackHandler — loguje kroki workflow (wywołania narzędzi,
   przejścia między łańcuchami) do stdout/loggera. Wywołania LLM są
   już logowane przez bramkę — handler pokrywa pozostałe zdarzenia.
"""
from __future__ import annotations

import logging
from typing import Any, Optional
from uuid import uuid4

from govai_sdk.client import GovAIConfig

logger = logging.getLogger(__name__)


def create_govai_llm(
    model: str,
    config: GovAIConfig,
    **kwargs: Any,
):
    """Zwraca ChatOpenAI skierowane na bramkę GovAI.

    Bramka jest w pełni zgodna z OpenAI Chat Completions API, więc
    LangChain nie widzi różnicy — routing, PII i audyt dzieją się w tle.

    Przykład:
        config = GovAIConfig(agent_id="a1000000-...")
        llm = create_govai_llm("claude-sonnet-4-6", config)
        chain = prompt | llm | parser
    """
    try:
        from langchain_openai import ChatOpenAI
    except ImportError as e:
        raise ImportError(
            "govai-sdk[langchain] wymagane: pip install govai-sdk[langchain]"
        ) from e

    return ChatOpenAI(
        model=model,
        base_url=config.gateway_v1,
        api_key="govai",  # bramka ignoruje api_key; autoryzacja przez X-Agent-ID
        default_headers={"X-Agent-ID": config.agent_id},
        **kwargs,
    )


class GovAICallbackHandler:
    """LangChain callback — loguje zdarzenia workflow poza wywołaniami LLM.

    Wywołania LLM są już w pełni logowane przez bramkę GovAI (PII, polityki,
    koszt, audit). Ten handler uzupełnia ślad o wywołania narzędzi i
    przejścia między łańcuchami.

    Użycie:
        handler = GovAICallbackHandler(config, task_id="opcjonalny-uuid")
        chain.invoke(input, config={"callbacks": [handler]})
    """

    def __init__(self, config: GovAIConfig, task_id: Optional[str] = None) -> None:
        self.config = config
        self.task_id = task_id or str(uuid4())

    # ── LLM ──────────────────────────────────────────────────────────────────

    def on_llm_start(
        self, serialized: dict, prompts: list[str], **kwargs: Any
    ) -> None:
        logger.info(
            "[GovAI] llm_start | agent=%s task=%s | model=%s | %d prompts",
            self.config.agent_id,
            self.task_id,
            serialized.get("name", "?"),
            len(prompts),
        )

    def on_llm_end(self, response: Any, **kwargs: Any) -> None:
        logger.info(
            "[GovAI] llm_end | agent=%s task=%s | generations=%d",
            self.config.agent_id,
            self.task_id,
            len(response.generations),
        )

    def on_llm_error(self, error: BaseException, **kwargs: Any) -> None:
        logger.error("[GovAI] llm_error | agent=%s | %s", self.config.agent_id, error)

    # ── Narzędzia (tool calls) ────────────────────────────────────────────────

    def on_tool_start(
        self, serialized: dict, input_str: str, **kwargs: Any
    ) -> None:
        logger.info(
            "[GovAI] tool_start | agent=%s task=%s | tool=%s | input=%.150s",
            self.config.agent_id,
            self.task_id,
            serialized.get("name", "?"),
            input_str,
        )

    def on_tool_end(self, output: str, **kwargs: Any) -> None:
        logger.info(
            "[GovAI] tool_end | agent=%s task=%s | output=%.150s",
            self.config.agent_id,
            self.task_id,
            output,
        )

    def on_tool_error(self, error: BaseException, **kwargs: Any) -> None:
        logger.warning(
            "[GovAI] tool_error | agent=%s task=%s | %s",
            self.config.agent_id,
            self.task_id,
            error,
        )

    # ── Łańcuch ───────────────────────────────────────────────────────────────

    def on_chain_start(
        self, serialized: dict, inputs: dict, **kwargs: Any
    ) -> None:
        logger.debug(
            "[GovAI] chain_start | %s | agent=%s",
            serialized.get("name", "?"),
            self.config.agent_id,
        )

    def on_chain_end(self, outputs: dict, **kwargs: Any) -> None:
        logger.debug("[GovAI] chain_end | agent=%s", self.config.agent_id)

    def on_chain_error(self, error: BaseException, **kwargs: Any) -> None:
        logger.error("[GovAI] chain_error | agent=%s | %s", self.config.agent_id, error)

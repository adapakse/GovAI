"""Integracja GovAI z Semantic Kernel.

Dwa mechanizmy (można stosować razem):

1. create_govai_service() — tworzy OpenAIChatCompletion wskazujące na bramkę GovAI.
   Bramka jest zgodna z OpenAI API, więc SK nie wymaga żadnych zmian logiki.

2. GovAIKernelFilter — filtr SK logujący wywołania funkcji/pluginów do loggera.
   Wywołania LLM są już logowane przez bramkę.

Użycie:
    from semantic_kernel import Kernel
    from govai_sdk import GovAIConfig
    from govai_sdk.semantic_kernel import create_govai_service, GovAIKernelFilter

    config = GovAIConfig(agent_id="a1000000-...")

    kernel = Kernel()
    kernel.add_service(create_govai_service("claude-sonnet-4-6", config))
    kernel.add_filter(GovAIKernelFilter.filter_type, GovAIKernelFilter(config))
"""
from __future__ import annotations

import logging
from typing import Any

from govai_sdk.client import GovAIConfig

logger = logging.getLogger(__name__)


def create_govai_service(model: str, config: GovAIConfig, service_id: str = "govai"):
    """Zwraca OpenAIChatCompletion SK wskazujące na bramkę GovAI.

    Bramka jest w pełni zgodna z OpenAI Chat Completions API —
    SK nie odróżnia jej od bezpośredniego połączenia z OpenAI.
    PII, polityki i audyt dzieją się transparentnie w bramce.
    """
    try:
        from openai import AsyncOpenAI
        from semantic_kernel.connectors.ai.open_ai import OpenAIChatCompletion
    except ImportError as e:
        raise ImportError(
            "govai-sdk[semantic-kernel] wymagane: pip install govai-sdk[semantic-kernel]"
        ) from e

    client = AsyncOpenAI(
        base_url=config.gateway_v1,
        api_key="govai",  # bramka ignoruje api_key; autoryzacja przez X-Agent-ID
        default_headers={"X-Agent-ID": config.agent_id},
    )
    return OpenAIChatCompletion(
        ai_model_id=model,
        async_client=client,
        service_id=service_id,
    )


class GovAIKernelFilter:
    """Semantic Kernel filter logujący wywołania pluginów/funkcji.

    Wywołania LLM są już logowane przez bramkę GovAI. Ten filtr pokrywa
    wywołania pluginów (native functions, semantic functions) w SK.

    Rejestracja:
        kernel.add_filter(GovAIKernelFilter.filter_type, GovAIKernelFilter(config))
    """

    try:
        from semantic_kernel.filters.filter_types import FilterTypes
        filter_type = FilterTypes.FUNCTION_INVOCATION
    except ImportError:
        filter_type = "function_invocation"  # fallback dla type checkerów

    def __init__(self, config: GovAIConfig) -> None:
        self.config = config

    async def on_function_invocation(
        self, context: Any, next: Any
    ) -> None:
        fn = getattr(context, "function", None)
        plugin = getattr(fn, "plugin_name", "?") if fn else "?"
        name = getattr(fn, "name", "?") if fn else "?"

        logger.info(
            "[GovAI] sk_function_start | agent=%s | %s/%s",
            self.config.agent_id,
            plugin,
            name,
        )
        try:
            await next(context)
        except Exception as exc:
            logger.error(
                "[GovAI] sk_function_error | agent=%s | %s/%s | %s",
                self.config.agent_id, plugin, name, exc,
            )
            raise

        logger.info(
            "[GovAI] sk_function_end | agent=%s | %s/%s",
            self.config.agent_id, plugin, name,
        )

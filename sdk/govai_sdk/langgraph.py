"""Integracja GovAI z LangGraph.

GovAIApprovalNode — węzeł grafu zatrzymujący wykonanie do momentu
zatwierdzenia przez człowieka przez kolejkę nadzoru GovAI (art. 14 AI Act).

Przepływ:
  1. Poprzedni węzeł wywołuje bramkę GovAI przez create_govai_llm().
  2. Bramka — jeśli agent ma wymóg nadzoru — zwraca {"status": "awaiting_oversight",
     "oversight_id": "..."} zamiast odpowiedzi.
  3. Węzeł poprzedni odkłada oversight_id do stanu grafu.
  4. GovAIApprovalNode() polluje API panelu do momentu decyzji recenzenta.
  5. Wynik (approved/rejected/escalated) trafia do stanu jako "oversight_result".
  6. Graf decyduje co dalej na podstawie "oversight_result.action".

Użycie:
    from langgraph.graph import StateGraph
    from govai_sdk.langgraph import govai_approval_node, GovAIConfig

    config = GovAIConfig(agent_id="...", api_token="...")

    def agent_node(state): ...      # wywołuje create_govai_llm
    def approval_node(state):       # węzeł oczekiwania
        return govai_approval_node(state, config)
    def finalize_node(state): ...   # state["oversight_result"]["action"] == "approved"

    g = StateGraph(MyState)
    g.add_node("agent", agent_node)
    g.add_node("approval", approval_node)
    g.add_node("finalize", finalize_node)
    g.add_edge("agent", "approval")
    g.add_conditional_edges(
        "approval",
        lambda s: s["oversight_result"]["action"],
        {"approved": "finalize", "rejected": END},
    )
"""
from __future__ import annotations

import asyncio
from typing import Any

from govai_sdk.client import GovAIClient, GovAIConfig


async def govai_approval_node(
    state: dict[str, Any],
    config: GovAIConfig,
    *,
    poll_interval: float = 5.0,
    timeout: float = 3600.0,
) -> dict[str, Any]:
    """Węzeł LangGraph: czeka na decyzję recenzenta GovAI.

    Wymaga state["oversight_id"] — ustaw go w poprzednim węźle po
    otrzymaniu {"status": "awaiting_oversight", "oversight_id": "..."} z bramki.

    Zwraca zaktualizowany stan z:
      oversight_result.action  — "approved" | "rejected" | "escalated"
      oversight_result.comment — opcjonalny komentarz recenzenta
    """
    oversight_id = state.get("oversight_id")
    if not oversight_id:
        raise ValueError(
            "govai_approval_node wymaga state['oversight_id']. "
            "Ustaw go po otrzymaniu awaiting_oversight z bramki GovAI."
        )

    client = GovAIClient(config)
    result = await client.wait_for_oversight(
        oversight_id, poll_interval=poll_interval, timeout=timeout
    )

    return {
        **state,
        "oversight_result": {
            "action": result.get("status"),       # approved / rejected / escalated
            "comment": result.get("reviewer_decision"),
            "reviewed_at": result.get("reviewed_at"),
            "oversight_id": oversight_id,
        },
    }


def govai_approval_node_sync(
    state: dict[str, Any],
    config: GovAIConfig,
    **kwargs: Any,
) -> dict[str, Any]:
    """Synchroniczna wersja govai_approval_node dla grafów bez async."""
    return asyncio.run(govai_approval_node(state, config, **kwargs))

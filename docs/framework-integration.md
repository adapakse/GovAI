# GovAI — Integracja frameworków AI

Przewodnik jak podłączyć agentów zbudowanych na popularnych frameworkach do bramki GovAI
bez przepisywania logiki agenta.

---

## Dlaczego integracja jest nietrywalna

GovAI przechwytuje **wywołania HTTP do chmurowych LLM**. Frameworki AI wprowadzają dwa
nowe przypadki, których sama bramka HTTP nie obsługuje:

| Typ | Przykłady | Problem |
|-----|-----------|---------|
| **Lokalne inference** | PyTorch, TensorFlow, HuggingFace local, llama.cpp | Brak wywołania HTTP — model działa w procesie, bramka go nie widzi |
| **Orkiestracja** | LangChain, LangGraph, Semantic Kernel, CrewAI | Jeden przepływ = wiele wywołań LLM + tool calls; nadzór powinien być na poziomie wyniku, nie każdego kroku |

---

## Strategia

### 1. Lokalne modele → wymagaj serwisu HTTP

**Zasada:** lokalne modele muszą być wystawione jako serwis HTTP zgodny z OpenAI API.
Bramka GovAI obsługuje je wtedy tak samo jak chmurowych dostawców.

Gotowe serwery:

| Serwer | Modele | Endpoint |
|--------|--------|----------|
| **Ollama** | Llama 3, Mistral, Bielik, Phi | `http://ollama:11434` |
| **vLLM** | dowolny model HuggingFace | `http://vllm:8000/v1` |
| **Triton Inference Server** | PyTorch, TensorFlow (ONNX) | `http://triton:8001/v2` + adapter |
| **llama.cpp server** | GGUF modele | `http://localhost:8080/v1` |

Rejestracja w GovAI (panel → Providerzy lub INSERT do `providers`):

```sql
INSERT INTO providers (name, provider_type, model_ids, base_url, max_data_sensitivity, priority, active)
VALUES (
    'Bielik On-Prem (Ollama)',
    'ollama',
    ARRAY['bielik-11b-v2.3-instruct', 'llama3.1'],
    'http://ollama:11434',
    'privileged',   -- dane tajne OK, serwer lokalny
    1,              -- priorytet 1 = preferowany
    true
);
```

Bramka automatycznie kieruje zapytania z danymi `confidential`/`privileged` do tego serwera.

---

### 2. Frameworki orkiestracji → base_url redirect

**Zasada:** każdy framework przyjmuje `base_url` dla klienta OpenAI. Wystarczy go przestawić
na bramkę GovAI — framework nie wie, że przechodzi przez proxy.

Bramka dostaje każde wywołanie LLM, skanuje PII, sprawdza polityki i loguje.

#### LangChain

```python
from langchain_openai import ChatOpenAI

llm = ChatOpenAI(
    model="claude-sonnet-4-6",
    base_url="http://localhost:8001/v1",
    api_key="govai",                          # bramka ignoruje; autoryzacja przez nagłówek
    default_headers={"X-Agent-ID": "a1000000-0000-0000-0000-000000000001"},
)

# Reszta kodu agenta bez zmian:
chain = prompt | llm | output_parser
result = chain.invoke({"input": "..."})
```

#### LangGraph

```python
from langgraph.graph import StateGraph
from langchain_openai import ChatOpenAI

llm = ChatOpenAI(
    model="claude-sonnet-4-6",
    base_url="http://localhost:8001/v1",
    api_key="govai",
    default_headers={"X-Agent-ID": "a2000000-0000-0000-0000-000000000002"},
)

def agent_node(state):
    response = llm.invoke(state["messages"])
    # Jeśli agent ma wymóg nadzoru, bramka zwróci awaiting_oversight
    if isinstance(response, dict) and response.get("status") == "awaiting_oversight":
        return {**state, "oversight_id": response["oversight_id"]}
    return {**state, "messages": [*state["messages"], response]}
```

#### Semantic Kernel

```python
from openai import AsyncOpenAI
from semantic_kernel.connectors.ai.open_ai import OpenAIChatCompletion
from semantic_kernel import Kernel

client = AsyncOpenAI(
    base_url="http://localhost:8001/v1",
    api_key="govai",
    default_headers={"X-Agent-ID": "a1000000-0000-0000-0000-000000000001"},
)

kernel = Kernel()
kernel.add_service(OpenAIChatCompletion(ai_model_id="claude-sonnet-4-6", async_client=client))
```

---

### 3. govai-sdk — gotowe helpery

Paczka `sdk/` zawiera gotowe wrapery dla LangChain, LangGraph i Semantic Kernel.

```bash
pip install -e ./sdk                    # podstawowe
pip install -e "./sdk[langchain]"       # + langchain-openai
pip install -e "./sdk[langgraph]"       # + langgraph
pip install -e "./sdk[semantic-kernel]" # + semantic-kernel
```

#### LangChain — create_govai_llm

```python
from govai_sdk import GovAIConfig
from govai_sdk.langchain import create_govai_llm, GovAICallbackHandler

config = GovAIConfig(
    agent_id="a1000000-0000-0000-0000-000000000001",
    api_token="eyJ...",  # JWT z POST /auth/login
)

llm = create_govai_llm("claude-sonnet-4-6", config)
handler = GovAICallbackHandler(config)

chain = prompt | llm | parser
result = chain.invoke({"input": "..."}, config={"callbacks": [handler]})
```

`GovAICallbackHandler` loguje wywołania narzędzi i przejścia między łańcuchami.
Wywołania LLM są logowane przez bramkę — bez podwójnego zapisu.

#### LangGraph — nadzór człowieka (art. 14)

```python
from langgraph.graph import StateGraph, END
from govai_sdk import GovAIConfig
from govai_sdk.langchain import create_govai_llm
from govai_sdk.langgraph import govai_approval_node

config = GovAIConfig(agent_id="a2000000-...", api_token="eyJ...")
llm = create_govai_llm("claude-sonnet-4-6", config)

async def credit_agent_node(state):
    response = await llm.ainvoke(state["messages"])
    # Bramka zwraca awaiting_oversight dla agenta wysokiego ryzyka
    if hasattr(response, "content") and "awaiting_oversight" in str(response):
        import json
        data = json.loads(response.content)
        return {**state, "oversight_id": data["oversight_id"]}
    return {**state, "messages": [*state["messages"], response], "oversight_id": None}

async def approval_node(state):
    # Czeka na decyzję recenzenta — polling co 5 sekund, timeout 1h
    return await govai_approval_node(state, config)

def should_continue(state):
    if state.get("oversight_id"):
        return "approval"
    return "finalize"

g = StateGraph(dict)
g.add_node("agent", credit_agent_node)
g.add_node("approval", approval_node)
g.add_node("finalize", lambda s: s)
g.set_entry_point("agent")
g.add_conditional_edges("agent", should_continue, {"approval": "approval", "finalize": "finalize"})
g.add_conditional_edges(
    "approval",
    lambda s: s["oversight_result"]["action"],
    {"approved": "finalize", "rejected": END, "escalated": END},
)
g.add_edge("finalize", END)

app = g.compile()
```

#### Semantic Kernel — create_govai_service

```python
from semantic_kernel import Kernel
from semantic_kernel.filters.filter_types import FilterTypes
from govai_sdk import GovAIConfig
from govai_sdk.semantic_kernel import create_govai_service, GovAIKernelFilter

config = GovAIConfig(agent_id="a1000000-...")

kernel = Kernel()
kernel.add_service(create_govai_service("claude-sonnet-4-6", config))
kernel.add_filter(FilterTypes.FUNCTION_INVOCATION, GovAIKernelFilter(config))

# Dalej normalny SK — pluginy, memory, planner bez zmian
```

---

## Co bramka robi automatycznie (dla każdego wywołania)

Bez względu na framework — jeśli wywołanie przejdzie przez `base_url` GovAI:

1. Weryfikacja agenta w rejestrze (aktywny / zawieszony)
2. Skan PII (Presidio) — maskuje PESEL, IBAN, NIP przed modelem
3. Sprawdzenie polityk — blokada lub wymóg nadzoru
4. Klasyfikacja wrażliwości danych → wybór providera
5. Wywołanie właściwego modelu (Anthropic / OpenAI / Ollama / vLLM)
6. Skan PII w odpowiedzi
7. Zapis do dziennika audytowego (TimescaleDB)

---

## Co SDK pokrywa dodatkowo

| Mechanizm | Co dodaje |
|-----------|-----------|
| `GovAICallbackHandler` | Logi tool calls i chain events (LLM call już w bramce) |
| `govai_approval_node` | Pauzowanie grafu LangGraph do decyzji recenzenta |
| `GovAIKernelFilter` | Logi wywołań pluginów SK |

---

## Nadzór człowieka w agencie orkiestracyjnym

Dla frameworków wielokrokowych (LangGraph, CrewAI, AutoGen) nadzór powinien być
**na poziomie wyniku workflow**, nie każdego wywołania LLM.

Wzorzec:
```
[krok 1] → [krok 2] → [decyzja końcowa] → GovAI Oversight Queue → [recenzent] → [wykonanie]
```

Rejestruj agenta orkiestracyjnego jako typ `high` ryzyka AI Act → bramka automatycznie
przekieruje wywołanie ostatniego kroku do kolejki nadzoru.

---

## Modele lokalne a zgodność z AI Act

Modele lokalne (Ollama, vLLM) mogą obsługiwać dane klasy `privileged` (tajemnica
adwokacka/radcowska) — żadne dane nie opuszczają sieci organizacji. Konfiguracja
w GovAI:

| `max_data_sensitivity` | Gdzie działa |
|------------------------|-------------|
| `public` | DeepSeek, inne zewnętrzne bez DPA |
| `internal` | Anthropic, OpenAI, Google (z DPA) |
| `confidential` | Chmura EU lub on-prem |
| `privileged` | Wyłącznie on-prem (Ollama, vLLM) |

Bramka dobiera providera automatycznie — agent nie musi wiedzieć, na jakim modelu działa.

---

## Checklist przed wdrożeniem

- [ ] Agent zarejestrowany w GovAI z poprawnym `risk_level` i `requires_oversight`
- [ ] `base_url` frameworka ustawiony na `http://<gateway>:8001/v1`
- [ ] Nagłówek `X-Agent-ID` zawiera UUID agenta z rejestru
- [ ] Provider lokalny (jeśli wymagany) zarejestrowany i aktywny w GovAI
- [ ] Polityki skonfigurowane dla agenta (G-001, G-002 i własne)
- [ ] Test: wywołanie z PII → `[PESEL]` w logach bramki
- [ ] Test: wywołanie blokowane → status `blocked` w dzienniku audytowym

"""
Agent Oceny Kredytowej — ryzyko WYSOKIE (Aneks III EU AI Act).
Każde wywołanie wymaga zatwierdzenia przez analityka kredytowego.
"""
import asyncio

from base_agent import BaseAgent

AGENT_ID = "a2000000-0000-0000-0000-000000000002"

SYSTEM_PROMPT = """Jesteś systemem oceny zdolności kredytowej.
Na podstawie dostarczonych danych finansowych (dochód, historia kredytowa, zobowiązania)
wydajesz rekomendację: ZATWIERDŹ / ODRZUĆ / WYMAGA_ANALIZY.
Zawsze podaj uzasadnienie i wskaż czynniki ryzyka.
Nie masz dostępu do zewnętrznych baz danych — pracujesz wyłącznie na dostarczonych danych."""

agent = BaseAgent(agent_id=AGENT_ID, name="Agent Oceny Kredytowej", system_prompt=SYSTEM_PROMPT)


async def main():
    print(f"\n{'='*60}")
    print(f"Agent: {agent.name} [WYSOKIE RYZYKO]")
    print(f"ID: {AGENT_ID}")
    print(f"Uwaga: każde wywołanie wymaga nadzoru człowieka")
    print(f"{'='*60}\n")

    wniosek = """Oceń wniosek kredytowy:
    - Wnioskowana kwota: 150 000 PLN na 240 miesięcy
    - Dochód netto wnioskodawcy: 7 500 PLN/miesiąc
    - Osoby na utrzymaniu: 2
    - Historia kredytowa: brak zaległości, 1 aktywny kredyt (rata 450 PLN)
    - Wiek: 34 lata
    - Zatrudnienie: umowa o pracę, staż 4 lata"""

    print(f"Wniosek:\n{wniosek}\n")
    result = await agent.call(wniosek)

    if result.get("status") == "awaiting_oversight":
        print(f"[NADZÓR WYMAGANY]")
        print(f"Wiadomość: {result['message']}")
        print(f"oversight_id: {result['oversight_id']}")
        print(f"\n→ Sprawdź pulpit nadzoru: http://localhost:3000/oversight")
    else:
        print(f"[WYNIK] {result}")


if __name__ == "__main__":
    asyncio.run(main())

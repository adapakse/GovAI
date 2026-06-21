"""
Repozytorium kluczy API — SQL dla tabeli api_keys używany bezpośrednio
w routerze auth (lista kluczy z JOIN agents oraz dezaktywacja).

Pozostałe operacje DB autentykacji znajdują się w services/auth_service.py.
Zwracamy surowy wynik asyncpg (.fetch -> list[Record], .execute -> str);
konwersję na dict robi router (_key_row).
Wszystkie wartości przekazywane jako parametry pozycyjne ($n) — brak interpolacji.
"""
from __future__ import annotations

from database import get_pool


async def list_api_keys() -> list:
    pool = get_pool()
    return await pool.fetch(
        """SELECT k.id, k.name, k.key_prefix, k.agent_id, a.name AS agent_name,
                  k.expires_at, k.last_used_at, k.active, k.created_at
           FROM api_keys k
           LEFT JOIN agents a ON a.id = k.agent_id
           ORDER BY k.created_at DESC""",
    )


async def deactivate_api_key(key_id: str) -> str:
    pool = get_pool()
    return await pool.execute(
        "UPDATE api_keys SET active = false WHERE id = $1", key_id,
    )

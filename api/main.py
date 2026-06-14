"""
GovAI Backend API — stub dla Tygodnia 1-2.
Pełna implementacja w Tygodniu 3 (rejestr agentów, polityki, nadzór, raporty).
"""
import asyncpg
import os
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://govai:govai_secret@localhost:5432/govai")
_pool = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _pool
    _pool = await asyncpg.create_pool(dsn=DATABASE_URL, min_size=2, max_size=10)
    yield
    if _pool:
        await _pool.close()


app = FastAPI(title="GovAI API", version="0.1.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


@app.get("/")
async def root():
    return {"service": "GovAI API", "version": "0.1.0", "status": "stub — implementacja Tydzień 3"}


@app.get("/health")
async def health():
    try:
        await _pool.fetchval("SELECT 1")
        db = "ok"
    except Exception as e:
        db = f"error: {e}"
    return {"status": "ok" if db == "ok" else "degraded", "postgres": db}


@app.get("/agents")
async def list_agents():
    rows = await _pool.fetch(
        "SELECT id, name, status, risk_level, requires_oversight, team, owner_name FROM agents ORDER BY name"
    )
    return [dict(r) for r in rows]


@app.get("/agents/{agent_id}")
async def get_agent(agent_id: str):
    row = await _pool.fetchrow("SELECT * FROM agents WHERE id = $1", agent_id)
    if not row:
        from fastapi import HTTPException
        raise HTTPException(404, "Agent nie znaleziony")
    return dict(row)


@app.get("/audit")
async def list_audit(limit: int = 50):
    rows = await _pool.fetch(
        """SELECT time, agent_name, event_type, policy_result,
                  pii_categories, pii_count, latency_ms, block_reason
           FROM audit_log
           ORDER BY time DESC
           LIMIT $1""",
        limit,
    )
    return [dict(r) for r in rows]


@app.get("/oversight/pending")
async def list_pending():
    rows = await _pool.fetch(
        """SELECT oq.id, oq.agent_id, a.name as agent_name, oq.task_id,
                  oq.agent_decision, oq.status, oq.ttl_expires_at, oq.created_at
           FROM oversight_queue oq
           JOIN agents a ON a.id = oq.agent_id
           WHERE oq.status = 'pending'
           ORDER BY oq.created_at""",
    )
    return [dict(r) for r in rows]

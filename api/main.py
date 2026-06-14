import logging
from contextlib import asynccontextmanager

import redis.asyncio as aioredis
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from config import settings
from database import close_pool, init_pool
from routers import agents, audit, dashboard, oversight, policies
from routers.dashboard import set_redis

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("GovAI API uruchamiana...")
    await init_pool()

    redis = await aioredis.from_url(settings.redis_url, decode_responses=True)
    set_redis(redis)

    logger.info("GovAI API gotowa")
    yield

    await close_pool()
    await redis.aclose()
    logger.info("GovAI API zatrzymana")


app = FastAPI(
    redirect_slashes=False,
    title="GovAI API",
    description=(
        "Backend API platformy GovAI — zarządzanie agentami AI zgodnie z EU AI Act. "
        "Rejestr agentów, polityki, nadzór człowieka, dziennik audytowy."
    ),
    version="0.2.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(agents.router)
app.include_router(policies.router)
app.include_router(oversight.router)
app.include_router(audit.router)
app.include_router(dashboard.router)


@app.get("/")
async def root():
    return {
        "service": "GovAI API",
        "version": "0.2.0",
        "docs": "/docs",
        "endpoints": {
            "agents":    "GET/POST /agents",
            "policies":  "GET/POST /policies",
            "oversight": "GET /oversight/pending",
            "audit":     "GET /audit",
            "dashboard": "GET /dashboard/summary",
            "ws":        "WS /ws/live-feed",
        },
    }


@app.get("/health")
async def health():
    from database import get_pool
    try:
        await get_pool().fetchval("SELECT 1")
        db = "ok"
    except Exception as e:
        db = f"error: {e}"
    return {"status": "ok" if db == "ok" else "degraded", "postgres": db, "version": "0.2.0"}

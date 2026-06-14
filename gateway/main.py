import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from config import settings
from database import close_pool, init_pool
from oversight import close_redis, init_redis, ttl_monitor_loop
from pii_scanner import PIIScanner
from policy_engine import PolicyEngine
from proxy import handle_chat_completion, init_components

logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("GovAI Gateway uruchamiana...")

    await init_pool()
    await init_redis()

    pii = PIIScanner()
    policy = PolicyEngine()
    init_components(pii, policy)

    monitor_task = asyncio.create_task(ttl_monitor_loop())
    logger.info("GovAI Gateway gotowa — nasłuchuje na porcie 8001")

    yield

    monitor_task.cancel()
    try:
        await monitor_task
    except asyncio.CancelledError:
        pass

    await close_pool()
    await close_redis()
    logger.info("GovAI Gateway zatrzymana")


app = FastAPI(
    title="GovAI Security Gateway",
    description=(
        "Bramka bezpieczeństwa AI — każde wywołanie agenta jest skanowane pod kątem PII, "
        "oceniane przez silnik polityk i rejestrowane w dzienniku audytowym zgodnym z EU AI Act."
    ),
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.post("/v1/chat/completions")
async def chat_completions(request: Request):
    """
    Główny endpoint bramki — kompatybilny z OpenAI Chat Completions API.
    Agenci wysyłają tu wywołania zamiast bezpośrednio do dostawcy modelu.

    Wymagane nagłówki:
    - X-Agent-ID: UUID agenta z rejestru GovAI
    - X-Task-ID: (opcjonalny) identyfikator zadania dla korelacji logów
    """
    return await handle_chat_completion(request)


@app.get("/health")
async def health():
    """Status zdrowia bramki i jej zależności."""
    from database import get_pool
    from oversight import get_redis

    checks = {}

    try:
        pool = get_pool()
        await pool.fetchval("SELECT 1")
        checks["postgres"] = "ok"
    except Exception as exc:
        checks["postgres"] = f"error: {exc}"

    try:
        redis = get_redis()
        await redis.ping()
        checks["redis"] = "ok"
    except Exception as exc:
        checks["redis"] = f"error: {exc}"

    checks["pii_scanner"] = "ok"
    checks["policy_engine"] = "ok"

    overall = "healthy" if all(v == "ok" for v in checks.values()) else "degraded"
    return {"status": overall, "checks": checks, "version": "0.1.0"}


@app.get("/")
async def root():
    return {
        "service": "GovAI Security Gateway",
        "version": "0.1.0",
        "docs": "/docs",
        "health": "/health",
        "endpoint": "POST /v1/chat/completions",
    }

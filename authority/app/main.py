"""ZLP License Authority - FastAPI application"""
import os
import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import logging
from alembic.config import Config
from alembic import command as alembic_command

from .database import engine
from .routers import health, activate, heartbeat, revoke, status, dashboard, billing
from .scheduler import start_scheduler, stop_scheduler

logger = logging.getLogger(__name__)


def _run_alembic_upgrade() -> None:
    cfg = Config("alembic.ini")
    alembic_command.upgrade(cfg, "head")


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting ZLP License Authority")
    await asyncio.to_thread(_run_alembic_upgrade)
    logger.info("Database migrations applied")
    start_scheduler()
    yield
    stop_scheduler()
    logger.info("Shutting down ZLP License Authority")
    await engine.dispose()


app = FastAPI(
    title="ZLP License Authority",
    description="Internal licensing infrastructure for self-hosted Zen products",
    version="1.0.0",
    lifespan=lifespan,
)

_cors_origins = [
    o.strip()
    for o in os.getenv("CORS_ORIGINS", "http://localhost:5173,http://localhost:3000").split(",")
    if o.strip()
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router, tags=["health"])
app.include_router(activate.router, tags=["activation"], prefix="/v1")
app.include_router(heartbeat.router, tags=["heartbeat"], prefix="/v1")
app.include_router(revoke.router, tags=["management"], prefix="/v1")
app.include_router(status.router, tags=["management"], prefix="/v1")
app.include_router(dashboard.router, tags=["dashboard"])
app.include_router(billing.router, tags=["billing"], prefix="/v1")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)

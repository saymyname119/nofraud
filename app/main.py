"""
app/main.py — FastAPI Application and Dependency Injection.

Spec §10.1:
  - 100% of I/O lives in the API route handler or its direct delegates.
  - The scoring and decision core remain pure functions.
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.api import webhooks
from app.database import init_db, get_session
from app.config import get_settings

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    logger.info("Starting FraudSpike API...")
    await init_db()
    yield
    # Shutdown
    logger.info("Shutting down FraudSpike API...")


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="FraudSpike",
        version="1.0.0",
        lifespan=lifespan,
        debug=settings.environment == "development"
    )

    app.include_router(webhooks.router, prefix="/api/v1/webhooks", tags=["Webhooks"])
    return app

app = create_app()

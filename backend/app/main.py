"""FastAPI application factory.

Run:  uvicorn app.main:app --reload
"""
import asyncio
import logging
from contextlib import asynccontextmanager, suppress
from typing import AsyncIterator, Optional

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.router import api_router
from app.core.config import settings
from app.core.exceptions import register_exception_handlers
from app.core.i18n import LocaleMiddleware, get_locale
from app.schemas.common import ok
from app.tasks.scheduler import sla_penalty_loop

logging.basicConfig(level=logging.DEBUG if settings.DEBUG else logging.INFO)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    sla_task: Optional[asyncio.Task] = None
    if settings.SLA_JOB_ENABLED:
        sla_task = asyncio.create_task(sla_penalty_loop(settings.SLA_JOB_INTERVAL_SECONDS))
    yield
    if sla_task is not None:
        sla_task.cancel()
        with suppress(asyncio.CancelledError):
            await sla_task


def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.APP_NAME,
        version=settings.APP_VERSION,
        description=(
            "B2B Security Manpower Marketplace. Send `Accept-Language: ar` (or `?lang=ar`) "
            "to receive every message and label in Arabic."
        ),
        openapi_url=f"{settings.API_V1_PREFIX}/openapi.json",
        docs_url="/docs",
        redoc_url="/redoc",
        lifespan=lifespan,
    )

    # CORS_ORIGINS defaults to ["*"] so index.html works even when opened from disk (Origin: null).
    # Browsers reject a wildcard origin with credentials; auth uses Bearer headers, not cookies.
    allow_all_origins = "*" in settings.CORS_ORIGINS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"] if allow_all_origins else settings.CORS_ORIGINS,
        allow_credentials=not allow_all_origins,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["Content-Language"],
    )
    # Added last = outermost: the locale is resolved before anything else runs.
    app.add_middleware(LocaleMiddleware)
    register_exception_handlers(app)

    app.include_router(api_router, prefix=settings.API_V1_PREFIX)

    @app.get("/health", tags=["Health"])
    def health():
        return ok({"status": "ok", "locale": get_locale(), "version": settings.APP_VERSION}, "common.healthy")

    return app


app = create_app()

import logging
import time

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.router import api_router
from app.core.config import settings
from app.core.limiter import limiter
from app.core.logging import setup_logging
from app.middleware.exception_handlers import init_exception_handlers

setup_logging()
logger = logging.getLogger("event_ledger")


def create_app() -> FastAPI:
    app = FastAPI(
        title="Event Ledger Service",
        description="Payment lifecycle event ingestion and reconciliation API",
        version="1.0.0",
        docs_url="/docs",
        redoc_url="/redoc",
        debug=settings.APP_DEBUG,
    )

    # --- Rate limiter (Redis-backed when REDIS_ENABLED=true) ---
    app.state.limiter = limiter

    # --- Exception handlers (includes rate limit handler) ---
    init_exception_handlers(app)

    # --- CORS ---
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"] if not settings.is_production else [],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # --- Request logging middleware ---
    @app.middleware("http")
    async def log_requests(request: Request, call_next) -> Response:
        start = time.perf_counter()
        response = await call_next(request)
        duration_ms = (time.perf_counter() - start) * 1000
        logger.info(
            "%s %s %d %.1fms",
            request.method,
            request.url.path,
            response.status_code,
            duration_ms,
        )
        return response

    # --- Routes ---
    app.include_router(api_router)

    @app.on_event("startup")
    async def on_startup() -> None:
        logger.info("Event Ledger Service starting — env=%s", settings.APP_ENV)

    @app.on_event("shutdown")
    async def on_shutdown() -> None:
        logger.info("Event Ledger Service shutting down")

    return app


app = create_app()


from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.routes import jobs
from app.core.config import settings
from app.core.logging import configure_logging, get_logger

# Configure logging as early as possible
configure_logging()
logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """
    Application lifespan handler.
    Code before 'yield' runs on startup; code after runs on shutdown.
    """
    logger.info(
        "Transaction Processing API starting",
        extra={
            "env": settings.app_env,
            "debug": settings.app_debug,
            "gemini_model": settings.gemini_model,
        },
    )
    # Ensure the uploads directory exists
    settings.upload_dir.mkdir(parents=True, exist_ok=True)
    yield
    logger.info("Transaction Processing API shutting down")


def create_app() -> FastAPI:
    """
    Application factory — returns a configured FastAPI instance.
    Using a factory function makes the app easier to test in isolation.
    """
    app = FastAPI(
        title="AI-Powered Transaction Processing Pipeline",
        description=(
            "Accepts dirty CSV financial transaction data, processes it asynchronously "
            "via Celery workers, detects anomalies, classifies transactions with Google "
            "Gemini, and returns a structured report."
        ),
        version="1.0.0",
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
        lifespan=lifespan,
    )

    # ── CORS ──────────────────────────────────────────────────────
    # In production, replace "*" with your actual frontend origin.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ── Routers ───────────────────────────────────────────────────
    app.include_router(jobs.router)

    # ── Health check ──────────────────────────────────────────────
    @app.get(
        "/health",
        tags=["Health"],
        summary="Health check",
        include_in_schema=False,
    )
    def health_check() -> JSONResponse:
        """Used by Docker Compose health checks and load balancers."""
        return JSONResponse({"status": "ok", "service": "transaction-api"})

    return app


app = create_app()

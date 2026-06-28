"""Configures structured JSON logging for the application."""

import logging
import sys
from typing import Any

from pythonjsonlogger import jsonlogger

from app.core.config import settings


def configure_logging() -> None:

    log_level = logging.DEBUG if settings.app_debug else logging.INFO

    # JSON formatter includes timestamp, level, logger name, and message (design decision for structured logging).
    formatter = jsonlogger.JsonFormatter(
        fmt="%(asctime)s %(levelname)s %(name)s %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)

    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)
    
    # Remove any default handlers (avoids duplicate output, Celery-specific behavior).
    root_logger.handlers.clear()
    root_logger.addHandler(handler)

    # Quieten noisy third-party loggers
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
    logging.getLogger("celery").setLevel(logging.INFO)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)

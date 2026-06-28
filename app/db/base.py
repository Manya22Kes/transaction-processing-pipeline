"""
app/db/base.py

SQLAlchemy engine, session factory, and declarative Base.

Design choices:
- We use SQLAlchemy 2.x-style type annotations in models but keep a
  2.0-compatible engine configuration for Celery (which is sync).
- The async session is used by FastAPI endpoints (via dependency injection).
- The sync session is used inside Celery tasks, which run in a normal
  synchronous thread pool.
"""

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.core.config import settings


class Base(DeclarativeBase):
    """Shared declarative base for all ORM models."""
    pass


# ── Synchronous engine (used by Celery workers and Alembic) ──────
# pool_pre_ping ensures stale connections are recycled automatically.
sync_engine = create_engine(
    settings.database_url,
    pool_pre_ping=True,
    pool_size=5,
    max_overflow=10,
    echo=settings.app_debug,
)

SyncSessionLocal = sessionmaker(
    bind=sync_engine,
    autocommit=False,
    autoflush=False,
)


def get_sync_db():
    """
    Dependency / context manager for synchronous database sessions.
    Usage in Celery tasks:

        with get_sync_db() as db:
            ...
    """
    db = SyncSessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

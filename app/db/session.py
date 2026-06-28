"""
app/db/session.py

FastAPI dependency that yields a synchronous SQLAlchemy session.
FastAPI handles concurrency at the ASGI level; using a synchronous
ORM session here is safe and avoids the complexity of async SQLAlchemy
(which would also require an async PostgreSQL driver like asyncpg).
"""

from typing import Generator

from sqlalchemy.orm import Session

from app.db.base import SyncSessionLocal


def get_db() -> Generator[Session, None, None]:
    """
    FastAPI dependency.  Yields a database session and guarantees
    proper cleanup (commit on success, rollback on exception).

    Usage:
        @router.get("/example")
        def example(db: Session = Depends(get_db)):
            ...
    """
    db: Session = SyncSessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

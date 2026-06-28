"""SQLAlchemy ORM model for the Job entity."""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Index, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class Job(Base):
    __tablename__ = "jobs"

    # ── Primary key ───────────────────────────────────────────────
    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
        comment="UUID primary key",
    )

    # ── File metadata ─────────────────────────────────────────────
    filename: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        comment="Original uploaded filename",
    )
    filepath: Mapped[str] = mapped_column(
        String(512),
        nullable=False,
        comment="Absolute path to the saved CSV on disk",
    )

    # ── Processing state ──────────────────────────────────────────
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="pending",
        index=True,
        comment="pending | processing | completed | failed",
    )

    # ── Row counts (populated after cleaning) ─────────────────────
    row_count_raw: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
        comment="Number of rows in the raw uploaded CSV",
    )
    row_count_clean: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
        comment="Number of rows after deduplication and cleaning",
    )

    # ── Error information (set if status = failed) ────────────────
    error_message: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="Human-readable error description if the job failed",
    )

    # ── Timestamps ────────────────────────────────────────────────
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        comment="When the Job record was created",
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="When processing finished (success or failure)",
    )

    # ── Relationships ─────────────────────────────────────────────
    transactions: Mapped[list["Transaction"]] = relationship(  # noqa: F821
        "Transaction",
        back_populates="job",
        cascade="all, delete-orphan",
    )
    summary: Mapped["JobSummary | None"] = relationship(  # noqa: F821
        "JobSummary",
        back_populates="job",
        uselist=False,
        cascade="all, delete-orphan",
    )

    # ── Composite index for listing jobs filtered by status ───────
    __table_args__ = (
        Index("ix_jobs_status_created_at", "status", "created_at"),
    )

    def __repr__(self) -> str:
        return f"<Job id={self.id!r} filename={self.filename!r} status={self.status!r}>"

"""SQLAlchemy ORM model for the Transaction entity."""

import uuid
from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class Transaction(Base):
    __tablename__ = "transactions"

    # ── Primary key ───────────────────────────────────────────────
    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        autoincrement=True,
    )

    # ── Foreign key to parent Job ─────────────────────────────────
    job_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("jobs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="Parent job UUID",
    )

    # ── Raw CSV fields (cleaned) ──────────────────────────────────
    txn_id: Mapped[str | None] = mapped_column(
        String(50),
        nullable=True,
        comment="Transaction ID from the CSV (may be blank in source)",
    )
    date: Mapped[date | None] = mapped_column(
        Date,
        nullable=True,
        comment="Transaction date normalised to ISO 8601",
    )
    merchant: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )
    amount: Mapped[float | None] = mapped_column(
        Numeric(precision=12, scale=2),
        nullable=True,
        comment="Transaction amount with currency symbol stripped",
    )
    currency: Mapped[str | None] = mapped_column(
        String(10),
        nullable=True,
        comment="Normalised to uppercase: INR or USD",
    )
    status: Mapped[str | None] = mapped_column(
        String(20),
        nullable=True,
        comment="Normalised to uppercase: SUCCESS | FAILED | PENDING",
    )
    category: Mapped[str | None] = mapped_column(
        String(50),
        nullable=True,
        comment="Spending category from CSV or filled with Uncategorised",
    )
    account_id: Mapped[str | None] = mapped_column(
        String(50),
        nullable=True,
        index=True,
    )
    notes: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    # ── Anomaly detection results ─────────────────────────────────
    is_anomaly: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        index=True,
    )
    anomaly_reason: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="Human-readable description of why this row was flagged",
    )

    # ── LLM classification results ────────────────────────────────
    llm_category: Mapped[str | None] = mapped_column(
        String(50),
        nullable=True,
        comment="Category predicted by Gemini (only set when original category was missing)",
    )
    llm_raw_response: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="Raw JSON string returned by the LLM for this transaction",
    )
    llm_failed: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        comment="True if all LLM retry attempts failed for this transaction",
    )

    # ── Audit timestamp ───────────────────────────────────────────
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    # ── Relationship ──────────────────────────────────────────────
    job: Mapped["Job"] = relationship("Job", back_populates="transactions")  # noqa: F821

    # ── Composite indexes for common query patterns ───────────────
    __table_args__ = (
        Index("ix_transactions_job_id_is_anomaly", "job_id", "is_anomaly"),
        Index("ix_transactions_job_id_category", "job_id", "category"),
    )

    def __repr__(self) -> str:
        return (
            f"<Transaction id={self.id} txn_id={self.txn_id!r} "
            f"merchant={self.merchant!r} amount={self.amount}>"
        )

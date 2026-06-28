"""Service for Transaction and JobSummary database operations."""

from typing import Any, Optional

import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.models.job import Job
from app.models.job_summary import JobSummary
from app.models.transaction import Transaction

logger = get_logger(__name__)


def bulk_insert_transactions(
    db: Session,
    job_id: str,
    df: pd.DataFrame,
) -> int:
    records: list[dict[str, Any]] = []

    for _, row in df.iterrows():
        # Convert NaN/NaT to None for proper NULL storage
        def safe(val: Any) -> Any:
            if pd.isna(val) if not isinstance(val, (list, dict)) else False:
                return None
            return val

        records.append(  # Prepare record for bulk insert
            {
                "job_id": job_id,
                "txn_id": safe(row.get("txn_id")),
                "date": safe(row.get("date")),
                "merchant": safe(row.get("merchant")),
                "amount": safe(row.get("amount")),
                "currency": safe(row.get("currency")),
                "status": safe(row.get("status")),
                "category": safe(row.get("category")),
                "account_id": safe(row.get("account_id")),
                "notes": safe(row.get("notes")),
                "is_anomaly": bool(row.get("is_anomaly", False)),
                "anomaly_reason": safe(row.get("anomaly_reason")),
                "llm_category": safe(row.get("llm_category")),
                "llm_raw_response": safe(row.get("llm_raw_response")),
                "llm_failed": bool(row.get("llm_failed", False)),
            }
        )

    if records:
        db.bulk_insert_mappings(Transaction, records)  # type: ignore[arg-type]
        db.flush()

    logger.info(
        "Transactions bulk inserted",
        extra={"job_id": job_id, "count": len(records)},
    )
    return len(records)


def update_transaction_llm_fields(
    db: Session,
    transaction_id: int,
    *,
    llm_category: Optional[str] = None,
    llm_raw_response: Optional[str] = None,
    llm_failed: bool = False,
) -> None:
    """Update LLM classification fields on a single transaction."""
    txn = db.get(Transaction, transaction_id)
    if not txn:
        return
    txn.llm_category = llm_category
    txn.llm_raw_response = llm_raw_response
    txn.llm_failed = llm_failed
    db.flush()


def get_transactions_for_job(
    db: Session,
    job_id: str,
) -> list[Transaction]:
    """Return all Transaction records for a given job."""
    stmt = select(Transaction).where(Transaction.job_id == job_id)
    return list(db.execute(stmt).scalars().all())


def get_job_summary(
    db: Session,
    job_id: str,
) -> Optional[JobSummary]:
    """Return the persisted JobSummary row for a job, or None if absent."""
    stmt = select(JobSummary).where(JobSummary.job_id == job_id)
    return db.execute(stmt).scalar_one_or_none()


def upsert_job_summary(
    db: Session,
    job_id: str,
    summary_data: dict[str, Any],
) -> JobSummary:
    # Check for an existing summary
    stmt = select(JobSummary).where(JobSummary.job_id == job_id)
    existing = db.execute(stmt).scalar_one_or_none()

    if existing:
        for key, value in summary_data.items():  # Update existing summary fields
            if hasattr(existing, key):
                setattr(existing, key, value)
        db.flush()
        logger.info("JobSummary updated", extra={"job_id": job_id})
        return existing

    job = db.get(Job, job_id)
    if not job:
        raise ValueError(f"Cannot create JobSummary: job '{job_id}' does not exist.")

    summary = JobSummary(job_id=job_id, **summary_data)  # Create new summary
    db.add(summary)
    job.summary = summary
    db.flush()
    logger.info("JobSummary created", extra={"job_id": job_id})
    return summary


def compute_category_breakdown(transactions: list[Transaction]) -> dict[str, float]:

    breakdown: dict[str, float] = {}
    for txn in transactions:
        if txn.amount is None:
            continue
        cat = txn.llm_category or txn.category or "Uncategorised"
        breakdown[cat] = round(breakdown.get(cat, 0.0) + float(txn.amount), 2)
    return breakdown

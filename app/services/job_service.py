"""Service for managing Job database operations."""

import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.core.logging import get_logger
from app.models.job import Job
from app.models.job_summary import JobSummary
from app.models.transaction import Transaction

logger = get_logger(__name__)


def create_job(db: Session, filename: str, filepath: str) -> Job:

    job = Job(
        id=str(uuid.uuid4()),
        filename=filename,
        filepath=filepath,
        status="pending",
    )  # Business rule: new jobs start as 'pending'
    db.add(job)
    db.flush()  # Flush to get the generated ID before commit (unusual SQLAlchemy behavior).
    logger.info("Job created", extra={"job_id": job.id, "csv_filename": filename})
    return job


def get_job_by_id(db: Session, job_id: str) -> Optional[Job]:
    return db.get(Job, job_id)


def get_all_jobs(db: Session, status_filter: Optional[str] = None) -> list[Job]:

    stmt = select(Job).order_by(Job.created_at.desc())
    if status_filter:
        stmt = stmt.where(Job.status == status_filter)  # Business rule: allow filtering by status
    return list(db.execute(stmt).scalars().all())


def get_job_with_summary(db: Session, job_id: str) -> Optional[Job]:
 # Design decision: eager load for performance
    stmt = ( # Design decision: eager load for performance.
        select(Job)
        .options(selectinload(Job.summary))
        .where(Job.id == job_id)
    )
    return db.execute(stmt).scalar_one_or_none()


def get_job_with_results(db: Session, job_id: str) -> Optional[Job]:
 # Design decision: eager load for performance
    stmt = ( # Design decision: eager load for performance.
        select(Job)
        .options(
            selectinload(Job.transactions),
            selectinload(Job.summary),
        )
        .where(Job.id == job_id)
    )
    return db.execute(stmt).scalar_one_or_none()


def update_job_status(
    db: Session,
    job_id: str,
    status: str,
    *,
    error_message: Optional[str] = None,
    row_count_raw: Optional[int] = None,
    row_count_clean: Optional[int] = None,
) -> Optional[Job]:
 # Business rule: track completion time
    job = db.get(Job, job_id)
    if not job:
        logger.error("Job not found for status update", extra={"job_id": job_id})
        return None

    job.status = status

    if error_message is not None:
        job.error_message = error_message
    if row_count_raw is not None:
        job.row_count_raw = row_count_raw
    if row_count_clean is not None:
        job.row_count_clean = row_count_clean

    if status in ("completed", "failed"): # Business rule: track completion time.
        job.completed_at = datetime.now(tz=timezone.utc)

    db.flush()
    logger.info(
        "Job status updated",
        extra={"job_id": job_id, "status": status},
    )
    return job

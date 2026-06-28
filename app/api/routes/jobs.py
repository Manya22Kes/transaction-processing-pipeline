"""API routes for managing transaction processing jobs."""

import shutil
import uuid
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, status
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.logging import get_logger
from app.db.session import get_db
from app.schemas.job import JobListItem, JobStatusResponse, JobUploadResponse
from app.schemas.transaction import AnomalyOut, JobResultsResponse, JobSummaryOut, TransactionOut
from app.services import job_service, transaction_service
from app.workers.tasks import process_job

logger = get_logger(__name__)

router = APIRouter(prefix="/jobs", tags=["Jobs"])

# Allowed MIME types and extensions for uploaded files
ALLOWED_CONTENT_TYPES = {"text/csv", "application/csv", "application/vnd.ms-excel"}
ALLOWED_EXTENSIONS = {".csv"}


# POST /jobs/upload

@router.post(
    "/upload",
    response_model=JobUploadResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Upload a CSV file for async processing",
    description=(
        "Accepts a CSV file, validates it, creates a Job record with status='pending', "
        "enqueues a background processing task, and returns the job_id immediately. "
        "Poll GET /jobs/{job_id}/status to track progress."
    ),
)
def upload_csv(
    file: UploadFile,
    db: Session = Depends(get_db),
) -> JobUploadResponse:
    """Step 1 of the user flow. Returns immediately — processing is async."""
    _validate_uploaded_file(file)
    # Use a UUID prefix to avoid filename collisions (design decision)
    safe_filename = f"{uuid.uuid4()}_{Path(file.filename or 'upload.csv').name}"
    save_path = settings.upload_dir / safe_filename

    try:
        with save_path.open("wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
    except OSError as exc:
        logger.error("Failed to save uploaded file", extra={"error": str(exc)})
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to save the uploaded file. Please try again.",
        ) from exc
    finally:
        file.file.close()

    # Validate that the saved file is a readable CSV
    _validate_csv_readable(save_path)

    # Create the Job record
    job = job_service.create_job(
        db=db,
        filename=file.filename or "upload.csv",
        filepath=str(save_path),
    )

    # Save values before commit because SQLAlchemy may expire ORM objects (SQLAlchemy behavior)
    # Commit the Job before queueing
    job_id = job.id
    job_filename = job.filename
    job_status = job.status

    # Make the Job visible to other database connections (Celery worker)
    db.commit()

    # Enqueue the Celery task
    process_job.apply_async(
        args=[job_id],
        queue="default",
    )

    logger.info(
        "Job enqueued for processing",
        extra={
            "job_id": job_id,
            "job_filename": job_filename,
        },
    )

    return JobUploadResponse(
        job_id=job_id,
        filename=job_filename,
        status=job_status,
        message="File accepted. Processing has started in the background.",
    )

# GET /jobs

@router.get(
    "",
    response_model=list[JobListItem],
    summary="List all jobs",
    description="Returns all jobs ordered by creation time (newest first). "
                "Use ?status= to filter by status (pending | processing | completed | failed).",
)
def list_jobs(
    status_filter: Optional[str] = Query(
        default=None,
        alias="status",
        description="Filter by job status: pending | processing | completed | failed",
    ),
    db: Session = Depends(get_db),
) -> list[JobListItem]:
    """Return all jobs, optionally filtered by status."""
    valid_statuses = ("pending", "processing", "completed", "failed")
    if status_filter and status_filter not in valid_statuses:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid status filter '{status_filter}'. "
                   "Must be one of: pending, processing, completed, failed.",
        )

    jobs = job_service.get_all_jobs(db, status_filter=status_filter)
    return [JobListItem.model_validate(job) for job in jobs]

# GET /jobs/{job_id}/status

@router.get(
    "/{job_id}/status",
    response_model=JobStatusResponse,
    summary="Get job status",
    description=(
        "Returns the current status of the job. "
        "When status == 'completed', a summary field with high-level statistics is included."
    ),
)
def get_job_status(
    job_id: str,
    db: Session = Depends(get_db),
) -> JobStatusResponse:
    """Poll this endpoint until status == 'completed' or 'failed'."""
    job = job_service.get_job_with_summary(db, job_id)
    if not job:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Job '{job_id}' not found.",
        )

    # Retrieve summary if the job is complete and a summary exists
    summary = job.summary or transaction_service.get_job_summary(db, job.id)

    summary_dict = None
    if job.status == "completed" and summary:
        s = summary
        summary_dict = {
            "total_spend_inr": s.total_spend_inr,
            "total_spend_usd": s.total_spend_usd,
            "anomaly_count": s.anomaly_count,
            "risk_level": s.risk_level,
            "narrative": s.narrative,
        }

    return JobStatusResponse(
        job_id=job.id,
        status=job.status,
        filename=job.filename,
        created_at=job.created_at,
        completed_at=job.completed_at,
        error_message=job.error_message,
        summary=summary_dict,
    )

# GET /jobs/{job_id}/results

@router.get(
    "/{job_id}/results",
    response_model=JobResultsResponse,
    summary="Get full job results",
    description=(
        "Returns the full structured output: "
        "cleaned transactions list, flagged anomalies, category breakdown, "
        "and the LLM-generated narrative summary."
    ),
)
def get_job_results(
    job_id: str,
    db: Session = Depends(get_db),
) -> JobResultsResponse:
    job = job_service.get_job_with_results(db, job_id)
    if not job:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Job '{job_id}' not found.",
        )

    transactions = job.transactions or []

    anomalies = [t for t in transactions if t.is_anomaly]

    category_breakdown = transaction_service.compute_category_breakdown(transactions)

    # Serialise
    txn_out = [TransactionOut.model_validate(t) for t in transactions]
    anomaly_out = [
        AnomalyOut(
            id=t.id,
            txn_id=t.txn_id,
            merchant=t.merchant,
            amount=float(t.amount) if t.amount is not None else None,
            currency=t.currency,
            account_id=t.account_id,
            anomaly_reason=t.anomaly_reason or "",
        )
        for t in anomalies
    ]
    summary = job.summary or transaction_service.get_job_summary(db, job.id)
    summary_out = JobSummaryOut.model_validate(summary) if summary else None

    return JobResultsResponse(
        job_id=job.id,
        status=job.status,
        total_transactions=len(transactions),
        transactions=txn_out,
        anomalies=anomaly_out,
        category_breakdown=category_breakdown,
        summary=summary_out,
    )

# Private validation helpers

def _validate_uploaded_file(file: UploadFile) -> None:
    if not file or not file.filename:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No file was uploaded.",
        )

    ext = Path(file.filename).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid file type '{ext}'. Only .csv files are accepted.",
        )

    # Content-type header is set by the client; accept common CSV variants (API edge case)
    ct = (file.content_type or "").lower()
    if ct and ct not in ALLOWED_CONTENT_TYPES and "text" not in ct:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unexpected content type '{ct}'. Expected a CSV file.",
        )


def _validate_csv_readable(path: Path) -> None:
    import pandas as pd

    try:
        df = pd.read_csv(path, nrows=5)
        if df.empty:
            raise ValueError("The CSV file contains no data rows.")
    except Exception as exc:
        # Remove the saved file since it's unusable (cleanup on error)
        path.unlink(missing_ok=True)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"The uploaded file is not a valid CSV: {exc}",
        ) from exc

"""Celery task for processing transaction data."""

import traceback
from contextlib import contextmanager
from typing import Any, Generator

import pandas as pd
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.db.base import SyncSessionLocal
from app.services import job_service, transaction_service
from app.services.llm_service import (
    classify_transactions_batch,
    generate_job_summary,
)
from app.utils.anomaly_detector import detect_anomalies
from app.utils.csv_cleaner import clean_dataframe, validate_csv_columns
from app.workers.celery_app import celery_app

logger = get_logger(__name__)

@contextmanager
def task_db_session() -> Generator[Session, None, None]:
    """
    Context manager that provides a sync SQLAlchemy session for use
    inside Celery tasks.  Commits on success, rolls back on error.
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

@celery_app.task(
    name="app.workers.tasks.process_job",
    bind=True,
    max_retries=0,          # We handle retries internally for LLM; not for the whole task
    acks_late=True,
)
def process_job(self: Any, job_id: str) -> dict[str, Any]:
    """
    Main processing task.  Called by Celery when a job is dequeued.

    Args:
        job_id: UUID string of the Job record to process.

    Returns:
        A summary dict (stored as Celery task result in Redis).
    """
    logger.info("Job started", extra={"job_id": job_id})

    with task_db_session() as db: # Design decision: update job status immediately.
        job = job_service.update_job_status(db, job_id, "processing")
        if not job:
            logger.error("Job not found, cannot process", extra={"job_id": job_id})
            return {"status": "failed", "reason": "Job record not found"}
        filepath = job.filepath

    try: # The entire pipeline is wrapped in a try-except to catch non-LLM failures.
        logger.info("Step 1: Reading CSV", extra={"job_id": job_id, "filepath": filepath})
        df_raw = _read_csv(filepath)
        logger.info("Step 2: Cleaning data", extra={"job_id": job_id})
        df_clean, raw_count = clean_dataframe(df_raw.copy())
        clean_count = len(df_clean)

        # Persist row counts after cleaning
        with task_db_session() as db:
            job_service.update_job_status(
                db,
                job_id,
                "processing",
                row_count_raw=raw_count,
                row_count_clean=clean_count,
            )

        logger.info(
            "Step 2: Cleaning completed",
            extra={"job_id": job_id, "raw_rows": raw_count, "clean_rows": clean_count},
        )
        logger.info("Step 3: Anomaly detection", extra={"job_id": job_id})
        df_clean = detect_anomalies(df_clean)
        anomaly_count = int(df_clean["is_anomaly"].sum())
        logger.info(
            "Step 3: Anomaly detection completed",
            extra={"job_id": job_id, "anomalies": anomaly_count},
        )
        logger.info("Step 4: LLM classification", extra={"job_id": job_id})
        df_clean = _run_llm_classification(df_clean, job_id)
        logger.info("Step 4: LLM classification completed", extra={"job_id": job_id})

        # Persist all transactions to the database
        with task_db_session() as db:
            transaction_service.bulk_insert_transactions(db, job_id, df_clean)
        logger.info("Step 5: LLM summary generation", extra={"job_id": job_id})
        _run_llm_summary(df_clean, job_id, anomaly_count)
    

        # Mark job as completed
        with task_db_session() as db:
            job_service.update_job_status(db, job_id, "completed")

        logger.info("Job finished successfully", extra={"job_id": job_id})
        return {"status": "completed", "job_id": job_id, "clean_rows": clean_count}

    except Exception as exc:
        error_msg = f"{type(exc).__name__}: {exc}"
        tb = traceback.format_exc()
        logger.error(
            "Job failed",
            extra={"job_id": job_id, "error": error_msg, "traceback": tb},
        )
        with task_db_session() as db:
            job_service.update_job_status(
                db, job_id, "failed", error_message=error_msg
            )
        return {"status": "failed", "job_id": job_id, "error": error_msg}
def _read_csv(filepath: str) -> pd.DataFrame:
    """
    Read the CSV from disk.
    Raises ValueError with a clear message if the file cannot be parsed
    or if required columns are missing.
    """
    try:
        df = pd.read_csv(filepath, dtype=str, keep_default_na=False)
    except Exception as exc:
        raise ValueError(f"Could not read CSV file: {exc}") from exc

    # Replace empty strings with pandas NA for consistent null handling (design decision).
    df = df.replace("", pd.NA)

    missing_cols = validate_csv_columns(df)
    if missing_cols:
        raise ValueError(f"CSV is missing required columns: {missing_cols}")

    return df


def _run_llm_classification(df: pd.DataFrame, job_id: str) -> pd.DataFrame:
    """
    Identifies uncategorised rows and batches them for LLM classification.
    On success: populates df['llm_category'] and df['llm_raw_response'].
    On failure: sets df['llm_failed'] = True for all uncategorised rows.

    Returns the modified DataFrame.
    """
    df["llm_category"] = df.get("llm_category", None)
    df["llm_raw_response"] = df.get("llm_raw_response", None)
    df["llm_failed"] = df.get("llm_failed", False)
    uncategorised_mask = df["category"] == "Uncategorised"
    uncategorised_df = df[uncategorised_mask]

    if uncategorised_df.empty:
        logger.info( # No uncategorised transactions — skipping LLM classification
            "No uncategorised transactions — skipping LLM classification",
            extra={"job_id": job_id},
        )

    # Prepare transaction data for the LLM call
    txn_list = [
        {
            "index": int(idx),
            "txn_id": row.get("txn_id"),
            "merchant": row.get("merchant", ""),
            "amount": row.get("amount"),
            "currency": row.get("currency", ""),
            "notes": row.get("notes", ""),
        }
        for idx, row in uncategorised_df.iterrows()
    ]

    category_map, raw_response, llm_failed = classify_transactions_batch(txn_list)

    if llm_failed:
        # Mark all uncategorised rows as llm_failed if the LLM call failed (design decision).
        df.loc[uncategorised_mask, "llm_failed"] = True
        logger.warning(
            "LLM classification failed — rows marked llm_failed",
            extra={"job_id": job_id, "affected_rows": int(uncategorised_mask.sum())},
        )
    else:
        for row_idx, category in category_map.items():
            if row_idx in df.index:
                df.at[row_idx, "llm_category"] = category
                df.at[row_idx, "llm_raw_response"] = raw_response

        # Any indices that weren't returned get marked as failed
        returned_indices = set(category_map.keys())
        for idx in uncategorised_df.index:
            if int(idx) not in returned_indices:
                df.at[idx, "llm_failed"] = True

    return df


def _run_llm_summary(
    df: pd.DataFrame,
    job_id: str,
    anomaly_count: int,
) -> None:
    """
    Generate and persist the LLM narrative summary.
    If the LLM call fails, the summary is skipped (not stored) — the
    job is still marked completed; a missing summary is acceptable.
    """
    # Convert the DataFrame to a list of plain dicts for the LLM
    transaction_dicts = df.to_dict(orient="records")

    summary_data, llm_failed = generate_job_summary(transaction_dicts, anomaly_count)

    if llm_failed or summary_data is None:
        logger.warning(
            "LLM summary generation failed — job will complete without summary",
            extra={"job_id": job_id},
        )
        return

    with task_db_session() as db:
        transaction_service.upsert_job_summary(db, job_id, summary_data)

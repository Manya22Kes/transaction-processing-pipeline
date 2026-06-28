"""Pydantic schemas for Transaction and JobSummary API responses."""

import datetime as dt
from typing import Any, Optional

from pydantic import BaseModel, Field


class TransactionOut(BaseModel):

    id: int
    job_id: str
    txn_id: Optional[str] = None
    date: Optional[dt.date] = None
    merchant: Optional[str] = None
    amount: Optional[float] = None
    currency: Optional[str] = None
    status: Optional[str] = None
    category: Optional[str] = None
    account_id: Optional[str] = None
    notes: Optional[str] = None
    is_anomaly: bool
    anomaly_reason: Optional[str] = None
    llm_category: Optional[str] = None
    llm_raw_response: Optional[str] = None
    llm_failed: bool

    model_config = {"from_attributes": True}


class AnomalyOut(BaseModel):
    """Compact view of a flagged anomaly transaction."""

    id: int
    txn_id: Optional[str] = None
    merchant: Optional[str] = None
    amount: Optional[float] = None
    currency: Optional[str] = None
    account_id: Optional[str] = None
    anomaly_reason: str

    model_config = {"from_attributes": True}


class JobSummaryOut(BaseModel):
    """LLM-generated summary statistics for a completed job."""

    total_spend_inr: Optional[float] = None
    total_spend_usd: Optional[float] = None
    top_merchants: Optional[Any] = None
    category_breakdown: Optional[Any] = None
    anomaly_count: Optional[int] = None
    narrative: Optional[str] = None
    risk_level: Optional[str] = None

    model_config = {"from_attributes": True}


class JobResultsResponse(BaseModel):

    job_id: str
    status: str
    total_transactions: int = Field(..., description="Count of cleaned transactions stored")
    transactions: list[TransactionOut] = Field(..., description="All cleaned transactions")
    anomalies: list[AnomalyOut] = Field(..., description="Flagged anomaly transactions only")
    category_breakdown: dict[str, float] = Field(
        default_factory=dict,
        description="Total spend per category",
    )
    summary: Optional[JobSummaryOut] = Field(
        None, description="LLM-generated narrative summary (None if not yet complete)"
    )

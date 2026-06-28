"""Pydantic schemas for the Job resource."""

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field


class JobUploadResponse(BaseModel):
    """Returned immediately after a CSV is accepted for processing."""

    job_id: str = Field(..., description="UUID of the newly created job")
    filename: str = Field(..., description="Original uploaded filename")
    status: str = Field(..., description="Initial status — always 'pending'")
    message: str = Field(..., description="Human-readable confirmation")


class JobListItem(BaseModel):
    """Compact representation used in GET /jobs list responses."""

    id: str
    filename: str
    status: str
    row_count_raw: Optional[int] = None
    row_count_clean: Optional[int] = None
    created_at: datetime

    model_config = {"from_attributes": True}


class JobStatusResponse(BaseModel):
    """
    Returned by GET /jobs/{job_id}/status.
    When status == 'completed', the summary field is populated.
    """

    job_id: str
    status: str
    filename: str
    created_at: datetime
    completed_at: Optional[datetime] = None
    error_message: Optional[str] = None
    summary: Optional[dict[str, Any]] = None

    model_config = {"from_attributes": True}

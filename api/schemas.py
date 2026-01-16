"""
Pydantic Schemas for ReguSense API.

Request and response models for API endpoints.
"""

from datetime import datetime
from typing import Any, Optional
from enum import Enum

from pydantic import BaseModel, Field


# =============================================================================
# Enums
# =============================================================================

class TaskStatus(str, Enum):
    """Celery task status."""
    PENDING = "PENDING"
    STARTED = "STARTED"
    SUCCESS = "SUCCESS"
    FAILURE = "FAILURE"
    RETRY = "RETRY"
    REVOKED = "REVOKED"


class ContradictionType(str, Enum):
    """Types of contradictions."""
    REVERSAL = "REVERSAL"
    BROKEN_PROMISE = "BROKEN_PROMISE"
    INCONSISTENCY = "INCONSISTENCY"
    NONE = "NONE"


# =============================================================================
# Detection Schemas
# =============================================================================

class DetectionRequest(BaseModel):
    """Request for contradiction detection."""
    
    statement: str = Field(
        ...,
        min_length=10,
        max_length=5000,
        description="The political statement to analyze",
        json_schema_extra={"example": "Enflasyon tek haneye düşecek"}
    )
    speaker: str = Field(
        default="",
        max_length=200,
        description="Optional speaker name for filtering",
        json_schema_extra={"example": "Mehmet Şimşek"}
    )
    threshold: int = Field(
        default=70,
        ge=0,
        le=100,
        description="Contradiction score threshold (0-100)",
    )
    filter_by_speaker: bool = Field(
        default=True,
        description="Filter historical search by speaker name",
    )


class HistoricalMatch(BaseModel):
    """A matched historical statement."""
    
    text: str
    speaker: str = ""
    date: str = ""
    topic: str = ""
    source: str = ""
    source_type: str = "UNKNOWN"
    similarity: float = 0.0


class DetectionResponse(BaseModel):
    """Response from contradiction detection."""
    
    is_contradiction: bool = Field(
        description="Whether a contradiction was detected"
    )
    contradiction_score: int = Field(
        ge=0,
        le=100,
        description="Contradiction confidence score (0-100)"
    )
    contradiction_type: ContradictionType = Field(
        description="Type of contradiction detected"
    )
    new_statement: str = Field(
        description="The analyzed statement"
    )
    speaker: str = Field(
        default="",
        description="Speaker of the statement"
    )
    explanation: str = Field(
        default="",
        description="AI-generated explanation of the contradiction"
    )
    key_conflict_points: list[str] = Field(
        default_factory=list,
        description="Key points of conflict identified"
    )
    historical_matches: list[HistoricalMatch] = Field(
        default_factory=list,
        description="Relevant historical statements found"
    )
    analysis_timestamp: str = Field(
        default_factory=lambda: datetime.now().isoformat(),
        description="Timestamp of the analysis"
    )


class BatchDetectionRequest(BaseModel):
    """Request for batch contradiction detection."""
    
    statements: list[dict[str, str]] = Field(
        ...,
        min_length=1,
        max_length=50,
        description="List of statements with 'text' and optional 'speaker' keys",
        json_schema_extra={
            "example": [
                {"text": "Statement 1", "speaker": "Speaker A"},
                {"text": "Statement 2", "speaker": "Speaker B"},
            ]
        }
    )
    threshold: int = Field(default=70, ge=0, le=100)


# =============================================================================
# Ingestion Schemas
# =============================================================================

class IngestRequest(BaseModel):
    """Request to ingest statements."""
    
    statements: list[dict[str, Any]] = Field(
        ...,
        min_length=1,
        description="List of statements to ingest",
        json_schema_extra={
            "example": [
                {
                    "text": "Enflasyon düşecek",
                    "speaker": "Mehmet Şimşek",
                    "date": "2024-01-15",
                    "topic": "Ekonomi",
                    "source": "TBMM",
                }
            ]
        }
    )


class IngestResponse(BaseModel):
    """Response from ingestion."""
    
    success: bool
    count: int = Field(description="Number of statements ingested")
    document_ids: list[str] = Field(
        default_factory=list,
        description="IDs of ingested documents"
    )
    message: str = ""


class ScrapeRequest(BaseModel):
    """Request to trigger scraping task."""
    
    commission: str = Field(
        default="PLAN_BUTCE",
        description="Commission key to scrape",
        json_schema_extra={"example": "PLAN_BUTCE"}
    )
    limit: int = Field(
        default=10,
        ge=1,
        le=100,
        description="Maximum number of transcripts to scrape"
    )


# =============================================================================
# Task Schemas
# =============================================================================

class TaskResponse(BaseModel):
    """Response for async task creation."""
    
    task_id: str = Field(description="Celery task ID")
    status: TaskStatus = Field(description="Current task status")
    message: str = Field(default="Task submitted successfully")


class TaskStatusResponse(BaseModel):
    """Response for task status query."""
    
    task_id: str
    status: TaskStatus
    result: Optional[dict[str, Any]] = None
    error: Optional[str] = None
    started_at: Optional[str] = None
    completed_at: Optional[str] = None


# =============================================================================
# Health & Stats Schemas
# =============================================================================

class HealthResponse(BaseModel):
    """Health check response."""
    
    status: str = "healthy"
    timestamp: str = Field(
        default_factory=lambda: datetime.now().isoformat()
    )
    version: str = "1.0.0"


class StatsResponse(BaseModel):
    """Memory statistics response."""
    
    collection_name: str
    document_count: int
    persist_dir: str
    model_name: str


class SpeakersResponse(BaseModel):
    """List of speakers response."""
    
    speakers: list[str]
    count: int

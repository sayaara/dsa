# -*- coding: utf-8 -*-
"""
===================================
Analysis models
===================================

Responsibilities:
1. Define the analysis request and response models
2. Define the task status model
3. Define the async task queue models
"""

from typing import Optional, List, Any, Literal
from enum import Enum

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, field_validator
from src.utils.analysis_metadata import SELECTION_SOURCE_PATTERN
from src.utils.market_review_region import normalize_market_review_region_strict


class TaskStatusEnum(str, Enum):
    """Task status enumeration"""
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCEL_REQUESTED = "cancel_requested"
    CANCELLED = "cancelled"


AnalysisPhase = Literal["auto", "premarket", "intraday", "postmarket"]


class AnalyzeRequest(BaseModel):
    """Analysis request parameters"""

    stock_code: Optional[str] = Field(
        None,
        description="Single stock code",
        json_schema_extra={"example": "AAPL"},
    )
    stock_codes: Optional[List[str]] = Field(
        None,
        description="Multiple stock codes (mutually exclusive with stock_code)",
        json_schema_extra={"example": ["AAPL", "MSFT"]},
    )
    report_type: str = Field(
        "detailed",
        description="Report type: simple (condensed) / detailed (full) / full (full) / brief (short)",
        pattern="^(simple|detailed|full|brief)$",
    )
    force_refresh: bool = Field(
        False,
        description="Force refresh (ignore cache)"
    )
    async_mode: bool = Field(
        False,
        description="Use asynchronous mode"
    )
    analysis_phase: AnalysisPhase = Field(
        "auto",
        description="Analysis phase override: auto (inferred) / premarket / intraday / postmarket",
    )
    stock_name: Optional[str] = Field(
        None,
        description="Stock name the user selected (provided by autocomplete)",
        json_schema_extra={"example": "Apple Inc."},
    )
    original_query: Optional[str] = Field(
        None,
        description="The user's raw input (e.g. Apple, apple inc, AAPL)",
        json_schema_extra={"example": "Apple"},
    )
    selection_source: Optional[str] = Field(
        None,
        description="How the stock was selected: manual (typed) | autocomplete | import | image (image recognition)",
        pattern=SELECTION_SOURCE_PATTERN,
        json_schema_extra={"example": "autocomplete"},
    )
    notify: bool = Field(
        True,
        description="Send push notifications (Telegram, Discord, etc.)"
    )
    report_language: Optional[Literal["en"]] = Field(
        None,
        validation_alias=AliasChoices("report_language", "reportLanguage"),
        description="Report output language for this analysis; defaults to the global REPORT_LANGUAGE",
    )
    skills: Optional[List[str]] = Field(
        None,
        validation_alias=AliasChoices("skills", "strategies"),
        description="Strategy skill IDs used for this analysis; compatible with the legacy strategies field",
        json_schema_extra={"example": ["bull_trend", "growth_quality"]},
    )

    model_config = ConfigDict(json_schema_extra={
        "example": {
            "stock_code": "AAPL",
            "report_type": "detailed",
            "force_refresh": False,
            "async_mode": False,
            "analysis_phase": "auto",
            "stock_name": "Apple Inc.",
            "original_query": "Apple",
            "selection_source": "autocomplete",
            "notify": True,
            "report_language": "zh",
            "skills": ["bull_trend"]
        }
    })


class MarketReviewRequest(BaseModel):
    """Market review trigger parameters."""

    send_notification: bool = Field(
        True,
        description="Send push notifications when the market review completes",
    )
    report_language: Optional[Literal["en"]] = Field(
        None,
        validation_alias=AliasChoices("report_language", "reportLanguage"),
        description="Report output language for this market review; defaults to the global REPORT_LANGUAGE",
    )
    region: Optional[str] = Field(
        None,
        min_length=1,
        max_length=64,
        description=(
            "Markets covered by this market review. Valid tokens are ca, us and both; both must "
            "be used alone, the others can be combined with commas. Input is case-insensitive, trimmed around"
            " each token, deduplicated and sorted as ca,us. An empty value, an empty token, an "
            "unknown token, both mixed with others, or more than 64 characters returns a 4xx for the whole "
            "request; nothing runs partially. Defaults to the runtime global MARKET_REVIEW_REGION."
        ),
        json_schema_extra={
            "example": "ca,us",
            "examples": ["ca", "us", "both"],
        },
    )

    @field_validator("region")
    @classmethod
    def normalize_region(cls, value: Optional[str]) -> Optional[str]:
        """Strictly validate request input and return its canonical ordering."""
        if value is None:
            return None
        return normalize_market_review_region_strict(value)


class MarketReviewAccepted(BaseModel):
    """Market review background task accepted response."""

    status: str = Field("accepted", description="Submission status")
    message: str = Field(..., description="Message")
    send_notification: bool = Field(..., description="Whether notifications are sent")
    region: str = Field(
        ...,
        description="Canonical market scope this task actually runs",
        examples=["us", "hk,us"],
    )
    trace_id: Optional[str] = Field(
        None,
        description="Diagnostic trace ID of this background task",
    )
    task_id: Optional[str] = Field(
        None,
        description="Task ID (returned only when a task is actually submitted)",
    )


class AnalysisResultResponse(BaseModel):
    """Analysis result response model"""

    query_id: str = Field(..., description="Unique identifier of the analysis record")
    trace_id: Optional[str] = Field(None, description="Diagnostic trace ID")
    stock_code: str = Field(..., description="Stock code")
    stock_name: Optional[str] = Field(None, description="Stock name")
    report: Optional[Any] = Field(None, description="Analysis report")
    diagnostic_summary: Optional[Any] = Field(None, description="Run diagnostic summary")
    created_at: str = Field(..., description="Creation time")

    model_config = ConfigDict(json_schema_extra={
        "example": {
            "query_id": "abc123def456",
            "stock_code": "AAPL",
            "stock_name": "Apple Inc.",
            "report": {
                "summary": {
                    "sentiment_score": 75,
                    "operation_advice": "Hold"
                }
            },
            "created_at": "2024-01-01T12:00:00"
        }
    })


class TaskAccepted(BaseModel):
    """Async task accepted response"""

    task_id: str = Field(..., description="Task ID, used to query status")
    trace_id: Optional[str] = Field(None, description="Diagnostic trace ID")
    status: str = Field(
        ...,
        description="Task status",
        pattern="^(pending|processing)$"
    )
    message: Optional[str] = Field(None, description="Message")
    analysis_phase: AnalysisPhase = Field("auto", description="Requested analysis phase")

    model_config = ConfigDict(json_schema_extra={
        "example": {
            "task_id": "task_abc123",
            "status": "pending",
            "message": "Analysis task accepted",
            "analysis_phase": "auto"
        }
    })


class BatchTaskAcceptedItem(BaseModel):
    """A single successfully submitted item within a batch async task."""

    task_id: str = Field(..., description="Task ID, used to query status")
    trace_id: Optional[str] = Field(None, description="Diagnostic trace ID")
    stock_code: str = Field(..., description="Stock code")
    status: str = Field(
        ...,
        description="Task status",
        pattern="^(pending|processing)$"
    )
    message: Optional[str] = Field(None, description="Message")
    analysis_phase: AnalysisPhase = Field("auto", description="Requested analysis phase")
    asset_type: Optional[Literal["stock", "index"]] = Field(
        None,
        description=(
            "Optional parser-derived asset type (stock/index), passed through from the submitted "
            "analysis_target; older clients may omit it"
        ),
    )

    model_config = ConfigDict(json_schema_extra={
        "example": {
            "task_id": "task_abc123",
            "stock_code": "AAPL",
            "status": "pending",
            "message": "Analysis task queued: AAPL",
            "analysis_phase": "auto"
        }
    })


class BatchDuplicateTaskItem(BaseModel):
    """A duplicate submission item within a batch async task."""

    stock_code: str = Field(..., description="Stock code")
    existing_task_id: str = Field(..., description="ID of the existing task")
    message: str = Field(..., description="Error message")

    model_config = ConfigDict(json_schema_extra={
        "example": {
            "stock_code": "AAPL",
            "existing_task_id": "task_existing_123",
            "message": "Stock AAPL is already being analyzed (task_id: task_existing_123)"
        }
    })


class RejectedTaskItem(BaseModel):
    """A target item explicitly rejected within a batch async task (for example an unregistered CSI index)."""

    stock_code: str = Field(..., description="Rejected target code")
    message: str = Field(..., description="Rejection reason")

    model_config = ConfigDict(json_schema_extra={
        "example": {
            "stock_code": "930956.CSI",
            "message": "unregistered CSI index: '930956.CSI' is not in the index registry",
        }
    })


class BatchTaskAcceptedResponse(BaseModel):
    """Batch async task accepted response."""

    accepted: List[BatchTaskAcceptedItem] = Field(default_factory=list, description="Tasks submitted successfully")
    duplicates: List[BatchDuplicateTaskItem] = Field(default_factory=list, description="Tasks skipped as duplicates")
    rejected: Optional[List[RejectedTaskItem]] = Field(
        None,
        description=(
            "Targets explicitly rejected from the batch (e.g. unregistered CSI indices); returned only for "
            "asynchronous batch requests"
        ),
    )
    message: str = Field(..., description="Summary message")

    model_config = ConfigDict(json_schema_extra={
        "example": {
            "accepted": [
                {
                    "task_id": "task_abc123",
                    "stock_code": "AAPL",
                    "status": "pending",
                    "message": "Analysis task queued: AAPL",
                    "analysis_phase": "auto"
                }
            ],
            "duplicates": [
                {
                    "stock_code": "MSFT",
                    "existing_task_id": "task_existing_456",
                    "message": "Stock MSFT is already being analyzed (task_id: task_existing_456)"
                }
            ],
            "message": "Submitted 1 task(s), skipped 1 duplicate(s)"
        }
    })


class TaskStatus(BaseModel):
    """Task status model"""

    task_id: str = Field(..., description="Task ID")
    trace_id: Optional[str] = Field(None, description="Diagnostic trace ID")
    status: TaskStatusEnum = Field(
        ...,
        description="Task status",
    )
    progress: Optional[int] = Field(
        None,
        description="Progress percentage (0-100)",
        ge=0,
        le=100
    )
    result: Optional[AnalysisResultResponse] = Field(
        None,
        description="Analysis result (present only when completed)"
    )
    market_review_report: Optional[str] = Field(
        None,
        description="Report text returned by a market-review task (market-review tasks only)",
    )
    market_review_payload: Optional[Any] = Field(
        None,
        description="Structured market-review payload for API/Web consumers.",
    )
    region: Optional[str] = Field(
        None,
        description="Canonical market scope the market-review task actually ran",
    )
    error: Optional[str] = Field(
        None,
        description="Error message (present only when failed)"
    )
    stock_name: Optional[str] = Field(None, description="Stock name")
    original_query: Optional[str] = Field(None, description="The user's raw input")
    selection_source: Optional[str] = Field(
        None,
        description="Selection source",
        pattern=SELECTION_SOURCE_PATTERN,
    )
    analysis_phase: Optional[AnalysisPhase] = Field(
        None,
        description=(
            "Requested analysis phase; may be empty for the historical DB fallback when the field was not "
            "persisted"
        ),
    )
    skills: Optional[List[str]] = Field(None, description="Strategy skill IDs used by this task")

    model_config = ConfigDict(json_schema_extra={
        "example": {
            "task_id": "task_abc123",
            "status": "completed",
            "progress": 100,
            "result": None,
            "market_review_report": None,
            "error": None,
            "stock_name": "Apple Inc.",
            "original_query": "Apple",
            "selection_source": "autocomplete",
            "analysis_phase": "auto",
            "skills": ["bull_trend"]
        }
    })


class TaskInfo(BaseModel):
    """
    Task details model

    Used for task list and SSE event delivery
    """

    task_id: str = Field(..., description="Task ID")
    trace_id: Optional[str] = Field(None, description="Diagnostic trace ID")
    stock_code: str = Field(..., description="Stock code")
    stock_name: Optional[str] = Field(None, description="Stock name")
    status: TaskStatusEnum = Field(..., description="Task status")
    progress: int = Field(0, description="Progress percentage (0-100)", ge=0, le=100)
    message: Optional[str] = Field(None, description="Status message")
    report_type: str = Field("detailed", description="Report type")
    created_at: str = Field(..., description="Creation time")
    started_at: Optional[str] = Field(None, description="Start time")
    completed_at: Optional[str] = Field(None, description="Completion time")
    error: Optional[str] = Field(None, description="Error message (present only when failed)")
    original_query: Optional[str] = Field(None, description="The user's raw input")
    selection_source: Optional[str] = Field(
        None,
        description="Selection source",
        pattern=SELECTION_SOURCE_PATTERN,
    )
    analysis_phase: AnalysisPhase = Field("auto", description="Requested analysis phase")
    skills: Optional[List[str]] = Field(None, description="Strategy skill IDs used by this task")
    region: Optional[str] = Field(
        None,
        description="Canonical market scope the market-review task actually ran",
    )
    asset_type: Optional[Literal["stock", "index"]] = Field(
        None,
        description=(
            "Optional parser-derived asset type (stock/index), passed through from the submitted "
            "analysis_target; older clients may omit it"
        ),
    )

    model_config = ConfigDict(json_schema_extra={
        "example": {
            "task_id": "abc123def456",
            "stock_code": "AAPL",
            "stock_name": "Apple Inc.",
            "status": "processing",
            "progress": 50,
            "message": "Analyzing...",
            "report_type": "detailed",
            "created_at": "2026-02-05T10:30:00",
            "started_at": "2026-02-05T10:30:01",
            "completed_at": None,
            "error": None,
            "original_query": "Apple",
            "selection_source": "autocomplete",
            "analysis_phase": "auto",
            "skills": ["bull_trend"]
        }
    })


class TaskListResponse(BaseModel):
    """Task list response model"""

    total: int = Field(..., description="Total tasks")
    pending: int = Field(..., description="Pending tasks")
    processing: int = Field(..., description="Tasks in progress")
    tasks: List[TaskInfo] = Field(..., description="Task list")

    model_config = ConfigDict(json_schema_extra={
        "example": {
            "total": 3,
            "pending": 1,
            "processing": 2,
            "tasks": []
        }
    })


class DuplicateTaskErrorResponse(BaseModel):
    """Duplicate task error response model"""

    error: str = Field("duplicate_task", description="Error type")
    message: str = Field(..., description="Error message")
    stock_code: str = Field(..., description="Stock code")
    existing_task_id: str = Field(..., description="ID of the existing task")

    model_config = ConfigDict(json_schema_extra={
        "example": {
            "error": "duplicate_task",
            "message": "Stock AAPL is already being analyzed",
            "stock_code": "AAPL",
            "existing_task_id": "abc123def456"
        }
    })

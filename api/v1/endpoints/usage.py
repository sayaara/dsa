# -*- coding: utf-8 -*-
"""LLM usage tracking endpoint."""

from __future__ import annotations

import logging
from datetime import date, datetime, timezone
from typing import Any, NamedTuple, Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, Query

from api.deps import get_database_manager
from api.v1.schemas.usage import UsageDashboardResponse, UsageSummaryResponse
from src.storage import DatabaseManager

logger = logging.getLogger(__name__)

DEFAULT_USAGE_TIMEZONE = "America/Toronto"

router = APIRouter()

_VALID_PERIODS = {"today", "month", "all"}


class UsageWindow(NamedTuple):
    """Query bounds plus the period's dates as reported to the client."""

    from_dt: datetime  # naive server-local time, like ``llm_usage.called_at``
    to_dt: datetime
    from_date: date  # in the usage timezone
    to_date: date


def _usage_timezone() -> ZoneInfo:
    """Return ``USAGE_TIMEZONE`` (default America/Toronto); an unknown name falls back to the default."""
    try:
        from src.config import get_config

        name = (getattr(get_config(), "usage_timezone", "") or "").strip() or DEFAULT_USAGE_TIMEZONE
    except Exception:  # noqa: BLE001 - the dashboard must not fail on config loading
        name = DEFAULT_USAGE_TIMEZONE
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        logger.warning("Unknown USAGE_TIMEZONE %r; using %s", name, DEFAULT_USAGE_TIMEZONE)
        return ZoneInfo(DEFAULT_USAGE_TIMEZONE)


def _to_server_local(moment: datetime) -> datetime:
    """Convert an aware datetime to the naive server-local form ``called_at`` is stored in."""
    return moment.astimezone().replace(tzinfo=None)


def _date_range(period: str, now: Optional[datetime] = None) -> UsageWindow:
    """Return the query window for ``period``.

    ``llm_usage.called_at`` is stored as naive server-local time (``datetime.now``), so the bounds
    are converted to that form. The period starts at midnight (``today``) or on the first of the
    month (``month``) in ``USAGE_TIMEZONE``, whatever the server's own timezone is.
    """
    tz = _usage_timezone()
    now_utc = now.astimezone(timezone.utc) if now is not None else datetime.now(timezone.utc)
    local_now = now_utc.astimezone(tz)
    to_dt = _to_server_local(now_utc)
    if period == "today":
        start = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
    elif period == "month":
        start = local_now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    else:  # all
        return UsageWindow(datetime(2000, 1, 1), to_dt, date(2000, 1, 1), local_now.date())
    return UsageWindow(_to_server_local(start), to_dt, start.date(), local_now.date())


def _normalize_period(period: str) -> str:
    return period if period in _VALID_PERIODS else "month"


def _enrich_call_record(row: dict[str, Any]) -> dict[str, Any]:
    called_at = row.get("called_at")
    if isinstance(called_at, datetime):
        called_at_value = called_at.isoformat()
    else:
        called_at_value = str(called_at or "")
    return {
        **row,
        "called_at": called_at_value,
    }


def _build_summary_payload(period: str, window: UsageWindow, data: dict[str, Any]) -> dict[str, Any]:
    return {
        "period": period,
        "from_date": window.from_date.isoformat(),
        "to_date": window.to_date.isoformat(),
        "total_calls": data.get("total_calls", 0),
        "total_prompt_tokens": data.get("total_prompt_tokens", 0),
        "total_completion_tokens": data.get("total_completion_tokens", 0),
        "total_tokens": data.get("total_tokens", 0),
        "by_call_type": data.get("by_call_type", []),
        "by_model": data.get("by_model", []),
    }


@router.get(
    "/summary",
    response_model=UsageSummaryResponse,
    summary="LLM token usage summary",
    description="Aggregate token consumption by period, call type, and model.",
)
def get_usage_summary(
    period: str = Query("month", description="'today' | 'month' | 'all'"),
    db_manager: DatabaseManager = Depends(get_database_manager),
) -> UsageSummaryResponse:
    normalized_period = _normalize_period(period)
    window = _date_range(normalized_period)
    data = db_manager.get_llm_usage_summary(window.from_dt, window.to_dt)
    return UsageSummaryResponse(**_build_summary_payload(normalized_period, window, data))


@router.get(
    "/dashboard",
    response_model=UsageDashboardResponse,
    summary="LLM token usage monitoring dashboard",
    description="Return token totals, model breakdowns, and recent LLM call records.",
)
def get_usage_dashboard(
    period: str = Query("month", description="'today' | 'month' | 'all'"),
    limit: int = Query(50, ge=1, le=200, description="Recent call records to include"),
    db_manager: DatabaseManager = Depends(get_database_manager),
) -> UsageDashboardResponse:
    normalized_period = _normalize_period(period)
    window = _date_range(normalized_period)
    data = db_manager.get_llm_usage_summary(window.from_dt, window.to_dt)
    records = db_manager.get_llm_usage_records(window.from_dt, window.to_dt, limit=limit)
    payload = _build_summary_payload(normalized_period, window, data)
    payload["recent_calls"] = [_enrich_call_record(row) for row in records]
    return UsageDashboardResponse(**payload)

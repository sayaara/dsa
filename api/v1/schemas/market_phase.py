# -*- coding: utf-8 -*-
"""Market phase summary schemas."""

from typing import List, Literal, Optional

from pydantic import BaseModel, Field


MarketPhaseValue = Literal[
    "premarket",
    "intraday",
    "lunch_break",
    "closing_auction",
    "postmarket",
    "non_trading",
    "unknown",
]


class MarketPhaseSummary(BaseModel):
    """Low-sensitivity market phase metadata exposed on report meta."""

    market: Optional[str] = Field(None, description="Market region")
    phase: MarketPhaseValue = Field(..., description="Market phase")
    market_local_time: Optional[str] = Field(None, description="Market local time")
    session_date: Optional[str] = Field(None, description="Market local date")
    effective_daily_bar_date: Optional[str] = Field(None, description="Date of the latest reusable complete daily bar")
    is_trading_day: Optional[bool] = Field(None, description="Whether it is a trading day")
    is_market_open_now: Optional[bool] = Field(None, description="Whether the market is open now")
    is_partial_bar: Optional[bool] = Field(None, description="Whether the latest daily bar may be incomplete")
    minutes_to_open: Optional[int] = Field(None, description="Minutes until open")
    minutes_to_close: Optional[int] = Field(None, description="Minutes until close")
    trigger_source: Optional[str] = Field(None, description="Trigger source")
    analysis_intent: Optional[str] = Field(None, description="Analysis intent")
    warnings: List[str] = Field(default_factory=list, description="Phase-inference degradation warning codes")

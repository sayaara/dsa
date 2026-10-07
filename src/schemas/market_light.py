# -*- coding: utf-8 -*-
"""Structured Market Light snapshot schema."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from src.core.market_registry import MARKET_CODE_SET


MarketRegion = Literal["us", "ca"]
MarketLightStatus = Literal["green", "yellow", "red"]
MarketLightDataQuality = Literal["ok", "partial", "unavailable"]
MARKET_LIGHT_REGIONS = MARKET_CODE_SET


class MarketLightDimension(BaseModel):
    """A single Market Light scoring dimension."""

    score: int = Field(ge=0, le=100)
    available: bool


class MarketLightDimensions(BaseModel):
    """Canonical Market Light dimension scores."""

    breadth: MarketLightDimension
    index: MarketLightDimension
    limit: MarketLightDimension


class MarketLightSnapshot(BaseModel):
    """Structured Market Light snapshot persisted and consumed by alerts."""

    region: MarketRegion
    trade_date: str
    status: MarketLightStatus
    score: int = Field(ge=0, le=100)
    label: str
    temperature_label: str
    reasons: list[str]
    guidance: str
    dimensions: MarketLightDimensions
    data_quality: MarketLightDataQuality

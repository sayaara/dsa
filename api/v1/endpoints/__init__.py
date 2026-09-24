# -*- coding: utf-8 -*-
"""
===================================
API v1 endpoints package initialization
===================================

Responsibilities:
1. Declare all endpoint router modules
"""

from api.v1.endpoints import (
    health,
    analysis,
    history,
    stocks,
    backtest,
    data,
    system_config,
    auth,
    agent,
    usage,
    portfolio,
    alerts,
    decision_signals,
    screening,
)
__all__ = [
    "health",
    "analysis",
    "history",
    "stocks",
    "backtest",
    "data",
    "system_config",
    "auth",
    "agent",
    "usage",
    "portfolio",
    "alerts",
    "decision_signals",
    "screening",
]

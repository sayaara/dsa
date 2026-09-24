# -*- coding: utf-8 -*-
"""
===================================
Service layer package initialization
===================================

Responsibilities:
1. Declare the exportable service classes (lazily imported, so heavy dependencies such as the LLM are not pulled in at startup)

Usage:
    Import directly from the submodule, for example:
    from src.services.history_service import HistoryService
"""


def __getattr__(name: str):
    """Deferred import: load a submodule only when it is accessed as src.services.X."""
    _lazy_map = {
        "AnalysisService": "src.services.analysis_service",
        "BacktestService": "src.services.backtest_service",
        "HistoryService": "src.services.history_service",
        "StockService": "src.services.stock_service",
        "TaskService": "src.services.task_service",
        "get_task_service": "src.services.task_service",
    }
    if name in _lazy_map:
        import importlib
        module = importlib.import_module(_lazy_map[name])
        return getattr(module, name)
    raise AttributeError(f"module 'src.services' has no attribute {name!r}")


__all__ = [
    "AnalysisService",
    "BacktestService",
    "HistoryService",
    "StockService",
    "TaskService",
    "get_task_service",
]

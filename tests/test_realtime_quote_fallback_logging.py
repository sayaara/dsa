# -*- coding: utf-8 -*-
"""Regression tests for realtime quote fallback logging semantics."""

import importlib.util
import logging
import sys
from types import SimpleNamespace
from unittest.mock import MagicMock

from tests.litellm_stub import ensure_litellm_stub

ensure_litellm_stub()

try:
    json_repair_available = importlib.util.find_spec("json_repair") is not None
except ValueError:
    json_repair_available = "json_repair" in sys.modules

if not json_repair_available and "json_repair" not in sys.modules:
    sys.modules["json_repair"] = MagicMock()

from data_provider.realtime_types import RealtimeSource, UnifiedRealtimeQuote
from src.core.pipeline import StockAnalysisPipeline
from src.enums import ReportType


class _DummyFetcher:
    def __init__(self, name: str, priority: int, result=None, error: Exception | None = None):
        self.name = name
        self.priority = priority
        self._result = result
        self._error = error

    def get_realtime_quote(self, *args, **kwargs):
        if self._error is not None:
            raise self._error
        return self._result


def _make_quote(
    code: str = "600519",
    name: str = "贵州茅台",
    source: RealtimeSource = RealtimeSource.LONGBRIDGE,
    **overrides,
) -> UnifiedRealtimeQuote:
    return UnifiedRealtimeQuote(
        code=code,
        name=name,
        source=source,
        price=1688.0,
        change_pct=1.2,
        **overrides,
    )


def _make_pipeline(enable_realtime_quote: bool, realtime_quote=None) -> StockAnalysisPipeline:
    pipeline = StockAnalysisPipeline.__new__(StockAnalysisPipeline)
    pipeline.config = SimpleNamespace(
        enable_realtime_quote=enable_realtime_quote,
        enable_chip_distribution=True,
        agent_mode=False,
        agent_skills=[],
        fundamental_stage_timeout_seconds=1.5,
        report_language="zh",
    )
    pipeline.fetcher_manager = MagicMock()
    pipeline.fetcher_manager.get_stock_name.return_value = "贵州茅台"
    pipeline.fetcher_manager.get_realtime_quote.return_value = realtime_quote
    pipeline.fetcher_manager.get_chip_distribution.return_value = None
    pipeline.fetcher_manager.get_fundamental_context.return_value = {
        "source_chain": [],
        "coverage": {},
    }
    pipeline.fetcher_manager.build_failed_fundamental_context.return_value = {
        "source_chain": [],
        "coverage": {},
    }
    pipeline.db = MagicMock()
    pipeline.db.save_fundamental_snapshot.return_value = None
    pipeline.db.get_data_range.return_value = []
    pipeline.db.get_analysis_context.return_value = {}
    pipeline.search_service = SimpleNamespace(is_available=False)
    pipeline.social_sentiment_service = SimpleNamespace(is_available=False)
    pipeline.query_source = "system"
    pipeline.trend_analyzer = MagicMock()
    pipeline.analyzer = MagicMock()
    pipeline.analyzer.analyze.return_value = None
    pipeline._attach_belong_boards_to_fundamental_context = MagicMock(side_effect=lambda code, ctx: ctx)
    pipeline._enhance_context = MagicMock(return_value={"realtime": {}})
    pipeline.save_context_snapshot = False
    return pipeline


def test_pipeline_warns_once_when_all_realtime_sources_fail(caplog):
    pipeline = _make_pipeline(enable_realtime_quote=True, realtime_quote=None)

    with caplog.at_level(logging.INFO):
        result = pipeline.analyze_stock("600519", ReportType.SIMPLE, "q1")

    assert result is None
    pipeline.fetcher_manager.get_stock_name.assert_called_once_with("600519", allow_realtime=False)
    pipeline.fetcher_manager.get_realtime_quote.assert_called_once_with("600519", log_final_failure=False)
    downgrade_logs = [
        record.message
        for record in caplog.records
        if "continuing with historical close prices" in record.message
    ]
    assert downgrade_logs == ["贵州茅台(600519) all real-time quote sources unavailable; continuing with historical close prices"]


def test_pipeline_logs_disabled_realtime_once_without_fetching_quote(caplog):
    pipeline = _make_pipeline(enable_realtime_quote=False, realtime_quote=_make_quote())

    with caplog.at_level(logging.INFO):
        result = pipeline.analyze_stock("600519", ReportType.SIMPLE, "q1")

    assert result is None
    pipeline.fetcher_manager.get_stock_name.assert_called_once_with("600519", allow_realtime=False)
    pipeline.fetcher_manager.get_realtime_quote.assert_not_called()
    downgrade_logs = [
        record.message
        for record in caplog.records
        if "continuing with historical close prices" in record.message
    ]
    assert downgrade_logs == ["贵州茅台(600519) real-time quotes disabled; continuing with historical close prices"]

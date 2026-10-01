# -*- coding: utf-8 -*-
"""Story 1.5 — focused Pipeline/CLI index integration tests.

Covers the deterministic acceptance matrix from
``_bmad-output/specs/spec-pipeline-cli-integration/verification.md``:
- V1  CLI target construction
- V2  Unsupported boundary (reject before provider calls, batch continues)
- V3  Canonical batch identity (alias dedupe, stock/index isolation)
- V4  Market/date propagation (SH/SZ/CSI -> cn)
- V5  Traditional capability matrix (skip modules zero bottom-layer calls)
- V6  Agent capability matrix (same negative/positive assertions)
- V7  Search semantics (name-only query subject for indices)
- V10 Daily data-source attribution (report/history wiring and fail-open cases)
- V11 Dry-run target/date propagation

Cross-layer V8-V9/V11-V12 compatibility remains covered by the existing history,
data-routing, task-service, schedule, and stock-regression suites.
"""

from __future__ import annotations

import re
import unittest
from datetime import date, datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from src.analyzer import AnalysisResult
from src.config import Config
from src.core.pipeline import StockAnalysisPipeline, INDEX_SKIP_MODULES
from src.enums import ReportType
from src.notification import NotificationService
from src.search_service import SearchResponse, SearchService
from src.services.stock_list_parser import (
    AnalysisTarget,
    ParseStatus,
    parse_analysis_target,
)


def _index_target(raw: str) -> AnalysisTarget:
    target = parse_analysis_target(raw)
    assert target.asset_type == ParseStatus.INDEX, f"{raw} should be index"
    return target


def _stock_target(raw: str) -> AnalysisTarget:
    target = parse_analysis_target(raw)
    assert target.asset_type == ParseStatus.STOCK, f"{raw} should be stock"
    return target


def _analysis_result(
    code: str, name: str, data_sources: str | None
) -> AnalysisResult:
    result = AnalysisResult(
        code=code,
        name=name,
        sentiment_score=60,
        trend_prediction="震荡",
        operation_advice="观望",
        data_sources=data_sources or "",
    )
    if data_sources is None:
        setattr(result, "data_sources", None)
    return result


def _render_aggregate_report(
    result: AnalysisResult,
    report_type: ReportType = ReportType.SIMPLE,
) -> str:
    with patch(
        "src.notification.get_config",
        return_value=Config(stock_list=[], report_renderer_enabled=False),
    ):
        service = NotificationService()
        pipeline = StockAnalysisPipeline.__new__(StockAnalysisPipeline)
        pipeline.notifier = service
        return pipeline._generate_aggregate_report([result], report_type)


def _analysis_pipeline(
    code: str,
    name: str,
    *,
    enable_search: bool = False,
    realtime_name: str | None = None,
) -> StockAnalysisPipeline:
    pipeline = StockAnalysisPipeline.__new__(StockAnalysisPipeline)
    pipeline.fetcher_manager = MagicMock()
    pipeline.fetcher_manager.build_not_supported_fundamental_context.return_value = {
        "status": "not_supported",
        "coverage": {},
        "source_chain": [],
        "belong_boards": [],
    }
    pipeline.db = MagicMock()
    pipeline.config = MagicMock()
    pipeline.config.enable_realtime_quote = realtime_name is not None
    pipeline.config.agent_mode = False
    pipeline.config.agent_skills = []
    pipeline.config.report_language = "zh"
    pipeline.config.fundamental_stage_timeout_seconds = 5.0
    pipeline.config.market_review_enabled = False
    pipeline.config.daily_market_context_enabled = False
    pipeline.config.report_type = "simple"
    pipeline.search_service = MagicMock() if enable_search else None
    if pipeline.search_service is not None:
        pipeline.search_service.is_available = True
        pipeline.search_service.search_comprehensive_intel.return_value = {}
    pipeline.social_sentiment_service = None
    pipeline.trend_analyzer = MagicMock()
    pipeline.analyzer = MagicMock()
    pipeline.analysis_skills = None
    pipeline.query_source = "cli"
    pipeline.save_context_snapshot = False
    pipeline.progress_callback = None
    pipeline.portfolio_context = None
    pipeline.analysis_phase = "auto"
    pipeline._emit_progress = MagicMock()
    pipeline._load_daily_market_context = MagicMock(return_value=None)
    pipeline._build_market_structure_context = MagicMock(return_value=None)
    pipeline._load_persisted_intelligence_context = MagicMock(return_value=None)
    pipeline._get_analysis_context_with_market_fallback = MagicMock(
        return_value={"code": code, "stock_name": name}
    )
    pipeline._enhance_context = MagicMock(
        return_value={"code": code, "stock_name": name}
    )
    pipeline._build_analysis_context_pack_outputs = MagicMock(
        return_value=("", None)
    )
    pipeline._build_legacy_analysis_artifacts = MagicMock()
    pipeline._refresh_decision_action_for_final_result = MagicMock()
    pipeline._build_query_context = MagicMock(return_value={})
    pipeline._build_context_snapshot = MagicMock(return_value={})
    pipeline._extract_decision_signal_after_history_save = MagicMock()
    pipeline.db.save_analysis_history.return_value = 1
    pipeline.db.save_fundamental_snapshot = MagicMock()
    pipeline.db.get_data_range.return_value = []
    pipeline.db.get_analysis_context.return_value = None
    pipeline.analyzer.analyze.return_value = MagicMock(
        success=True,
        code=code,
        name=name,
        sentiment_score=60,
        operation_advice="观望",
        decision_type="hold",
        confidence_level="中",
        report_language="zh",
        dashboard={},
    )
    if realtime_name is not None:
        realtime_quote = MagicMock()
        realtime_quote.name = realtime_name
        realtime_quote.price = 3000.0
        realtime_quote.volume_ratio = 1.0
        realtime_quote.turnover_rate = 0.0
        realtime_quote.pe_ratio = None
        realtime_quote.pb_ratio = None
        realtime_quote.total_mv = None
        realtime_quote.circ_mv = None
        pipeline.fetcher_manager.get_realtime_quote.return_value = realtime_quote
    return pipeline


class PipelineIndexTargetsTestCase(unittest.TestCase):
    """V1 — CLI target construction produces expected type + canonical identity."""



    def test_v2_unregistered_csi_is_unsupported(self) -> None:
        target = parse_analysis_target("930956.CSI")
        self.assertEqual(target.asset_type, ParseStatus.UNSUPPORTED)
        self.assertIsNotNone(target.unsupported_reason)




class PipelineMarketDatePropagationTestCase(unittest.TestCase):
    """V4 — SH/SZ/CSI indices all use cn for market/date semantics."""

    def _pipeline(self) -> StockAnalysisPipeline:
        pipeline = StockAnalysisPipeline.__new__(StockAnalysisPipeline)
        pipeline.fetcher_manager = MagicMock()
        pipeline.db = MagicMock()
        return pipeline



    def test_v4_stock_still_uses_market_for_stock(self) -> None:
        with patch(
            "src.core.pipeline.get_effective_trading_date",
            return_value=date(2026, 8, 26),
        ), patch(
            "src.core.pipeline.get_market_for_stock", return_value="cn"
        ) as mock_market:
            StockAnalysisPipeline._resolve_resume_target_date("600519")
        mock_market.assert_called_once_with("600519")



class PipelineCapabilityMatrixTestCase(unittest.TestCase):
    """V5/V6 — INDEX_SKIP_MODULES zero bottom-layer calls for index targets."""

    def test_index_skip_modules_contains_all_six(self) -> None:
        self.assertEqual(
            INDEX_SKIP_MODULES,
            frozenset({
                "chip_distribution",
                "fundamental",
                "belong_boards",
                "capital_flow",
                "lhb",
                "corporate_events",
            }),
        )


    def test_v6_agent_tool_filter_removes_index_incompatible_tools(self) -> None:
        from src.agent.tools.registry import ToolRegistry, ToolDefinition, ToolParameter

        registry = ToolRegistry()
        for name in (
            "get_realtime_quote",
            "get_daily_history",
            "get_stock_info",
            "get_analysis_context",
        ):
            registry.register(
                ToolDefinition(
                    name=name,
                    description=name,
                    parameters=[
                        ToolParameter(
                            name="stock_code",
                            type="string",
                            description="stock code",
                        )
                    ],
                    handler=lambda **kw: {},
                )
            )

        executor = MagicMock()
        executor.tool_registry = registry
        pipeline = StockAnalysisPipeline.__new__(StockAnalysisPipeline)
        filtered = pipeline._filter_agent_tools_for_index(executor)

        names = set(filtered.tool_registry.list_names())
        self.assertIn("get_realtime_quote", names)
        self.assertIn("get_daily_history", names)
        self.assertIn("get_analysis_context", names)
        self.assertNotIn("get_stock_info", names)



class PipelineDailySourceAttributionTestCase(unittest.TestCase):
    """V10 — persisted daily providers reach history and existing reports."""







class PipelineSearchSemanticsTestCase(unittest.TestCase):
    """V7 — index search query subject is the Chinese name only."""


    def test_v7_stock_search_keeps_code(self) -> None:
        pipeline = _analysis_pipeline("600519", "贵州茅台", enable_search=True)

        pipeline.analyze_stock("600519", MagicMock(), "q1")

        call_kwargs = pipeline.search_service.search_comprehensive_intel.call_args.kwargs
        self.assertEqual(call_kwargs["stock_code"], "600519")

    def test_v7_provider_queries_contain_only_chinese_index_name(self) -> None:
        service = SearchService(
            searxng_public_instances_enabled=False,
            news_max_age_days=3,
            news_strategy_profile="short",
        )
        provider = MagicMock()
        provider.name = "DummyProvider"
        provider.is_available = True

        def search(query: str, **_kwargs) -> SearchResponse:
            return SearchResponse(
                query=query,
                results=[],
                provider="DummyProvider",
                success=True,
            )

        provider.search.side_effect = search
        service._providers = [provider]

        service.search_comprehensive_intel(
            stock_code="",
            stock_name="上证50",
            max_searches=5,
        )

        queries = [call.args[0] for call in provider.search.call_args_list]
        self.assertTrue(queries)
        for query in queries:
            self.assertIn("上证50", query)
            self.assertNotRegex(query, re.compile(r"\d{6}"))
            self.assertNotIn("sh000016", query.casefold())


class PipelineBatchFailureIsolationTestCase(unittest.TestCase):
    """V2/V10 — unsupported targets rejected before provider calls; batch continues."""



class PipelineDryRunTestCase(unittest.TestCase):
    """V11 — dry-run preserves target identity through resume checks."""



if __name__ == "__main__":
    unittest.main()

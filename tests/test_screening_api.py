# -*- coding: utf-8 -*-
"""Tests for the built-in screening endpoints."""

from __future__ import annotations

import os
import sys
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict
from unittest.mock import ANY, MagicMock, patch
import threading

from fastapi import HTTPException
import pandas as pd

try:
    import litellm  # noqa: F401
except ModuleNotFoundError:
    sys.modules["litellm"] = MagicMock()

from api.v1.endpoints import screening as screening_endpoint
from src.config import Config
from src.services import screening_service
from src.services.screening import REFERENCE_REVISION
from src.services.screening.config import Config as ScreeningPipelineConfig
from src.services.task_queue import TaskInfo, TaskStatus as QueueTaskStatus


def _screening_unavailable() -> HTTPException:
    return HTTPException(
        status_code=424,
        detail={"error": "screening_unavailable", "message": "Screening is unavailable"},
    )


def _raise_screening_unavailable() -> None:
    raise _screening_unavailable()


def _sleeping_constituent_source(*, symbol: str) -> pd.DataFrame:
    del symbol
    time.sleep(5)
    return pd.DataFrame()


def _make_screening_core(
    *,
    screen=None,
    list_strategies=None,
    get_status=None,
) -> SimpleNamespace:
    return SimpleNamespace(
        screen=screen or MagicMock(return_value=[]),
        list_strategies=list_strategies or (lambda: [{"id": "dual_low", "name": "双低选股", "description": "", "category": "价值"}]),
        get_status=get_status or (lambda: {"supported_markets": ["cn"], "contract_version": "1", "version": "0.2.0", "strategy_count": 1}),
    )


@contextmanager
def _patch_screening_core(core: SimpleNamespace):
    """Replace native screening entry points without recreating an adapter layer."""
    with (
        patch("src.services.screening_service.run_screening_pipeline", new=core.screen),
        patch("src.services.screening_service.load_screening_strategies", new=core.list_strategies),
        patch("src.services.screening_service._call_screening_status", new=core.get_status),
    ):
        yield core


def _screening_unavailable_diagnostics() -> Dict[str, str]:
    return {
        "reason": "unexpected_exception",
        "stage": "get_status",
        "error_type": "RuntimeError",
    }


class ScreeningOpportunitiesApiTestCase(unittest.TestCase):
    def setUp(self) -> None:
        Config.reset_instance()
        self.env_patch = patch.dict(os.environ, {"SCREENING_DATA_DIR": ""}, clear=False)
        self.env_patch.start()

    def tearDown(self) -> None:
        self.env_patch.stop()
        Config.reset_instance()

    def _config(self, *, enabled: bool) -> Config:
        return Config(screening_enabled=enabled)

    @staticmethod
    def _request(cookies=None) -> SimpleNamespace:
        return SimpleNamespace(cookies=cookies or {})

    def _screen(self, config: Config, *, mock_enrichment: bool = True, **kwargs):
        if not mock_enrichment:
            return screening_endpoint.screening_screen(
                screening_endpoint.ScreeningScreenRequest(**kwargs),
                http_request=self._request(),
                config=config,
            )
        with patch(
            "src.services.screening_service._enrich_candidates_with_dsa",
            side_effect=lambda candidates: (
                candidates,
                {
                    "enabled": True,
                    "max_candidates": 3,
                    "requested_count": min(len(candidates), 3),
                    "enriched_count": 0,
                    "warnings": [],
                },
            ),
        ):
            return screening_endpoint.screening_screen(
                screening_endpoint.ScreeningScreenRequest(**kwargs),
                http_request=self._request(),
                config=config,
            )

    def _strategies(self, config: Config):
        return screening_endpoint.screening_strategies(request=self._request(), config=config)

    def test_builtin_screening_core_loads_bundled_strategies(self) -> None:
        status = screening_service._call_screening_status()
        strategies = screening_service._list_strategies()

        self.assertTrue(status["available"])
        self.assertEqual(status["engine"], "builtin")
        self.assertEqual(status["reference_revision"], REFERENCE_REVISION)
        self.assertEqual(status["strategy_count"], len(strategies))
        self.assertIn("dual_low", {item["id"] for item in strategies})

    def test_status_exposes_builtin_engine_provenance(self) -> None:
        payload = screening_endpoint.screening_status(config=self._config(enabled=True))

        self.assertTrue(payload["available"])
        self.assertEqual(payload["engine"], "builtin")
        self.assertEqual(payload["reference_revision"], REFERENCE_REVISION)

    def test_status_defaults_to_disabled(self) -> None:
        config = self._config(enabled=False)

        with patch("src.services.screening_service._call_screening_status", side_effect=_raise_screening_unavailable):
            payload = screening_endpoint.screening_status(config=config)

        self.assertEqual(payload["enabled"], False)
        self.assertEqual(payload["available"], False)
        self.assertEqual(payload["engine"], "builtin")
        self.assertNotIn("diagnostics", payload)

    def test_status_includes_engine_contract_metadata(self) -> None:
        config = self._config(enabled=True)

        with patch(
            "src.services.screening_service._call_screening_status",
            return_value={"available": True, "contract_version": "1", "version": "0.2.0", "strategy_count": 8},
        ):
            payload = screening_endpoint.screening_status(config=config)

        self.assertTrue(payload["available"])
        self.assertEqual(payload["contract_version"], "1")
        self.assertEqual(payload["version"], "0.2.0")
        self.assertEqual(payload["strategy_count"], 8)

    def test_status_includes_screening_source_health_snapshot(self) -> None:
        config = self._config(enabled=True)

        with (
            patch(
                "src.services.screening_service._call_screening_status",
                return_value={"available": True, "contract_version": "1", "version": "0.2.0", "strategy_count": 8},
            ),
            patch(
                "src.services.screening_service._get_screening_source_health_snapshot",
                return_value={"snapshot": {"sina": {"failures": 2, "disabled": False}}},
            ),
        ):
            payload = screening_endpoint.screening_status(config=config)

        self.assertEqual(payload["source_health"]["snapshot"]["sina"]["failures"], 2)

    def test_status_preserves_engine_available_false_without_diagnostics(self) -> None:
        config = self._config(enabled=False)

        with patch(
            "src.services.screening_service._call_screening_status",
            return_value={"available": False, "contract_version": "1", "version": "0.2.0", "strategy_count": 0},
        ):
            payload = screening_endpoint.screening_status(config=config)

        self.assertFalse(payload["available"])
        self.assertEqual(payload["contract_version"], "1")
        self.assertNotIn("diagnostics", payload)

    def test_status_logs_and_reports_strategy_load_diagnostics(self) -> None:
        config = self._config(enabled=False)

        with (
            patch(
                "src.services.screening_service.load_screening_strategies",
                side_effect=RuntimeError("strategy load failed"),
            ),
            self.assertLogs("src.services.screening_service", level="WARNING") as captured,
        ):
            payload = screening_endpoint.screening_status(config=config)

        self.assertFalse(payload["available"])
        self.assertEqual(payload["diagnostics"]["reason"], "unexpected_exception")
        self.assertEqual(payload["diagnostics"]["stage"], "strategy_load")
        self.assertEqual(payload["diagnostics"]["error_type"], "RuntimeError")
        self.assertIn("Unexpected Screening strategy_load failure", "\n".join(captured.output))

    def test_strategies_returns_native_strategy_metadata(self) -> None:
        config = self._config(enabled=True)
        fake_module = _make_screening_core(
            list_strategies=lambda: [
                {"id": "dual_low", "name": "双低选股", "description": "value", "category": "价值"},
                {"id": "trend_quality", "title": "趋势质量", "description": "trend", "tag": "框架"},
            ],
        )

        with _patch_screening_core(fake_module):
            payload = self._strategies(config=config)

        self.assertEqual(payload["enabled"], True)
        self.assertEqual(payload["strategy_count"], 2)
        self.assertEqual(payload["strategies"][0]["id"], "dual_low")
        self.assertEqual(payload["strategies"][0]["name"], "双低选股")
        self.assertEqual(payload["strategies"][1]["name"], "趋势质量")

    def test_strategies_rejects_when_engine_is_unavailable(self) -> None:
        config = self._config(enabled=True)

        with (
            patch(
                "src.services.screening_service._get_screening_status_snapshot",
                return_value=({}, False, _screening_unavailable_diagnostics()),
            ),
        ):
            with self.assertRaises(HTTPException) as caught:
                self._strategies(config=config)

        self.assertEqual(caught.exception.status_code, 424)
        self.assertEqual(caught.exception.detail["error"], "screening_unavailable")
        self.assertEqual(caught.exception.detail.get("diagnostics", {}).get("reason"), "unexpected_exception")

    def test_screen_rejects_when_disabled(self) -> None:
        config = self._config(enabled=False)

        with self.assertRaises(HTTPException) as caught:
            self._screen(config)

        self.assertEqual(caught.exception.status_code, 403)
        self.assertEqual(caught.exception.detail["error"], "screening_disabled")

    def test_screen_rejects_when_screening_unavailable(self) -> None:
        config = self._config(enabled=True)

        with (
            patch(
                "src.services.screening_service._get_screening_status_snapshot",
                return_value=({}, False, _screening_unavailable_diagnostics()),
            ),
        ):
            with self.assertRaises(HTTPException) as caught:
                self._screen(config)

        self.assertEqual(caught.exception.status_code, 424)
        self.assertEqual(caught.exception.detail["error"], "screening_unavailable")
        self.assertEqual(caught.exception.detail.get("diagnostics", {}).get("reason"), "unexpected_exception")
        self.assertIn("Screening failed to initialize", caught.exception.detail["message"])

    def test_start_screen_task_submits_background_work(self) -> None:
        config = self._config(enabled=True)
        fake_queue = MagicMock()
        fake_queue.submit_background_task.return_value = SimpleNamespace(
            task_id="screen-task-1",
            trace_id="screen-task-1",
            status=QueueTaskStatus.PENDING,
            message="Screening 选股任务已提交",
        )

        with (
            patch("api.v1.endpoints.screening.get_task_queue", return_value=fake_queue),
            patch("api.v1.endpoints.screening.uuid.uuid4", return_value=SimpleNamespace(hex="screen-task-1")),
            patch.object(
                screening_endpoint.ScreeningService,
                "screen",
                return_value={"enabled": True, "candidates": [], "candidate_count": 0},
            ) as screen_mock,
        ):
            payload = screening_endpoint.screening_start_screen_task(
                screening_endpoint.ScreeningScreenRequest(market="cn", strategy="dual_low", max_results=3),
                http_request=self._request(),
                config=config,
            )
            run_task = fake_queue.submit_background_task.call_args.args[0]
            result = run_task()

        self.assertEqual(payload.task_id, "screen-task-1")
        self.assertEqual(payload.max_results, 3)
        fake_queue.submit_background_task.assert_called_once()
        self.assertEqual(fake_queue.submit_background_task.call_args.kwargs["report_type"], "screening_screen")
        screen_mock.assert_called_once_with(
            strategy="dual_low",
            market="cn",
            max_results=3,
            selection_seed="",
            progress_callback=ANY,
        )
        screen_mock.call_args.kwargs["progress_callback"](66, "Running LLM re-ranking of the candidates")
        self.assertEqual(result["candidate_count"], 0)
        fake_queue.update_task_progress.assert_any_call(
            "screen-task-1",
            20,
            "Screening is running; it keeps running in the background while external data sources are slow",
        )
        fake_queue.update_task_progress.assert_any_call(
            "screen-task-1",
            66,
            "Running LLM re-ranking of the candidates",
        )

    def test_screen_task_status_returns_screening_result(self) -> None:
        task = TaskInfo(
            task_id="screen-task-1",
            trace_id="screen-task-1",
            stock_code="screening_screen",
            status=QueueTaskStatus.COMPLETED,
            progress=100,
            message="任务执行完成",
            result={"enabled": True, "candidates": [], "candidate_count": 0},
            report_type="screening_screen",
        )
        fake_queue = MagicMock()
        fake_queue.get_task.return_value = task

        with patch("api.v1.endpoints.screening.get_task_queue", return_value=fake_queue):
            payload = screening_endpoint.screening_screen_task_status("screen-task-1")

        self.assertEqual(payload.status, "completed")
        self.assertEqual(payload.result["candidate_count"], 0)

    def test_screen_task_status_rejects_non_screening_task(self) -> None:
        task = TaskInfo(
            task_id="analysis-task-1",
            stock_code="600519",
            status=QueueTaskStatus.COMPLETED,
            report_type="detailed",
        )
        fake_queue = MagicMock()
        fake_queue.get_task.return_value = task

        with patch("api.v1.endpoints.screening.get_task_queue", return_value=fake_queue):
            with self.assertRaises(HTTPException) as caught:
                screening_endpoint.screening_screen_task_status("analysis-task-1")

        self.assertEqual(caught.exception.status_code, 404)
        self.assertEqual(caught.exception.detail["error"], "screening_screen_task_not_found")

    def test_screen_calls_pipeline_and_normalizes_llm_fields(self) -> None:
        config = self._config(enabled=True)
        fake_module = _make_screening_core(
            screen=MagicMock(
                return_value={
                    "run_id": "run123",
                    "strategy": "dual_low",
                    "market": "cn",
                    "snapshot_count": 100,
                    "snapshot_source": "em_datacenter",
                    "after_filter_count": 5,
                    "llm_ranked": True,
                    "llm_coverage": 1.0,
                    "llm_model_used": "openai/gpt-4.1",
                    "llm_attempted_models": ["deepseek/deepseek-chat", "openai/gpt-4.1"],
                    "llm_failure_reason": "",
                    "ranking_mode": "llm",
                    "warnings": "fallback",
                    "degradation": ["Snapshot source fallback: em_datacenter: retry from cache"],
                    "source_errors": "sina timeout",
                    "llm_parse_errors": "retry parsed partial JSON",
                    "deep_analysis_requested": False,
                    "post_analyzers": ["scorecard"],
                    "daily_enriched": True,
                    "daily_enrich_count": 12,
                    "risk_enabled": True,
                    "portfolio_diversity_enabled": True,
                    "portfolio_concentration_notes": ["sector concentration adjusted"],
                    "result_variant_applied": True,
                    "result_variant_pool_size": 4,
                    "result_variant_rotated_slots": 1,
                    "candidates": [
                        {
                            "code": "600519",
                            "name": "Kweichow Moutai",
                            "score": 88.5,
                            "llm_score": 90.0,
                            "llm_thesis": "LLM likes the setup",
                            "risk_level": "medium",
                            "risk_flags": ["valuation"],
                            "price": 1688.0,
                            "industry": "Baijiu",
                            "factor_scores": {"value": 88.0},
                        }
                    ],
                }
            ),
        )

        with _patch_screening_core(fake_module):
            payload = self._screen(
                config,
                market="cn",
                strategy="dual_low",
                max_results=5,
                variant_seed="browser-a",
            )

        fake_module.screen.assert_called_once_with(
            "dual_low",
            market="cn",
            max_output=5,
            use_llm=True,
            context=ANY,
            selection_seed="browser-a",
            config=ANY,
            progress_callback=None,
            daily_history_fetcher=ANY,
        )
        self.assertEqual(fake_module.screen.call_args.kwargs["context"]["llm"]["model"], "")
        self.assertEqual(payload["run_id"], "run123")
        self.assertEqual(payload["snapshot_count"], 100)
        self.assertEqual(payload["snapshot_source"], "em_datacenter")
        self.assertEqual(payload["after_filter_count"], 5)
        self.assertEqual(payload["llm_ranked"], True)
        self.assertEqual(payload["llm_coverage"], 1.0)
        self.assertEqual(payload["llm_model_used"], "openai/gpt-4.1")
        self.assertEqual(
            payload["llm_attempted_models"],
            ["deepseek/deepseek-chat", "openai/gpt-4.1"],
        )
        self.assertEqual(payload["ranking_mode"], "llm")
        self.assertEqual(
            payload["warnings"],
            ["fallback", "Snapshot source fallback: em_datacenter: retry from cache"],
        )
        self.assertEqual(
            payload["degradation"],
            ["Snapshot source fallback: em_datacenter: retry from cache"],
        )
        self.assertEqual(payload["source_errors"], ["sina timeout"])
        self.assertEqual(payload["llm_parse_errors"], ["retry parsed partial JSON"])
        self.assertEqual(payload["candidate_count"], 1)
        self.assertEqual(payload["post_analyzers"], ["scorecard"])
        self.assertEqual(payload["daily_enriched"], True)
        self.assertEqual(payload["daily_enrich_count"], 12)
        self.assertEqual(payload["portfolio_concentration_notes"], ["sector concentration adjusted"])
        self.assertEqual(payload["result_variant_applied"], True)
        self.assertEqual(payload["result_variant_pool_size"], 4)
        self.assertEqual(payload["result_variant_rotated_slots"], 1)
        self.assertEqual(payload["candidates"][0]["code"], "600519")
        self.assertEqual(payload["candidates"][0]["llm_score"], 90.0)
        self.assertEqual(payload["candidates"][0]["llm_thesis"], "LLM likes the setup")
        self.assertEqual(payload["candidates"][0]["risk_level"], "medium")
        self.assertEqual(payload["candidates"][0]["price"], 1688.0)
        self.assertEqual(payload["candidates"][0]["industry"], "Baijiu")

    def test_screen_prefers_dsa_daily_history_for_screening_enrichment(self) -> None:
        config = self._config(enabled=True)
        from src.services.screening import daily as daily_module

        builtin_daily_fetch = daily_module.fetch_daily_history
        original_daily_fetch = MagicMock(side_effect=AssertionError("Screening daily fetch should not run first"))
        captured: Dict[str, Any] = {}

        def screen_with_daily_fetch(strategy: str, **kwargs: Any) -> Dict[str, Any]:
            daily_fetcher = kwargs["daily_history_fetcher"]
            daily_df = daily_fetcher(
                "600519",
                lookback_days=20,
                source="akshare",
                retries=1,
            )
            captured["daily_df"] = daily_df
            captured["context"] = kwargs.get("context")
            return {
                "strategy": strategy,
                "candidates": [{"code": "600519", "score": 88.0}],
            }

        fake_module = _make_screening_core(screen=MagicMock(side_effect=screen_with_daily_fetch))

        with (
            patch.object(daily_module, "fetch_daily_history", original_daily_fetch),
            _patch_screening_core(fake_module),
            patch(
                "src.services.screening_service.get_dsa_daily_history",
                return_value=(
                    [
                        {
                            "trade_date": "20260603",
                            "close": "10.5",
                            "vol": "123400",
                        }
                    ],
                    "EfinanceFetcher",
                ),
            ) as dsa_history_mock,
        ):
            payload = self._screen(config, market="cn", strategy="dual_low", max_results=5)

        daily_df = captured["daily_df"]
        self.assertEqual(daily_df.attrs["source"], "dsa:EfinanceFetcher")
        self.assertEqual(daily_df.loc[0, "date"], "2026-06-03")
        self.assertEqual(daily_df.loc[0, "volume"], 123400)
        self.assertEqual(daily_df.loc[0, "open"], 10.5)
        self.assertEqual(payload["candidate_count"], 1)
        self.assertIn("daily_history", captured["context"]["dsa"]["capabilities"])
        self.assertIs(captured["context"]["dsa"]["get_daily_history"], dsa_history_mock)
        dsa_history_mock.assert_called_once_with("600519", lookback_days=20)
        original_daily_fetch.assert_not_called()
        self.assertIs(daily_module.fetch_daily_history, builtin_daily_fetch)

    def test_screen_enriches_top_candidates_with_dsa_context(self) -> None:
        config = self._config(enabled=True)
        fake_manager = SimpleNamespace(get_stock_name=MagicMock(return_value="贵州茅台"))
        fake_module = _make_screening_core(
            screen=MagicMock(
                return_value={
                    "candidates": [
                        {
                            "code": "600519",
                            "score": 88.5,
                            "reason": "Screening pick",
                        }
                    ]
                }
            ),
        )

        with (
            _patch_screening_core(fake_module),
            patch("src.services.screening_service._get_dsa_fetcher_manager", return_value=fake_manager),
            patch(
                "src.services.screening_service.get_dsa_realtime_quote",
                return_value={"price": 1688.0, "change_pct": 1.2, "amount": 100000000.0},
            ),
            patch(
                "src.services.screening_service.get_dsa_fundamental_context",
                return_value={"market": "cn", "coverage": {"valuation": "available"}},
            ),
            patch(
                "src.services.screening_service.search_dsa_stock_news",
                return_value={
                    "success": True,
                    "provider": "test",
                    "results": [{"title": "贵州茅台最新公告", "source": "测试源"}],
                },
            ),
            patch(
                "src.services.screening_service.search_dsa_stock_events",
                return_value={
                    "success": True,
                    "provider": "test",
                    "results": [{"title": "贵州茅台年度报告", "source": "测试源"}],
                },
            ),
        ):
            payload = self._screen(
                config,
                market="cn",
                strategy="dual_low",
                max_results=5,
                mock_enrichment=False,
            )

        candidate = payload["candidates"][0]
        self.assertEqual(candidate["name"], "贵州茅台")
        self.assertEqual(candidate["price"], 1688.0)
        self.assertTrue(candidate["dsa_context"]["enriched"])
        self.assertEqual(candidate["dsa_news"][0]["title"], "贵州茅台最新公告")
        self.assertEqual(candidate["dsa_events"][0]["title"], "贵州茅台年度报告")
        self.assertIn("Quote: price", candidate["dsa_analysis_summary"])
        self.assertEqual(payload["dsa_enrichment"]["enriched_count"], 1)

    def test_screen_reuses_screening_dsa_context_without_refetch(self) -> None:
        config = self._config(enabled=True)
        fake_module = _make_screening_core(
            screen=MagicMock(
                return_value={
                    "candidates": [
                        {
                            "code": "600519",
                            "name": "贵州茅台",
                            "score": 88.5,
                            "dsa_context": {
                                "enriched": True,
                                "quote": {"price": 1688.0, "change_pct": 1.2},
                                "warnings": ["from_screening_provider"],
                            },
                            "dsa_news": [{"title": "贵州茅台最新公告", "source": "测试源"}],
                            "dsa_analysis_summary": "DSA新闻: 贵州茅台最新公告",
                        }
                    ]
                }
            ),
        )

        with (
            _patch_screening_core(fake_module),
            patch("src.services.screening_service.get_dsa_realtime_quote") as quote_mock,
            patch("src.services.screening_service.get_dsa_fundamental_context") as fundamentals_mock,
            patch("src.services.screening_service.search_dsa_stock_news") as news_mock,
            patch("src.services.screening_service.search_dsa_stock_events") as events_mock,
        ):
            payload = self._screen(
                config,
                market="cn",
                strategy="dual_low",
                max_results=5,
                mock_enrichment=False,
            )

        candidate = payload["candidates"][0]
        self.assertTrue(candidate["dsa_context"]["enriched"])
        self.assertEqual(candidate["dsa_news"][0]["title"], "贵州茅台最新公告")
        self.assertEqual(candidate["dsa_analysis_summary"], "DSA新闻: 贵州茅台最新公告")
        self.assertEqual(payload["dsa_enrichment"]["enriched_count"], 1)
        self.assertEqual(payload["dsa_enrichment"]["warnings"], ["from_screening_provider"])
        quote_mock.assert_not_called()
        fundamentals_mock.assert_not_called()
        news_mock.assert_not_called()
        events_mock.assert_not_called()

    def test_screen_reuses_context_news_results_without_refetch(self) -> None:
        config = self._config(enabled=True)
        fake_module = _make_screening_core(
            screen=MagicMock(
                return_value={
                    "candidates": [
                        {
                            "code": "600519",
                            "name": "贵州茅台",
                            "score": 88.5,
                            "dsa_context": {
                                "enriched": True,
                                "quote": {"price": 1688.0, "change_pct": 1.2},
                                "news": {
                                    "success": True,
                                    "summary": "DSA新闻：贵州茅台最新公告",
                                    "results": [{"title": "贵州茅台最新公告", "source": "测试源"}],
                                },
                                "warnings": ["from_screening_provider"],
                            },
                            "dsa_news": [],
                        }
                    ]
                }
            ),
        )

        with (
            _patch_screening_core(fake_module),
            patch("src.services.screening_service.get_dsa_realtime_quote") as quote_mock,
            patch("src.services.screening_service.get_dsa_fundamental_context") as fundamentals_mock,
            patch("src.services.screening_service.search_dsa_stock_news") as news_mock,
            patch("src.services.screening_service.search_dsa_stock_events") as events_mock,
        ):
            payload = self._screen(
                config,
                market="cn",
                strategy="dual_low",
                max_results=5,
                mock_enrichment=False,
            )

        candidate = payload["candidates"][0]
        self.assertEqual(candidate["dsa_news"][0]["title"], "贵州茅台最新公告")
        self.assertEqual(candidate["dsa_analysis_summary"], "DSA新闻：贵州茅台最新公告")
        self.assertEqual(payload["dsa_enrichment"]["enriched_count"], 1)
        self.assertEqual(payload["dsa_enrichment"]["warnings"], ["from_screening_provider"])
        quote_mock.assert_not_called()
        fundamentals_mock.assert_not_called()
        news_mock.assert_not_called()
        events_mock.assert_not_called()

    def test_screen_completes_light_screening_context_with_news_only(self) -> None:
        config = self._config(enabled=True)
        fake_module = _make_screening_core(
            screen=MagicMock(
                return_value={
                    "candidates": [
                        {
                            "code": "600519",
                            "name": "贵州茅台",
                            "score": 88.5,
                            "dsa_context": {
                                "enriched": True,
                                "profile": "pre_rank_light",
                                "news_included": False,
                                "quote": {"price": 1688.0, "change_pct": 1.2},
                                "fundamentals": {"coverage": {"valuation": "available"}},
                                "news": {
                                    "success": False,
                                    "skipped": True,
                                    "reason": "pre_rank_light_context",
                                    "results": [],
                                },
                            },
                            "dsa_news": [],
                            "dsa_analysis_summary": "DSA行情: 现价 1688.0",
                        }
                    ]
                }
            ),
        )
        fake_manager = SimpleNamespace(get_stock_name=MagicMock(return_value="贵州茅台"))

        with (
            _patch_screening_core(fake_module),
            patch("src.services.screening_service._get_dsa_fetcher_manager", return_value=fake_manager),
            patch("src.services.screening_service.get_dsa_realtime_quote") as quote_mock,
            patch("src.services.screening_service.get_dsa_fundamental_context") as fundamentals_mock,
            patch(
                "src.services.screening_service.search_dsa_stock_news",
                return_value={
                    "success": True,
                    "provider": "test",
                    "results": [{"title": "贵州茅台最新公告", "source": "测试源"}],
                },
            ) as news_mock,
            patch(
                "src.services.screening_service.search_dsa_stock_events",
                return_value={"success": False, "results": []},
            ),
        ):
            payload = self._screen(
                config,
                market="cn",
                strategy="dual_low",
                max_results=5,
                mock_enrichment=False,
            )

        candidate = payload["candidates"][0]
        self.assertEqual(candidate["dsa_context"]["profile"], "post_rank_full")
        self.assertTrue(candidate["dsa_context"]["news_included"])
        self.assertEqual(candidate["dsa_context"]["quote"]["price"], 1688.0)
        self.assertEqual(candidate["dsa_context"]["fundamentals"]["coverage"]["valuation"], "available")
        self.assertEqual(candidate["dsa_news"][0]["title"], "贵州茅台最新公告")
        quote_mock.assert_not_called()
        fundamentals_mock.assert_not_called()
        news_mock.assert_called_once()

    def test_dsa_pre_rank_candidate_context_omits_news(self) -> None:
        fake_manager = SimpleNamespace(get_stock_name=MagicMock(return_value="贵州茅台"))

        with (
            patch("src.services.screening_service._get_dsa_fetcher_manager", return_value=fake_manager),
            patch(
                "src.services.screening_service.get_dsa_realtime_quote",
                return_value={"price": 1688.0, "change_pct": 1.2, "amount": 100000000.0},
            ),
            patch(
                "src.services.screening_service.get_dsa_fundamental_context",
                return_value={"market": "cn", "coverage": {"valuation": "available"}},
            ),
            patch("src.services.screening_service.search_dsa_stock_news") as news_mock,
        ):
            context = screening_service.get_dsa_candidate_context("600519", "贵州茅台")

        self.assertEqual(context["profile"], "pre_rank_light")
        self.assertFalse(context["news_included"])
        self.assertTrue(context["news"]["skipped"])
        self.assertEqual(context["quote"]["price"], 1688.0)
        self.assertEqual(context["fundamentals"]["coverage"]["valuation"], "available")
        news_mock.assert_not_called()

    def test_screen_bridges_dsa_llm_config_into_screening_runtime(self) -> None:
        config = Config(
            screening_enabled=True,
            litellm_model="gemini/gemini-2.5-flash",
            litellm_fallback_models=["deepseek/deepseek-chat"],
            llm_channels=[
                {
                    "name": "gemini",
                    "protocol": "gemini",
                    "enabled": True,
                    "base_url": "",
                    "api_keys": ["dsa-gemini-key"],
                    "models": ["gemini/gemini-2.5-flash"],
                    "extra_headers": {"x-tenant": "dsa"},
                }
            ],
        )
        captured: dict[str, object] = {}

        def screen_impl(_strategy: str, **kwargs):
            captured["config"] = kwargs.get("config")
            captured["context"] = kwargs.get("context")
            return {"candidates": []}

        fake_module = _make_screening_core(screen=MagicMock(side_effect=screen_impl))

        with (
            patch.dict(
                screening_service.os.environ,
                {
                    "GEMINI_API_KEY": "outer-key",
                    "TUSHARE_TOKEN": "",
                    "SNAPSHOT_SOURCE_PRIORITY": "",
                    "LLM_CANDIDATE_CONTEXT_ENABLED": "true",
                    "LLM_CANDIDATE_MULTIPLIER": "",
                    "LLM_MAX_CANDIDATES": "",
                    "DAILY_FETCH_RETRIES": "",
                    "DAILY_FETCH_MAX_WORKERS": "",
                },
                clear=False,
            ),
            _patch_screening_core(fake_module),
        ):
            payload = self._screen(config, market="cn", strategy="dual_low", max_results=5)
            self.assertEqual(screening_service.os.environ.get("GEMINI_API_KEY"), "outer-key")

        pipeline_config = captured["config"]
        self.assertIsInstance(pipeline_config, ScreeningPipelineConfig)
        self.assertEqual(pipeline_config.llm_model, "gemini/gemini-2.5-flash")
        self.assertEqual(pipeline_config.llm_fallback_models, ["deepseek/deepseek-chat"])
        self.assertEqual(pipeline_config.llm_channels[0]["name"], "gemini")
        self.assertEqual(pipeline_config.llm_channels[0]["protocol"], "gemini")
        self.assertEqual(pipeline_config.llm_channels[0]["api_keys"], ["dsa-gemini-key"])
        self.assertFalse(pipeline_config.llm_candidate_context_enabled)
        self.assertEqual(pipeline_config.llm_candidate_multiplier, 2)
        self.assertEqual(pipeline_config.llm_max_candidates, 10)
        self.assertEqual(pipeline_config.daily_source, "yfinance")
        self.assertEqual(pipeline_config.daily_fetch_retries, 3)
        self.assertEqual(pipeline_config.daily_fetch_max_workers, 1)
        self.assertEqual(
            pipeline_config.snapshot_source_priority,
            ["yfinance"],
        )
        self.assertEqual(pipeline_config.data_dir, screening_service.DSA_SCREENING_DATA_DIR)
        self.assertEqual(
            pipeline_config.fallback_snapshot_path,
            screening_service.DSA_SCREENING_DATA_DIR / "snapshot.last_good.json",
        )
        self.assertEqual(
            pipeline_config.daily_history_cache_dir,
            screening_service.DSA_SCREENING_DATA_DIR / "daily_history",
        )
        self.assertEqual(
            pipeline_config.industry_provider_cache_dir,
            screening_service.DSA_SCREENING_DATA_DIR / "industry_provider_cache",
        )
        context = captured["context"]
        self.assertIsInstance(context, dict)
        self.assertEqual(context["llm"]["model"], "gemini/gemini-2.5-flash")
        self.assertFalse(context["llm"]["candidate_context_enabled"])
        self.assertEqual(context["llm"]["candidate_multiplier"], 2)
        self.assertEqual(context["llm"]["max_candidates"], 10)
        self.assertEqual(context["llm"]["channels"][0]["api_keys"], ["dsa-gemini-key"])
        self.assertEqual(context["llm"]["channels"][0]["extra_headers"], {"x-tenant": "dsa"})
        self.assertEqual(context["llm"]["model_list"][0]["litellm_params"]["extra_headers"], {"x-tenant": "dsa"})
        self.assertIn("get_candidate_context", context["dsa"])
        self.assertEqual(context["dsa"]["mode"], "pre_rank_light")
        self.assertEqual(context["dsa"]["max_candidates"], 3)
        self.assertFalse(context["dsa"]["include_news"])
        self.assertNotIn("search_stock_news", context["dsa"])
        self.assertEqual(payload["candidate_count"], 0)

    def test_screen_injects_dsa_channel_headers_into_screening_litellm_calls(self) -> None:
        config = Config(
            screening_enabled=True,
            litellm_model="gemini/gemini-2.5-flash",
            llm_channels=[
                {
                    "name": "gemini",
                    "protocol": "gemini",
                    "enabled": True,
                    "api_keys": ["dsa-gemini-key"],
                    "models": ["gemini/gemini-2.5-flash"],
                    "extra_headers": {"x-tenant": "dsa"},
                }
            ],
        )
        completion_calls: list[dict[str, object]] = []

        def completion_impl(**kwargs):
            completion_calls.append(kwargs)
            return SimpleNamespace(choices=[])

        fake_litellm = SimpleNamespace(completion=completion_impl)

        def screen_impl(_strategy: str, **_kwargs):
            fake_litellm.completion(
                model="gemini/gemini-2.5-flash",
                api_key="dsa-gemini-key",
                messages=[{"role": "user", "content": "rank"}],
            )
            return {"candidates": []}

        fake_module = _make_screening_core(screen=MagicMock(side_effect=screen_impl))

        with (
            patch.dict(sys.modules, {"litellm": fake_litellm}, clear=False),
            _patch_screening_core(fake_module),
        ):
            payload = self._screen(config, market="cn", strategy="dual_low", max_results=5)

        self.assertEqual(payload["candidate_count"], 0)
        self.assertEqual(completion_calls[0]["extra_headers"], {"x-tenant": "dsa"})
        self.assertIsNot(fake_litellm.completion, completion_impl)
        self.assertTrue(
            getattr(fake_litellm.completion, "_screening_litellm_completion_bridge", False),
        )

    def test_screen_bridges_legacy_openai_fields_into_screening_runtime_env(self) -> None:
        config = Config(
            screening_enabled=True,
            litellm_model="openai/gpt-4o-mini",
            openai_api_keys=["dsa-openai-key"],
            openai_base_url="https://openai-compatible.example/v1",
        )
        captured: dict[str, object] = {}

        def screen_impl(_strategy: str, **kwargs):
            captured["config"] = kwargs.get("config")
            captured["context"] = kwargs.get("context")
            return {"candidates": []}

        fake_module = _make_screening_core(screen=MagicMock(side_effect=screen_impl))

        with (
            patch.dict(
                screening_service.os.environ,
                {
                    "OPENAI_API_KEY": "outer-openai-key",
                    "OPENAI_BASE_URL": "https://outer-openai.example/v1",
                },
                clear=False,
            ),
            _patch_screening_core(fake_module),
        ):
            payload = self._screen(config, market="cn", strategy="dual_low", max_results=5)
            self.assertEqual(screening_service.os.environ.get("OPENAI_API_KEY"), "outer-openai-key")
            self.assertEqual(screening_service.os.environ.get("OPENAI_BASE_URL"), "https://outer-openai.example/v1")

        pipeline_config = captured["config"]
        self.assertIsInstance(pipeline_config, ScreeningPipelineConfig)
        self.assertEqual(pipeline_config.llm_api_key, "dsa-openai-key")
        self.assertEqual(pipeline_config.llm_base_url, "https://openai-compatible.example/v1")
        self.assertEqual(pipeline_config.llm_model, "openai/gpt-4o-mini")

        context = captured["context"]
        self.assertIsInstance(context, dict)
        self.assertEqual(context["llm"]["channels"], [])
        self.assertEqual(context["llm"]["model_list"], [])
        self.assertEqual(payload["candidate_count"], 0)

    def test_screen_injects_openai_compatible_model_headers_into_screening_litellm_calls(self) -> None:
        config = Config(
            screening_enabled=True,
            litellm_model="openai/gpt-4o-mini",
            litellm_fallback_models=["openai/gpt-4o-mini"],
            llm_model_list=[
                {
                    "model_name": "openai/gpt-4o-mini",
                    "litellm_params": {
                        "model": "openai/gpt-4o-mini",
                        "api_key": "dsa-openai-key",
                        "api_base": "https://openai-compatible.example/v1",
                        "extra_headers": {"x-tenant": "dsa"},
                    },
                },
            ],
        )
        completion_calls: list[dict[str, object]] = []

        def completion_impl(**kwargs):
            completion_calls.append(kwargs)
            return SimpleNamespace(choices=[])

        fake_litellm = SimpleNamespace(completion=completion_impl)

        def screen_impl(_strategy: str, **_kwargs):
            fake_litellm.completion(
                model="openai/gpt-4o-mini",
                api_key="dsa-openai-key",
                api_base="https://openai-compatible.example/v1",
                messages=[{"role": "user", "content": "rank"}],
            )
            return {"candidates": []}

        fake_module = _make_screening_core(screen=MagicMock(side_effect=screen_impl))

        with (
            patch.dict(sys.modules, {"litellm": fake_litellm}, clear=False),
            _patch_screening_core(fake_module),
        ):
            payload = self._screen(config, market="cn", strategy="dual_low", max_results=5)

        self.assertEqual(payload["candidate_count"], 0)
        self.assertEqual(completion_calls[0]["extra_headers"], {"x-tenant": "dsa"})
        self.assertEqual(
            completion_calls[0]["api_base"],
            "https://openai-compatible.example/v1",
        )
        self.assertIsNot(fake_litellm.completion, completion_impl)
        self.assertTrue(
            getattr(fake_litellm.completion, "_screening_litellm_completion_bridge", False),
        )

    def test_screen_bridges_openai_channel_base_url_and_headers(self) -> None:
        config = Config(
            screening_enabled=True,
            litellm_model="openai/gpt-4o-mini",
            litellm_fallback_models=["openai/gpt-4.1"],
            llm_channels=[
                {
                    "name": "openai",
                    "protocol": "openai",
                    "enabled": True,
                    "base_url": "https://primary-openai.example/v1",
                    "api_keys": ["dsa-openai-primary"],
                    "models": ["openai/gpt-4o-mini", "openai/gpt-4.1"],
                    "extra_headers": {"x-route": "primary", "x-tenant": "dsa"},
                }
            ],
        )
        completion_calls: list[Dict[str, object]] = []

        def completion_impl(**kwargs: Any) -> Any:
            completion_calls.append(kwargs)
            return SimpleNamespace(choices=[])

        fake_litellm = SimpleNamespace(completion=completion_impl)

        captured: dict[str, object] = {}

        def screen_impl(_strategy: str, **kwargs: Dict[str, Any]) -> dict[str, object]:
            captured["config"] = kwargs.get("config")
            captured["context"] = kwargs.get("context")
            fake_litellm.completion(
                model="openai/gpt-4o-mini",
                api_key="dsa-openai-primary",
                api_base="https://primary-openai.example/v1",
                messages=[{"role": "user", "content": "primary"}],
            )
            fake_litellm.completion(
                model="openai/gpt-4.1",
                api_key="dsa-openai-primary",
                api_base="https://primary-openai.example/v1",
                messages=[{"role": "user", "content": "fallback"}],
            )
            return {"candidates": []}

        fake_module = _make_screening_core(screen=MagicMock(side_effect=screen_impl))

        with (
            patch.dict(sys.modules, {"litellm": fake_litellm}, clear=False),
            _patch_screening_core(fake_module),
        ):
            payload = self._screen(config, market="cn", strategy="dual_low", max_results=5)

        self.assertEqual(payload["candidate_count"], 0)
        self.assertEqual(len(completion_calls), 2)
        pipeline_config = captured["config"]
        self.assertIsInstance(pipeline_config, ScreeningPipelineConfig)
        self.assertEqual(pipeline_config.llm_base_url, "https://primary-openai.example/v1")
        self.assertEqual(pipeline_config.llm_api_key, "dsa-openai-primary")
        self.assertEqual(pipeline_config.llm_channels[0]["name"], "openai")
        self.assertEqual(pipeline_config.llm_channels[0]["base_url"], "https://primary-openai.example/v1")
        self.assertEqual(pipeline_config.llm_channels[0]["api_keys"], ["dsa-openai-primary"])
        self.assertEqual(completion_calls[0]["extra_headers"], {"x-route": "primary", "x-tenant": "dsa"})
        self.assertEqual(completion_calls[1]["extra_headers"], {"x-route": "primary", "x-tenant": "dsa"})
        context = captured["context"]
        self.assertIsInstance(context, dict)
        self.assertEqual(context["llm"]["channels"][0]["base_url"], "https://primary-openai.example/v1")
        self.assertEqual(context["llm"]["channels"][0]["extra_headers"], {"x-route": "primary", "x-tenant": "dsa"})
        self.assertEqual(context["llm"]["model_list"][0]["litellm_params"]["api_base"], "https://primary-openai.example/v1")
        self.assertEqual(context["llm"]["fallback_models"], ["openai/gpt-4.1"])
        self.assertEqual(payload["candidate_count"], 0)

    def test_screen_injects_openai_compatible_fallback_headers_for_multiple_models(self) -> None:
        config = Config(
            screening_enabled=True,
            litellm_model="openai/gpt-4o-mini",
            litellm_fallback_models=["openai/gpt-4.1"],
            llm_model_list=[
                {
                    "model_name": "openai/gpt-4o-mini",
                    "litellm_params": {
                        "model": "openai/gpt-4o-mini",
                        "api_key": "dsa-openai-primary",
                        "api_base": "https://primary.openai.example/v1",
                        "extra_headers": {"x-route": "primary", "x-tenant": "dsa"},
                    },
                },
                {
                    "model_name": "openai/gpt-4.1",
                    "litellm_params": {
                        "model": "openai/gpt-4.1",
                        "api_key": "dsa-openai-fallback",
                        "api_base": "https://fallback.openai.example/v1",
                        "extra_headers": {"x-route": "fallback", "x-tenant": "dsa"},
                    },
                },
            ],
        )
        completion_calls: list[Dict[str, object]] = []

        def completion_impl(**kwargs: Any) -> Any:
            completion_calls.append(kwargs)
            return SimpleNamespace(choices=[])

        fake_litellm = SimpleNamespace(completion=completion_impl)

        def screen_impl(_strategy: str, **_kwargs) -> dict[str, object]:
            fake_litellm.completion(
                model="openai/gpt-4o-mini",
                api_key="dsa-openai-primary",
                api_base="https://primary.openai.example/v1",
                messages=[{"role": "user", "content": "rank-1"}],
            )
            fake_litellm.completion(
                model="openai/gpt-4.1",
                api_key="dsa-openai-fallback",
                api_base="https://fallback.openai.example/v1",
                messages=[{"role": "user", "content": "rank-2"}],
            )
            return {"candidates": []}

        fake_module = _make_screening_core(screen=MagicMock(side_effect=screen_impl))

        with (
            patch.dict(sys.modules, {"litellm": fake_litellm}, clear=False),
            _patch_screening_core(fake_module),
        ):
            payload = self._screen(config, market="cn", strategy="dual_low", max_results=5)

        self.assertEqual(payload["candidate_count"], 0)
        primary_call = next(
            call for call in completion_calls if call["model"] == "openai/gpt-4o-mini"
        )
        fallback_call = next(
            call for call in completion_calls if call["model"] == "openai/gpt-4.1"
        )
        self.assertEqual(primary_call["extra_headers"], {"x-route": "primary", "x-tenant": "dsa"})
        self.assertEqual(
            fallback_call["extra_headers"],
            {"x-route": "fallback", "x-tenant": "dsa"},
        )
        self.assertEqual(primary_call["api_base"], "https://primary.openai.example/v1")
        self.assertEqual(fallback_call["api_base"], "https://fallback.openai.example/v1")
        self.assertTrue(getattr(fake_litellm.completion, "_screening_litellm_completion_bridge", False))

    def test_screen_handles_concurrent_requests_without_litellm_header_cross_pollution(self) -> None:
        config_a = Config(
            screening_enabled=True,
            litellm_model="gemini/gemini-2.5-flash",
            llm_channels=[
                {
                    "name": "gemini",
                    "protocol": "gemini",
                    "enabled": True,
                    "api_keys": ["dsa-gemini-key-a"],
                    "models": ["gemini/gemini-2.5-flash"],
                    "extra_headers": {"x-tenant": "tenant-a"},
                }
            ],
        )
        config_b = Config(
            screening_enabled=True,
            litellm_model="gemini/gemini-2.5-flash",
            llm_channels=[
                {
                    "name": "gemini",
                    "protocol": "gemini",
                    "enabled": True,
                    "api_keys": ["dsa-gemini-key-b"],
                    "models": ["gemini/gemini-2.5-flash"],
                    "extra_headers": {"x-tenant": "tenant-b"},
                }
            ],
        )

        completion_calls: list[Dict[str, Any]] = []
        thread_b_ready = threading.Event()
        completion_lock = threading.Lock()

        def completion_impl(**kwargs: Any) -> Any:
            with completion_lock:
                completion_calls.append(kwargs)
            return SimpleNamespace(choices=[])

        fake_litellm = SimpleNamespace(completion=completion_impl)

        def screen_impl(_strategy: str, **kwargs: Any) -> Dict[str, Any]:
            context = kwargs.get("context") or {}
            llm = context.get("llm", {})
            channels = llm.get("channels") or []
            headers = (channels[0] if channels else {}).get("extra_headers", {})
            tenant = headers.get("x-tenant")
            if tenant == "tenant-a":
                thread_b_ready.wait(timeout=2)
            else:
                thread_b_ready.set()
            fake_litellm.completion(
                model="gemini/gemini-2.5-flash",
                api_key=(channels[0].get("api_keys") or [""])[0],
                messages=[{"role": "user", "content": "rank"}],
            )
            return {"candidates": []}

        fake_module = _make_screening_core(screen=MagicMock(side_effect=screen_impl))

        def _run_screen(config: Config) -> None:
            self._screen(config, market="cn", strategy="dual_low", max_results=5, mock_enrichment=False)

        with (
            patch.dict(sys.modules, {"litellm": fake_litellm}, clear=False),
            _patch_screening_core(fake_module),
        ):
            thread_a = threading.Thread(target=_run_screen, args=(config_a,))
            thread_b = threading.Thread(target=_run_screen, args=(config_b,))
            thread_a.start()
            thread_b.start()
            thread_a.join()
            thread_b.join()

        self.assertEqual(len(completion_calls), 2)
        self.assertCountEqual(
            [call.get("extra_headers", {}).get("x-tenant") for call in completion_calls],
            ["tenant-a", "tenant-b"],
        )
        self.assertTrue(
            thread_a.is_alive() is False and thread_b.is_alive() is False,
        )

    def test_screen_disabled_preserves_existing_llm_env_state(self) -> None:
        config = self._config(enabled=False)
        baseline_env = {
            "OPENAI_API_KEY": "legacy-openai-key",
            "OPENAI_BASE_URL": "https://outer.example.com/v1",
            "LITELLM_MODEL": "openai/gpt-4o-mini",
        }
        original_env = {key: screening_service.os.environ.get(key) for key in baseline_env}

        with (
            patch.dict(screening_service.os.environ, baseline_env, clear=False),
            patch("src.services.screening_service._build_screening_runtime_env") as runtime_env_mock,
            self.assertRaises(HTTPException) as caught,
        ):
            self._screen(config, market="cn", strategy="dual_low", max_results=5)
            for key, value in baseline_env.items():
                self.assertEqual(screening_service.os.environ.get(key), value)

        self.assertEqual(caught.exception.status_code, 403)
        self.assertEqual(caught.exception.detail["error"], "screening_disabled")
        runtime_env_mock.assert_not_called()
        for key, value in baseline_env.items():
            self.assertEqual(screening_service.os.environ.get(key), original_env[key])

    def test_screen_preserves_explicit_screening_snapshot_source_priority(self) -> None:
        config = self._config(enabled=True)
        captured: dict[str, object] = {}

        def screen_impl(_strategy: str, **_kwargs):
            captured["snapshot_priority"] = screening_service.os.environ.get("SNAPSHOT_SOURCE_PRIORITY")
            return {"candidates": []}

        fake_module = _make_screening_core(screen=MagicMock(side_effect=screen_impl))

        with (
            patch.dict(screening_service.os.environ, {"SNAPSHOT_SOURCE_PRIORITY": "tushare,em_datacenter"}, clear=False),
            _patch_screening_core(fake_module),
        ):
            payload = self._screen(config, market="cn", strategy="dual_low", max_results=5)

        self.assertEqual(captured["snapshot_priority"], "tushare,em_datacenter")
        self.assertEqual(payload["candidate_count"], 0)

    def test_screen_preserves_explicit_daily_source(self) -> None:
        config = self._config(enabled=True)
        captured: dict[str, object] = {}

        def screen_impl(_strategy: str, **_kwargs):
            captured["daily_source"] = screening_service.os.environ.get("DAILY_SOURCE")
            return {"candidates": []}

        fake_module = _make_screening_core(screen=MagicMock(side_effect=screen_impl))

        with (
            patch.dict(screening_service.os.environ, {"DAILY_SOURCE": "akshare"}, clear=False),
            _patch_screening_core(fake_module),
        ):
            payload = self._screen(config, market="cn", strategy="dual_low", max_results=5)

        self.assertEqual(captured["daily_source"], "akshare")
        self.assertEqual(payload["candidate_count"], 0)

    def test_dsa_daily_history_bridge_preserves_cache_kwargs_for_screening_fallback(self) -> None:
        import src.services.screening.daily as daily_module

        captured: dict[str, object] = {}
        expected = object()

        def fallback_fetch(code: str, **kwargs):
            captured["code"] = code
            captured.update(kwargs)
            return expected

        with (
            patch.object(daily_module, "fetch_daily_history", new=fallback_fetch),
            patch("src.services.screening_service.get_dsa_daily_history", side_effect=RuntimeError("dsa unavailable")),
        ):
            daily_fetcher = screening_service._build_screening_dsa_daily_history_fetcher()
            self.assertIsNotNone(daily_fetcher)
            result = daily_fetcher(
                "000001",
                lookback_days=90,
                source="auto",
                retries=4,
                cache_dir=Path("data/screening/daily_history"),
                cache_ttl_seconds=321.0,
            )

        self.assertIs(result, expected)
        self.assertEqual(captured["code"], "000001")
        self.assertEqual(captured["lookback_days"], 90)
        self.assertEqual(captured["source"], "auto")
        self.assertEqual(captured["retries"], 4)
        self.assertEqual(captured["cache_dir"], Path("data/screening/daily_history"))
        self.assertEqual(captured["cache_ttl_seconds"], 321.0)

    def test_dsa_daily_history_fetchers_are_request_local_when_calls_overlap(self) -> None:
        import src.services.screening.daily as daily_module

        builtin_fetch = daily_module.fetch_daily_history
        barrier = threading.Barrier(2)
        fallback_fetch = MagicMock(side_effect=lambda code, **_kwargs: f"fallback:{code}")

        def unavailable_dsa(code: str, *, lookback_days: int = 120):
            barrier.wait(timeout=5)
            raise RuntimeError(f"dsa unavailable for {code}:{lookback_days}")

        with (
            patch.object(daily_module, "fetch_daily_history", new=fallback_fetch),
            patch("src.services.screening_service.get_dsa_daily_history", side_effect=unavailable_dsa) as dsa_mock,
        ):
            first_fetcher = screening_service._build_screening_dsa_daily_history_fetcher()
            second_fetcher = screening_service._build_screening_dsa_daily_history_fetcher()
            self.assertIsNotNone(first_fetcher)
            self.assertIsNotNone(second_fetcher)

            with ThreadPoolExecutor(max_workers=2) as executor:
                first_future = executor.submit(first_fetcher, "000001", lookback_days=30)
                second_future = executor.submit(second_fetcher, "000002", lookback_days=30)

            self.assertEqual(first_future.result(), "fallback:000001")
            self.assertEqual(second_future.result(), "fallback:000002")
            self.assertIs(daily_module.fetch_daily_history, fallback_fetch)
            self.assertEqual(dsa_mock.call_count, 2)
            self.assertEqual(fallback_fetch.call_count, 2)

        self.assertIs(daily_module.fetch_daily_history, builtin_fetch)

    def test_fetch_daily_history_wraps_yfinance_with_daily_timeout(self) -> None:
        import src.services.screening.daily as daily_module

        wrapped_calls: list[dict[str, object]] = []

        def fake_wrapper(fetcher, source: str, *args, **kwargs):
            wrapped_calls.append(
                {
                    "fetcher": fetcher.__name__,
                    "source": source,
                    "args": args,
                    "kwargs": kwargs,
                }
            )
            return pd.DataFrame(
                [
                    {
                        "date": "2026-06-03",
                        "open": 10.0,
                        "high": 10.5,
                        "low": 9.8,
                        "close": 10.2,
                        "volume": 123400,
                    }
                ]
            )

        with patch.object(daily_module, "_call_daily_wrapper", side_effect=fake_wrapper):
            result = daily_module.fetch_daily_history(
                "aapl",
                lookback_days=20,
                source="yfinance",
                retries=0,
            )
            with self.assertRaises(ValueError):
                daily_module.fetch_daily_history("AAPL", source="tencent", retries=0)

        self.assertEqual(
            wrapped_calls,
            [
                {
                    "fetcher": "fetch_daily_history_yfinance",
                    "source": "yfinance",
                    "args": ("AAPL",),
                    "kwargs": {"lookback_days": 20},
                },
            ],
        )
        self.assertEqual(result.attrs["daily_source"], "yfinance")

    def test_dsa_daily_history_bridge_writes_last_good_cache_on_dsa_success(self) -> None:
        import src.services.screening.daily as daily_module

        cache_dir = Path("data/screening/daily_history")
        cache_path = cache_dir / "000001.auto.90.json"

        with (
            patch.object(
                daily_module,
                "fetch_daily_history",
                new=MagicMock(side_effect=AssertionError("Screening fallback should not run")),
            ),
            patch(
                "src.services.screening_service.get_dsa_daily_history",
                return_value=(
                    [
                        {
                            "trade_date": "20260603",
                            "close": "10.5",
                            "vol": "123400",
                        }
                    ],
                    "EfinanceFetcher",
                ),
            ),
            patch.object(daily_module, "_daily_history_cache_path", return_value=cache_path) as cache_path_mock,
            patch.object(daily_module, "_write_daily_history_cache") as cache_write_mock,
        ):
            daily_fetcher = screening_service._build_screening_dsa_daily_history_fetcher()
            self.assertIsNotNone(daily_fetcher)
            result = daily_fetcher(
                "000001",
                lookback_days=90,
                source="auto",
                retries=2,
                cache_dir=cache_dir,
                cache_ttl_seconds=321.0,
            )

        self.assertEqual(result.attrs["source"], "dsa:EfinanceFetcher")
        self.assertEqual(result.attrs["daily_source"], "dsa:EfinanceFetcher")
        self.assertEqual(result.attrs["daily_requested_source"], "auto")
        cache_path_mock.assert_called_once_with(
            cache_dir,
            code="000001",
            source="auto",
            lookback_days=90,
        )
        cache_write_mock.assert_called_once()
        self.assertEqual(cache_write_mock.call_args.args[0], cache_path)
        self.assertIs(cache_write_mock.call_args.args[1], result)
        self.assertEqual(cache_write_mock.call_args.kwargs["code"], "000001")
        self.assertEqual(cache_write_mock.call_args.kwargs["source"], "auto")
        self.assertEqual(cache_write_mock.call_args.kwargs["lookback_days"], 90)

    def test_screen_preserves_explicit_openai_base_url_without_openai_channel(self) -> None:
        config = Config(
            screening_enabled=True,
            litellm_model="deepseek/deepseek-chat",
            llm_channels=[
                {
                    "name": "deepseek",
                    "protocol": "deepseek",
                    "enabled": True,
                    "base_url": "https://api.deepseek.example/v1",
                    "api_keys": ["runtime-deepseek-key"],
                    "models": ["deepseek/deepseek-chat"],
                }
            ],
        )
        captured: dict[str, object] = {}

        def screen_impl(_strategy: str, **_kwargs):
            captured["openai_base_url"] = screening_service.os.environ.get("OPENAI_BASE_URL")
            captured["llm_openai_base_url"] = screening_service.os.environ.get("LLM_OPENAI_BASE_URL")
            captured["openai_api_key"] = screening_service.os.environ.get("OPENAI_API_KEY")
            return {"candidates": []}

        fake_module = _make_screening_core(screen=MagicMock(side_effect=screen_impl))

        with (
            patch.dict(
                screening_service.os.environ,
                {
                    "OPENAI_BASE_URL": "https://outer-openai.example/v1",
                    "LLM_OPENAI_BASE_URL": "https://outer-openai-channel.example/v1",
                    "OPENAI_API_KEY": "outer-openai-key",
                },
                clear=False,
            ),
            _patch_screening_core(fake_module),
        ):
            payload = self._screen(config, market="cn", strategy="dual_low", max_results=5)

        self.assertEqual(captured["openai_base_url"], "https://outer-openai.example/v1")
        self.assertEqual(captured["llm_openai_base_url"], "https://outer-openai-channel.example/v1")
        self.assertEqual(captured["openai_api_key"], "outer-openai-key")
        self.assertEqual(payload["candidate_count"], 0)

    def test_screening_runtime_snapshot_priority_is_yfinance_only(self) -> None:
        config = self._config(enabled=True)

        with patch.dict(screening_service.os.environ, {"SNAPSHOT_SOURCE_PRIORITY": ""}, clear=False):
            env = screening_service._build_screening_runtime_env(config)

        self.assertEqual(env["SNAPSHOT_SOURCE_PRIORITY"], "yfinance")

    def test_screening_runtime_env_preserves_responses_api_surface(self) -> None:
        config = Config(
            screening_enabled=True,
            litellm_model="openai/gpt-5.6-sol",
            llm_channels=[
                {
                    "name": "draft",
                    "protocol": "openai",
                    "api_surface": "responses",
                    "enabled": True,
                    "base_url": "https://api.example.com/v1",
                    "api_keys": ["sk-draft"],
                    "models": ["openai/gpt-5.6-sol"],
                }
            ],
        )

        env = screening_service._build_screening_runtime_env(config)

        self.assertEqual(env["LLM_DRAFT_API_SURFACE"], "responses")
        with patch.dict(os.environ, env, clear=True):
            runtime_config = ScreeningPipelineConfig.from_env()
        self.assertEqual(runtime_config.llm_channels[0]["api_surface"], "responses")

    def test_screening_runtime_env_skips_unknown_api_surface(self) -> None:
        with patch.dict(
            os.environ,
            {
                "LLM_CHANNELS": "draft",
                "LLM_DRAFT_PROTOCOL": "openai",
                "LLM_DRAFT_API_SURFACE": "respones",
                "LLM_DRAFT_API_KEY": "sk-draft",
                "LLM_DRAFT_MODELS": "gpt-5.6-sol",
            },
            clear=True,
        ):
            runtime_config = ScreeningPipelineConfig.from_env()

        self.assertEqual(runtime_config.llm_channels, [])

    def test_screening_runtime_env_uses_provider_protocol_before_validating_surface(self) -> None:
        with patch.dict(
            os.environ,
            {
                "LLM_CHANNELS": "gemini",
                "LLM_GEMINI_API_SURFACE": "responses",
                "LLM_GEMINI_API_KEY": "gemini-key",
                "LLM_GEMINI_MODELS": "gemini-2.5-flash",
            },
            clear=True,
        ):
            runtime_config = ScreeningPipelineConfig.from_env()

        self.assertEqual(runtime_config.llm_channels, [])

    def test_screening_runtime_env_skips_openai_responses_channel_with_non_openai_model(self) -> None:
        with patch.dict(
            os.environ,
            {
                "LLM_CHANNELS": "draft",
                "LLM_DRAFT_PROTOCOL": "openai",
                "LLM_DRAFT_API_SURFACE": "responses",
                "LLM_DRAFT_API_KEY": "sk-draft",
                "LLM_DRAFT_MODELS": "anthropic/claude-sonnet-4-6",
            },
            clear=True,
        ):
            runtime_config = ScreeningPipelineConfig.from_env()

        self.assertEqual(runtime_config.llm_channels, [])

    def test_screening_runtime_env_skips_openai_responses_channel_with_direct_provider_model(self) -> None:
        with patch.dict(
            os.environ,
            {
                "LLM_CHANNELS": "draft",
                "LLM_DRAFT_PROTOCOL": "openai",
                "LLM_DRAFT_API_SURFACE": "responses",
                "LLM_DRAFT_API_KEY": "sk-draft",
                "LLM_DRAFT_MODELS": "xai/grok-beta",
            },
            clear=True,
        ):
            runtime_config = ScreeningPipelineConfig.from_env()

        self.assertEqual(runtime_config.llm_channels, [])

    def test_screening_runtime_env_skips_duplicate_route_alias_with_mixed_surfaces(self) -> None:
        with patch.dict(
            os.environ,
            {
                "LLM_CHANNELS": "chat,responses",
                "LLM_CHAT_PROTOCOL": "openai",
                "LLM_CHAT_API_KEY": "sk-chat",
                "LLM_CHAT_MODELS": "gpt-5.6-sol",
                "LLM_RESPONSES_PROTOCOL": "openai",
                "LLM_RESPONSES_API_SURFACE": "responses",
                "LLM_RESPONSES_API_KEY": "sk-responses",
                "LLM_RESPONSES_MODELS": "gpt-5.6-sol",
            },
            clear=True,
        ):
            runtime_config = ScreeningPipelineConfig.from_env()

        self.assertEqual(runtime_config.llm_channels, [])

    def test_screening_runtime_env_keeps_generic_channel_openai_default(self) -> None:
        with patch.dict(
            os.environ,
            {
                "LLM_CHANNELS": "draft",
                "LLM_DRAFT_API_KEY": "sk-draft",
                "LLM_DRAFT_MODELS": "gpt-5.6-sol",
            },
            clear=True,
        ):
            runtime_config = ScreeningPipelineConfig.from_env()

        self.assertEqual(runtime_config.llm_channels[0]["protocol"], "openai")

    def test_screening_runtime_env_skips_unsupported_hermes_responses_surface(self) -> None:
        with patch.dict(
            os.environ,
            {
                "LLM_CHANNELS": "hermes",
                "LLM_HERMES_API_SURFACE": "responses",
                "LLM_HERMES_API_KEY": "sk-hermes",
                "LLM_HERMES_MODELS": "hermes-agent",
            },
            clear=True,
        ):
            runtime_config = ScreeningPipelineConfig.from_env()

        self.assertEqual(runtime_config.llm_channels, [])

    def test_screen_preserves_explicit_candidate_context_provider_override(self) -> None:
        config = self._config(enabled=True)
        captured: dict[str, object] = {}

        def screen_impl(_strategy: str, **_kwargs):
            captured["providers"] = screening_service.os.environ.get("LLM_CANDIDATE_CONTEXT_PROVIDERS")
            return {"candidates": []}

        fake_module = _make_screening_core(screen=MagicMock(side_effect=screen_impl))

        with (
            patch.dict(screening_service.os.environ, {"LLM_CANDIDATE_CONTEXT_PROVIDERS": "news,announcement"}, clear=False),
            _patch_screening_core(fake_module),
        ):
            payload = self._screen(config, market="cn", strategy="dual_low", max_results=5)

        self.assertEqual(captured["providers"], "news,announcement")
        self.assertEqual(payload["candidate_count"], 0)

    def test_screen_filters_undeclared_managed_fallbacks_for_dsa_routes(self) -> None:
        config = Config(
            screening_enabled=True,
            litellm_model="gemini/gemini-3-flash-preview",
            litellm_fallback_models=["gemini/gemini-2.5-flash"],
            llm_channels=[
                {
                    "name": "gemini",
                    "protocol": "gemini",
                    "enabled": True,
                    "base_url": "",
                    "api_keys": ["dsa-gemini-key"],
                    "models": ["gemini/gemini-3-flash-preview"],
                },
                {
                    "name": "deepseek",
                    "protocol": "deepseek",
                    "enabled": True,
                    "base_url": "https://api.deepseek.com",
                    "api_keys": ["dsa-deepseek-key"],
                    "models": ["deepseek/deepseek-chat"],
                },
            ],
            llm_model_list=[
                {
                    "model_name": "gemini/gemini-3-flash-preview",
                    "litellm_params": {
                        "model": "gemini/gemini-3-flash-preview",
                        "api_key": "dsa-gemini-key",
                    },
                },
                {
                    "model_name": "deepseek/deepseek-chat",
                    "litellm_params": {
                        "model": "deepseek/deepseek-chat",
                        "api_key": "dsa-deepseek-key",
                        "api_base": "https://api.deepseek.com",
                    },
                },
            ],
        )
        captured: dict[str, object] = {}

        def screen_impl(_strategy: str, **kwargs):
            captured["config"] = kwargs.get("config")
            captured["context"] = kwargs.get("context")
            return {"candidates": []}

        fake_module = _make_screening_core(screen=MagicMock(side_effect=screen_impl))

        with _patch_screening_core(fake_module):
            payload = self._screen(config, market="cn", strategy="dual_low", max_results=5)

        pipeline_config = captured["config"]
        self.assertIsInstance(pipeline_config, ScreeningPipelineConfig)
        self.assertEqual(pipeline_config.llm_model, "gemini/gemini-3-flash-preview")
        self.assertEqual(pipeline_config.llm_fallback_models, ["deepseek/deepseek-chat"])
        self.assertEqual(
            [channel["name"] for channel in pipeline_config.llm_channels],
            ["gemini", "deepseek"],
        )
        context = captured["context"]
        self.assertIsInstance(context, dict)
        self.assertEqual(context["llm"]["fallback_models"], ["deepseek/deepseek-chat"])
        self.assertEqual(payload["candidate_count"], 0)

    def test_screen_does_not_run_when_engine_is_unavailable(self) -> None:
        config = self._config(enabled=True)
        fake_module = _make_screening_core(screen=MagicMock(return_value={"candidates": []}))

        with (
            patch(
                "src.services.screening_service._get_screening_status_snapshot",
                return_value=({}, False, _screening_unavailable_diagnostics()),
            ),
            _patch_screening_core(fake_module),
        ):
            with self.assertRaises(HTTPException) as caught:
                self._screen(config, market="cn", strategy="dual_low", max_results=5)

        self.assertEqual(caught.exception.status_code, 424)
        self.assertEqual(caught.exception.detail.get("diagnostics", {}).get("reason"), "unexpected_exception")
        fake_module.screen.assert_not_called()

    def test_screen_normalizes_non_finite_values(self) -> None:
        config = self._config(enabled=True)
        fake_module = _make_screening_core(
            screen=MagicMock(
                return_value={
                    "picks": [
                        {
                            "code": "600519",
                            "name": "Kweichow Moutai",
                            "score": float("nan"),
                            "ranking_reason": "Screening pick",
                            "nested": {"pe": float("inf"), "pb": float("-inf"), "eps": 20.5},
                        },
                    ],
                }
            ),
        )

        with _patch_screening_core(fake_module):
            payload = self._screen(config, market="cn", strategy="dual_low", max_results=5)

        self.assertIsNone(payload["candidates"][0]["score"])
        self.assertIsNone(payload["candidates"][0]["raw"]["score"])
        self.assertIsNone(payload["candidates"][0]["raw"]["nested"]["pe"])
        self.assertIsNone(payload["candidates"][0]["raw"]["nested"]["pb"])

    def test_screen_allows_non_listed_strategy_as_custom(self) -> None:
        config = self._config(enabled=True)
        fake_module = _make_screening_core(
            list_strategies=lambda: [{"id": "dual_low", "name": "双低选股"}],
            screen=MagicMock(return_value={"candidates": []}),
        )

        with _patch_screening_core(fake_module):
            payload = self._screen(config, market="cn", strategy="custom_alpha", max_results=5)

        fake_module.screen.assert_called_once_with(
            "custom_alpha",
            market="cn",
            max_output=5,
            use_llm=True,
            context=ANY,
            selection_seed="",
            config=ANY,
            progress_callback=None,
            daily_history_fetcher=ANY,
        )
        self.assertEqual(payload["candidates"], [])
        self.assertEqual(payload["candidate_count"], 0)

    def test_screen_rejects_unsupported_market(self) -> None:
        config = self._config(enabled=True)
        fake_module = _make_screening_core(
            get_status=lambda: {"supported_markets": ["hk", "us"]},
            screen=MagicMock(return_value=[]),
        )

        with _patch_screening_core(fake_module):
            with self.assertRaises(HTTPException) as caught:
                self._screen(config, market="cn", strategy="dual_low", max_results=5)

        self.assertEqual(caught.exception.status_code, 422)
        self.assertEqual(caught.exception.detail["error"], "screening_invalid_market")

    def test_screen_maps_pipeline_value_error_to_bad_request(self) -> None:
        config = self._config(enabled=True)
        fake_module = _make_screening_core(
            screen=MagicMock(side_effect=ValueError("Only market='cn' is currently supported")),
        )

        with _patch_screening_core(fake_module):
            with self.assertRaises(HTTPException) as caught:
                self._screen(config, market="cn", strategy="dual_low", max_results=5)

        self.assertEqual(caught.exception.status_code, 400)
        self.assertEqual(caught.exception.detail["error"], "screening_screen_rejected")


if __name__ == "__main__":
    unittest.main()

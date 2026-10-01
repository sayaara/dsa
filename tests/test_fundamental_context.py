# -*- coding: utf-8 -*-
"""
Tests for structured fundamental context (P0).
"""

import os
import sys
import time
import unittest
from threading import BoundedSemaphore, Event
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from data_provider.base import DataFetcherManager


class _DummyFetcher:
    def __init__(self, name: str, priority: int, rankings=None):
        self.name = name
        self.priority = priority
        self._rankings = rankings

    def get_sector_rankings(self, _n: int = 5):
        return self._rankings


class _DummyBoardFetcher:
    def __init__(self, name: str, priority: int, boards=None):
        self.name = name
        self.priority = priority
        self._boards = boards or []

    def get_belong_board(self, _stock_code: str):
        return self._boards


class TestFundamentalContext(unittest.TestCase):
    def test_not_supported_builder_uses_existing_fundamental_schema(self) -> None:
        manager = DataFetcherManager(fetchers=[])

        context = manager.build_not_supported_fundamental_context(
            "sh000016", "index target: fundamental modules skipped"
        )

        self.assertEqual(context["status"], "not_supported")
        self.assertTrue(context["coverage"])
        self.assertTrue(
            all(status == "not_supported" for status in context["coverage"].values())
        )
        self.assertEqual(
            context["errors"], ["index target: fundamental modules skipped"]
        )

    def test_offshore_market_returns_not_supported_when_adapter_empty(self) -> None:
        """When yfinance adapter has no data, offshore (US/HK) status is not_supported.

        capital_flow / dragon_tiger / boards stay not_supported regardless of
        adapter outcome since yfinance has no equivalent feed for those blocks.
        """
        manager = DataFetcherManager(fetchers=[])
        cfg = SimpleNamespace(
            enable_fundamental_pipeline=True,
            fundamental_cache_ttl_seconds=0,
            fundamental_stage_timeout_seconds=1.5,
            fundamental_fetch_timeout_seconds=0.8,
            fundamental_retry_max=1,
        )
        empty_bundle = {
            "status": "not_supported",
            "growth": {},
            "earnings": {},
            "belong_boards": [],
            "source_chain": [],
            "errors": [],
        }
        with patch("src.config.get_config", return_value=cfg), \
                patch.object(manager, "get_realtime_quote", return_value=None), \
                patch(
                    "data_provider.yfinance_fundamental_adapter.YfinanceFundamentalAdapter.get_fundamental_bundle",
                    return_value=empty_bundle,
                ):
            ctx = manager.get_fundamental_context("AAPL")
        self.assertEqual(ctx["market"], "us")
        self.assertEqual(ctx["status"], "not_supported")
        self.assertEqual(ctx["coverage"].get("growth"), "not_supported")
        self.assertEqual(ctx["coverage"].get("earnings"), "not_supported")
        self.assertEqual(ctx["coverage"].get("capital_flow"), "not_supported")
        self.assertEqual(ctx["coverage"].get("dragon_tiger"), "not_supported")
        self.assertEqual(ctx["coverage"].get("boards"), "not_supported")
        self.assertEqual(ctx.get("belong_boards"), [])

    def test_offshore_market_populates_blocks_when_adapter_has_data(self) -> None:
        """US/HK fundamental context surfaces yfinance bundle into growth/earnings/belong_boards."""
        manager = DataFetcherManager(fetchers=[])
        cfg = SimpleNamespace(
            enable_fundamental_pipeline=True,
            fundamental_cache_ttl_seconds=0,
            fundamental_stage_timeout_seconds=2.0,
            fundamental_fetch_timeout_seconds=1.5,
            fundamental_retry_max=1,
        )
        quote = SimpleNamespace(
            pe_ratio=32.5,
            pb_ratio=58.2,
            total_mv=3.4e12,
            circ_mv=3.4e12,
            source=SimpleNamespace(value="longbridge"),
        )
        bundle = {
            "status": "partial",
            "growth": {
                "revenue_yoy": 16.5,
                "net_profit_yoy": 19.3,
                "roe": 141.4,
                "gross_margin": 47.8,
            },
            "earnings": {
                "financial_report": {
                    "report_date": "2026-03-31",
                    "revenue": 1.11e11,
                    "net_profit_parent": 2.95e10,
                    "operating_cash_flow": 2.87e10,
                    "roe": 141.4,
                    "currency": "USD",
                },
                "dividend": {
                    "events": [{
                        "event_date": "2026-05-11",
                        "ex_dividend_date": "2026-05-11",
                        "cash_dividend_per_share": 0.27,
                        "is_pre_tax": True,
                    }],
                    "ttm_event_count": 4,
                    "ttm_cash_dividend_per_share": 1.05,
                    "ttm_dividend_yield_pct": 0.36,
                },
            },
            "belong_boards": [
                {"name": "Technology", "type": "Sector"},
                {"name": "Consumer Electronics", "type": "Industry"},
            ],
            "source_chain": ["growth:yfinance.info"],
            "errors": [],
        }
        with patch("src.config.get_config", return_value=cfg), \
                patch.object(manager, "get_realtime_quote", return_value=quote), \
                patch(
                    "data_provider.yfinance_fundamental_adapter.YfinanceFundamentalAdapter.get_fundamental_bundle",
                    return_value=bundle,
                ):
            ctx = manager.get_fundamental_context("AAPL")
        self.assertEqual(ctx["market"], "us")
        # Offshore status considers valuation/growth/earnings plus any populated
        # capital_flow / boards blocks; "ok" when the populated blocks are ok.
        self.assertEqual(ctx["status"], "ok")
        self.assertEqual(ctx["coverage"].get("growth"), "ok")
        self.assertEqual(ctx["coverage"].get("earnings"), "ok")
        self.assertEqual(ctx["coverage"].get("capital_flow"), "not_supported")
        # belong_boards from the bundle surface the boards block (was hard-coded
        # not_supported before the Futu integration made it data-driven).
        self.assertEqual(ctx["coverage"].get("boards"), "ok")
        growth_data = ctx["growth"].get("data") or {}
        self.assertEqual(growth_data.get("revenue_yoy"), 16.5)
        self.assertEqual(growth_data.get("roe"), 141.4)
        financial_report = (ctx["earnings"].get("data") or {}).get("financial_report") or {}
        self.assertEqual(financial_report.get("currency"), "USD")
        self.assertEqual(financial_report.get("revenue"), 1.11e11)
        dividend = (ctx["earnings"].get("data") or {}).get("dividend") or {}
        self.assertEqual(dividend.get("ttm_cash_dividend_per_share"), 1.05)
        self.assertEqual(dividend.get("ttm_dividend_yield_pct"), 0.36)
        self.assertEqual(ctx.get("belong_boards"), [
            {"name": "Technology", "type": "Sector"},
            {"name": "Consumer Electronics", "type": "Industry"},
        ])


    def test_run_with_timeout_limits_hanging_workers(self) -> None:
        manager = DataFetcherManager(fetchers=[])
        manager._fundamental_timeout_slots = BoundedSemaphore(1)

        unblock = Event()

        def _hanging_task():
            unblock.wait(timeout=0.5)
            return 1

        try:
            result, err, _ = manager._run_with_timeout(_hanging_task, 0.01, "hang")
            self.assertIsNone(result)
            self.assertIn("timeout", err or "")

            result2, err2, _ = manager._run_with_timeout(_hanging_task, 0.01, "hang")
            self.assertIsNone(result2)
            self.assertIn("worker pool exhausted", err2 or "")
        finally:
            unblock.set()
            time.sleep(0.02)

    def test_infer_block_status_treats_all_null_payload_as_non_ok(self) -> None:
        self.assertEqual(
            DataFetcherManager._infer_block_status(
                {"revenue_yoy": None, "net_profit_yoy": None, "summary": ""},
                "partial",
            ),
            "partial",
        )
        self.assertEqual(
            DataFetcherManager._infer_block_status(
                {"revenue_yoy": None, "net_profit_yoy": None},
                "not_supported",
            ),
            "not_supported",
        )
        self.assertEqual(
            DataFetcherManager._infer_block_status(
                {"revenue_yoy": 0.0},
                "partial",
            ),
            "ok",
        )


    def test_fundamental_cache_key_isolated_by_budget_bucket(self) -> None:
        manager = DataFetcherManager(fetchers=[])
        key_default = manager._get_fundamental_cache_key("600519")
        key_low = manager._get_fundamental_cache_key("600519", 0.4)
        key_high = manager._get_fundamental_cache_key("600519", 1.5)

        self.assertNotEqual(key_default, key_low)
        self.assertNotEqual(key_low, key_high)
        self.assertIn("budget=", key_low)



    def test_missing_value_helpers_keep_common_null_compatibility(self) -> None:
        for value in (None, np.nan, "", "  ", "null", "NaN", " n/a "):
            self.assertTrue(DataFetcherManager._is_missing_board_value(value))
        self.assertFalse(DataFetcherManager._is_missing_board_value("白酒"))
        self.assertFalse(DataFetcherManager._has_meaningful_payload(np.array([None, np.nan])))
        self.assertTrue(DataFetcherManager._has_meaningful_payload(np.array([None, "白酒"])))

    def test_missing_value_helpers_log_expected_pd_isna_fallback(self) -> None:
        sentinel = object()
        with patch("data_provider.base.pd.isna", side_effect=ValueError("ambiguous")):
            with self.assertLogs("data_provider.base", level="DEBUG") as logs:
                self.assertFalse(DataFetcherManager._is_missing_board_value(sentinel))
                self.assertTrue(DataFetcherManager._has_meaningful_payload(sentinel))

        joined_logs = "\n".join(logs.output)
        self.assertIn("[board_value] pd.isna fallback", joined_logs)
        self.assertIn("[fundamental_payload] pd.isna fallback", joined_logs)

    def test_missing_value_helpers_propagate_array_protocol_pd_isna_errors(self) -> None:
        class _ArrayProtocolErrorPayload:
            def __array__(self):
                raise ValueError("boom")

        payload = _ArrayProtocolErrorPayload()
        with self.assertRaises(ValueError):
            DataFetcherManager._is_missing_board_value(payload)
        with self.assertRaises(ValueError):
            DataFetcherManager._has_meaningful_payload(payload)

    def test_missing_value_helpers_propagate_unexpected_pd_isna_errors(self) -> None:
        sentinel = object()
        with patch("data_provider.base.pd.isna", side_effect=RuntimeError("boom")):
            with self.assertRaises(RuntimeError):
                DataFetcherManager._is_missing_board_value(sentinel)
            with self.assertRaises(RuntimeError):
                DataFetcherManager._has_meaningful_payload(sentinel)


if __name__ == "__main__":
    unittest.main()

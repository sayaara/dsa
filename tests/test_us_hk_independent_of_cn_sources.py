# -*- coding: utf-8 -*-
"""US and HK routing must never touch the China-specific data sources."""

import sys
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

if "litellm" not in sys.modules:
    sys.modules["litellm"] = MagicMock()
if "json_repair" not in sys.modules:
    sys.modules["json_repair"] = MagicMock()

import pandas as pd

from data_provider.base import DataFetcherManager
from data_provider.market_codes import is_hk_stock_code, is_us_code

CN_SOURCES = (
    "EfinanceFetcher",
    "AkshareFetcher",
    "TushareFetcher",
    "TencentFetcher",
    "PytdxFetcher",
    "BaostockFetcher",
    "TickFlowFetcher",
)


class _Fetcher:
    def __init__(self, name: str, priority: int, frame=None):
        self.name = name
        self.priority = priority
        self.frame = frame
        self.calls = []

    def get_daily_data(self, *args, **kwargs):
        self.calls.append(("daily", args, kwargs))
        if self.frame is None:
            raise RuntimeError(f"{self.name} has no data")
        return self.frame

    def get_realtime_quote(self, *args, **kwargs):
        self.calls.append(("realtime", args, kwargs))
        return None

    def get_stock_name(self, *args, **kwargs):
        self.calls.append(("name", args, kwargs))
        return None


def _frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "date": pd.to_datetime(["2026-09-28", "2026-09-29"]),
            "open": [1.0, 2.0],
            "high": [1.0, 2.0],
            "low": [1.0, 2.0],
            "close": [1.0, 2.0],
            "volume": [100, 200],
            "amount": [100.0, 400.0],
            "pct_chg": [0.0, 100.0],
        }
    )


class TestMarketCodes(unittest.TestCase):
    def test_hk_codes(self):
        for code in ("0700.HK", "hk00700", "00700", "1810"):
            self.assertTrue(is_hk_stock_code(code), code)
        for code in ("600519", "AAPL", "", None):
            self.assertFalse(is_hk_stock_code(code), code)

    def test_us_codes(self):
        self.assertTrue(is_us_code("AAPL"))
        self.assertFalse(is_us_code("600519"))


class TestUsHkRoutingSkipsCnSources(unittest.TestCase):
    def _manager(self):
        cn = [_Fetcher(name, i) for i, name in enumerate(CN_SOURCES)]
        yfinance = _Fetcher("YfinanceFetcher", 4, frame=_frame())
        longbridge = _Fetcher("LongbridgeFetcher", 5)
        manager = DataFetcherManager(fetchers=cn + [yfinance, longbridge])
        return manager, cn, yfinance

    @patch("src.config.get_config")
    def test_hk_daily_uses_no_cn_source(self, mock_get_config):
        mock_get_config.return_value = SimpleNamespace(enable_realtime_quote=True)
        manager, cn, yfinance = self._manager()
        df, source = manager.get_daily_data("0700.HK", days=2)
        self.assertEqual(source, "YfinanceFetcher")
        self.assertFalse(df.empty)
        for fetcher in cn:
            self.assertEqual(fetcher.calls, [], fetcher.name)

    @patch("src.config.get_config")
    def test_us_daily_uses_no_cn_source(self, mock_get_config):
        mock_get_config.return_value = SimpleNamespace(enable_realtime_quote=True)
        manager, cn, yfinance = self._manager()
        df, source = manager.get_daily_data("AAPL", days=2)
        self.assertEqual(source, "YfinanceFetcher")
        for fetcher in cn:
            self.assertEqual(fetcher.calls, [], fetcher.name)

    @patch("src.config.get_config")
    def test_hk_realtime_default_priority_uses_no_cn_source(self, mock_get_config):
        mock_get_config.return_value = SimpleNamespace(
            enable_realtime_quote=True,
            futu_hk_realtime_source_priority="futu,longbridge,yfinance",
        )
        manager, cn, _ = self._manager()
        manager.get_realtime_quote("0700.HK")
        for fetcher in cn:
            self.assertEqual(fetcher.calls, [], fetcher.name)

    @patch("src.config.get_config")
    def test_hk_stock_name_uses_no_cn_source(self, mock_get_config):
        mock_get_config.return_value = SimpleNamespace(enable_realtime_quote=False)
        manager, cn, _ = self._manager()
        manager.get_stock_name("0700.HK", allow_realtime=False)
        for fetcher in cn:
            self.assertEqual(fetcher.calls, [], fetcher.name)


if __name__ == "__main__":
    unittest.main()

# -*- coding: utf-8 -*-
"""
Regression tests for Hong Kong realtime quote routing.
"""

import sys
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

if "litellm" not in sys.modules:
    sys.modules["litellm"] = MagicMock()
if "json_repair" not in sys.modules:
    sys.modules["json_repair"] = MagicMock()

from data_provider.base import DataFetcherManager


class _DummyFetcher:
    def __init__(self, name: str, priority: int, result=None):
        self.name = name
        self.priority = priority
        self.result = result
        self.calls = []

    def get_realtime_quote(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        return self.result


class TestHKRealtimeRouting(unittest.TestCase):
    """Ensure HK realtime lookup does not fan out into A-share sources."""


    @patch("src.config.get_config")
    def test_default_hk_priority_does_not_call_akshare(self, mock_get_config):
        mock_get_config.return_value = SimpleNamespace(
            enable_realtime_quote=True,
            realtime_source_priority="tencent,akshare_sina,efinance,akshare_em,tushare",
        )
        akshare = _DummyFetcher("AkshareFetcher", 1, result={"should": "not be called"})
        manager = DataFetcherManager(fetchers=[akshare])

        self.assertIsNone(manager.get_realtime_quote("1810.HK"))
        self.assertEqual(akshare.calls, [])

    @patch("data_provider.futu_fetcher.FutuFetcher.has_configured_endpoint", return_value=True)
    @patch("src.config.get_config")
    def test_manager_routes_hk_through_configured_futu_priority(self, mock_get_config, mock_has_ep):
        mock_get_config.return_value = SimpleNamespace(
            enable_realtime_quote=True,
            realtime_source_priority="tencent,akshare_sina,efinance,akshare_em,tushare",
            futu_hk_realtime_source_priority="futu,akshare,yfinance",
        )
        futu_quote = MagicMock()
        futu_quote.has_basic_data.return_value = True
        futu = _DummyFetcher("FutuFetcher", 0, result=futu_quote)
        akshare = _DummyFetcher("AkshareFetcher", 1, result=None)

        manager = DataFetcherManager(fetchers=[futu, akshare])
        quote = manager.get_realtime_quote("HK01810")

        self.assertIs(quote, futu_quote)
        self.assertEqual(len(futu.calls), 1)
        self.assertEqual(akshare.calls, [])




    @patch("data_provider.futu_fetcher.FutuFetcher.has_configured_endpoint", return_value=True)
    @patch("src.config.get_config")
    def test_manager_does_not_supplement_when_primary_is_complete(self, mock_get_config, mock_has_ep):
        """A complete first-source quote should not trigger extra source calls."""
        mock_get_config.return_value = SimpleNamespace(
            enable_realtime_quote=True,
            realtime_source_priority="tencent,akshare_sina,efinance,akshare_em,tushare",
            futu_hk_realtime_source_priority="futu,akshare,yfinance",
            realtime_cache_ttl=None,
        )
        futu_quote = MagicMock()
        futu_quote.has_basic_data.return_value = True
        for field in DataFetcherManager._SUPPLEMENT_FIELDS:
            setattr(futu_quote, field, 1.0)
        futu = _DummyFetcher("FutuFetcher", 0, result=futu_quote)
        akshare = _DummyFetcher("AkshareFetcher", 1, result=None)

        manager = DataFetcherManager(fetchers=[futu, akshare])
        quote = manager.get_realtime_quote("HK00700")

        self.assertIs(quote, futu_quote)
        self.assertEqual(len(futu.calls), 1)
        self.assertEqual(akshare.calls, [])

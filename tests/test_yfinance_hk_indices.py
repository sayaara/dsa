# -*- coding: utf-8 -*-
"""
Unit tests for the HK index fetch logic in data_provider/yfinance_fetcher

Uses unittest.mock to fake the yfinance API responses, covering:
- _get_hk_main_indices: bulk HK index fetching
- the correctness of the HK index Yahoo Finance symbol mapping
- partial and total failure degradation
"""
import sys
import os
import unittest
from unittest.mock import MagicMock, patch
import pandas as pd

# Mock the possibly missing dependencies before importing data_provider, so environment differences cannot break the tests
if 'fake_useragent' not in sys.modules:
    sys.modules['fake_useragent'] = MagicMock()

# Make sure the project modules are importable
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))


def _make_mock_hist(close: float, prev_close: float, high: float = None, low: float = None) -> pd.DataFrame:
    """Build a mock history DataFrame carrying the fields the percentage change needs"""
    high = high if high is not None else close + 100
    low = low if low is not None else close - 100
    return pd.DataFrame({
        'Close': [prev_close, close],
        'Open': [prev_close - 50, close - 30],
        'High': [prev_close + 100, high],
        'Low': [prev_close - 100, low],
        'Volume': [5000000000.0, 5200000000.0],
    }, index=pd.DatetimeIndex(['2025-02-16', '2025-02-17']))


def _make_mock_yf(hist_df: pd.DataFrame):
    """Build a mock yf module whose Ticker().history() returns the given DataFrame"""
    mock_ticker = MagicMock()
    mock_ticker.history.return_value = hist_df
    mock_yf = MagicMock()
    mock_yf.Ticker.return_value = mock_ticker
    return mock_yf


class TestHkIndexSymbolMapping(unittest.TestCase):
    """Check that the HK index Yahoo Finance symbol mapping is correct"""

    def setUp(self):
        from data_provider.yfinance_fetcher import YfinanceFetcher
        self.fetcher = YfinanceFetcher()

    def test_hk_indices_mapping_symbols(self):
        """The HK index mapping should use the correct Yahoo Finance symbols"""
        mock_yf = MagicMock()
        mock_ticker = MagicMock()
        mock_ticker.history.return_value = pd.DataFrame()
        mock_yf.Ticker.return_value = mock_ticker

        self.fetcher._get_hk_main_indices(mock_yf)

        # Collect the arguments of every Ticker() call
        ticker_calls = [call.args[0] for call in mock_yf.Ticker.call_args_list]

        self.assertIn('^HSI', ticker_calls, 'the Hang Seng Index should use ^HSI')
        self.assertIn('HSTECH.HK', ticker_calls, 'the Hang Seng TECH Index should use HSTECH.HK, not ^HSTECH')
        self.assertIn('^HSCE', ticker_calls, 'the Hang Seng China Enterprises Index should use ^HSCE, not ^HSCEI')

    def test_hk_index_names_are_english(self):
        """HK index display names reach English market reviews, so they must be English"""
        with patch.object(self.fetcher, '_fetch_yf_ticker_data', return_value=None) as fetch:
            self.fetcher._get_hk_main_indices(MagicMock())

        names = {call.args[3]: call.args[2] for call in fetch.call_args_list}
        self.assertEqual(names, {
            'HSI': 'Hang Seng Index',
            'HSTECH': 'Hang Seng TECH Index',
            'HSCEI': 'Hang Seng China Enterprises Index',
        })

    def test_hk_indices_mapping_no_invalid_symbols(self):
        """Make sure the known-bad legacy mapping symbols are gone for good"""
        mock_yf = MagicMock()
        mock_ticker = MagicMock()
        mock_ticker.history.return_value = pd.DataFrame()
        mock_yf.Ticker.return_value = mock_ticker

        self.fetcher._get_hk_main_indices(mock_yf)

        ticker_calls = [call.args[0] for call in mock_yf.Ticker.call_args_list]

        self.assertNotIn('^HSTECH', ticker_calls, '^HSTECH 不是有效的 Yahoo Finance 符号')
        self.assertNotIn('^HSCEI', ticker_calls, '^HSCEI 不是有效的 Yahoo Finance 符号')


class TestGetHkMainIndices(unittest.TestCase):
    """Tests for bulk HK index fetching in _get_hk_main_indices"""

    def setUp(self):
        from data_provider.yfinance_fetcher import YfinanceFetcher
        self.fetcher = YfinanceFetcher()

    def test_returns_list_when_all_succeed(self):
        """When every index fetch succeeds, a list of three indices is returned"""
        mock_hist = _make_mock_hist(close=20000.0, prev_close=19800.0)
        mock_yf = _make_mock_yf(mock_hist)

        result = self.fetcher._get_hk_main_indices(mock_yf)

        self.assertIsNotNone(result)
        self.assertIsInstance(result, list)
        self.assertEqual(len(result), 3)

        codes = {item['code'] for item in result}
        self.assertEqual(codes, {'HSI', 'HSTECH', 'HSCEI'})

        for item in result:
            self.assertIn('code', item)
            self.assertIn('name', item)
            self.assertIn('current', item)
            self.assertIn('change_pct', item)
            self.assertIn('prev_close', item)
            self.assertIn('amplitude', item)

    def test_returns_correct_computed_values(self):
        """Check the computed percentage change and amplitude"""
        mock_hist = _make_mock_hist(
            close=20000.0, prev_close=19800.0, high=20200.0, low=19700.0
        )
        mock_yf = _make_mock_yf(mock_hist)

        result = self.fetcher._get_hk_main_indices(mock_yf)

        self.assertIsNotNone(result)
        item = result[0]
        self.assertEqual(item['current'], 20000.0)
        self.assertEqual(item['prev_close'], 19800.0)
        self.assertAlmostEqual(item['change'], 200.0)
        expected_pct = (200.0 / 19800.0) * 100
        self.assertAlmostEqual(item['change_pct'], expected_pct)
        expected_amplitude = ((20200.0 - 19700.0) / 19800.0) * 100
        self.assertAlmostEqual(item['amplitude'], expected_amplitude)

    def test_handles_partial_failure(self):
        """When some indices have an empty history, the ones with data are still returned"""
        call_count = [0]

        def history_side_effect(period):
            call_count[0] += 1
            if call_count[0] == 1:
                return _make_mock_hist(close=20000.0, prev_close=19800.0)
            return pd.DataFrame()

        mock_ticker = MagicMock()
        mock_ticker.history.side_effect = history_side_effect
        mock_yf = MagicMock()
        mock_yf.Ticker.return_value = mock_ticker

        result = self.fetcher._get_hk_main_indices(mock_yf)

        self.assertIsNotNone(result)
        self.assertIsInstance(result, list)
        self.assertEqual(len(result), 1)

    def test_returns_none_when_all_fail(self):
        """When every fetch fails, None is returned"""
        mock_yf = _make_mock_yf(pd.DataFrame())

        result = self.fetcher._get_hk_main_indices(mock_yf)

        self.assertIsNone(result)

    def test_handles_ticker_exception(self):
        """A Ticker.history exception skips that index rather than failing the whole call"""
        mock_ticker = MagicMock()
        mock_ticker.history.side_effect = Exception("Network error")
        mock_yf = MagicMock()
        mock_yf.Ticker.return_value = mock_ticker

        result = self.fetcher._get_hk_main_indices(mock_yf)

        self.assertIsNone(result)

    def test_return_codes_match_expected_keys(self):
        """The returned code field should be HSI/HSTECH/HSCEI, matching the MarketAnalyzer prompt"""
        mock_hist = _make_mock_hist(close=20000.0, prev_close=19800.0)
        mock_yf = _make_mock_yf(mock_hist)

        result = self.fetcher._get_hk_main_indices(mock_yf)

        self.assertIsNotNone(result)
        codes = [item['code'] for item in result]
        self.assertIn('HSI', codes)
        self.assertIn('HSTECH', codes)
        self.assertIn('HSCEI', codes)


class TestGetMainIndicesDispatch(unittest.TestCase):
    """Tests for get_main_indices region dispatch"""

    def setUp(self):
        from data_provider.yfinance_fetcher import YfinanceFetcher
        self.fetcher = YfinanceFetcher()

    def test_region_hk_dispatches_to_hk_method(self):
        """region='hk' should delegate to _get_hk_main_indices"""
        mock_yf = MagicMock()
        with patch.dict('sys.modules', {'yfinance': mock_yf}):
            with patch.object(self.fetcher, '_get_hk_main_indices', return_value=[{'code': 'HSI'}]) as mock_hk:
                result = self.fetcher.get_main_indices(region='hk')

                mock_hk.assert_called_once()
                self.assertEqual(result, [{'code': 'HSI'}])


if __name__ == '__main__':
    unittest.main()

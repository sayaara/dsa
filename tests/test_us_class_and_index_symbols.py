# -*- coding: utf-8 -*-
"""US share classes (BRK.B / BRK-B) and index symbols (^GSPC, SPX) are handled consistently.

Live check (2026-10-09, yfinance): ``BRK.B`` and ``BF.B`` return no data from Yahoo Finance while
``BRK-B`` and ``BF-B`` do, so the Yahoo fetcher must send the dash form.
"""

import pytest

from data_provider import is_us_stock_code
from data_provider.yfinance_fetcher import YfinanceFetcher
from src.core.trading_calendar import get_market_for_stock
from src.market_context import detect_market
from src.report_units import currency_for_stock
from src.search_service import SearchService


@pytest.mark.parametrize("code", ["BRK.B", "BRK-B", "brk.b", "BF.B", "BF-B", "AAPL"])
def test_us_share_classes_are_us_stocks_in_every_form(code):
    assert is_us_stock_code(code.upper())
    assert detect_market(code) == "us"
    assert get_market_for_stock(code) == "us"
    assert currency_for_stock(code) == "USD"
    assert SearchService._is_foreign_stock(code)


@pytest.mark.parametrize("code", ["^GSPC", "^DJI", "SPX"])
def test_us_index_symbols_are_us_market(code):
    assert not is_us_stock_code(code)
    assert detect_market(code) == "us"
    assert get_market_for_stock(code) == "us"
    assert currency_for_stock(code) == "USD"
    assert SearchService._is_foreign_stock(code)


@pytest.mark.parametrize(
    "code, yahoo",
    [
        ("BRK.B", "BRK-B"),
        ("brk.b", "BRK-B"),
        ("BRK-B", "BRK-B"),
        ("BF.B", "BF-B"),
        ("AAPL", "AAPL"),
        ("SPX", "^GSPC"),
        ("^GSPC", "^GSPC"),
        ("RY.TO", "RY.TO"),
        ("TECK-B.TO", "TECK-B.TO"),
    ],
)
def test_yahoo_symbol_uses_the_dash_share_class(code, yahoo):
    fetcher = YfinanceFetcher.__new__(YfinanceFetcher)
    assert fetcher._convert_stock_code(code) == yahoo


@pytest.mark.parametrize("code", ["TECK-B.TO", "RY.TO", "VOD.L", "600519"])
def test_non_us_symbols_are_not_us_stocks(code):
    assert not is_us_stock_code(code)

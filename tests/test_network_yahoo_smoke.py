# -*- coding: utf-8 -*-
"""Live Yahoo Finance smoke tests for the supported markets (US and Canada).

Marked ``network``: excluded from the offline suite and run by the scheduled
``network-smoke`` workflow, which needs no API key for these. A failure here means
Yahoo Finance is unreachable or changed its response shape for a supported market.
"""

import pytest

from data_provider.yfinance_fetcher import YfinanceFetcher

pytestmark = pytest.mark.network


@pytest.fixture(scope="module")
def fetcher() -> YfinanceFetcher:
    return YfinanceFetcher()


@pytest.mark.parametrize("code", ["AAPL", "RY.TO"])
def test_daily_bars_are_returned_for_each_market(fetcher: YfinanceFetcher, code: str) -> None:
    df = fetcher.get_daily_data(code, days=10)

    assert not df.empty, code
    for column in ("date", "open", "high", "low", "close", "volume"):
        assert column in df.columns, (code, column)
    assert (df["close"] > 0).all(), code


@pytest.mark.parametrize(("code", "market"), [("MSFT", "us"), ("RY.TO", "ca")])
def test_realtime_quote_carries_price_and_market(fetcher: YfinanceFetcher, code: str, market: str) -> None:
    quote = fetcher.get_realtime_quote(code)

    assert quote is not None, code
    assert quote.price and quote.price > 0, code
    assert quote.market == market


@pytest.mark.parametrize("region", ["us", "ca"])
def test_main_indices_are_available_for_market_review(fetcher: YfinanceFetcher, region: str) -> None:
    indices = fetcher.get_main_indices(region=region)

    assert indices, region
    assert all(item.get("current") for item in indices), region

# -*- coding: utf-8 -*-
"""Hong Kong is not currently supported.

New Hong Kong input is refused with a clear reason, data sources are never asked
for Hong Kong codes (so ``HK00700`` is not fetched as a US ticker), and portfolio
rows stored while Hong Kong was supported still replay.
"""

from unittest.mock import MagicMock

import pytest

from data_provider.base import DataFetchError, DataFetcherManager
from src.core.market_registry import MARKET_CODE_SET, get_market
from src.services.portfolio_service import PortfolioService
from src.services.stock_list_parser import ParseStatus, parse_analysis_target

HK_INPUTS = ("0700.HK", "00700.HK", "hk00700", "HK00700", "HK.00700", "00700", "0941", "０７００.HK")


def test_hk_is_not_a_registered_market() -> None:
    assert "hk" not in MARKET_CODE_SET
    assert get_market("hk") is None


@pytest.mark.parametrize("raw", HK_INPUTS)
def test_parser_rejects_hong_kong_codes(raw: str) -> None:
    target = parse_analysis_target(raw)
    assert target.asset_type == ParseStatus.UNSUPPORTED
    assert target.exchange == "HK"
    assert "Hong Kong" in (target.unsupported_reason or "")


@pytest.mark.parametrize("raw", ("AAPL", "BRK.B", "RY.TO", "HOOD", "HKD"))
def test_parser_still_accepts_us_and_canada(raw: str) -> None:
    assert parse_analysis_target(raw).asset_type == ParseStatus.STOCK


def _manager_with(fetcher: MagicMock) -> DataFetcherManager:
    manager = DataFetcherManager.__new__(DataFetcherManager)
    DataFetcherManager.__init__(manager, fetchers=[fetcher])
    return manager


def test_daily_data_refuses_hong_kong_codes_without_asking_any_source() -> None:
    fetcher = MagicMock()
    fetcher.name = "YfinanceFetcher"
    fetcher.priority = 4
    manager = _manager_with(fetcher)

    with pytest.raises(DataFetchError, match="Hong Kong"):
        manager.get_daily_data("HK00700", days=30)
    fetcher.get_daily_data.assert_not_called()


def test_realtime_quote_returns_none_for_hong_kong_codes(monkeypatch) -> None:
    fetcher = MagicMock()
    fetcher.name = "YfinanceFetcher"
    fetcher.priority = 4
    manager = _manager_with(fetcher)
    config = MagicMock(enable_realtime_quote=True)
    monkeypatch.setattr("src.config.get_config", lambda: config)

    assert manager.get_realtime_quote("00700.HK") is None
    fetcher.get_realtime_quote.assert_not_called()


def test_new_portfolio_writes_reject_hk_but_stored_rows_replay() -> None:
    with pytest.raises(ValueError, match="market must be one of: ca, us"):
        PortfolioService._normalize_market("hk")
    assert PortfolioService._normalize_stored_market(" HK ") == "hk"

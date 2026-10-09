# -*- coding: utf-8 -*-
"""Canada (TSX / TSXV / CSE / NEO) support across classification, routing and prompts."""

import json
from datetime import date
from pathlib import Path

import pytest

from api.v1.endpoints.stocks import _STOCK_CODE_RE
from data_provider.base import DataFetcherManager, _market_tag, normalize_stock_code
from data_provider.us_index_mapping import is_us_stock_code
from src.core import trading_calendar
from src.market_context import detect_market, get_market_guidelines, get_market_role
from src.notification import NotificationService
from src.services.portfolio_service import PortfolioService
from src.services.stock_code_utils import is_code_like, normalize_code
from src.services.stock_index_remote_service import validate_stock_index_payload
from src.services.stock_list_parser import ParseStatus, parse_analysis_target

CANADIAN = ["RY.TO", "SHOP.TO", "ABX.V", "XYZ.CN", "BAM-A.TO", "REI-UN.TO"]


@pytest.mark.parametrize("code", CANADIAN)
def test_canadian_symbols_are_not_us_stocks(code: str) -> None:
    assert is_us_stock_code(code) is False
    assert _market_tag(code) == "ca"
    assert trading_calendar.get_market_for_stock(code) == "ca"
    assert detect_market(code) == "ca"


def test_us_dotted_share_classes_stay_us() -> None:
    for code in ("BRK.B", "BF.B", "AAPL"):
        assert is_us_stock_code(code) is True
        assert _market_tag(code) == "us"


@pytest.mark.parametrize("code", CANADIAN)
def test_parser_accepts_canadian_symbols_as_stocks(code: str) -> None:
    target = parse_analysis_target(code.lower())
    assert target.asset_type == ParseStatus.STOCK
    assert target.canonical_id == code
    assert target.exchange == code.rsplit(".", 1)[1]
    assert target.unsupported_reason is None


def test_parser_rejects_registered_suffix_with_invalid_base() -> None:
    target = parse_analysis_target("TOOLONGNAME.TO")
    assert target.asset_type == ParseStatus.UNSUPPORTED
    assert "invalid symbol" in (target.unsupported_reason or "")


def test_parser_still_rejects_removed_asian_suffixes() -> None:
    for code in ("7203.T", "005930.KS", "2330.TW"):
        assert parse_analysis_target(code).asset_type == ParseStatus.UNSUPPORTED


@pytest.mark.parametrize("code", CANADIAN)
def test_code_helpers_recognize_canadian_symbols(code: str) -> None:
    assert is_code_like(code) is True
    assert normalize_code(code.lower()) == code
    assert normalize_stock_code(code.lower()) == code
    assert _STOCK_CODE_RE.match(code)


def test_api_validator_rejects_malformed_canadian_symbols() -> None:
    for code in ("TOOLONGNAME.TO", "RY.TX", "RY."):
        assert not _STOCK_CODE_RE.match(code)


def test_trading_calendar_knows_the_tsx() -> None:
    assert trading_calendar.MARKET_EXCHANGE["ca"] == "XTSE"
    assert trading_calendar.MARKET_TIMEZONE["ca"] == "America/Toronto"
    # Canada Day (2026-07-01) is a TSX holiday, the neighbouring Wednesday is a session.
    assert trading_calendar.is_market_open("ca", date(2026, 7, 1)) is False
    assert trading_calendar.is_market_open("ca", date(2026, 7, 2)) is True


def test_daily_routing_includes_yahoo_for_canada() -> None:
    assert "ca" in DataFetcherManager._DAILY_MARKET_FETCHER_SUPPORT["YfinanceFetcher"]
    assert "ca" not in DataFetcherManager._DAILY_MARKET_FETCHER_SUPPORT["FinnhubFetcher"]


def test_market_prompt_context_is_canadian_not_us_or_a_share() -> None:
    assert get_market_role("RY.TO", "en") == "Canadian stock"
    assert get_market_role("RY.TO", "zh") == "加拿大股票"
    guidelines = get_market_guidelines("SHOP.TO", "en")
    assert "Canadian stock" in guidelines and "CAD" in guidelines
    assert "A-share" not in guidelines
    assert get_market_role("AAPL", "en") == "US stock"


def test_cad_amounts_use_the_canadian_dollar_suffix() -> None:
    assert NotificationService._format_per_share(1.5, "CAD").endswith("加元")
    assert NotificationService._format_amount_cn(2e8, "CAD").endswith("加元")


def test_portfolio_accepts_canada_with_cad_default_currency() -> None:
    assert PortfolioService._normalize_market("CA") == "ca"
    assert PortfolioService._default_currency_for_market("ca") == "CAD"


def test_bundled_stock_index_has_valid_canadian_rows() -> None:
    path = Path(__file__).resolve().parents[1] / "apps" / "dsa-web" / "public" / "stocks.index.json"
    rows = json.loads(path.read_text(encoding="utf-8"))
    validate_stock_index_payload(rows)
    canadian = [row for row in rows if row[6] == "CA"]
    # The curated rows plus the S&P/TSX Composite constituents (scripts/generate_ca_stock_index.py).
    assert len(canadian) >= 200
    codes = {row[0] for row in canadian}
    assert {"RY.TO", "SHOP.TO", "TECK-B.TO", "CAR-UN.TO"} <= codes
    assert {"AC.TO", "AP-UN.TO", "ACO-X.TO", "BBD-B.TO", "CCL-B.TO", "X.TO"} <= codes
    assert not {"BLX.TO", "IIP-UN.TO", "OLA.TO", "SES.TO"} & codes  # no longer traded
    assert len(codes) == len(canadian)
    assert all(code.endswith(".TO") or code.split(".")[-1] in {"V", "CN", "NE"} for code in codes)
    from src.services.market_symbol_utils import get_suffix_market

    assert all(get_suffix_market(code) == "ca" for code in codes)


def test_api_schemas_accept_the_ca_market() -> None:
    from typing import get_args

    from api.v1.schemas.decision_signals import DecisionSignalMarket
    from api.v1.schemas.intelligence import MarketValue
    from api.v1.schemas.portfolio import PortfolioAccountCreateRequest

    assert "ca" in get_args(DecisionSignalMarket)
    assert "ca" in get_args(MarketValue)
    assert PortfolioAccountCreateRequest(name="TFSA", market="ca").market == "ca"

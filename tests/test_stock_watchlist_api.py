# -*- coding: utf-8 -*-
"""Watchlist API regressions for stock-code variant matching."""

import pytest
from fastapi import HTTPException

from api.v1.endpoints.stocks import add_to_watchlist, get_watchlist, remove_from_watchlist
from api.v1.schemas.history import WatchlistRequest


class FakeSystemConfigService:
    def __init__(self, stock_list: str) -> None:
        self.stock_list = stock_list
        self.config_version = "cfg-v1"
        self.update_calls: list[str] = []

    def get_config(self, include_schema: bool = False) -> dict:
        return {
            "config_version": self.config_version,
            "items": [{"key": "STOCK_LIST", "value": self.stock_list}],
        }

    def update(self, **kwargs) -> None:
        items = kwargs["items"]
        self.stock_list = items[0]["value"]
        self.update_calls.append(self.stock_list)


@pytest.mark.parametrize(
    ("code", "reason"),
    [
        ("600519", "mainland China"),
        ("HK00700", "Hong Kong"),
        ("0700.HK", "Hong Kong"),
        ("00700", "Hong Kong"),
        ("VOD.L", "exchange suffix 'L'"),
    ],
)
def test_watchlist_add_rejects_unsupported_market_codes(code: str, reason: str) -> None:
    service = FakeSystemConfigService("AAPL")

    with pytest.raises(HTTPException) as exc_info:
        add_to_watchlist(WatchlistRequest(stock_code=code), service=service)

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail["error"] == "unsupported_stock_code"
    assert reason in exc_info.value.detail["message"]
    assert service.update_calls == []


@pytest.mark.parametrize("code", ["AAPL", "BRK.B", "RY.TO", "TECK-B.TO"])
def test_watchlist_add_accepts_us_and_canadian_codes(code: str) -> None:
    service = FakeSystemConfigService("")

    response = add_to_watchlist(WatchlistRequest(stock_code=code), service=service)

    assert response.stock_codes == [code]
    assert service.update_calls == [code]


def test_watchlist_remove_deletes_raw_hk_code_from_prefixed_variant_request() -> None:
    service = FakeSystemConfigService("00700")

    response = remove_from_watchlist(
        WatchlistRequest(stock_code="HK00700"),
        service=service,
    )

    assert response.stock_codes == []
    assert service.stock_list == ""
    assert service.update_calls == [""]


def test_watchlist_matching_is_case_insensitive_for_us_tickers() -> None:
    service = FakeSystemConfigService("aapl")

    add_response = add_to_watchlist(
        WatchlistRequest(stock_code="AAPL"),
        service=service,
    )
    remove_response = remove_from_watchlist(
        WatchlistRequest(stock_code="AAPL"),
        service=service,
    )

    assert add_response.stock_codes == ["aapl"]
    assert remove_response.stock_codes == []
    assert service.update_calls == [""]


def test_watchlist_reads_common_copy_paste_separators() -> None:
    service = FakeSystemConfigService("600519，300750  AAPL")

    response = get_watchlist(service=service)

    assert response.stock_codes == ["600519", "300750", "AAPL"]


def test_watchlist_add_normalizes_existing_mixed_separators_on_write() -> None:
    service = FakeSystemConfigService("600519，300750")

    response = add_to_watchlist(
        WatchlistRequest(stock_code="AAPL"),
        service=service,
    )

    assert response.stock_codes == ["600519", "300750", "AAPL"]
    assert service.stock_list == "600519,300750,AAPL"
    assert service.update_calls == ["600519,300750,AAPL"]

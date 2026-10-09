# -*- coding: utf-8 -*-
"""The generic English broker CSV format: columns, sides, currencies and encodings."""

from unittest.mock import MagicMock

import pytest

from src.services.portfolio_import_service import PortfolioImportService


@pytest.fixture
def service():
    return PortfolioImportService(portfolio_service=MagicMock(), repo=MagicMock())


@pytest.mark.parametrize(
    "label, expected",
    [
        ("usd", "USD"),
        ("CAD", "CAD"),
        (" cad ", "CAD"),
        ("", None),
        ("   ", None),
        (None, None),
        ("US Dollar", None),
        ("人民币", None),
    ],
)
def test_currency_label_normalization(label, expected):
    assert PortfolioImportService._normalize_currency_label(label) == expected


def test_generic_csv_parses_required_and_optional_columns(service):
    csv_text = (
        "Date,Symbol,Side,Quantity,Price,Commission,Fees,Tax,Currency,Trade ID\n"
        "2026-01-02,aapl,Buy,10,190.5,1,0.5,0,USD,T-1\n"
        "2026-01-03,RY.TO,SELL,5,\"1,120\",2,,,cad,T-2\n"
        "2026-01-04,TECK-B.TO,bought,3,50,,,,,\n"
    )
    parsed = service.parse_trade_csv(broker="generic", content=csv_text.encode("utf-8"))

    assert parsed["broker"] == "generic"
    assert parsed["skipped_count"] == 0
    records = parsed["records"]
    assert [(r["symbol"], r["side"], r["quantity"], r["price"]) for r in records] == [
        ("AAPL", "buy", 10.0, 190.5),
        ("RY.TO", "sell", 5.0, 1120.0),
        ("TECK-B.TO", "buy", 3.0, 50.0),
    ]
    assert [r["fee"] for r in records] == [1.5, 2.0, 0.0]
    assert [r["currency"] for r in records] == ["USD", "CAD", None]
    assert [r["trade_uid"] for r in records] == ["T-1", "T-2", None]


def test_generic_csv_header_aliases_are_case_insensitive(service):
    csv_text = "TRADE DATE,Ticker,Action,Qty,Trade Price\n2026-01-02,MSFT,Sold,2,400\n"
    parsed = service.parse_trade_csv(broker="csv", content=csv_text.encode("utf-8"))

    assert parsed["broker"] == "generic"
    assert [(r["symbol"], r["side"]) for r in parsed["records"]] == [("MSFT", "sell")]


def test_generic_csv_skips_rows_with_unknown_side_or_missing_values(service):
    csv_text = (
        "Date,Symbol,Side,Quantity,Price\n"
        "2026-01-02,AAPL,Dividend,10,1\n"
        "2026-01-02,AAPL,Buy,0,190\n"
        "not a date,AAPL,Buy,1,190\n"
        "2026-01-02,AAPL,Buy,1,190\n"
    )
    parsed = service.parse_trade_csv(broker="generic", content=csv_text.encode("utf-8"))

    assert parsed["record_count"] == 1
    assert parsed["skipped_count"] == 3


def test_generic_csv_reads_windows_1252_exports(service):
    csv_text = "Date,Symbol,Side,Quantity,Price,Note\n2026-01-02,AAPL,Buy,1,190,caf\xe9\n"
    parsed = service.parse_trade_csv(broker="generic", content=csv_text.encode("cp1252"))

    assert parsed["record_count"] == 1


def test_mainland_broker_formats_are_not_registered(service):
    assert [item["broker"] for item in service.list_supported_brokers()] == ["generic"]
    for broker in ("huatai", "citic", "cmb", "zhongxin", "zhaoshang"):
        with pytest.raises(ValueError, match="broker must be one of: generic"):
            service.parse_trade_csv(broker=broker, content=b"Date,Symbol\n")

# -*- coding: utf-8 -*-
"""Broker CSV import maps currency labels to ISO codes."""

from unittest.mock import MagicMock

import pytest

from src.services.portfolio_import_service import PortfolioImportService


@pytest.fixture
def service():
    return PortfolioImportService(portfolio_service=MagicMock(), repo=MagicMock())


@pytest.mark.parametrize(
    "label, expected",
    [
        ("人民币", "CNY"),
        ("RMB", "CNY"),
        ("rmb", "CNY"),
        ("港币", "HKD"),
        ("港元", "HKD"),
        ("美元", "USD"),
        ("加元", "CAD"),
        ("usd", "USD"),
        ("CAD", "CAD"),
        ("", None),
        ("   ", None),
        (None, None),
        ("未知币种", None),
        ("US Dollar", None),
    ],
)
def test_currency_label_normalization(label, expected):
    assert PortfolioImportService._normalize_currency_label(label) == expected


def test_csv_currency_column_is_normalized(service):
    csv_text = (
        "成交日期,证券代码,买卖标志,成交数量,成交均价,成交编号,币种\n"
        "2026-01-02,00700,买入,100,300,T-1,港币\n"
        "2026-01-03,AAPL,买入,10,190,T-2,美元\n"
        "2026-01-04,SHOP.TO,买入,5,120,T-3,\n"
    )
    parsed = service.parse_trade_csv(broker="huatai", content=csv_text.encode("utf-8"))

    assert [r["currency"] for r in parsed["records"]] == ["HKD", "USD", None]

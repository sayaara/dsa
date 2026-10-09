# -*- coding: utf-8 -*-
"""Report units: B/M + ISO currency outside zh, 亿/万 + currency word for zh."""

import pytest

from src.report_units import (
    currency_for_stock,
    format_money_amount,
    format_per_share_amount,
    format_share_volume,
)


@pytest.mark.parametrize(
    "code, expected",
    [("AAPL", "USD"), ("BRK.B", "USD"), ("RY.TO", "CAD"), ("ABX.V", "CAD"), ("", ""), (None, "")],
)
def test_currency_for_stock(code, expected):
    assert currency_for_stock(code) == expected


@pytest.mark.parametrize(
    "amount, currency, language, expected",
    [
        (3.9e11, "CAD", "en", "390.00B CAD"),
        (9.9e8, "usd", "en", "990.00M USD"),
        (-1.25e7, "CAD", "en", "-12.50M CAD"),
        (12_345, "USD", "en", "12,345 USD"),
        (9.9e8, "", "en", "990.00M"),
        (9.9e8, "US Dollar", "en", "990.00M"),
        (9.9e8, "CAD", "ko", "990.00M CAD"),
        (9.9e8, "CAD", "zh", "9.90 亿加元"),
        (-1.25e7, "USD", "zh", "-1250.00 万美元"),
        (9.9e8, None, "zh", "9.90 亿元"),
        (None, "USD", "en", "N/A"),
        ("n/a", "USD", "en", "N/A"),
        (float("nan"), "USD", "en", "N/A"),
        (True, "USD", "en", "N/A"),
    ],
)
def test_format_money_amount(amount, currency, language, expected):
    assert format_money_amount(amount, currency, language) == expected


@pytest.mark.parametrize(
    "volume, language, expected",
    [
        (5_200_000, "en", "5.20M shares"),
        (2.5e9, "en", "2.50B shares"),
        (12_345, "en", "12,345 shares"),
        (5_200_000, "zh", "520.00 万股"),
        (2.5e9, "zh", "25.00 亿股"),
        (None, "en", "N/A"),
    ],
)
def test_format_share_volume(volume, language, expected):
    assert format_share_volume(volume, language) == expected


def test_format_per_share_amount():
    assert format_per_share_amount(5.9, "CAD", "en") == "5.9000 CAD"
    assert format_per_share_amount(5.9, None, "en") == "5.9000"
    assert format_per_share_amount(5.9, "CAD", "zh") == "5.9000 加元"
    assert format_per_share_amount("x", "CAD", "en") == "N/A"

# -*- coding: utf-8 -*-
"""English company-name lookup for US and Canadian stocks (audit B2)."""

from unittest.mock import patch

import pytest

from src.services import english_stock_names as names
from src.services.name_to_code_resolver import resolve_name_to_code


@pytest.fixture(autouse=True)
def _fresh_cache():
    names.clear_english_name_cache()
    yield
    names.clear_english_name_cache()


def _row(code, name, market, aliases=()):
    return [code, code, name, name.upper(), name.upper(), list(aliases), market, "stock", True, 100]


_ROWS = [
    _row("AAPL", "APPLE", "US"),
    _row("RY.TO", "Royal Bank of Canada", "CA"),
    _row("TD.TO", "The Toronto-Dominion Bank", "CA"),
    _row("SHOP.TO", "Shopify Inc.", "CA"),
    _row("TECK-B.TO", "Teck Resources Ltd. Class B", "CA"),
    _row("TRI", "THOMSON REUTERS", "US"),
    _row("TRI.TO", "Thomson Reuters Corporation", "CA"),
    _row("FMCB", "FARMERS & MERCHANTS BANK OF LONG BEACH", "US"),
    _row("FMAO", "FARMERS & MERCHANTS BANCORP", "US"),
    _row("0011.HK", "Hang Seng Bank", "HK"),
]


@pytest.fixture
def index_rows():
    with patch.object(names, "_load_rows", return_value=_ROWS):
        yield


@pytest.mark.parametrize(
    "text, expected",
    [
        ("Apple Inc.", "apple"),
        ("The Toronto-Dominion Bank", "toronto dominion bank"),
        ("Teck Resources Ltd. Class B", "teck resources"),
        ("SHOPIFY 'A'", "shopify"),
        ("Farmers & Merchants", "farmers and merchants"),
    ],
)
def test_normalize_english_name(text, expected):
    assert names.normalize_english_name(text) == expected


@pytest.mark.parametrize(
    "text, expected",
    [
        ("Apple", "AAPL"),
        ("apple inc", "AAPL"),
        ("Royal Bank of Canada", "RY.TO"),
        ("royal bank of canada", "RY.TO"),
        ("Toronto-Dominion Bank", "TD.TO"),
        ("Shopify", "SHOP.TO"),
        ("Teck Resources", "TECK-B.TO"),
        ("Royal Bank", "RY.TO"),  # unique word prefix
        ("Thomson Reuters", None),  # interlisted: ambiguous
        ("Farmers & Merchants", None),  # ambiguous prefix
        ("Hang Seng Bank", None),  # Hong Kong rows are not indexed
        ("Bank", None),
        ("hello world", None),
        ("", None),
    ],
)
def test_resolve_english_stock_name(index_rows, text, expected):
    assert names.resolve_english_stock_name(text) == expected


def test_curated_unsupported_market_name_is_returned_for_the_caller_to_reject(index_rows):
    # The curated map still has Tencent; callers run the code through the parser and answer
    # "Hong Kong ... not supported" instead of "unrecognized symbol".
    assert names.resolve_english_stock_name("Tencent") == "00700"


def test_curated_names_take_precedence(index_rows):
    # STOCK_ENGLISH_NAME_MAP lists GOOGL before GOOG for "Alphabet" / "Google".
    assert names.resolve_english_stock_name("Google") == "GOOGL"
    assert names.resolve_english_stock_name("Alphabet Inc.") == "GOOGL"


def test_ticker_shaped_words(index_rows):
    word = names.english_name_for_ticker_shaped_word
    assert word("Apple") == "AAPL"
    assert word("apple") == "AAPL"
    assert word("APPLE") is None  # typed as a ticker
    assert word("aapl") is None  # not a name
    assert word("Royal") is None  # prefix matching is not used for ticker-shaped words
    assert word("Royal Bank of Canada") is None  # not ticker-shaped


def test_resolve_name_to_code_uses_english_names(index_rows):
    assert resolve_name_to_code("Apple") == "AAPL"
    assert resolve_name_to_code("Royal Bank of Canada") == "RY.TO"
    assert resolve_name_to_code("aapl") == "AAPL"
    assert resolve_name_to_code("APPLE") == "APPLE"


def test_bundled_index_resolves_common_us_and_canadian_names():
    # The real stocks.index.json shipped with the Web app.
    for text, code in (
        ("Apple", "AAPL"),
        ("Royal Bank of Canada", "RY.TO"),
        ("Shopify", "SHOP.TO"),
        ("Enbridge", "ENB.TO"),
        ("Tesla", "TSLA"),
        # S&P/TSX Composite rows (audit B4): the TSX listing, not a US OTC ticker.
        ("Air Canada", "AC.TO"),
        ("CCL Industries", "CCL-B.TO"),
        ("TMX Group", "X.TO"),
        # Interlisted on a US exchange: ambiguous, as with "Thomson Reuters".
        ("Equifax", None),
    ):
        assert names.resolve_english_stock_name(text) == code, text


def test_api_resolves_english_names_instead_of_ticker_shaped_words(index_rows):
    from api.v1.endpoints.analysis import _resolve_analysis_input

    assert _resolve_analysis_input("Apple") == ("AAPL", None)
    assert _resolve_analysis_input("apple inc") == ("AAPL", None)
    assert _resolve_analysis_input("Royal Bank of Canada") == ("RY.TO", None)
    assert _resolve_analysis_input("AAPL") == ("AAPL", None)
    assert _resolve_analysis_input("aapl") == ("AAPL", None)


def test_bot_resolves_english_names_instead_of_ticker_shaped_words(index_rows):
    from bot.commands.analyze import AnalyzeCommand

    resolve = AnalyzeCommand()._resolve_analysis_input
    assert resolve("Apple") == ("AAPL", None)
    assert resolve("Shopify") == ("SHOP.TO", None)
    assert resolve("aapl") == ("AAPL", None)

# -*- coding: utf-8 -*-
"""Interlisted companies: a name never picks between the TSX and the US listing (audit B4)."""

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from src.data.interlisted import INTERLISTED_PAIRS
from src.services import english_stock_names as names
from src.services.name_to_code_resolver import resolve_name_to_code

_BUNDLED_INDEX = Path(__file__).resolve().parent.parent / "apps" / "dsa-web" / "public" / "stocks.index.json"


@pytest.fixture(autouse=True)
def _fresh_cache():
    names.clear_english_name_cache()
    yield
    names.clear_english_name_cache()


def _row(code, name, market):
    return [code, code, name, name.upper(), name.upper(), [], market, "stock", True, 100]


_ROWS = [
    _row("AAPL", "APPLE", "US"),
    _row("SHOP", "SHOPIFY 'A' (NAS)", "US"),
    _row("SHOP.TO", "Shopify Inc.", "CA"),
    _row("TU", "TELUS (NYS)", "US"),
    _row("T.TO", "TELUS Corporation", "CA"),
    _row("T", "AT&T", "US"),
    _row("EFX", "EQUIFAX", "US"),
    _row("EFX.TO", "Equifax Inc.", "CA"),
    _row("HBM", "HUDBAY MINERALS (NYS)", "US"),
    _row("HBM.TO", "Hudbay Minerals Inc.", "CA"),
    _row("AC.TO", "Air Canada", "CA"),
    _row("ACDVF", "AIR CANADA VOTING (OTC) AND VARIABLE VOTING", "US"),
    # RY.TO without its US row: the pair is not active, so the name resolves as before.
    _row("RY.TO", "Royal Bank of Canada", "CA"),
]


@pytest.fixture
def index_rows():
    with patch.object(names, "_load_rows", return_value=_ROWS):
        yield


# --- the reviewed data ---------------------------------------------------------------------


def _bundled_rows():
    return {row[0]: row for row in json.loads(_BUNDLED_INDEX.read_text(encoding="utf-8"))}


def test_every_pair_is_a_tsx_listing_and_a_us_exchange_listing_in_the_bundled_index():
    rows = _bundled_rows()
    for tsx_code, us_code in INTERLISTED_PAIRS:
        tsx, us = rows.get(tsx_code), rows.get(us_code)
        assert tsx is not None and us is not None, (tsx_code, us_code)
        assert tsx[6] == "CA" and tsx_code.endswith(".TO") and tsx[8] is not False, tsx_code
        assert us[6] == "US" and us[8] is not False, us_code
        assert "(OTC)" not in us[2], f"{us_code} is an OTC quote, not an exchange listing"


def test_each_symbol_belongs_to_one_pair():
    symbols = [code for pair in INTERLISTED_PAIRS for code in pair]
    assert len(symbols) == len(set(symbols))


def test_a_shared_ticker_is_not_a_pair():
    pairs = set(INTERLISTED_PAIRS)
    assert ("T.TO", "TU") in pairs and ("T.TO", "T") not in pairs  # TELUS, not AT&T
    assert ("IMG.TO", "IAG") in pairs and ("IAG.TO", "IAG") not in pairs  # IAMGOLD, not iA Financial
    assert ("CNR.TO", "CNI") in pairs and ("CNR.TO", "CNR") not in pairs


# --- name resolution -----------------------------------------------------------------------


def test_interlisted_names_resolve_to_nothing(index_rows):
    for text in ("Shopify", "Shopify Inc.", "Telus", "telus", "Equifax", "Hudbay", "Hudbay Minerals"):
        assert names.resolve_english_stock_name(text) is None, text
        assert resolve_name_to_code(text) is None, text


def test_interlisted_names_list_both_listings_with_exchange_and_currency(index_rows):
    company = names.find_interlisted_listings("Shopify")
    assert company is not None
    assert company.name == "Shopify Inc."
    assert [(item.code, item.exchange, item.currency) for item in company.listings] == [
        ("SHOP", "Nasdaq", "USD"),
        ("SHOP.TO", "TSX", "CAD"),
    ]
    assert company.choice_message() == (
        "Shopify Inc. is listed on more than one exchange: SHOP (Nasdaq, USD) or SHOP.TO (TSX, CAD)."
        " Enter the symbol you want."
    )
    # A different ticker on each exchange, found from either name; no exchange tag shows "US".
    assert [item.code for item in names.find_interlisted_listings("Telus").listings] == ["TU", "T.TO"]
    assert names.find_interlisted_listings("Equifax").listings[0].label() == "EFX (US, USD)"
    # A word prefix that matches only the two listings of one company.
    assert names.find_interlisted_listings("Hudbay").listings[0].label() == "HBM (NYSE, USD)"


def test_symbols_and_other_names_are_unchanged(index_rows):
    for symbol in ("SHOP", "SHOP.TO", "TU", "T", "EFX", "BCE", "600519"):
        assert names.find_interlisted_listings(symbol) is None, symbol
    assert resolve_name_to_code("SHOP") == "SHOP"
    assert resolve_name_to_code("shop") == "SHOP"
    assert resolve_name_to_code("TELUS") == "TELUS"  # all capitals: a ticker, as before
    assert resolve_name_to_code("Apple") == "AAPL"
    # An OTC quote is not a second listing; nor is a pair whose US row is missing.
    assert resolve_name_to_code("Air Canada") == "AC.TO"
    assert resolve_name_to_code("Royal Bank of Canada") == "RY.TO"
    assert names.find_interlisted_listings("Air Canada") is None


def test_bundled_index_interlisted_names():
    for text, codes in (
        ("Shopify", ["SHOP", "SHOP.TO"]),
        ("Royal Bank of Canada", ["RY", "RY.TO"]),
        ("Enbridge", ["ENB", "ENB.TO"]),
        ("Telus", ["TU", "T.TO"]),
        ("Cameco", ["CCJ", "CCO.TO"]),
        ("Equifax", ["EFX", "EFX.TO"]),
        ("Hudbay", ["HBM", "HBM.TO"]),
    ):
        company = names.find_interlisted_listings(text)
        assert company is not None, text
        assert [item.code for item in company.listings] == codes
        assert resolve_name_to_code(text) is None, text
    assert resolve_name_to_code("Air Canada") == "AC.TO"
    assert resolve_name_to_code("iA Financial") == "IAG.TO"


# --- callers -------------------------------------------------------------------------------


def test_api_rejects_an_interlisted_name_with_both_listings(index_rows):
    from api.v1.endpoints.analysis import _resolve_analysis_input, trigger_analysis

    with pytest.raises(Exception) as excinfo:
        _resolve_analysis_input("Telus")
    assert excinfo.value.status_code == 400
    assert excinfo.value.detail["message"] == (
        "TELUS Corporation is listed on more than one exchange: TU (NYSE, USD) or T.TO (TSX, CAD)."
        " Enter the symbol you want."
    )
    assert _resolve_analysis_input("T.TO") == ("T.TO", None)
    assert _resolve_analysis_input("TU") == ("TU", None)

    with patch("api.v1.endpoints.analysis.get_task_queue") as queue_mock:
        with pytest.raises(Exception) as excinfo:
            trigger_analysis(
                request=SimpleNamespace(
                    stock_code="Shopify",
                    stock_codes=None,
                    report_type="detailed",
                    force_refresh=False,
                    async_mode=True,
                    analysis_phase="auto",
                ),
                config=SimpleNamespace(),
            )
    assert excinfo.value.status_code == 400
    assert "SHOP (Nasdaq, USD) or SHOP.TO (TSX, CAD)" in excinfo.value.detail["message"]
    queue_mock.assert_not_called()


def test_bot_rejects_an_interlisted_name_with_both_listings(index_rows):
    from bot.commands.analyze import AnalyzeCommand

    command = AnalyzeCommand()
    code, message = command._resolve_analysis_input("Shopify")
    assert code is None
    assert message == (
        "Shopify Inc. is listed on more than one exchange: SHOP (Nasdaq, USD) or SHOP.TO (TSX, CAD)."
        " Enter the symbol you want."
    )
    assert command._resolve_analysis_input("telus")[1].startswith("TELUS Corporation is listed")
    assert command._resolve_analysis_input("SHOP.TO") == ("SHOP.TO", None)
    assert command._resolve_analysis_input("Apple") == ("AAPL", None)

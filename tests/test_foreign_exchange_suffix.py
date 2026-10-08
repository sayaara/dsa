# -*- coding: utf-8 -*-
"""Foreign exchange suffixes are rejected instead of being analyzed as US stocks.

``VOD.L`` (London), ``SAP.DE`` (Xetra), ``BHP.AX`` (Sydney) and similar Yahoo symbols used to
match the US dotted-ticker shape: the parser returned a US stock, Yahoo was asked for the
foreign listing and the prompt labelled its prices in USD.
"""

from __future__ import annotations

import pytest

from api.v1.endpoints.analysis import _resolve_analysis_input
from bot.commands.analyze import AnalyzeCommand
from data_provider.us_index_mapping import is_us_stock_code
from src.services.market_symbol_utils import unsupported_exchange_suffix
from src.services.stock_code_utils import is_code_like, normalize_code
from src.services.stock_list_parser import ParseStatus, parse_analysis_target

FOREIGN = [
    ("VOD.L", "L"),
    ("vod.l", "L"),
    ("SHEL.L", "L"),
    ("BMW.F", "F"),
    ("SAP.DE", "DE"),
    ("BHP.AX", "AX"),
    ("AIR.PA", "PA"),
    ("ASML.AS", "AS"),
    ("NESN.SW", "SW"),
    ("RELIANCE.NS", "NS"),
    ("TCS.BO", "BO"),
    ("D05.SI", "SI"),
    ("WALMEX.MX", "MX"),
    ("PETR4.SA", "SA"),
]

STILL_SUPPORTED = [
    ("AAPL", "US"),
    ("BRK.B", "US"),
    ("BRK.A", "US"),
    ("BF.B", "US"),
    ("HEI.A", "US"),
    ("AAPL.US", "US"),
    ("RY.TO", "TO"),
    ("TECK-B.TO", "TO"),
    ("REI-UN.TO", "TO"),
    ("ABX.V", "V"),
    ("SHOP.NE", "NE"),
    ("WEED.CN", "CN"),
]


@pytest.mark.parametrize(("raw", "suffix"), FOREIGN)
def test_parser_rejects_foreign_exchange_suffixes(raw: str, suffix: str) -> None:
    target = parse_analysis_target(raw)
    assert target.asset_type == ParseStatus.UNSUPPORTED
    assert target.exchange == suffix
    assert f"exchange suffix '{suffix}' is not supported" in target.unsupported_reason


@pytest.mark.parametrize(("raw", "exchange"), STILL_SUPPORTED)
def test_us_share_classes_and_canadian_symbols_stay_supported(raw: str, exchange: str) -> None:
    target = parse_analysis_target(raw)
    assert target.asset_type == ParseStatus.STOCK
    assert target.exchange == exchange
    assert unsupported_exchange_suffix(raw) is None


def test_helper_ignores_symbols_without_an_alphabetic_suffix() -> None:
    for raw in ("AAPL", "BRK-B", "^GSPC", "600519", "SH.600519", "HK.00700", ""):
        assert unsupported_exchange_suffix(raw) is None


def test_data_layer_no_longer_treats_foreign_listings_as_us() -> None:
    assert not is_us_stock_code("VOD.L")
    assert not is_us_stock_code("BMW.F")
    assert is_us_stock_code("BRK.B")
    assert is_us_stock_code("BF.B")


def test_code_helpers_send_foreign_forms_to_the_parser() -> None:
    # Code-like, so callers parse them (and get the reason) instead of trying name resolution.
    assert is_code_like("SAP.DE")
    assert is_code_like("VOD.L")
    # But they never normalize to a code.
    assert normalize_code("VOD.L") is None
    assert normalize_code("SAP.DE") is None
    assert normalize_code("BRK.B") == "BRK.B"


@pytest.mark.parametrize("raw", ["VOD.L", "SAP.DE", "BHP.AX"])
def test_api_input_resolution_returns_the_unsupported_reason(raw: str) -> None:
    code, target = _resolve_analysis_input(raw)
    assert code == raw
    assert target.asset_type == ParseStatus.UNSUPPORTED
    assert "is not supported" in target.unsupported_reason


@pytest.mark.parametrize("raw", ["VOD.L", "SAP.DE", "BHP.AX"])
def test_bot_analyze_rejects_foreign_listings(raw: str) -> None:
    code, message = AnalyzeCommand()._resolve_analysis_input(raw)
    assert code is None
    assert message.startswith(f"Cannot analyze `{raw}`")
    assert "is not supported" in message


@pytest.mark.parametrize("raw", ["BRK.B", "RY.TO", "ABX.V"])
def test_bot_analyze_keeps_supported_dotted_symbols(raw: str) -> None:
    code, _target = AnalyzeCommand()._resolve_analysis_input(raw)
    assert code == raw

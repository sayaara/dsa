# -*- coding: utf-8 -*-
"""Tests for shared suffix-only market symbol helpers."""

import re

import src.services.market_symbol_utils as msu
from src.services.market_symbol_utils import (
    SuffixMarketSpec,
    get_suffix_market,
    is_suffix_market_symbol,
    market_suffixes,
    normalize_suffix_market_symbol,
    registered_suffixes,
    suffix_base_lookup_allowed,
)


def test_removed_asian_suffix_markets_are_not_registered() -> None:
    for code in ("7203.T", "005930.KS", "2330.TW", "6505.TWO"):
        assert get_suffix_market(code) is None
        assert is_suffix_market_symbol(code) is False
    assert normalize_suffix_market_symbol("7203.t") is None


def test_canada_symbols_are_detected_and_normalized() -> None:
    for code in ("RY.TO", "ry.to", "SHOP.TO", "ABX.V", "XYZ.CN", "ABC.NE", "BAM-A.TO", "REI-UN.TO", "TECK-B.TO"):
        assert get_suffix_market(code) == "ca", code
        assert is_suffix_market_symbol(code, "ca") is True
        assert is_suffix_market_symbol(code, "us") is False
    assert normalize_suffix_market_symbol("ry.to") == "RY.TO"
    assert normalize_suffix_market_symbol("bam-a.to") == "BAM-A.TO"
    assert market_suffixes("ca") == ("TO", "V", "CN", "NE")
    assert {"TO", "V", "CN", "NE"} <= registered_suffixes()


def test_canada_detection_rejects_invalid_or_foreign_symbols() -> None:
    for code in ("TOOLONGNAME.TO", "RY.", ".TO", "RY", "AAPL", "BRK.B", "0700.HK", "RY.TX", "A_B.TO", "-A.TO", "A--B.TO"):
        assert get_suffix_market(code) is None, code
        assert normalize_suffix_market_symbol(code) is None, code


def test_alphanumeric_and_numeric_specs_both_work(monkeypatch) -> None:
    """The mechanism supports numeric bases (digit_lengths) and pattern bases."""
    numeric = SuffixMarketSpec("xx", ("XX",), (4, 5))
    pattern = SuffixMarketSpec("yy", ("YY",), base_pattern=re.compile(r"[A-Z]{2,3}"))
    monkeypatch.setattr(msu, "_SUFFIX_TO_SPEC", {"XX": numeric, "YY": pattern})
    monkeypatch.setattr(msu, "_MARKET_TO_SPEC", {"xx": numeric, "yy": pattern})

    assert get_suffix_market("1234.xx") == "xx"
    assert get_suffix_market("123.XX") is None
    assert get_suffix_market("AB.YY") == "yy"
    assert get_suffix_market("A.YY") is None
    assert get_suffix_market("1234.YY") is None


def test_suffix_market_detection_rejects_ambiguous_or_invalid_bare_codes() -> None:
    assert get_suffix_market("005930") is None
    assert get_suffix_market("2330") is None
    assert get_suffix_market("123.T") is None


def test_bare_base_lookup_is_not_allowed_for_any_suffix_market() -> None:
    assert suffix_base_lookup_allowed("7203.T") is False
    assert suffix_base_lookup_allowed("RY.TO") is False

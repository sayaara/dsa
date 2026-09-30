# -*- coding: utf-8 -*-
"""Tests for shared suffix-only market symbol helpers."""

import src.services.market_symbol_utils as msu
from src.services.market_symbol_utils import (
    SuffixMarketSpec,
    get_suffix_market,
    is_suffix_market_symbol,
    normalize_suffix_market_symbol,
    suffix_base_lookup_allowed,
)


def test_no_suffix_market_is_registered_by_default() -> None:
    for code in ("7203.T", "005930.KS", "2330.TW", "6505.TWO", "RY.TO"):
        assert get_suffix_market(code) is None
        assert is_suffix_market_symbol(code) is False
    assert normalize_suffix_market_symbol("7203.t") is None


def test_registered_suffix_market_is_detected_and_normalized(monkeypatch) -> None:
    """The mechanism stays usable for a future market such as Canada."""
    spec = SuffixMarketSpec("ca", ("TO", "V"), (1, 2, 3, 4, 5))
    monkeypatch.setattr(msu, "_SUFFIX_TO_SPEC", {"TO": spec, "V": spec})
    monkeypatch.setattr(msu, "_MARKET_TO_SPEC", {"ca": spec})

    assert get_suffix_market("1234.to") == "ca"
    assert is_suffix_market_symbol("12.V", "ca") is True
    assert is_suffix_market_symbol("12.V", "us") is False
    assert normalize_suffix_market_symbol("1234.to") == "1234.TO"
    assert msu.market_suffixes("ca") == ("TO", "V")


def test_suffix_market_detection_rejects_ambiguous_or_invalid_bare_codes() -> None:
    assert get_suffix_market("005930") is None
    assert get_suffix_market("2330") is None
    assert get_suffix_market("123.T") is None


def test_bare_base_lookup_is_not_allowed_for_any_suffix_market() -> None:
    assert suffix_base_lookup_allowed("7203.T") is False
    assert suffix_base_lookup_allowed("1234.TO") is False

# -*- coding: utf-8 -*-
"""The market registry is the single list of supported markets.

Adding a market means one ``MarketSpec`` entry plus the per-market content that
these tests check for, so a half-added market fails here instead of silently
falling back to US wording.
"""

from zoneinfo import ZoneInfo

import pytest

from src.core import market_registry
from src.core.market_profile import MARKET_PROFILES
from src.core.market_registry import MARKET_CODE_SET, MARKET_CODES, MARKETS, get_market
from src.core.market_strategy import MARKET_STRATEGY_BLUEPRINTS
from src.core.trading_calendar import MARKET_EXCHANGE, MARKET_TIMEZONE
from src.market_context import _MARKET_GUIDELINES, _MARKET_ROLES
from src.services.decision_signal_service import DEFAULT_INTRADAY_TTL_HOURS
from src.services.market_symbol_utils import market_suffixes
from src.services.portfolio_service import VALID_MARKETS
from src.utils.market_review_region import MARKET_REVIEW_REGION_ORDER


def test_codes_are_unique_lowercase_and_sorted() -> None:
    codes = [spec.code for spec in MARKETS]
    assert len(codes) == len(set(codes))
    assert all(code == code.lower() and code.isalpha() for code in codes)
    assert MARKET_CODES == tuple(sorted(codes))
    assert MARKET_CODE_SET == frozenset(codes)


def test_symbol_suffixes_are_not_shared_between_markets() -> None:
    seen: dict[str, str] = {}
    for spec in MARKETS:
        for suffix in spec.symbol_suffixes:
            assert suffix == suffix.upper()
            assert suffix not in seen, f"{suffix} claimed by {seen.get(suffix)} and {spec.code}"
            seen[suffix] = spec.code
        if spec.symbol_suffixes:
            assert spec.symbol_base_pattern is not None or spec.symbol_digit_lengths, spec.code


@pytest.mark.parametrize("spec", MARKETS, ids=lambda spec: spec.code)
def test_each_market_has_valid_facts(spec) -> None:
    assert len(spec.currency) == 3 and spec.currency.isupper()
    ZoneInfo(spec.timezone)
    assert 0 < spec.regular_session_hours <= 24
    assert spec.closing_auction_minutes >= 0
    assert spec.name and spec.label


@pytest.mark.parametrize("code", MARKET_CODES)
def test_each_market_has_its_per_market_content(code) -> None:
    assert MARKET_PROFILES[code].region == code
    assert MARKET_STRATEGY_BLUEPRINTS[code].region == code
    assert isinstance(_MARKET_ROLES[code], str) and _MARKET_ROLES[code]
    assert isinstance(_MARKET_GUIDELINES[code], str) and _MARKET_GUIDELINES[code]


@pytest.mark.parametrize("code", MARKET_CODES)
def test_derived_tables_follow_the_registry(code) -> None:
    spec = get_market(code)
    assert MARKET_EXCHANGE[code] == spec.exchange_calendar
    assert MARKET_TIMEZONE[code] == spec.timezone
    assert DEFAULT_INTRADAY_TTL_HOURS[code] == spec.regular_session_hours
    assert code in VALID_MARKETS
    assert code in MARKET_REVIEW_REGION_ORDER
    assert market_suffixes(code) == spec.symbol_suffixes


def test_no_content_for_unregistered_markets() -> None:
    assert set(MARKET_PROFILES) == MARKET_CODE_SET
    assert set(MARKET_STRATEGY_BLUEPRINTS) == MARKET_CODE_SET
    assert set(_MARKET_ROLES) == MARKET_CODE_SET
    assert set(_MARKET_GUIDELINES) == MARKET_CODE_SET


def test_lookup_is_case_insensitive_and_rejects_unknown() -> None:
    assert get_market(" CA ").code == "ca"
    assert get_market("jp") is None
    assert get_market(None) is None
    assert market_registry.is_supported_market("us") is True
    assert market_registry.is_supported_market("cn") is False

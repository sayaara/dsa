# -*- coding: utf-8 -*-
"""Single registry of the markets the product supports.

Each ``MarketSpec`` holds the plain facts about one market: currency, exchange
calendar, timezone, session length and, for suffix markets, the Yahoo symbol
suffixes. Modules that used to keep their own ``{"us": ..., "ca": ...}`` tables
derive them from here, so adding a market starts with one entry below.

Richer per-market content (market-review profile, strategy blueprint, prompt
guidelines) stays in its own module, keyed by ``MarketSpec.code``;
``tests/test_market_registry.py`` fails when a registered market is missing one.

Keep this module free of project imports: data providers, the trading calendar
and symbol parsing all import it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional, Pattern


@dataclass(frozen=True)
class MarketSpec:
    """Facts about one supported market."""

    code: str
    # Full English name and the short label used in report and log text.
    name: str
    label: str
    currency: str
    # exchange-calendars code and IANA timezone of the primary exchange.
    exchange_calendar: str
    timezone: str
    # Length of the regular session; the intraday decision-signal TTL fallback.
    regular_session_hours: float
    # Minutes before the close treated as the closing auction (0 = none).
    closing_auction_minutes: int = 0
    # Yahoo symbol suffixes for suffix markets (``RY.TO``). Empty for markets
    # whose symbols have no suffix (US tickers) or bespoke parsing.
    symbol_suffixes: tuple[str, ...] = ()
    # Numeric bases of these lengths, or bases matching this pattern.
    symbol_digit_lengths: tuple[int, ...] = ()
    symbol_base_pattern: Optional[Pattern[str]] = None


US = MarketSpec(
    code="us",
    name="United States",
    label="US",
    currency="USD",
    exchange_calendar="XNYS",
    timezone="America/New_York",
    regular_session_hours=6.5,
    closing_auction_minutes=5,
)

HK = MarketSpec(
    code="hk",
    name="Hong Kong",
    label="HK",
    currency="HKD",
    exchange_calendar="XHKG",
    timezone="Asia/Hong_Kong",
    regular_session_hours=5.5,
    closing_auction_minutes=10,
)

# Canada: TSX (.TO), TSX Venture (.V), CSE (.CN) and NEO (.NE). Bases are 1-6
# alphanumerics with an optional hyphenated class or unit marker, as Yahoo
# writes them (``RY.TO``, ``BAM-A.TO``, ``REI-UN.TO``).
CA = MarketSpec(
    code="ca",
    name="Canada",
    label="Canada",
    currency="CAD",
    exchange_calendar="XTSE",
    timezone="America/Toronto",
    regular_session_hours=6.5,
    closing_auction_minutes=10,
    symbol_suffixes=("TO", "V", "CN", "NE"),
    symbol_base_pattern=re.compile(r"[A-Z0-9]{1,6}(?:-[A-Z]{1,2})?"),
)

MARKETS: tuple[MarketSpec, ...] = (US, HK, CA)

_BY_CODE = {spec.code: spec for spec in MARKETS}


def get_market(code: Optional[str]) -> Optional[MarketSpec]:
    """Return the spec for a market code (case-insensitive), or None."""

    return _BY_CODE.get((code or "").strip().lower())


def market_codes() -> tuple[str, ...]:
    """Return every supported market code, sorted alphabetically."""

    return tuple(sorted(_BY_CODE))


def is_supported_market(code: Optional[str]) -> bool:
    return get_market(code) is not None


# Alphabetical tuple and set of every supported market code, for membership
# checks and stable iteration.
MARKET_CODES: tuple[str, ...] = market_codes()
MARKET_CODE_SET: frozenset[str] = frozenset(MARKET_CODES)

# -*- coding: utf-8 -*-
"""Shared market-symbol helpers for suffix-only offshore markets.

Keep this module dependency-light so it can be used by data providers, market
context, trading calendars, stock-index loading, and API input normalization
without introducing import cycles.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional, Pattern


@dataclass(frozen=True)
class SuffixMarketSpec:
    """A suffix-only Yahoo Finance market rule."""

    market: str
    suffixes: tuple[str, ...]
    digit_lengths: tuple[int, ...] = ()
    # Alphanumeric markets (Canada) match the base against this pattern instead of
    # requiring a purely numeric base of ``digit_lengths`` digits.
    base_pattern: Optional[Pattern[str]] = None

    def accepts_base(self, base: str) -> bool:
        if self.base_pattern is not None:
            return self.base_pattern.fullmatch(base) is not None
        return base.isdigit() and len(base) in self.digit_lengths


# Suffix-only Yahoo markets. Canada: TSX (.TO), TSX Venture (.V), CSE (.CN) and
# NEO (.NE). Bases are 1-6 alphanumerics with an optional hyphenated class or unit
# marker, as Yahoo writes them (``RY.TO``, ``BAM-A.TO``, ``REI-UN.TO``).
_SUFFIX_MARKET_SPECS: tuple[SuffixMarketSpec, ...] = (
    SuffixMarketSpec(
        market="ca",
        suffixes=("TO", "V", "CN", "NE"),
        base_pattern=re.compile(r"[A-Z0-9]{1,6}(?:-[A-Z]{1,2})?"),
    ),
)

_MARKET_TO_SPEC = {spec.market: spec for spec in _SUFFIX_MARKET_SPECS}
_SUFFIX_TO_SPEC = {
    suffix: spec
    for spec in _SUFFIX_MARKET_SPECS
    for suffix in spec.suffixes
}


def split_suffix_symbol(stock_code: str) -> tuple[str, str] | None:
    """Return ``(base, suffix)`` for dotted symbols, upper-cased and stripped."""

    code = (stock_code or "").strip().upper()
    if "." not in code:
        return None
    base, suffix = code.rsplit(".", 1)
    if not base or not suffix:
        return None
    return base, suffix


def get_suffix_market(stock_code: str) -> Optional[str]:
    """Return the market for supported suffix-only Yahoo symbols, else None."""

    parts = split_suffix_symbol(stock_code)
    if parts is None:
        return None
    base, suffix = parts
    spec = _SUFFIX_TO_SPEC.get(suffix)
    if spec is None:
        return None
    if not spec.accepts_base(base):
        return None
    return spec.market


def is_suffix_market_symbol(stock_code: str, market: Optional[str] = None) -> bool:
    """Return whether a stock code is a supported suffix-only Yahoo symbol."""

    detected = get_suffix_market(stock_code)
    if market is None:
        return detected is not None
    return detected == (market or "").strip().lower()


def normalize_suffix_market_symbol(stock_code: str) -> Optional[str]:
    """Normalize supported suffix-only symbols to upper-case Yahoo form."""

    parts = split_suffix_symbol(stock_code)
    if parts is None:
        return None
    base, suffix = parts
    if get_suffix_market(f"{base}.{suffix}") is None:
        return None
    return f"{base}.{suffix}"


def suffix_base_lookup_allowed(canonical_code: str) -> bool:
    """Return True when a suffix-market code may be resolved from its bare base.

    No suffix market currently allows bare-base lookup.
    """

    return False


def registered_suffixes() -> frozenset[str]:
    """Return every suffix claimed by a registered suffix market."""

    return frozenset(_SUFFIX_TO_SPEC)


def market_suffixes(market: str) -> tuple[str, ...]:
    spec = _MARKET_TO_SPEC.get((market or "").strip().lower())
    return spec.suffixes if spec else ()

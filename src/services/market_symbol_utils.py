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

from src.core.market_registry import MARKETS


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


# Suffix-only Yahoo markets: every registered market that declares symbol suffixes.
_SUFFIX_MARKET_SPECS: tuple[SuffixMarketSpec, ...] = tuple(
    SuffixMarketSpec(
        market=spec.code,
        suffixes=spec.symbol_suffixes,
        digit_lengths=spec.symbol_digit_lengths,
        base_pattern=spec.symbol_base_pattern,
    )
    for spec in MARKETS
    if spec.symbol_suffixes
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


# ``BASE.SUFFIX`` with an alphabetic exchange suffix, as Yahoo writes non-US listings
# (``VOD.L``, ``SAP.DE``, ``RELIANCE.NS``).
_DOTTED_SYMBOL_RE = re.compile(r"^([A-Z0-9][A-Z0-9-]*)\.([A-Z]{1,4})$")
# Yahoo's one-letter exchange suffixes: London and Frankfurt. Any other single letter after
# a 1-5 letter ticker is a US share class (``BRK.B``, ``BF.B``); Tokyo's ``.T`` only follows
# numeric codes.
_SINGLE_LETTER_EXCHANGE_SUFFIXES = frozenset({"L", "F"})


def unsupported_exchange_suffix(stock_code: str) -> Optional[str]:
    """Return the exchange suffix of a dotted symbol that no supported market owns.

    ``None`` for symbols without such a suffix, for registered suffix markets
    (``RY.TO``), for the explicit US form (``AAPL.US``) and for US share classes
    (``BRK.B``). Without this check a foreign listing such as ``VOD.L`` matched the
    US dotted-ticker shape and was analyzed as a US stock.
    """

    match = _DOTTED_SYMBOL_RE.match((stock_code or "").strip().upper())
    if match is None:
        return None
    base, suffix = match.groups()
    if suffix in _SUFFIX_TO_SPEC or suffix == "US":
        return None
    is_share_class = (
        len(suffix) == 1
        and suffix not in _SINGLE_LETTER_EXCHANGE_SUFFIXES
        and base.isalpha()
        and len(base) <= 5
    )
    return None if is_share_class else suffix


def market_suffixes(market: str) -> tuple[str, ...]:
    spec = _MARKET_TO_SPEC.get((market or "").strip().lower())
    return spec.suffixes if spec else ()

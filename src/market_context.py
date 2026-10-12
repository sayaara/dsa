# -*- coding: utf-8 -*-
"""
Market context detection for LLM prompts.

Detects the market (US, Canada) from a stock code and returns
market-specific role descriptions so prompts are not hardcoded to a
single market.

Fixes: #644
"""

import re
from typing import Optional

from src.services.market_symbol_utils import get_suffix_market


def detect_market(stock_code: Optional[str]) -> str:
    """Detect market from stock code.

    Returns:
        One of 'us', a registered suffix market, or 'unknown'.
    """
    if not stock_code:
        return "unknown"

    code = stock_code.strip().upper()

    # Suffix-only Yahoo symbols of registered suffix markets. Bare numeric
    # codes keep existing fallback semantics to avoid cross-market collisions.
    suffix_market = get_suffix_market(code)
    if suffix_market:
        return suffix_market

    # US stocks: 1-5 uppercase letters (AAPL, TSLA, GOOGL)
    # Also handles share classes written BRK.B or BRK-B
    if re.match(r'^[A-Z]{1,5}([.-][A-Z]{1,2})?$', code):
        return "us"

    # US indices, including Yahoo caret symbols (^GSPC, ^DJI) and aliases (SPX)
    from data_provider.us_index_mapping import is_us_index_code

    if is_us_index_code(code):
        return "us"

    # Unrecognized shape; prompts fall back to the US wording
    return "unknown"


# -- Market-specific role descriptions --

_MARKET_ROLES = {
    "us": "US stock",
    "ca": "Canadian stock",
}

_MARKET_GUIDELINES = {
    "us": (
        "- This analysis covers a **US stock** (listed on NYSE/NASDAQ).\n"
        "- US stocks have no daily price limits (but have circuit breakers), allow T+0 and pre/after-market trading. Consider USD FX, Fed policy, and SEC regulations."
    ),
    "ca": (
        "- This analysis covers a **Canadian stock** (listed on the TSX, TSX Venture, CSE or NEO).\n"
        "- Canadian stocks have no daily price limits (but have circuit breakers), settle T+1, and are priced in CAD. Consider CAD FX, Bank of Canada policy, the energy and metals commodity cycle, and the heavy weight of financials."
    ),
}


def get_market_role(stock_code: Optional[str], lang: Optional[str] = None) -> str:
    """Return the market-specific role description for the LLM prompt, such as 'US stock'.

    ``lang`` is kept for the existing call sites; prompts are English-only.
    """
    return _MARKET_ROLES.get(detect_market(stock_code), _MARKET_ROLES["us"])


def get_market_guidelines(stock_code: Optional[str], lang: Optional[str] = None) -> str:
    """Return the market-specific analysis guidelines for the LLM prompt.

    ``lang`` is kept for the existing call sites; prompts are English-only.
    """
    return _MARKET_GUIDELINES.get(detect_market(stock_code), _MARKET_GUIDELINES["us"])

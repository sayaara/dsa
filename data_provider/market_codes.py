# -*- coding: utf-8 -*-
"""
Market code classification that does not depend on any regional data source.

US and Hong Kong routing must be decidable without importing any
regional fetcher, so the shared predicates live here.
"""

from .us_index_mapping import is_us_stock_code


def is_hk_stock_code(stock_code: str) -> bool:
    """
    Decide whether a code is a Hong Kong equity code.

    Rules:
    - ``.HK`` suffix (``0700.HK``) or ``HK`` prefix (``hk00700``) with 1-5 digits
    - Bare 4-5 pure digits (mainland 6-digit codes never clash with these)

    The digit range matches ``data_provider.base._is_hk_market``,
    ``YfinanceFetcher._convert_stock_code`` and ``LongbridgeFetcher._is_hk_code``.
    """
    code = (stock_code or "").strip().lower()
    if code.endswith(".hk"):
        numeric_part = code[:-3]
        return numeric_part.isdigit() and 1 <= len(numeric_part) <= 5
    if code.startswith("hk"):
        numeric_part = code[2:]
        return numeric_part.isdigit() and 1 <= len(numeric_part) <= 5
    return code.isdigit() and 4 <= len(code) <= 5


def is_us_code(stock_code: str) -> bool:
    """Decide whether a code is a US stock (US indices excluded)."""
    return is_us_stock_code(stock_code)

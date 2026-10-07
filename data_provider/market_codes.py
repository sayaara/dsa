# -*- coding: utf-8 -*-
"""
Market code classification that does not depend on any regional data source.

US routing must be decidable without importing any regional fetcher, so the
shared predicates live here.
"""

from .us_index_mapping import is_us_stock_code


def is_us_code(stock_code: str) -> bool:
    """Decide whether a code is a US stock (US indices excluded)."""
    return is_us_stock_code(stock_code)

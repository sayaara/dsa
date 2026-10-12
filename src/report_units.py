# -*- coding: utf-8 -*-
"""Units for volumes and money amounts in rendered reports.

Reports are English-only: amounts use B/M scaling with the ISO currency code. The
``report_language`` arguments are kept for the existing call sites.
"""

from __future__ import annotations

from typing import Any, Optional

from src.core.market_registry import get_market
from src.market_context import detect_market


def _to_number(value: Any) -> Optional[float]:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != number:  # NaN
        return None
    return number


def _iso_currency(currency: Optional[str]) -> str:
    code = (currency or "").strip().upper()
    return code if len(code) == 3 and code.isascii() and code.isalpha() else ""


def currency_for_stock(code: Any) -> str:
    """Return the ISO currency of a stock's market (registry), or "" when unknown."""
    spec = get_market(detect_market(str(code or "")))
    return spec.currency if spec is not None else ""


def format_share_volume(volume: Any, report_language: Optional[str]) -> str:
    """Format a share volume as B/M shares."""
    number = _to_number(volume)
    if number is None:
        return "N/A"
    if number >= 1e9:
        return f"{number / 1e9:.2f}B shares"
    if number >= 1e6:
        return f"{number / 1e6:.2f}M shares"
    return f"{number:,.0f} shares"


def format_money_amount(amount: Any, currency: Optional[str], report_language: Optional[str]) -> str:
    """Format a money amount (signed) with B/M scaling and the ISO currency code."""
    number = _to_number(amount)
    if number is None:
        return "N/A"
    sign = "-" if number < 0 else ""
    magnitude = abs(number)
    iso = _iso_currency(currency)
    suffix = f" {iso}" if iso else ""
    if magnitude >= 1e9:
        return f"{sign}{magnitude / 1e9:.2f}B{suffix}"
    if magnitude >= 1e6:
        return f"{sign}{magnitude / 1e6:.2f}M{suffix}"
    return f"{sign}{magnitude:,.0f}{suffix}"


def format_per_share_amount(value: Any, currency: Optional[str], report_language: Optional[str]) -> str:
    """Format a per-share money value (for example a dividend) with its currency."""
    number = _to_number(value)
    if number is None:
        return "N/A"
    iso = _iso_currency(currency)
    return f"{number:.4f} {iso}" if iso else f"{number:.4f}"

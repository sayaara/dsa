# -*- coding: utf-8 -*-
"""Report-language-aware units for volumes and money amounts in rendered reports.

Chinese reports keep the 亿/万 scale with a Chinese currency word. Every other report
language uses B/M scaling with the ISO currency code, so an English report never
shows Chinese units and never labels US or Canadian money as yuan.
"""

from __future__ import annotations

from typing import Any, Optional

from src.core.market_registry import get_market
from src.market_context import detect_market
from src.report_language import normalize_report_language

# Chinese currency words for zh reports; an unknown currency keeps the historical 元.
_ZH_CURRENCY_WORDS = {
    "USD": "美元",
    "HKD": "港元",
    "CAD": "加元",
    "CNY": "元",
    "RMB": "元",
    "CNH": "元",
}


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


def _is_zh(report_language: Optional[str]) -> bool:
    return normalize_report_language(report_language) == "zh"


def _iso_currency(currency: Optional[str]) -> str:
    code = (currency or "").strip().upper()
    return code if len(code) == 3 and code.isascii() and code.isalpha() else ""


def currency_for_stock(code: Any) -> str:
    """Return the ISO currency of a stock's market (registry), or "" when unknown."""
    spec = get_market(detect_market(str(code or "")))
    return spec.currency if spec is not None else ""


def format_share_volume(volume: Any, report_language: Optional[str]) -> str:
    """Format a share volume: 亿股/万股 for zh, B/M shares otherwise."""
    number = _to_number(volume)
    if number is None:
        return "N/A"
    if _is_zh(report_language):
        if number >= 1e8:
            return f"{number / 1e8:.2f} 亿股"
        if number >= 1e4:
            return f"{number / 1e4:.2f} 万股"
        return f"{number:.0f} 股"
    if number >= 1e9:
        return f"{number / 1e9:.2f}B shares"
    if number >= 1e6:
        return f"{number / 1e6:.2f}M shares"
    return f"{number:,.0f} shares"


def format_money_amount(amount: Any, currency: Optional[str], report_language: Optional[str]) -> str:
    """Format a money amount (signed): 亿/万 + currency word for zh, B/M + ISO code otherwise."""
    number = _to_number(amount)
    if number is None:
        return "N/A"
    sign = "-" if number < 0 else ""
    magnitude = abs(number)
    if _is_zh(report_language):
        word = _ZH_CURRENCY_WORDS.get(_iso_currency(currency), "元")
        if magnitude >= 1e8:
            return f"{sign}{magnitude / 1e8:.2f} 亿{word}"
        if magnitude >= 1e4:
            return f"{sign}{magnitude / 1e4:.2f} 万{word}"
        return f"{sign}{magnitude:.0f} {word}"
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
    if _is_zh(report_language):
        return f"{number:.4f} {_ZH_CURRENCY_WORDS.get(_iso_currency(currency), '元')}"
    iso = _iso_currency(currency)
    return f"{number:.4f} {iso}" if iso else f"{number:.4f}"

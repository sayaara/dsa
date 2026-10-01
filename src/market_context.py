# -*- coding: utf-8 -*-
"""
Market context detection for LLM prompts.

Detects the market (HK, US, Canada) from a stock code and returns
market-specific role descriptions so prompts are not hardcoded to a
single market.

Fixes: https://github.com/ZhuLinsen/daily_stock_analysis/issues/644
"""

import re
from typing import Optional

from src.services.market_symbol_utils import get_suffix_market
from src.report_language import resolve_report_language


def detect_market(stock_code: Optional[str]) -> str:
    """Detect market from stock code.

    Returns:
        One of 'hk', 'us', a registered suffix market, or 'unknown'.
    """
    if not stock_code:
        return "unknown"

    code = stock_code.strip().upper()

    # HK stocks: HK00700, 00700.HK, or 5-digit pure numbers
    if code.startswith("HK") or code.endswith(".HK"):
        return "hk"
    lower = code.lower()
    if lower.endswith(".hk"):
        return "hk"
    # 5-digit pure numbers are HK
    if code.isdigit() and len(code) == 5:
        return "hk"

    # Suffix-only Yahoo symbols of registered suffix markets. Bare numeric
    # codes keep existing fallback semantics to avoid cross-market collisions.
    suffix_market = get_suffix_market(code)
    if suffix_market:
        return suffix_market

    # US stocks: 1-5 uppercase letters (AAPL, TSLA, GOOGL)
    # Also handles suffixed forms like BRK.B
    if re.match(r'^[A-Z]{1,5}(\.[A-Z]{1,2})?$', code):
        return "us"

    # Unrecognized shape; prompts fall back to the US wording
    return "unknown"


# -- Market-specific role descriptions --

_MARKET_ROLES = {
    "hk": {
        "zh": "港股",
        "en": "Hong Kong stock",
    },
    "us": {
        "zh": "美股",
        "en": "US stock",
    },
    "ca": {
        "zh": "加拿大股票",
        "en": "Canadian stock",
    },
}

_MARKET_GUIDELINES = {
    "hk": {
        "zh": (
            "- 本次分析对象为 **港股**（香港交易所上市股票）。\n"
            "- 港股无涨跌停限制，支持 T+0 交易，需关注港币汇率、南北向资金流及联交所特有规则。"
        ),
        "en": (
            "- This analysis covers a **Hong Kong stock** (listed on HKEX).\n"
            "- HK stocks have no daily price limits, allow T+0 trading. Consider HKD FX, Southbound/Northbound flows, and HKEX-specific rules."
        ),
    },
    "us": {
        "zh": (
            "- 本次分析对象为 **美股**（美国交易所上市股票）。\n"
            "- 美股无涨跌停限制（但有熔断机制），支持 T+0 交易和盘前盘后交易，需关注美元汇率、美联储政策及 SEC 监管动态。"
        ),
        "en": (
            "- This analysis covers a **US stock** (listed on NYSE/NASDAQ).\n"
            "- US stocks have no daily price limits (but have circuit breakers), allow T+0 and pre/after-market trading. Consider USD FX, Fed policy, and SEC regulations."
        ),
    },
    "ca": {
        "zh": (
            "- 本次分析对象为 **加拿大股票**（多伦多证券交易所 TSX / 创业板 TSXV 等上市）。\n"
            "- 加拿大股市无涨跌停限制（但有熔断机制），当前为 T+1 结算，价格以加元（CAD）计价；需关注加元汇率、加拿大央行政策、大宗商品（能源与金属）周期及金融板块集中度。"
        ),
        "en": (
            "- This analysis covers a **Canadian stock** (listed on the TSX, TSX Venture, CSE or NEO).\n"
            "- Canadian stocks have no daily price limits (but have circuit breakers), settle T+1, and are priced in CAD. Consider CAD FX, Bank of Canada policy, the energy and metals commodity cycle, and the heavy weight of financials."
        ),
    },
}


def get_market_role(stock_code: Optional[str], lang: Optional[str] = None) -> str:
    """Return market-specific role description for LLM prompt.

    Args:
        stock_code: The stock code being analyzed.
        lang: 'zh' or 'en'.

    Returns:
        Role string like '美股' or 'US stock investment analysis'.
    """
    lang = resolve_report_language(lang)
    market = detect_market(stock_code)
    lang_key = "en" if lang in ("en", "ko") else "zh"
    return _MARKET_ROLES.get(market, _MARKET_ROLES["us"])[lang_key]


def get_market_guidelines(stock_code: Optional[str], lang: Optional[str] = None) -> str:
    """Return market-specific analysis guidelines for LLM prompt.

    Args:
        stock_code: The stock code being analyzed.
        lang: 'zh' or 'en'.

    Returns:
        Multi-line string with market-specific guidelines.
    """
    lang = resolve_report_language(lang)
    market = detect_market(stock_code)
    lang_key = "en" if lang in ("en", "ko") else "zh"
    return _MARKET_GUIDELINES.get(market, _MARKET_GUIDELINES["us"])[lang_key]

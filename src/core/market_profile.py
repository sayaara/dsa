# -*- coding: utf-8 -*-
"""
Market region configuration for the broad-market review

Defines per-region metadata such as the index, news search terms and prompt hints,
so MarketAnalyzer can switch review behaviour by region across Canada, HK and US.
"""

from dataclasses import dataclass
from typing import List


@dataclass
class MarketProfile:
    """Market region configuration for the broad-market review"""

    region: str  # "ca" | "hk" | "us"
    # Index code used to judge the overall trend: ca uses the S&P/TSX Composite, hk uses HSI, us uses S&P SPX
    mood_index_code: str
    # News search keywords
    news_queries: List[str]
    # Prompt hint for the index commentary
    prompt_index_hint: str


US_PROFILE = MarketProfile(
    region="us",
    mood_index_code="SPX",
    news_queries=[
        "美股 大盘",
        "US stock market",
        "S&P 500 NASDAQ",
    ],
    prompt_index_hint="分析标普500、纳斯达克、道指等各指数走势特点",
)

HK_PROFILE = MarketProfile(
    region="hk",
    mood_index_code="HSI",
    news_queries=[
        "港股 大盘 复盘",
        "Hong Kong stock market",
        "恒生指数 行情",
    ],
    prompt_index_hint="分析恒生指数、恒生科技指数、国企指数等各指数走势特点",
)

CA_PROFILE = MarketProfile(
    region="ca",
    mood_index_code="TSX",
    news_queries=[
        "TSX market recap",
        "S&P/TSX Composite",
        "加拿大股市 大盘",
    ],
    prompt_index_hint="分析标普/多伦多证交所综合指数（S&P/TSX Composite）与创业板综合指数等各指数走势特点",
)


def get_profile(region: str) -> MarketProfile:
    """Return the MarketProfile matching the given region"""
    if region == "us":
        return US_PROFILE
    if region == "hk":
        return HK_PROFILE
    if region == "ca":
        return CA_PROFILE
    return US_PROFILE

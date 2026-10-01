# -*- coding: utf-8 -*-
"""
Market region configuration for the broad-market review

Defines per-region metadata such as the index, news search terms and prompt hints,
so MarketAnalyzer can switch review behaviour by region across HK and US.
"""

from dataclasses import dataclass
from typing import List


@dataclass
class MarketProfile:
    """Market region configuration for the broad-market review"""

    region: str  # "hk" | "us"
    # Index code used to judge the overall trend: hk uses HSI, us uses S&P SPX
    mood_index_code: str
    # News search keywords
    news_queries: List[str]
    # Prompt hint for the index commentary
    prompt_index_hint: str
    # Whether the market overview includes advancer/decliner counts and limit up/down (not available for HK/US)
    has_market_stats: bool
    # Whether the market overview includes sector moves (not available for HK/US yet)
    has_sector_rankings: bool


US_PROFILE = MarketProfile(
    region="us",
    mood_index_code="SPX",
    news_queries=[
        "美股 大盘",
        "US stock market",
        "S&P 500 NASDAQ",
    ],
    prompt_index_hint="分析标普500、纳斯达克、道指等各指数走势特点",
    has_market_stats=False,
    has_sector_rankings=False,
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
    has_market_stats=False,
    has_sector_rankings=False,
)

def get_profile(region: str) -> MarketProfile:
    """Return the MarketProfile matching the given region"""
    if region == "us":
        return US_PROFILE
    if region == "hk":
        return HK_PROFILE
    return US_PROFILE

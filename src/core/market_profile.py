# -*- coding: utf-8 -*-
"""
Market region configuration for the broad-market review

Defines per-region metadata such as the index, news search terms and prompt hints,
so MarketAnalyzer can switch review behaviour by region across Canada and the US.
"""

from dataclasses import dataclass, field
from typing import List


@dataclass
class MarketProfile:
    """Market region configuration for the broad-market review"""

    region: str  # "ca" | "us"
    # Index code used to judge the overall trend: ca uses the S&P/TSX Composite, us uses S&P SPX
    mood_index_code: str
    # News search keywords. The search provider gets each query as is, so a query's
    # language decides the language of the articles that come back.
    news_queries: List[str]
    # Prompt hint for the index commentary (zh reviews; en text is in MarketAnalyzer._get_index_hint)
    prompt_index_hint: str
    # News search keywords for zh reviews (dormant language)
    news_queries_zh: List[str] = field(default_factory=list)


US_PROFILE = MarketProfile(
    region="us",
    mood_index_code="SPX",
    news_queries=[
        "Wall Street stock market close",
        "US stock market",
        "S&P 500 NASDAQ",
    ],
    prompt_index_hint="分析标普500、纳斯达克、道指等各指数走势特点",
    news_queries_zh=["美股 大盘", "US stock market", "S&P 500 NASDAQ"],
)

CA_PROFILE = MarketProfile(
    region="ca",
    mood_index_code="TSX",
    news_queries=[
        "TSX market recap",
        "S&P/TSX Composite",
        "Canadian stocks today",
    ],
    prompt_index_hint="分析标普/多伦多证交所综合指数（S&P/TSX Composite）与创业板综合指数等各指数走势特点",
    news_queries_zh=["TSX market recap", "S&P/TSX Composite", "加拿大股市 大盘"],
)


MARKET_PROFILES = {profile.region: profile for profile in (US_PROFILE, CA_PROFILE)}


def get_profile(region: str) -> MarketProfile:
    """Return the MarketProfile matching the given region (US when unknown)."""
    return MARKET_PROFILES.get(region, US_PROFILE)

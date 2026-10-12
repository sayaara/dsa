# -*- coding: utf-8 -*-
"""
Market region configuration for the broad-market review

Defines per-region metadata such as the index, news search terms and prompt hints,
so MarketAnalyzer can switch review behaviour by region across Canada and the US.
"""

from dataclasses import dataclass
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


US_PROFILE = MarketProfile(
    region="us",
    mood_index_code="SPX",
    news_queries=[
        "Wall Street stock market close",
        "US stock market",
        "S&P 500 NASDAQ",
    ],
)

CA_PROFILE = MarketProfile(
    region="ca",
    mood_index_code="TSX",
    news_queries=[
        "TSX market recap",
        "S&P/TSX Composite",
        "Canadian stocks today",
    ],
)


MARKET_PROFILES = {profile.region: profile for profile in (US_PROFILE, CA_PROFILE)}


def get_profile(region: str) -> MarketProfile:
    """Return the MarketProfile matching the given region (US when unknown)."""
    return MARKET_PROFILES.get(region, US_PROFILE)

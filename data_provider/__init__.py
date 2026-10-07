# -*- coding: utf-8 -*-
"""
===================================
Data source strategy layer - package initialization
===================================

This package applies the strategy pattern to manage multiple data sources, providing:
1. A unified data retrieval interface
2. Automatic failover
3. Rate-control strategies to avoid being blocked

Data sources (a lower priority number wins; sources with the same priority keep their initialization order):
1. FinnhubFetcher (Priority 2, optional) - US quotes, needs FINNHUB_API_KEY
2. AlphaVantageFetcher (optional) - US daily bars, needs ALPHA_VANTAGE_API_KEY
3. YfinanceFetcher (Priority 4) - from the yfinance library, the default for every registered market
4. LongbridgeFetcher (Priority 5, optional) - Longbridge OpenAPI, US fallback

Note: a lower priority number wins, and sources with the same priority keep their initialization order
"""

from .base import BaseFetcher, DataFetcherManager
from .yfinance_fetcher import YfinanceFetcher
from .longbridge_fetcher import LongbridgeFetcher
from .finnhub_fetcher import FinnhubFetcher
from .alphavantage_fetcher import AlphaVantageFetcher
from .us_index_mapping import is_us_index_code, is_us_stock_code, get_us_index_yf_symbol, US_INDEX_MAPPING

__all__ = [
    'BaseFetcher',
    'DataFetcherManager',
    'YfinanceFetcher',
    'LongbridgeFetcher',
    'FinnhubFetcher',
    'AlphaVantageFetcher',
    'is_us_index_code',
    'is_us_stock_code',
    'get_us_index_yf_symbol',
    'US_INDEX_MAPPING',
]

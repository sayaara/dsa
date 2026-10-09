# -*- coding: utf-8 -*-
"""
===================================
US index and stock code utilities
===================================

Provides:
1. US index code mapping (for example SPX -> ^GSPC)
2. US stock code recognition (AAPL, TSLA and so on)

US indices require a ^ prefix in Yahoo Finance, unlike stock codes.
"""

import re

from src.services.market_symbol_utils import get_suffix_market, unsupported_exchange_suffix

# US code regex: 1-5 uppercase letters with an optional .X suffix (such as BRK.B)
# A share class is written with a dot (BRK.B, the app's form) or a dash (BRK-B, Yahoo's form).
_US_STOCK_PATTERN = re.compile(r'^[A-Z]{1,5}([.-][A-Z])?$')


# User input -> (Yahoo Finance symbol, display name)
US_INDEX_MAPPING = {
    # S&P 500
    'SPX': ('^GSPC', 'S&P 500'),
    '^GSPC': ('^GSPC', 'S&P 500'),
    'GSPC': ('^GSPC', 'S&P 500'),
    # Dow Jones Industrial Average
    'DJI': ('^DJI', 'Dow Jones Industrial Average'),
    '^DJI': ('^DJI', 'Dow Jones Industrial Average'),
    'DJIA': ('^DJI', 'Dow Jones Industrial Average'),
    # Nasdaq Composite
    'IXIC': ('^IXIC', 'Nasdaq Composite'),
    '^IXIC': ('^IXIC', 'Nasdaq Composite'),
    'NASDAQ': ('^IXIC', 'Nasdaq Composite'),
    # Nasdaq 100
    'NDX': ('^NDX', 'Nasdaq 100'),
    '^NDX': ('^NDX', 'Nasdaq 100'),
    # VIX volatility index
    'VIX': ('^VIX', 'CBOE Volatility Index (VIX)'),
    '^VIX': ('^VIX', 'CBOE Volatility Index (VIX)'),
    # Russell 2000
    'RUT': ('^RUT', 'Russell 2000'),
    '^RUT': ('^RUT', 'Russell 2000'),
}


def is_us_index_code(code: str) -> bool:
    """
    Decide whether the code is a US index symbol.

    Args:
        code: a stock or index code, such as 'SPX' or 'DJI'

    Returns:
        True when it is a known US index symbol, otherwise False

    Examples:
        >>> is_us_index_code('SPX')
        True
        >>> is_us_index_code('AAPL')
        False
    """
    return (code or '').strip().upper() in US_INDEX_MAPPING


def is_us_stock_code(code: str) -> bool:
    """
    Decide whether the code is a US stock symbol (excluding US indices).

    A US stock code is 1-5 uppercase letters with an optional share class such as BRK.B or BRK-B.
    US indices (SPX, DJI and so on) are explicitly excluded.

    Args:
        code: a stock code, such as 'AAPL', 'TSLA' or 'BRK.B'

    Returns:
        True when it is a US stock symbol, otherwise False

    Examples:
        >>> is_us_stock_code('AAPL')
        True
        >>> is_us_stock_code('TSLA')
        True
        >>> is_us_stock_code('BRK.B')
        True
        >>> is_us_stock_code('SPX')
        False
        >>> is_us_stock_code('600519')
        False
    """
    normalized = (code or '').strip().upper()
    # A US index is not a stock
    if normalized in US_INDEX_MAPPING:
        return False
    # Registered suffix markets (for example ``ABX.V`` on TSX Venture) look like a US
    # dotted share class but belong to their own market.
    if get_suffix_market(normalized) is not None:
        return False
    # So do foreign exchange suffixes (``VOD.L`` on London, ``BMW.F`` on Frankfurt).
    if unsupported_exchange_suffix(normalized) is not None:
        return False
    return bool(_US_STOCK_PATTERN.match(normalized))


def get_us_index_yf_symbol(code: str) -> tuple:
    """
    Get the Yahoo Finance symbol and display name of a US index.

    Args:
        code: the user input, such as 'SPX', '^GSPC' or 'DJI'

    Returns:
        A (yf_symbol, display_name) tuple, or (None, None) when not found.

    Examples:
        >>> get_us_index_yf_symbol('SPX')
        ('^GSPC', 'S&P 500')
        >>> get_us_index_yf_symbol('AAPL')
        (None, None)
    """
    normalized = (code or '').strip().upper()
    return US_INDEX_MAPPING.get(normalized, (None, None))

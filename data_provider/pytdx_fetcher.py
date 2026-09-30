# -*- coding: utf-8 -*-
"""
===================================
PytdxFetcher - Tongdaxin data source (Priority 2)
===================================

Data source: Tongdaxin quote servers (the pytdx library)
Strengths: free, no token required, direct connection to the quote servers
Benefits: real-time data, stable, no quota limits

Key strategies:
1. Automatic failover across multiple servers
2. Automatic reconnect on connection timeout
3. Retry with exponential backoff on failure
"""

import logging
import re
import time
from contextlib import contextmanager
from typing import Optional, Generator, List, Tuple

import pandas as pd
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
    before_sleep_log,
)

from .base import (
    BaseFetcher,
    DataFetchError,
    DataSourceUnavailableError,
    STANDARD_COLUMNS,
    is_bse_code,
    normalize_stock_code,
    _is_hk_market,
)
import os

logger = logging.getLogger(__name__)

_PYTDX_CONNECTION_COOLDOWN_SECONDS = 15.0


def _parse_hosts_from_env() -> Optional[List[Tuple[str, int]]]:
    """
    Build the Tongdaxin server list from environment variables.

    Priority order:
    1. PYTDX_SERVERS: comma-separated "ip:port,ip:port" (e.g. "192.168.1.1:7709,10.0.0.1:7709")
    2. PYTDX_HOST + PYTDX_PORT: a single server
    3. None when neither is configured (the caller then uses DEFAULT_HOSTS)
    """
    servers = os.getenv("PYTDX_SERVERS", "").strip()
    if servers:
        result = []
        for part in servers.split(","):
            part = part.strip()
            if ":" in part:
                host, port_str = part.rsplit(":", 1)
                host, port_str = host.strip(), port_str.strip()
                if host and port_str:
                    try:
                        result.append((host, int(port_str)))
                    except ValueError:
                        logger.warning(f"Invalid PYTDX_SERVERS entry: {part}")
            else:
                logger.warning(f"Invalid PYTDX_SERVERS entry (missing port): {part}")
        if result:
            return result

    host = os.getenv("PYTDX_HOST", "").strip()
    port_str = os.getenv("PYTDX_PORT", "").strip()
    if host and port_str:
        try:
            return [(host, int(port_str))]
        except ValueError:
            logger.warning(f"Invalid PYTDX_HOST/PYTDX_PORT: {host}:{port_str}")

    return None


def _is_us_code(stock_code: str) -> bool:
    """
    Decide whether a code is a US-equity code
    
    US ticker rules:
    - 1-5 uppercase letters, e.g. 'AAPL', 'TSLA'
    - May contain '.', e.g. 'BRK.B'
    """
    code = stock_code.strip().upper()
    return bool(re.match(r'^[A-Z]{1,5}(\.[A-Z])?$', code))


class PytdxFetcher(BaseFetcher):
    """
    Tongdaxin data source implementation
    
    Priority: 2 (same tier as Tushare)
    Data source: Tongdaxin quote servers
    
    Key strategies:
    - Automatically pick the best server
    - Switch servers automatically when a connection fails
    - Retry with exponential backoff on failure
    
    Pytdx characteristics:
    - Free, no registration required
    - Connects directly to the quote servers
    - Supports both real-time quotes and historical data
    - Supports stock name lookup
    """
    
    name = "PytdxFetcher"
    priority = int(os.getenv("PYTDX_PRIORITY", "2"))
    
    # Default Tongdaxin quote server list
    DEFAULT_HOSTS = [
        ("119.147.212.81", 7709),  # Shenzhen
        ("112.74.214.43", 7727),   # Shenzhen
        ("221.231.141.60", 7709),  # Shanghai
        ("101.227.73.20", 7709),   # Shanghai
        ("101.227.77.254", 7709),  # Shanghai
        ("14.215.128.18", 7709),   # Guangzhou
        ("59.173.18.140", 7709),   # Wuhan
        ("180.153.39.51", 7709),   # Hangzhou
    ]
    # Pytdx get_security_list returns at most 1000 items per page
    SECURITY_LIST_PAGE_SIZE = 1000
    
    def __init__(self, hosts: Optional[List[Tuple[str, int]]] = None):
        """
        Initialise PytdxFetcher

        Args:
            hosts: server list [(host, port), ...]. When omitted, the environment
                   variables PYTDX_SERVERS (ip:port,ip:port) or PYTDX_HOST+PYTDX_PORT
                   take precedence; otherwise the built-in DEFAULT_HOSTS is used.
        """
        if hosts is not None:
            self._hosts = hosts
        else:
            env_hosts = _parse_hosts_from_env()
            self._hosts = env_hosts if env_hosts else self.DEFAULT_HOSTS
        self._api = None
        self._connected = False
        self._current_host_idx = 0
        self._stock_list_cache = None  # stock list cache
        self._stock_name_cache = {}    # stock name cache {code: name}
        self._unavailable_until = 0.0
        self._last_unavailable_reason = ""

    def _is_in_connection_cooldown(self) -> bool:
        return time.time() < self._unavailable_until

    def _mark_connection_cooldown(self, reason: str) -> None:
        self._unavailable_until = time.time() + _PYTDX_CONNECTION_COOLDOWN_SECONDS
        self._last_unavailable_reason = str(reason or "").strip()
        logger.info(
            "Pytdx connection failed, entering cooldown %.0fs: %s",
            _PYTDX_CONNECTION_COOLDOWN_SECONDS,
            self._last_unavailable_reason or "unknown",
        )

    def is_available_for_request(self, capability: str = "") -> bool:
        return not self._is_in_connection_cooldown()
    
    def _get_pytdx(self):
        """
        Load the pytdx module lazily
        
        Imported only on first use, so a missing install does not break import
        """
        try:
            from pytdx.hq import TdxHq_API
            return TdxHq_API
        except ImportError:
            logger.warning("pytdx not installed, run: pip install pytdx")
            return None
    
    @contextmanager
    def _pytdx_session(self) -> Generator:
        """
        Pytdx connection context manager
        
        Guarantees:
        1. Automatic connect on entering the context
        2. Automatic disconnect on leaving the context
        3. A correct disconnect even when an exception is raised
        
        Example:
            with self._pytdx_session() as api:
                # run data queries here
        """
        if self._is_in_connection_cooldown():
            raise DataSourceUnavailableError(
                f"Pytdx temporarily unavailable: {self._last_unavailable_reason or 'connection cooldown'}"
            )

        TdxHq_API = self._get_pytdx()
        if TdxHq_API is None:
            raise DataFetchError("pytdx 库未安装")
        
        api = TdxHq_API()
        connected = False
        
        try:
            # Try to connect (the best server is picked automatically)
            for i in range(len(self._hosts)):
                host_idx = (self._current_host_idx + i) % len(self._hosts)
                host, port = self._hosts[host_idx]
                
                try:
                    if api.connect(host, port, time_out=5):
                        connected = True
                        self._current_host_idx = host_idx
                        logger.debug(f"Pytdx connected: {host}:{port}")
                        break
                except Exception as e:
                    logger.debug(f"Pytdx connect {host}:{port} failed: {e}")
                    continue
            
            if not connected:
                self._mark_connection_cooldown("Pytdx 无法连接任何服务器")
                raise DataFetchError("Pytdx 无法连接任何服务器")
            
            yield api
            
        finally:
            # Make sure the connection is closed
            try:
                api.disconnect()
                logger.debug("Pytdx connection closed")
            except Exception as e:
                logger.warning(f"Pytdx error while disconnecting: {e}")
    
    def _get_market_code(self, stock_code: str) -> Tuple[int, str]:
        """
        Determine the market from the stock code
        
        Pytdx market codes:
        - 0: Shenzhen
        - 1: Shanghai
        
        Args:
            stock_code: stock code
            
        Returns:
            A (market, code) tuple
        """
        raw_code = stock_code.strip()
        upper = raw_code.upper()
        prefix, separator, suffix = raw_code.partition(".")
        if separator and prefix:
            prefix_upper = prefix.strip().upper()
            if prefix_upper in ('SH', 'SS'):
                normalized = normalize_stock_code(suffix.strip())
                if normalized.isdigit() and len(normalized) == 6:
                    return 1, normalized
            if prefix_upper == 'SZ':
                normalized = normalize_stock_code(suffix.strip())
                if normalized.isdigit() and len(normalized) == 6:
                    return 0, normalized

        code = normalize_stock_code(raw_code)

        if upper.startswith(('SH', 'SS')) or upper.endswith(('.SH', '.SS')):
            return 1, code
        if upper.startswith('SZ') or upper.endswith('.SZ'):
            return 0, code
        
        # Infer the exchange from the code prefix
        # Shanghai: 60xxxx, 68xxxx (STAR Market)
        # Shenzhen: 00xxxx, 30xxxx (ChiNext), 002xxx (SME board)
        if code.startswith(('60', '68')):
            return 1, code  # Shanghai
        else:
            return 0, code  # Shenzhen

    def _build_stock_list_cache(self, api) -> None:
        """
        Build a full stock code -> name cache from paginated security lists.
        """
        self._stock_list_cache = {}

        for market in (0, 1):
            start = 0
            while True:
                stocks = api.get_security_list(market, start) or []
                for stock in stocks:
                    code = stock.get('code')
                    name = stock.get('name')
                    if code and name:
                        self._stock_list_cache[code] = name

                if len(stocks) < self.SECURITY_LIST_PAGE_SIZE:
                    break

                start += self.SECURITY_LIST_PAGE_SIZE
    
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=30),
        retry=retry_if_exception_type((ConnectionError, TimeoutError)),
        before_sleep=before_sleep_log(logger, logging.WARNING),
    )
    def _fetch_raw_data(self, stock_code: str, start_date: str, end_date: str) -> pd.DataFrame:
        """
        Fetch raw data from Tongdaxin
        
        Uses get_security_bars() to fetch daily bars
        
        Flow:
        1. Reject US tickers (unsupported)
        2. Manage the connection with the context manager
        3. Resolve the market code
        4. Call the API to fetch candlestick data
        """
        # US equities are unsupported; raise so DataFetcherManager switches to another source
        if _is_us_code(stock_code):
            raise DataFetchError(f"PytdxFetcher 不支持美股 {stock_code}，请使用 AkshareFetcher 或 YfinanceFetcher")

        # HK equities are unsupported; raise so DataFetcherManager switches to another source
        if _is_hk_market(stock_code):
            raise DataFetchError(f"PytdxFetcher 不支持港股 {stock_code}，请使用 AkshareFetcher")

        # BSE-listed stocks are unsupported; raise so DataFetcherManager switches to another source
        if is_bse_code(stock_code):
            raise DataFetchError(
                f"PytdxFetcher 不支持北交所 {stock_code}，将自动切换其他数据源"
            )
        
        market, code = self._get_market_code(stock_code)
        
        # Estimate how many trading days need to be fetched
        from datetime import datetime as dt
        start_dt = dt.strptime(start_date, '%Y-%m-%d')
        end_dt = dt.strptime(end_date, '%Y-%m-%d')
        days = (end_dt - start_dt).days
        count = min(max(days * 5 // 7 + 10, 30), 800)  # estimated trading days, capped at 800
        
        logger.debug(f"calling Pytdx get_security_bars(market={market}, code={code}, count={count})")
        
        with self._pytdx_session() as api:
            try:
                # Fetch daily candlesticks
                # category: 9 = daily, 0 = 5min, 1 = 15min, 2 = 30min, 3 = 1 hour
                data = api.get_security_bars(
                    category=9,  # daily bars
                    market=market,
                    code=code,
                    start=0,  # start from the most recent bar
                    count=count
                )
                
                if data is None or len(data) == 0:
                    raise DataFetchError(f"Pytdx 未查询到 {stock_code} 的数据")
                
                # Convert to a DataFrame
                df = api.to_df(data)
                
                # Filter by date range
                df['datetime'] = pd.to_datetime(df['datetime'])
                df = df[(df['datetime'] >= start_date) & (df['datetime'] <= end_date)]
                
                return df
                
            except Exception as e:
                if isinstance(e, DataFetchError):
                    raise
                raise DataFetchError(f"Pytdx 获取数据失败: {e}") from e
    
    def _normalize_data(self, df: pd.DataFrame, stock_code: str) -> pd.DataFrame:
        """
        Normalise Pytdx data
        
        Column names returned by Pytdx:
        datetime, open, high, low, close, vol, amount
        
        Mapped onto the standard column names:
        date, open, high, low, close, volume, amount, pct_chg
        """
        df = df.copy()
        
        # Column mapping
        column_mapping = {
            'datetime': 'date',
            'vol': 'volume',
        }
        
        df = df.rename(columns=column_mapping)
        
        # Compute the percentage change (pytdx does not return it)
        if 'pct_chg' not in df.columns and 'close' in df.columns:
            df['pct_chg'] = df['close'].pct_change() * 100
            df['pct_chg'] = df['pct_chg'].fillna(0).round(2)
        
        # Add the stock code column
        df['code'] = stock_code
        
        # Keep only the columns we need
        keep_cols = ['code'] + STANDARD_COLUMNS
        existing_cols = [col for col in keep_cols if col in df.columns]
        df = df[existing_cols]
        
        return df
    
    def get_stock_name(self, stock_code: str) -> Optional[str]:
        """
        Fetch the stock name
        
        Args:
            stock_code: stock code
            
        Returns:
            The stock name, or None on failure
        """
        # HK equities are unsupported (pytdx carries no HK data)
        if _is_hk_market(stock_code):
            return None

        # Check the cache first
        if stock_code in self._stock_name_cache:
            return self._stock_name_cache[stock_code]
        
        try:
            market, code = self._get_market_code(stock_code)
            
            with self._pytdx_session() as api:
                # Fetch the stock list (cached)
                if self._stock_list_cache is None:
                    self._build_stock_list_cache(api)
                
                # Look up the stock name
                name = self._stock_list_cache.get(code)
                if name:
                    self._stock_name_cache[stock_code] = name
                    return name
                
                # Fall back to get_finance_info
                finance_info = api.get_finance_info(market, code)
                if finance_info and 'name' in finance_info:
                    name = finance_info['name']
                    self._stock_name_cache[stock_code] = name
                    return name
                
        except Exception as e:
            logger.debug(f"Pytdx fetching the stock name failed {stock_code}: {e}")
        
        return None
    
    def get_realtime_quote(self, stock_code: str) -> Optional[dict]:
        """
        Fetch the real-time quote
        
        Args:
            stock_code: stock code
            
        Returns:
            A real-time quote dict, or None on failure
        """
        if is_bse_code(stock_code):
            raise DataFetchError(
                f"PytdxFetcher 不支持北交所 {stock_code}，将自动切换其他数据源"
            )
        try:
            market, code = self._get_market_code(stock_code)
            
            with self._pytdx_session() as api:
                data = api.get_security_quotes([(market, code)])
                
                if data and len(data) > 0:
                    quote = data[0]
                    return {
                        'code': stock_code,
                        'name': quote.get('name', ''),
                        'price': quote.get('price', 0),
                        'open': quote.get('open', 0),
                        'high': quote.get('high', 0),
                        'low': quote.get('low', 0),
                        'pre_close': quote.get('last_close', 0),
                        'volume': quote.get('vol', 0),
                        'amount': quote.get('amount', 0),
                        'bid_prices': [quote.get(f'bid{i}', 0) for i in range(1, 6)],
                        'ask_prices': [quote.get(f'ask{i}', 0) for i in range(1, 6)],
                    }
        except Exception as e:
            logger.warning(f"Pytdx fetching realtime quote failed {stock_code}: {e}")
        
        return None


if __name__ == "__main__":
    # Manual test harness
    logging.basicConfig(level=logging.DEBUG)
    
    fetcher = PytdxFetcher()
    
    try:
        # Test historical data
        df = fetcher.get_daily_data('600519')  # 茅台
        print(f"获取成功，共 {len(df)} 条数据")
        print(df.tail())
        
        # Test the stock name lookup
        name = fetcher.get_stock_name('600519')
        print(f"股票名称: {name}")
        
        # Test the real-time quote
        quote = fetcher.get_realtime_quote('600519')
        print(f"实时行情: {quote}")
        
    except Exception as e:
        print(f"获取失败: {e}")

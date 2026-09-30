# -*- coding: utf-8 -*-
"""
===================================
BaostockFetcher - Secondary data source 2 (Priority 3)
===================================

Data source: Baostock
Strengths: free, no token required, but login/logout must be managed
Benefits: stable, no quota limits

Key strategies:
1. Manage the bs.login() / bs.logout() lifecycle
2. Use a context manager to prevent connection leaks
3. Retry with exponential backoff on failure
"""

import logging
import re
from contextlib import contextmanager
from datetime import datetime
from typing import Optional, Generator

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
    STANDARD_COLUMNS,
    is_bse_code,
    normalize_stock_code,
    _is_hk_market,
)
import os

logger = logging.getLogger(__name__)


def _is_us_code(stock_code: str) -> bool:
    """
    Decide whether a code is a US-equity code
    
    US ticker rules:
    - 1-5 uppercase letters, e.g. 'AAPL', 'TSLA'
    - May contain '.', e.g. 'BRK.B'
    """
    code = stock_code.strip().upper()
    return bool(re.match(r'^[A-Z]{1,5}(\.[A-Z])?$', code))


class BaostockFetcher(BaseFetcher):
    """
    Baostock data source implementation
    
    Priority: 3
    Data source: Baostock API
    
    Key strategies:
    - Manage the connection lifecycle with a context manager
    - Log in and out on every request to prevent connection leaks
    - Retry with exponential backoff on failure
    
    Baostock characteristics:
    - Free, no registration required
    - Requires an explicit login/logout
    - Data is updated with a slight delay (T+1)
    """
    
    name = "BaostockFetcher"
    priority = int(os.getenv("BAOSTOCK_PRIORITY", "3"))
    
    def __init__(self):
        """Initialise BaostockFetcher"""
        self._bs_module = None
    
    def _get_baostock(self):
        """
        Load the baostock module lazily
        
        Imported only on first use, so a missing install does not break import
        """
        if self._bs_module is None:
            import baostock as bs
            self._bs_module = bs
        return self._bs_module
    
    @contextmanager
    def _baostock_session(self) -> Generator:
        """
        Baostock connection context manager
        
        Guarantees:
        1. Automatic login on entering the context
        2. Automatic logout on leaving the context
        3. A correct logout even when an exception is raised
        
        Example:
            with self._baostock_session():
                # run data queries here
        """
        bs = self._get_baostock()
        login_result = None
        
        try:
            # Log in to Baostock
            login_result = bs.login()
            
            if login_result.error_code != '0':
                raise DataFetchError(f"Baostock 登录失败: {login_result.error_msg}")
            
            logger.debug("Baostock login succeeded")
            
            yield bs
            
        finally:
            # Ensure logout so the connection is not leaked
            try:
                logout_result = bs.logout()
                if logout_result.error_code == '0':
                    logger.debug("Baostock logout succeeded")
                else:
                    logger.warning(f"Baostock logout error: {logout_result.error_msg}")
            except Exception as e:
                logger.warning(f"Baostock error during logout: {e}")
    
    def _convert_stock_code(self, stock_code: str) -> str:
        """
        Convert a stock code to Baostock format
        
        Format required by Baostock:
        - Shanghai: sh.600519
        - Shenzhen: sz.000001
        
        Args:
            stock_code: raw code, e.g. '600519', '000001'
            
        Returns:
            Baostock-formatted code, e.g. 'sh.600519', 'sz.000001'
        """
        raw_code = stock_code.strip()
        upper = raw_code.upper()

        # HK stocks are not supported by Baostock
        if _is_hk_market(raw_code):
            raise DataFetchError(f"BaostockFetcher 不支持港股 {raw_code}，请使用 AkshareFetcher")

        # Keep tolerating existing lowercase baostock-format input; 6-digit bare codes are still the recommended configuration.
        if raw_code.startswith(('sh.', 'sz.')):
            return raw_code.lower()

        exchange_hint = None
        if upper.startswith(('SH', 'SS')) or upper.endswith(('.SH', '.SS')):
            exchange_hint = 'sh'
        elif upper.startswith('SZ') or upper.endswith('.SZ'):
            exchange_hint = 'sz'

        code = normalize_stock_code(raw_code)

        if exchange_hint in ('sh', 'sz') and code.isdigit() and len(code) == 6:
            return f"{exchange_hint}.{code}"
        
        # ETF: Shanghai ETF (51xx, 52xx, 56xx, 58xx) -> sh; Shenzhen ETF (15xx, 16xx, 18xx) -> sz
        if len(code) == 6:
            if code.startswith(('51', '52', '56', '58')):
                return f"sh.{code}"
            if code.startswith(('15', '16', '18')):
                return f"sz.{code}"

        # Infer the exchange from the code prefix
        if code.startswith(('600', '601', '603', '605', '688')):
            return f"sh.{code}"
        elif code.startswith(('000', '001', '002', '003', '300', '301')):
            return f"sz.{code}"
        else:
            logger.warning(f"cannot determine the market for stock {code}, defaulting to Shenzhen")
            return f"sz.{code}"
    
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=30),
        retry=retry_if_exception_type((ConnectionError, TimeoutError)),
        before_sleep=before_sleep_log(logger, logging.WARNING),
    )
    def _fetch_raw_data(self, stock_code: str, start_date: str, end_date: str) -> pd.DataFrame:
        """
        Fetch raw data from Baostock
        
        Uses query_history_k_data_plus() to fetch daily bars
        
        Flow:
        1. Reject US tickers (unsupported)
        2. Manage the connection with the context manager
        3. Convert the stock code format
        4. Call the query API
        5. Convert the result into a DataFrame
        """
        # US equities are unsupported; raise so DataFetcherManager switches to another source
        if _is_us_code(stock_code):
            raise DataFetchError(f"BaostockFetcher 不支持美股 {stock_code}，请使用 AkshareFetcher 或 YfinanceFetcher")

        # HK equities are unsupported; raise so DataFetcherManager switches to another source
        if _is_hk_market(stock_code):
            raise DataFetchError(f"BaostockFetcher 不支持港股 {stock_code}，请使用 AkshareFetcher")

        # BSE-listed stocks are unsupported; raise so DataFetcherManager switches to another source
        if is_bse_code(stock_code):
            raise DataFetchError(
                f"BaostockFetcher 不支持北交所 {stock_code}，将自动切换其他数据源"
            )
        
        # Convert the code format
        bs_code = self._convert_stock_code(stock_code)
        
        logger.debug(f"calling Baostock query_history_k_data_plus({bs_code}, {start_date}, {end_date})")
        
        with self._baostock_session() as bs:
            try:
                # Query daily bars
                # adjustflag: 1 = back-adjusted, 2 = forward-adjusted, 3 = unadjusted
                rs = bs.query_history_k_data_plus(
                    code=bs_code,
                    fields="date,open,high,low,close,volume,amount,pctChg",
                    start_date=start_date,
                    end_date=end_date,
                    frequency="d",  # daily bars
                    adjustflag="2"  # forward-adjusted
                )
                
                if rs.error_code != '0':
                    raise DataFetchError(f"Baostock 查询失败: {rs.error_msg}")
                
                # Convert to a DataFrame
                data_list = []
                while rs.next():
                    data_list.append(rs.get_row_data())
                
                if not data_list:
                    raise DataFetchError(f"Baostock 未查询到 {stock_code} 的数据")
                
                df = pd.DataFrame(data_list, columns=rs.fields)
                
                return df
                
            except Exception as e:
                if isinstance(e, DataFetchError):
                    raise
                raise DataFetchError(f"Baostock 获取数据失败: {e}") from e
    
    def _normalize_data(self, df: pd.DataFrame, stock_code: str) -> pd.DataFrame:
        """
        Normalise Baostock data
        
        Column names returned by Baostock:
        date, open, high, low, close, volume, amount, pctChg
        
        Mapped onto the standard column names:
        date, open, high, low, close, volume, amount, pct_chg
        """
        df = df.copy()
        
        # Column mapping (only pctChg needs handling)
        column_mapping = {
            'pctChg': 'pct_chg',
        }
        
        df = df.rename(columns=column_mapping)
        
        # Numeric conversion (Baostock returns everything as strings)
        numeric_cols = ['open', 'high', 'low', 'close', 'volume', 'amount', 'pct_chg']
        for col in numeric_cols:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors='coerce')
        
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
        
        Uses the Baostock query_stock_basic endpoint to fetch basic stock info
        
        Args:
            stock_code: stock code
            
        Returns:
            The stock name, or None on failure
        """
        # Check the cache
        if hasattr(self, '_stock_name_cache') and stock_code in self._stock_name_cache:
            return self._stock_name_cache[stock_code]
        
        # Initialise the cache
        if not hasattr(self, '_stock_name_cache'):
            self._stock_name_cache = {}
        
        try:
            bs_code = self._convert_stock_code(stock_code)
            
            with self._baostock_session() as bs:
                # Query basic stock info
                rs = bs.query_stock_basic(code=bs_code)
                
                if rs.error_code == '0':
                    data_list = []
                    while rs.next():
                        data_list.append(rs.get_row_data())
                    
                    if data_list:
                        # Fields returned by Baostock: code, code_name, ipoDate, outDate, type, status
                        fields = rs.fields
                        name_idx = fields.index('code_name') if 'code_name' in fields else None
                        if name_idx is not None and len(data_list[0]) > name_idx:
                            name = data_list[0][name_idx]
                            self._stock_name_cache[stock_code] = name
                            logger.debug(f"Baostock stock name fetched: {stock_code} -> {name}")
                            return name
                
        except Exception as e:
            logger.warning(f"Baostock fetching the stock name failed {stock_code}: {e}")
        
        return None
    
    def get_stock_list(self) -> Optional[pd.DataFrame]:
        """
        Fetch the stock list
        
        Uses the Baostock query_stock_basic endpoint to fetch the full stock list
        
        Returns:
            A DataFrame with code and name columns, or None on failure
        """
        try:
            with self._baostock_session() as bs:
                # Query basic info for every stock
                rs = bs.query_stock_basic()
                
                if rs.error_code == '0':
                    data_list = []
                    while rs.next():
                        data_list.append(rs.get_row_data())
                    
                    if data_list:
                        df = pd.DataFrame(data_list, columns=rs.fields)
                        
                        # Convert the code format (strip the sh. or sz. prefix)
                        df['code'] = df['code'].apply(lambda x: x.split('.')[1] if '.' in x else x)
                        df = df.rename(columns={'code_name': 'name'})
                        
                        # Update the cache
                        if not hasattr(self, '_stock_name_cache'):
                            self._stock_name_cache = {}
                        for _, row in df.iterrows():
                            self._stock_name_cache[row['code']] = row['name']
                        
                        logger.info(f"Baostock stock list fetched: {len(df)} rows")
                        return df[['code', 'name']]
                
        except Exception as e:
            logger.warning(f"Baostock fetching the stock list failed: {e}")
        
        return None


if __name__ == "__main__":
    # Manual test harness
    logging.basicConfig(level=logging.DEBUG)
    
    fetcher = BaostockFetcher()
    
    try:
        # Test historical data
        df = fetcher.get_daily_data('600519')  # 茅台
        print(f"获取成功，共 {len(df)} 条数据")
        print(df.tail())
        
        # Test the stock name lookup
        name = fetcher.get_stock_name('600519')
        print(f"股票名称: {name}")
        
    except Exception as e:
        print(f"获取失败: {e}")

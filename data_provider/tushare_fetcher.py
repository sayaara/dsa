# -*- coding: utf-8 -*-
"""
===================================
TushareFetcher - Secondary data source 1 (Priority 2)
===================================

Data source: Tushare Pro API
Constraints: requires a token and is subject to request quotas
Benefits: high data quality, stable endpoints

Flow-control strategy:
1. Maintain a per-minute call counter
2. Sleep until the next minute once the free quota (80 calls/min) is exhausted
3. Retry with exponential backoff via tenacity
"""

import json as _json
import logging
import re
import time
from datetime import datetime, timedelta
from typing import Optional, Tuple, List, Dict, Any

import pandas as pd
import requests
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
    before_sleep_log,
)

from .base import BaseFetcher, DataFetchError, RateLimitError, STANDARD_COLUMNS,is_bse_code, is_st_stock, is_kc_cy_stock, normalize_stock_code, _is_hk_market
from .realtime_types import UnifiedRealtimeQuote, ChipDistribution
from src.config import get_config
import os
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)


# ETF code prefixes by exchange
# Shanghai: 51xxxx, 52xxxx, 56xxxx, 58xxxx
# Shenzhen: 15xxxx, 16xxxx, 18xxxx
_ETF_SH_PREFIXES = ('51', '52', '56', '58')
_ETF_SZ_PREFIXES = ('15', '16', '18')
_ETF_ALL_PREFIXES = _ETF_SH_PREFIXES + _ETF_SZ_PREFIXES


def _is_etf_code(stock_code: str) -> bool:
    """
    Check if the code is an ETF fund code.

    ETF code ranges:
    - Shanghai ETF: 51xxxx, 52xxxx, 56xxxx, 58xxxx
    - Shenzhen ETF: 15xxxx, 16xxxx, 18xxxx
    """
    code = normalize_stock_code(stock_code)
    return code.startswith(_ETF_ALL_PREFIXES) and len(code) == 6


def _is_us_code(stock_code: str) -> bool:
    """
    Decide whether a code is a US-equity code
    
    US ticker rules:
    - 1-5 uppercase letters, e.g. 'AAPL', 'TSLA'
    - May contain '.', e.g. 'BRK.B'
    """
    code = stock_code.strip().upper()
    return bool(re.match(r'^[A-Z]{1,5}(\.[A-Z])?$', code))


def _resolve_tushare_http_url() -> Optional[str]:
    """Read the ``TUSHARE_HTTP_URL`` environment variable and validate it.

    - Empty / whitespace-only / unset -> return ``None`` so the caller keeps the official default endpoint.
    - When set, it is returned stripped and must start with ``http://`` or ``https://``,
      which stops a bare host name (e.g. ``api.tushare.pro``) being mistaken by
      ``requests`` for a relative path and failing the request.
    """
    raw = os.getenv("TUSHARE_HTTP_URL")
    if not raw:
        return None
    url = raw.strip()
    if not url:
        return None
    if not (url.startswith("http://") or url.startswith("https://")):
        raise ValueError(
            "TUSHARE_HTTP_URL 必须以 http:// 或 https:// 开头，"
            f"当前值为 {url!r}"
        )
    return url


class _TushareHttpClient:
    """Lightweight Tushare Pro client that does not require the tushare SDK."""

    def __init__(self, token: str, timeout: int = 30, api_url: str = "http://api.tushare.pro") -> None:
        self._token = token
        self._timeout = timeout
        self._api_url = api_url

    def query(self, api_name: str, fields: str = "", **kwargs) -> pd.DataFrame:
        req_params = {
            "api_name": api_name,
            "token": self._token,
            "params": kwargs,
            "fields": fields,
        }
        res = requests.post(self._api_url, json=req_params, timeout=self._timeout)
        if res.status_code != 200:
            raise Exception(f"Tushare API HTTP {res.status_code}")

        result = _json.loads(res.text)
        if result.get("code") != 0:
            raise Exception(result.get("msg") or f"Tushare API error code {result.get('code')}")

        data = result.get("data") or {}
        columns = data.get("fields") or []
        items = data.get("items") or []
        return pd.DataFrame(items, columns=columns)

    def __getattr__(self, api_name: str):
        if api_name.startswith("_"):
            raise AttributeError(api_name)

        def caller(**kwargs) -> pd.DataFrame:
            return self.query(api_name, **kwargs)

        return caller


class TushareFetcher(BaseFetcher):
    """
    Tushare Pro data source implementation
    
    Priority: 2
    Data source: Tushare Pro API
    
    Key strategies:
    - A per-minute call counter that keeps requests inside the quota
    - Forced wait once 80 calls/minute is reached
    - Retry with exponential backoff on failure
    
    Quotas (Tushare free tier):
    - At most 80 requests per minute
    - At most 500 requests per day
    """
    
    name = "TushareFetcher"
    priority = int(os.getenv("TUSHARE_PRIORITY", "2"))  # default priority; adjusted dynamically from config in __init__

    def __init__(self, rate_limit_per_minute: int = 80):
        """
        Initialise TushareFetcher

        Args:
            rate_limit_per_minute: maximum requests per minute (default 80, the Tushare free quota)
        """
        self.rate_limit_per_minute = rate_limit_per_minute
        self._call_count = 0  # calls made in the current minute
        self._minute_start: Optional[float] = None  # start of the current counting window
        self._api: Optional[object] = None  # Tushare API instance
        self.date_list: Optional[List[str]] = None  # trading-day cache (newest first)
        self._date_list_end: Optional[str] = None  # cut-off date the cache was built for, used to refresh across days

        # Try to initialise the API
        self._init_api()

        # Adjust the priority dynamically from the API initialisation result
        self.priority = self._determine_priority()
    
    def _init_api(self) -> None:
        """
        Initialise the Tushare API

        The data source is unavailable when no token is configured.
        The built-in HTTP client is used directly to avoid a hard runtime dependency on the
        tushare SDK, which cuts initialisation failures caused by a missing package under Docker / PyInstaller / multiple virtualenvs.
        """
        config = get_config()

        if not config.tushare_token:
            logger.warning("Tushare Token 未配置，此数据源不可用")
            return

        try:
            self._api = self._build_api_client(config.tushare_token)
            logger.info("Tushare API 初始化成功")
        except Exception as e:
            logger.error(f"Tushare API 初始化失败: {e}")
            self._api = None

    def _build_api_client(self, token: str) -> _TushareHttpClient:
        """
        Build a lightweight Tushare Pro client over direct HTTP requests.

        The project already normalizes all Pro calls through the same request
        contract, so we do not need the official tushare SDK during runtime.

        ``TUSHARE_HTTP_URL`` can point requests at a self-hosted or third-party compatible
        endpoint, which helps when ``api.tushare.pro`` is not directly reachable.
        Leaving it empty or unset keeps the official default endpoint and behaves exactly as before.
        """
        api_url = _resolve_tushare_http_url()
        if api_url:
            logger.info("Tushare 使用自定义接入地址: %s", api_url)
            client = _TushareHttpClient(token=token, api_url=api_url)
        else:
            client = _TushareHttpClient(token=token)
        logger.debug("Tushare API client configured for direct HTTP calls")
        return client

    def _determine_priority(self) -> int:
        """
        Determine the priority from the token configuration and API initialisation state

        Strategy:
        - Token configured and API initialised: priority -1 (absolute highest, ahead of efinance)
        - Otherwise: priority 2 (the default)

        Returns:
            The priority number (0 = highest; larger numbers rank lower)
        """
        config = get_config()

        if config.tushare_token and self._api is not None:
            # Token configured and API initialised, so promote to the highest priority
            logger.info("✅ 检测到 TUSHARE_TOKEN 且 API 初始化成功，Tushare 数据源优先级提升为最高 (Priority -1)")
            return -1

        # No token or failed initialisation, so keep the default priority
        return 2

    def is_available(self) -> bool:
        """
        Check whether the data source is available

        Returns:
            True when available, False otherwise
        """
        return self._api is not None

    def _check_rate_limit(self) -> None:
        """
        Check and apply the rate limit
        
        Flow-control strategy:
        1. Check whether a new minute has started
        2. Reset the counter if it has
        3. Sleep when this minute's call count exceeds the limit
        """
        current_time = time.time()
        
        # Check whether the counter needs resetting (a new minute)
        if self._minute_start is None:
            self._minute_start = current_time
            self._call_count = 0
        elif current_time - self._minute_start >= 60:
            # A minute has elapsed, so reset the counter
            self._minute_start = current_time
            self._call_count = 0
            logger.debug("速率限制计数器已重置")
        
        # Check whether the quota has been exceeded
        if self._call_count >= self.rate_limit_per_minute:
            # Work out how long to wait (until the next minute)
            elapsed = current_time - self._minute_start
            sleep_time = max(0, 60 - elapsed) + 1  # +1 second of headroom
            
            logger.warning(
                f"Tushare 达到速率限制 ({self._call_count}/{self.rate_limit_per_minute} 次/分钟)，"
                f"等待 {sleep_time:.1f} 秒..."
            )
            
            time.sleep(sleep_time)
            
            # Reset the counter
            self._minute_start = time.time()
            self._call_count = 0
        
        # Increment the call count
        self._call_count += 1
        logger.debug(f"Tushare 当前分钟调用次数: {self._call_count}/{self.rate_limit_per_minute}")

    def _call_api_with_rate_limit(self, method_name: str, **kwargs) -> pd.DataFrame:
        """Wrap every Tushare API call in the shared rate limiter."""
        if self._api is None:
            raise DataFetchError("Tushare API 未初始化，请检查 Token 配置")

        self._check_rate_limit()
        method = getattr(self._api, method_name)
        return method(**kwargs)

    def _get_china_now(self) -> datetime:
        """Return the current time in the Shanghai time zone so tests can cover the cross-day refresh."""
        return datetime.now(ZoneInfo("Asia/Shanghai"))

    def _get_trade_dates(self, end_date: Optional[str] = None) -> List[str]:
        """Refresh the trading-calendar cache once per calendar day so a long-running service does not reuse a stale calendar."""
        if self._api is None:
            return []

        china_now = self._get_china_now()
        requested_end_date = end_date or china_now.strftime("%Y%m%d")

        if self.date_list is not None and self._date_list_end == requested_end_date:
            return self.date_list

        start_date = (china_now - timedelta(days=20)).strftime("%Y%m%d")
        df_cal = self._call_api_with_rate_limit(
            "trade_cal",
            exchange="SSE",
            start_date=start_date,
            end_date=requested_end_date,
        )

        if df_cal is None or df_cal.empty or "cal_date" not in df_cal.columns:
            logger.warning("[Tushare] trade_cal 返回为空，无法更新交易日历缓存")
            self.date_list = []
            self._date_list_end = requested_end_date
            return self.date_list

        trade_dates = sorted(
            df_cal[df_cal["is_open"] == 1]["cal_date"].astype(str).tolist(),
            reverse=True,
        )
        self.date_list = trade_dates
        self._date_list_end = requested_end_date
        return trade_dates

    @staticmethod
    def _pick_trade_date(trade_dates: List[str], use_today: bool) -> Optional[str]:
        """Pick today or the previous trading day from the available trading-day list."""
        if not trade_dates:
            return None
        if use_today or len(trade_dates) == 1:
            return trade_dates[0]
        return trade_dates[1]

    @staticmethod
    def _detect_exchange_hint(stock_code: str) -> Optional[str]:
        """Return SH/SZ/BJ when the raw user input carries an explicit exchange hint."""
        upper = (stock_code or "").strip().upper()
        if upper.startswith(("SH", "SS")) or upper.endswith((".SH", ".SS")):
            return "SH"
        if upper.startswith("SZ") or upper.endswith(".SZ"):
            return "SZ"
        if upper.startswith("BJ") or upper.endswith(".BJ"):
            return "BJ"
        return None

    @classmethod
    def _get_legacy_realtime_symbol(cls, stock_code: str) -> str:
        """Build the legacy tushare symbol while preserving explicit SH/SZ hints."""
        code = normalize_stock_code(stock_code)
        exchange_hint = cls._detect_exchange_hint(stock_code)

        if code == '000001' and exchange_hint == 'SH':
            return 'sh000001'
        if code == '399001':
            return 'sz399001'
        if code == '399006':
            return 'sz399006'
        if code == '000300':
            return 'sh000300'
        if is_bse_code(code):
            return f"bj{code}"
        return code
    
    def _convert_stock_code(self, stock_code: str) -> str:
        """
        Convert A-share / ETF / BSE codes into a Tushare ts_code (HK logic excluded).

        Formats Tushare expects:
        - Shanghai stocks: 600519.SH
        - Shenzhen stocks: 000001.SZ
        - Shanghai ETFs: 510050.SH
        - Shenzhen ETFs: 159919.SZ

        Args:
            stock_code: raw code, e.g. '600519', '000001', '563230'

        Returns:
            The Tushare-formatted code, e.g. '600519.SH', '000001.SZ'
        """
        raw_code = stock_code.strip()
        
        # Already has suffix.
        if '.' in raw_code:
            upper = raw_code.upper()
            code = normalize_stock_code(raw_code)
            exchange_hint = self._detect_exchange_hint(raw_code)
            if exchange_hint in ("SH", "SZ", "BJ") and code.isdigit():
                return f"{code}.{exchange_hint}"

            ts_code = upper
            if ts_code.endswith('.SS'):
                return f"{ts_code[:-3]}.SH"
            return ts_code

        if _is_us_code(raw_code):
            raise DataFetchError(f"TushareFetcher 不支持美股 {raw_code}，请使用 AkshareFetcher 或 YfinanceFetcher")

        if _is_hk_market(raw_code):
            #raise DataFetchError(f"TushareFetcher 不支持港股 {raw_code}，请使用 AkshareFetcher")
            return normalize_stock_code(raw_code)

        code = normalize_stock_code(raw_code)
        exchange_hint = self._detect_exchange_hint(raw_code)

        if exchange_hint == "SH":
            return f"{code}.SH"
        if exchange_hint == "SZ":
            return f"{code}.SZ"
        if exchange_hint == "BJ":
            return f"{code}.BJ"

        # ETF: determine exchange by prefix
        if code.startswith(_ETF_SH_PREFIXES) and len(code) == 6:
            return f"{code}.SH"
        if code.startswith(_ETF_SZ_PREFIXES) and len(code) == 6:
            return f"{code}.SZ"
        
        # BSE (Beijing Stock Exchange): 8xxxxx, 4xxxxx, 920xxx
        if is_bse_code(code):
            return f"{code}.BJ"
        
        # Regular stocks
        # Shanghai: 600xxx, 601xxx, 603xxx, 605xxx, 688xxx (STAR Market)
        # Shenzhen: 000xxx, 001xxx, 002xxx, 003xxx, 300xxx, 301xxx (ChiNext)
        if code.startswith(('600', '601', '603', '605', '688')):
            return f"{code}.SH"
        elif code.startswith(('000', '001', '002', '003', '300', '301')):
            return f"{code}.SZ"
        else:
            logger.warning(f"无法确定股票 {code} 的市场，默认使用深市")
            return f"{code}.SZ"

    def _convert_hk_stock_code_for_tushare(self, stock_code: str) -> str:
        """
        Convert user input into the ts_code the Tushare Pro API expects (including HK nnnnn.HK).

        - Non-HK: delegate to _convert_stock_code (A-shares / ETFs / BSE and so on).
        - HK: normalise HK00700, 00700, 00700.HK and similar into 5 digits + .HK.
        """
        raw_code = stock_code.strip()
        if _is_hk_market(raw_code):
            if "." in raw_code:
                ts_code = raw_code.upper()
                if ts_code.endswith(".SS"):
                    return f"{ts_code[:-3]}.SH"
                if ts_code.endswith(".HK"):
                    return ts_code
            digits = re.sub(r"\D", "", raw_code)
            if not digits:
                raise DataFetchError(f"无法识别港股代码 {raw_code}")
            code = digits[-5:].rjust(5, "0")
            return f"{code}.HK"
        return self._convert_stock_code(stock_code)

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=30),
        retry=retry_if_exception_type((ConnectionError, TimeoutError)),
        before_sleep=before_sleep_log(logger, logging.WARNING),
    )
    def _fetch_raw_data(self, stock_code: str, start_date: str, end_date: str) -> pd.DataFrame:
        """
        Fetch raw data from Tushare
        
        Pick the endpoint by code type:
        - Ordinary stocks: daily()
        - ETFs: fund_daily()
        
        Flow:
        1. Check that the API is available
        2. Reject US tickers (unsupported)
        3. Apply the rate limit
        4. Convert the stock code format
        5. Pick the endpoint by code type and call it
        """
        if self._api is None:
            raise DataFetchError("Tushare API 未初始化，请检查 Token 配置")
        
        # US stocks not supported
        if _is_us_code(stock_code):
            raise DataFetchError(f"TushareFetcher 不支持美股 {stock_code}，请使用 AkshareFetcher 或 YfinanceFetcher")
        
        # Rate-limit check
        self._check_rate_limit()
        
        is_hk = _is_hk_market(stock_code)
         # Decide whether this is an ETF or HK code, to pick the right endpoint
        is_etf = _is_etf_code(stock_code)
        if is_hk:
            ts_code = self._convert_hk_stock_code_for_tushare(stock_code)
            api_name = "hk_daily"
        else:
            ts_code = self._convert_stock_code(stock_code)
            api_name = "fund_daily" if is_etf else "daily"
        
        # Convert date format (Tushare requires YYYYMMDD)
        ts_start = start_date.replace('-', '')
        ts_end = end_date.replace('-', '')
        
       

        logger.debug(f"调用 Tushare {api_name}({ts_code}, {ts_start}, {ts_end})")
        
        try:
            if is_hk:
                # HK stocks use the hk_daily endpoint
                df = self._api.hk_daily(
                    ts_code=ts_code,
                    start_date=ts_start,
                    end_date=ts_end,
                )
            elif is_etf:
                # ETF uses fund_daily interface
                df = self._api.fund_daily(
                    ts_code=ts_code,
                    start_date=ts_start,
                    end_date=ts_end,
                )
            else:
                # Regular A-share stocks use daily interface
                df = self._api.daily(
                    ts_code=ts_code,
                    start_date=ts_start,
                    end_date=ts_end,
                )
            
            return df
            
        except Exception as e:
            error_msg = str(e).lower()
            
            # Detect a quota overrun
            if any(keyword in error_msg for keyword in ['quota', '配额', 'limit', '权限']):
                logger.warning(f"Tushare 配额可能超限: {e}")
                raise RateLimitError(f"Tushare 配额超限: {e}") from e
            
            raise DataFetchError(f"Tushare 获取数据失败: {e}") from e
    
    def _normalize_data(self, df: pd.DataFrame, stock_code: str) -> pd.DataFrame:
        """
        Normalise Tushare data
        
        Column names returned by Tushare daily / fund_daily:
        ts_code, trade_date, open, high, low, close, pre_close, change, pct_chg, vol, amount
        
        Mapped onto the standard column names:
        date, open, high, low, close, volume, amount, pct_chg

        Unit scaling applies to A-shares only (and to ETFs and other endpoints sharing those units):
        - vol is denominated in lots, so multiply by 100 to get shares
        - amount is denominated in thousands of yuan, so multiply by 1000 to get yuan

        The vol / amount returned by hk_daily are already usable as-is, so no scaling is applied.
        """
        df = df.copy()
        is_hk = _is_hk_market(stock_code)

        # Column mapping
        column_mapping = {
            'trade_date': 'date',
            'vol': 'volume',
            # open, high, low, close, amount and pct_chg keep the same names
        }
        
        df = df.rename(columns=column_mapping)
        
        # Convert the date format (YYYYMMDD -> YYYY-MM-DD)
        if 'date' in df.columns:
            df['date'] = pd.to_datetime(df['date'], format='%Y%m%d')
        
        # Volume / turnover: only A-share endpoints need unit conversion (hk_daily does not)
        if 'volume' in df.columns and not is_hk:
            df['volume'] = df['volume'] * 100
        
        if 'amount' in df.columns and not is_hk:
            df['amount'] = df['amount'] * 1000
        
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
        
        Uses the Tushare stock_basic endpoint to fetch basic stock information
        
        Args:
            stock_code: stock code
            
        Returns:
            The stock name, or None on failure
        """
        if self._api is None:
            logger.warning("Tushare API 未初始化，无法获取股票名称")
            return None

        # Check the cache
        if hasattr(self, '_stock_name_cache') and stock_code in self._stock_name_cache:
            return self._stock_name_cache[stock_code]
        
        # Initialise the cache
        if not hasattr(self, '_stock_name_cache'):
            self._stock_name_cache = {}
        
        try:
            # Rate-limit check
            self._check_rate_limit()
            

            # Pick the basic-info endpoint by market and instrument type
            if _is_hk_market(stock_code):
                ts_code = self._convert_hk_stock_code_for_tushare(stock_code)
                # HK stocks: use hk_basic
                df = self._api.hk_basic(
                    ts_code=ts_code,
                    fields='ts_code,name'
                )
            elif _is_etf_code(stock_code):
                ts_code = self._convert_stock_code(stock_code)
                # ETFs: use fund_basic
                df = self._api.fund_basic(
                    ts_code=ts_code,
                    fields='ts_code,name'
                )
            else:
                ts_code = self._convert_stock_code(stock_code)
                # A-share stocks: use stock_basic
                df = self._api.stock_basic(
                    ts_code=ts_code,
                    fields='ts_code,name'
                )
            
            if df is not None and not df.empty:
                name = df.iloc[0]['name']
                self._stock_name_cache[stock_code] = name
                logger.debug(f"Tushare 获取股票名称成功: {stock_code} -> {name}")
                return name
            
        except Exception as e:
            logger.warning(f"Tushare 获取股票名称失败 {stock_code}: {e}")
        
        return None
    
    def get_stock_list(self) -> Optional[pd.DataFrame]:
        """
        Fetch the stock list
        
        Uses the Tushare stock_basic endpoint to fetch the A-share list (HK excluded).
        
        Returns:
            A DataFrame with code, name, industry, area and market columns, or None on failure
        """
        if self._api is None:
            logger.warning("Tushare API 未初始化，无法获取股票列表")
            return None
        
        try:
            self._check_rate_limit()

            df = self._api.stock_basic(
                exchange='',
                list_status='L',
                fields='ts_code,name,industry,area,market'
            )

            if df is None or df.empty:
                return None

            df = df.copy()
            df['code'] = df['ts_code'].astype(str).str.split('.').str[0]

            if not hasattr(self, '_stock_name_cache'):
                self._stock_name_cache = {}
            for _, row in df.iterrows():
                self._stock_name_cache[row['code']] = row['name']

            logger.info(f"Tushare 获取股票列表成功: {len(df)} 条")
            return df[['code', 'name', 'industry', 'area', 'market']]

        except Exception as e:
            logger.warning(f"Tushare 获取股票列表失败: {e}")

        return None
    
    def get_realtime_quote(self, stock_code: str) -> Optional[UnifiedRealtimeQuote]:
        """
        Fetch the real-time quote

        Strategy:
        1. Try the Pro endpoint first (needs 2000 points): richer data, more reliable
        2. Fall back to the legacy endpoint on failure: lower barrier, less data

        Args:
            stock_code: stock code

        Returns:
            A UnifiedRealtimeQuote object, or None on failure
        """
        if self._api is None:
            return None

        # HK stocks not supported by Tushare
        if _is_hk_market(stock_code):
            logger.debug(f"TushareFetcher 跳过港股实时行情 {stock_code}")
            return None

        normalized_code = normalize_stock_code(stock_code)

        from .realtime_types import (
            RealtimeSource,
            safe_float, safe_int
        )

        # Rate-limit check
        self._check_rate_limit()

        # Try the Pro endpoint
        try:
            ts_code = self._convert_stock_code(stock_code)
            # Try the Pro real-time endpoint (requires points)
            df = self._api.quotation(ts_code=ts_code)

            if df is not None and not df.empty:
                row = df.iloc[0]
                logger.debug(f"Tushare Pro 实时行情获取成功: {stock_code}")

                return UnifiedRealtimeQuote(
                    code=normalized_code,
                    name=str(row.get('name', '')),
                    source=RealtimeSource.TUSHARE,
                    price=safe_float(row.get('price')),
                    change_pct=safe_float(row.get('pct_chg')),  # the Pro endpoint usually returns the percentage change directly
                    change_amount=safe_float(row.get('change')),
                    volume=safe_int(row.get('vol')),
                    amount=safe_float(row.get('amount')),
                    high=safe_float(row.get('high')),
                    low=safe_float(row.get('low')),
                    open_price=safe_float(row.get('open')),
                    pre_close=safe_float(row.get('pre_close')),
                    turnover_rate=safe_float(row.get('turnover_ratio')), # the Pro endpoint may carry the turnover rate
                    pe_ratio=safe_float(row.get('pe')),
                    pb_ratio=safe_float(row.get('pb')),
                    total_mv=safe_float(row.get('total_mv')),
                )
        except Exception as e:
            # Log at debug level only, do not raise, and continue to the fallback
            logger.debug(f"Tushare Pro 实时行情不可用 (可能是积分不足): {e}")

        # Fallback: try the legacy endpoint
        try:
            import tushare as ts

            symbol = self._get_legacy_realtime_symbol(stock_code)

            # Call the legacy real-time endpoint (ts.get_realtime_quotes)
            df = ts.get_realtime_quotes(symbol)

            if df is None or df.empty:
                return None

            row = df.iloc[0]

            # Compute the percentage change
            price = safe_float(row['price'])
            pre_close = safe_float(row['pre_close'])
            change_pct = 0.0
            change_amount = 0.0

            if price and pre_close and pre_close > 0:
                change_amount = price - pre_close
                change_pct = (change_amount / pre_close) * 100

            # Build the unified object
            return UnifiedRealtimeQuote(
                code=normalized_code,
                name=str(row['name']),
                source=RealtimeSource.TUSHARE,
                price=price,
                change_pct=round(change_pct, 2),
                change_amount=round(change_amount, 2),
                volume=safe_int(row['volume']) // 100,  # convert to lots
                amount=safe_float(row['amount']),
                high=safe_float(row['high']),
                low=safe_float(row['low']),
                open_price=safe_float(row['open']),
                pre_close=pre_close,
            )

        except Exception as e:
            logger.warning(f"Tushare (旧版) 获取实时行情失败 {stock_code}: {e}")
            return None

    def get_main_indices(self, region: str = "cn") -> Optional[List[dict]]:
        """
        Fetch main index real-time quotes (Tushare Pro); A-shares only
        """
        if region != "cn":
            return None
        if self._api is None:
            return None

        from .realtime_types import safe_float

        # Index mapping: Tushare code -> name
        indices_map = {
            '000001.SH': '上证指数',
            '399001.SZ': '深证成指',
            '399006.SZ': '创业板指',
            '000688.SH': '科创50',
            '000016.SH': '上证50',
            '000300.SH': '沪深300',
        }

        try:
            self._check_rate_limit()

            # Tushare index_daily returns history; real-time data needs another endpoint or an estimate
            # Free Tushare accounts may not be able to read real-time index quotes, so this is the fallback
            # Use index_daily to read the most recent trading day

            end_date = datetime.now().strftime('%Y%m%d')
            start_date = (datetime.now() - pd.Timedelta(days=5)).strftime('%Y%m%d')

            results = []

            # Fetch every index in one pass
            for ts_code, name in indices_map.items():
                try:
                    df = self._api.index_daily(ts_code=ts_code, start_date=start_date, end_date=end_date)
                    if df is not None and not df.empty:
                        row = df.iloc[0] # the latest day

                        current = safe_float(row['close'])
                        prev_close = safe_float(row['pre_close'])

                        results.append({
                            'code': ts_code.split('.')[0], # the sh000001 form needs converting; keep bare digits here
                            'name': name,
                            'current': current,
                            'change': safe_float(row['change']),
                            'change_pct': safe_float(row['pct_chg']),
                            'open': safe_float(row['open']),
                            'high': safe_float(row['high']),
                            'low': safe_float(row['low']),
                            'prev_close': prev_close,
                            'volume': safe_float(row['vol']),
                            'amount': safe_float(row['amount']) * 1000, # thousands of yuan -> yuan
                            'amplitude': 0.0 # Tushare index_daily does not return the amplitude
                        })
                except Exception as e:
                    logger.debug(f"Tushare 获取指数 {name} 失败: {e}")
                    continue

            if results:
                return results
            else:
                logger.warning("[Tushare] 未获取到指数行情数据")

        except Exception as e:
            logger.error(f"[Tushare] 获取指数行情失败: {e}")

        return None

    def get_market_stats(self) -> Optional[dict]:
        """
        Fetch market advance/decline statistics (Tushare Pro)
        2000 points; this endpoint (ts.pro_api().rt_k) may be called twice a day
        Endpoint limits: https://tushare.pro/document/1?doc_id=108
        """
        if self._api is None:
            return None

        try:
            logger.info("[Tushare] ts.pro_api() 获取市场统计...")
            
            # Get the current China time and decide whether the market is open
            china_now = self._get_china_now()
            current_clock = china_now.strftime("%H:%M")
            current_date = china_now.strftime("%Y%m%d")

            trade_dates = self._get_trade_dates(current_date)
            if not trade_dates:
                return None

            if current_date in trade_dates:
                if current_clock < '09:30' or current_clock > '16:30':
                    use_realtime = False
                else:
                    use_realtime = True
            else:
                use_realtime = False

            # For live trading, use a source that can serve live data such as akshare or efinance
            if use_realtime:
                try:
                    df = self._call_api_with_rate_limit("rt_k", ts_code='3*.SZ,6*.SH,0*.SZ,92*.BJ')
                    if df is not None and not df.empty:
                        return self._calc_market_stats(df)
                    
                except Exception as e:
                    logger.error(f"[Tushare] ts.pro_api().rt_k 尝试获取实时数据失败: {e}")
                    return None
            else:

                if current_date not in trade_dates:
                    last_date = self._pick_trade_date(trade_dates, use_today=True)  # take the most recent date
                else:
                    if current_clock < '09:30': 
                        last_date = self._pick_trade_date(trade_dates, use_today=False)  # take the previous day's data
                    else:  # i.e. '> 16:30'
                        last_date = self._pick_trade_date(trade_dates, use_today=True)  # take today's data

                if last_date is None:
                    return None

                try:
                    df = self._call_api_with_rate_limit(
                        "daily",
                        ts_code='3*.SZ,6*.SH,0*.SZ,92*.BJ',
                        start_date=last_date,
                        end_date=last_date,
                    )
                    # Endpoints disagree on column-name case (rt_k returns lowercase, daily uppercase), so lowercase them all
                    df.columns = [col.lower() for col in df.columns]

                    # Fetch basic stock info (code and name)
                    df_basic = self._call_api_with_rate_limit("stock_basic", fields='ts_code,name')
                    df = pd.merge(df, df_basic, on='ts_code', how='left')
                    # Multiply the daily amount column by 1000 to match the other data sources
                    if 'amount' in df.columns:
                        df['amount'] = df['amount'] * 1000

                    if df is not None and not df.empty:
                        return self._calc_market_stats(df)
                except Exception as e:
                    logger.error(f"[Tushare] ts.pro_api().daily 获取数据失败: {e}")
                    

            
        except Exception as e:
            logger.error(f"[Tushare] 获取市场统计失败: {e}")

        return None
    
    def _calc_market_stats(
            self,
            df: pd.DataFrame,
            ) -> Optional[Dict[str, Any]]:
            """Compute advance/decline statistics from a quote DataFrame."""
            import numpy as np

            df = df.copy()
            
            # 1. Extract the comparison inputs: latest price and previous close
            # Tolerate the differing column names returned by sina/em, efinance, tushare and xtdata
            code_col = next((c for c in ['代码', '股票代码', 'ts_code','stock_code'] if c in df.columns), None)
            name_col = next((c for c in ['名称', '股票名称','name','name'] if c in df.columns), None)
            close_col = next((c for c in ['最新价', '最新价', 'close','lastPrice'] if c in df.columns), None)
            pre_close_col = next((c for c in ['昨收', '昨日收盘', 'pre_close','lastClose'] if c in df.columns), None)
            amount_col = next((c for c in ['成交额', '成交额', 'amount','amount'] if c in df.columns), None) 
            
            limit_up_count = 0
            limit_down_count = 0
            up_count = 0
            down_count = 0
            flat_count = 0

            for code, name, current_price, pre_close, amount in zip(
                df[code_col], df[name_col], df[close_col], df[pre_close_col], df[amount_col]
            ):
                
                # Halt filter: efinance sometimes omits the price for halted stocks and shows '-', while em shows none
                if pd.isna(current_price) or pd.isna(pre_close) or current_price in ['-'] or pre_close in ['-'] or amount == 0:
                    continue
                
                # em and efinance return strings, so convert to float
                current_price = float(current_price)
                pre_close = float(pre_close)
                
                # Get the bare numeric code with any prefix stripped
                pure_code = normalize_stock_code(str(code)) 

                # A. Determine each stock's price-limit ratio (using the bare numeric code)
                if is_bse_code(pure_code): 
                    ratio = 0.30
                elif is_kc_cy_stock(pure_code): #pure_code.startswith(('688', '30')):
                    ratio = 0.20
                elif is_st_stock(name): #'ST' in str_name:
                    ratio = 0.05
                else:
                    ratio = 0.10

                # B. Compute the limit-up/limit-down price strictly by A-share rules: previous close * (1 +/- ratio), rounded to 2 decimals
                limit_up_price = np.floor(pre_close * (1 + ratio) * 100 + 0.5) / 100.0
                limit_down_price = np.floor(pre_close * (1 - ratio) * 100 + 0.5) / 100.0

                limit_up_price_Tolerance = round(abs(pre_close * (1 + ratio) - limit_up_price), 10)
                limit_down_price_Tolerance = round(abs(pre_close * (1 - ratio) - limit_down_price), 10)

                # C. Exact comparison
                if current_price > 0 :
                    is_limit_up = (current_price > 0) and (abs(current_price - limit_up_price) <= limit_up_price_Tolerance)
                    is_limit_down = (current_price > 0) and (abs(current_price - limit_down_price) <= limit_down_price_Tolerance)

                    if is_limit_up:
                        limit_up_count += 1
                    if is_limit_down:
                        limit_down_count += 1

                    if current_price > pre_close:
                        up_count += 1
                    elif current_price < pre_close:
                        down_count += 1
                    else:
                        flat_count += 1
                    
            # Count the buckets
            stats = {
                'up_count': up_count,
                'down_count': down_count,
                'flat_count': flat_count,
                'limit_up_count': limit_up_count,
                'limit_down_count': limit_down_count,
                'total_amount': 0.0,
            }
            
            # Turnover statistics
            if amount_col and amount_col in df.columns:
                df[amount_col] = pd.to_numeric(df[amount_col], errors='coerce')
                stats['total_amount'] = (df[amount_col].sum() / 1e8)
                
            return stats

    def get_trade_time(self,early_time='09:30',late_time='16:30') -> Optional[str]:
        '''
        Work out the start date for which data is available at the current time

        Args:
                early_time: defaults to '09:30'
                late_time: defaults to '16:30'
                between early_time and late_time the previous trading day's data is used; outside that window today's data is used
        Returns:
                start_date: the first date for which data is available
        '''
        china_now = self._get_china_now()
        china_date = china_now.strftime("%Y%m%d")
        china_clock = china_now.strftime("%H:%M")

        trade_dates = self._get_trade_dates(china_date)
        if not trade_dates:
            return None

        if china_date in trade_dates:
            if  early_time < china_clock < late_time: # window where the previous trading day's data is used
                use_today = False
            else:
                use_today = True
        else:
            # Non-trading day: today is absent from trade_dates, so trade_dates[0] is the most recent trading day
            use_today = True

        start_date = self._pick_trade_date(trade_dates, use_today=use_today)
        if start_date is None:
            return None

        if not use_today:
            logger.info(f"[Tushare] 当前时间 {china_clock} 可能无法获取当天筹码分布，尝试获取前一个交易日的数据 {start_date}")

        return start_date
    
    def get_sector_rankings(self, n: int = 5) -> Optional[Tuple[list, list]]:
        """
        Fetch the industry-sector advance/decline ranking (Tushare Pro)
        
        Data source priority:
        1. THS endpoint (ts.pro_api().moneyflow_ind_ths)
        2. East Money endpoint (ts.pro_api().moneyflow_ind_dc)
        Note: the two endpoints classify industries and define sectors differently, so their results disagree
        """
        def _get_rank_top_n(df: pd.DataFrame, change_col: str, industry_name: str, n: int) -> Tuple[list, list]:
            df[change_col] = pd.to_numeric(df[change_col], errors='coerce')
            df = df.dropna(subset=[change_col])

            # Top n by gain
            top = df.nlargest(n, change_col)
            top_sectors = [
                {'name': row[industry_name], 'change_pct': row[change_col]}
                for _, row in top.iterrows()
            ]

            bottom = df.nsmallest(n, change_col)
            bottom_sectors = [
                {'name': row[industry_name], 'change_pct': row[change_col]}
                for _, row in bottom.iterrows()
            ]
            return top_sectors, bottom_sectors

        # Today's data only becomes available after 15:30
        start_date = self.get_trade_time(early_time='00:00', late_time='15:30')
        if not start_date:
            return None

        # Prefer the THS endpoint
        logger.info("[Tushare] ts.pro_api().moneyflow_ind_ths 获取板块排行(同花顺)...")
        try:
            df = self._call_api_with_rate_limit("moneyflow_ind_ths", trade_date=start_date)
            if df is not None and not df.empty:
                change_col = 'pct_change'
                name = 'industry'
                if change_col in df.columns:
                    return _get_rank_top_n(df, change_col, name, n)
        except Exception as e:
            logger.warning(f"[Tushare] 获取同花顺行业板块涨跌榜失败: {e} 尝试东财接口")

        # THS endpoint failed, so fall back to the East Money endpoint
        logger.info("[Tushare] ts.pro_api().moneyflow_ind_dc 获取板块排行(东财)...")
        try:
            df = self._call_api_with_rate_limit("moneyflow_ind_dc", trade_date=start_date)
            if df is not None and not df.empty:
                df = df[df['content_type'] == '行业']  # keep only industry sectors
                change_col = 'pct_change'
                name = 'name'
                if change_col in df.columns:
                    return _get_rank_top_n(df, change_col, name, n)
        except Exception as e:
            logger.warning(f"[Tushare] 获取东财行业板块涨跌榜失败: {e}")
            return None
        
        # Empty result or failed call, so return None
        return None
    
    

    
    def get_chip_distribution(self, stock_code: str) -> Optional[ChipDistribution]:
        """
        Fetch chip-distribution data
        
        Data source: ts.pro_api().cyq_chips()
        Includes: profitable ratio, average cost, chip concentration
        
        Note: ETFs and indices have no chip distribution and return None directly; HK stocks are unsupported and also return None.
        Below 5000 points: 15 calls per day, 5 per hour
        
        Args:
            stock_code: stock code
            
        Returns:
            A ChipDistribution object (for the latest trading day), or None on failure

        """
        if _is_us_code(stock_code):
            logger.warning(f"[Tushare] TushareFetcher 不支持美股 {stock_code} 的筹码分布")
            return None
        
        if _is_etf_code(stock_code):
            logger.warning(f"[Tushare] TushareFetcher 不支持 ETF {stock_code} 的筹码分布")
            return None

        if _is_hk_market(stock_code):
            logger.warning(f"[Tushare] TushareFetcher 不支持港股 {stock_code} 的筹码分布")
            return None
        
        try:
            # Today's data only becomes available after 19:00
            start_date = self.get_trade_time(early_time='00:00', late_time='19:00') 
            if not start_date:
                return None

            ts_code = self._convert_stock_code(stock_code)

            df = self._call_api_with_rate_limit(
                "cyq_chips",
                ts_code=ts_code,
                start_date=start_date,
                end_date=start_date,
            )
            if df is not None and not df.empty:
                daily_df = self._call_api_with_rate_limit(
                    "daily",
                    ts_code=ts_code,
                    start_date=start_date,
                    end_date=start_date,
                )
                if daily_df is None or daily_df.empty:
                    return None
                current_price = daily_df.iloc[0]['close']
                metrics = self.compute_cyq_metrics(df, current_price)

                chip = ChipDistribution(
                    code=stock_code,
                    date=datetime.strptime(start_date, '%Y%m%d').strftime('%Y-%m-%d'),
                    profit_ratio=metrics['获利比例'],
                    avg_cost=metrics['平均成本'],
                    cost_90_low=metrics['90成本-低'],
                    cost_90_high=metrics['90成本-高'],
                    concentration_90=metrics['90集中度'],
                    cost_70_low=metrics['70成本-低'],
                    cost_70_high=metrics['70成本-高'],
                    concentration_70=metrics['70集中度'],
                )
                
                logger.info(f"[筹码分布] {stock_code} 日期={chip.date}: 获利比例={chip.profit_ratio:.1%}, "
                        f"平均成本={chip.avg_cost}, 90%集中度={chip.concentration_90:.2%}, "
                        f"70%集中度={chip.concentration_70:.2%}")
                return chip

        except Exception as e:
            logger.warning(f"[Tushare] 获取筹码分布失败 {stock_code}: {e}")
            return None

    def compute_cyq_metrics(self, df: pd.DataFrame, current_price: float) -> dict:
        """
        Compute the common chip metrics from the Tushare chip-distribution detail table (cyq_chips)
        :param df: a DataFrame with 'price' and 'percent' columns
        :param current_price: the stock's current or closing price for the day (used for the profitable ratio)
        :return: a dict of the chip metrics
        """
        import numpy as np
        # 1. Sort by ascending price (Tushare usually returns the rows in reverse order)
        df_sorted = df.sort_values(by='price', ascending=True).reset_index(drop=True)

        # 2. Normalise to 100% so floating-point error in the raw percent sum cannot accumulate
        total_percent = df_sorted['percent'].sum()

        df_sorted['norm_percent'] = df_sorted['percent'] / total_percent * 100

        # 3. Compute the cumulative chip distribution
        df_sorted['cumsum'] = df_sorted['norm_percent'].cumsum()

        # --- Profitable ratio ---
        # Sum of all chips priced at or below the current price
        winner_rate = df_sorted[df_sorted['price'] <= current_price]['norm_percent'].sum()

        # --- Average cost ---
        # Weighted average of the prices
        avg_cost = np.average(df_sorted['price'], weights=df_sorted['norm_percent'])

        # --- Helper: the price at a given cumulative ratio ---
        def get_percentile_price(target_pct):
            # Find the first row index where the running sum reaches the target percentage
            idx = df_sorted['cumsum'].searchsorted(target_pct)
            idx = min(idx, len(df_sorted) - 1) # guard against overrunning the end
            return df_sorted.loc[idx, 'price']

        # --- 90% cost band and concentration ---
        # Trim 5% from each end
        cost_90_low = get_percentile_price(5)
        cost_90_high = get_percentile_price(95)
        if (cost_90_high + cost_90_low) != 0:
            concentration_90 = (cost_90_high - cost_90_low) / (cost_90_high + cost_90_low) * 100
        else:
            concentration_90 = 0.0
            
        # --- 70% cost band and concentration ---
        # Trim 15% from each end
        cost_70_low = get_percentile_price(15)
        cost_70_high = get_percentile_price(85)
        if (cost_70_high + cost_70_low) != 0:
            concentration_70 = (cost_70_high - cost_70_low) / (cost_70_high + cost_70_low) * 100
        else:
            concentration_70 = 0.0

        # Return the formatted result
        return {
            "获利比例": round(winner_rate/100, 4), # /100 to match akshare, which returns a decimal fraction
            "平均成本": round(avg_cost, 4),
            "90成本-低": round(cost_90_low, 4),
            "90成本-高": round(cost_90_high, 4),
            "90集中度": round(concentration_90/100, 4),
            "70成本-低": round(cost_70_low, 4),
            "70成本-高": round(cost_70_high, 4),
            "70集中度": round(concentration_70/100, 4)
        }



if __name__ == "__main__":
    # Manual test harness
    logging.basicConfig(level=logging.DEBUG)
    
    fetcher = TushareFetcher()
    
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

    # Test the market statistics
    print("\n" + "=" * 50)
    print("Testing get_market_stats (tushare)")
    print("=" * 50)
    try:
        stats = fetcher.get_market_stats()
        if stats:
            print(f"Market Stats successfully computed:")
            print(f"Up: {stats['up_count']} (Limit Up: {stats['limit_up_count']})")
            print(f"Down: {stats['down_count']} (Limit Down: {stats['limit_down_count']})")
            print(f"Flat: {stats['flat_count']}")
            print(f"Total Amount: {stats['total_amount']:.2f} 亿 (Yi)")
        else:
            print("Failed to compute market stats.")
    except Exception as e:
        print(f"Failed to compute market stats: {e}")


    # Test the chip-distribution data
    print("\n" + "=" * 50)
    print("测试筹码分布数据获取")
    print("=" * 50)
    try:
        chip = fetcher.get_chip_distribution('600519')  # 茅台
    except Exception as e:
        print(f"[筹码分布] 获取失败: {e}")

    # Test the industry-sector ranking
    print("\n" + "=" * 50)
    print("测试行业板块排名获取")
    print("=" * 50)
    try:
        rankings = fetcher.get_sector_rankings(n=5)
        if rankings:
            top, bottom = rankings
            print("涨幅榜 Top 5:")
            for sector in top:
                print(f"{sector['name']}: {sector['change_pct']}%")
            print("\n跌幅榜 Top 5:")
            for sector in bottom:
                print(f"{sector['name']}: {sector['change_pct']}%")
        else:
            print("未获取到行业板块排名数据")
    except Exception as e:
        print(f"[行业板块排名] 获取失败: {e}")

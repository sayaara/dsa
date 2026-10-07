# -*- coding: utf-8 -*-
"""
===================================
Data source base class and manager
===================================

Design pattern: Strategy
- BaseFetcher: abstract base class defining the shared interface
- DataFetcherManager: strategy manager implementing automatic failover

Anti-ban strategy:
1. Every fetcher carries its own flow-control logic
2. Failures switch automatically to the next data source
3. Exponential-backoff retries
"""

import logging
import random
import time
from threading import BoundedSemaphore, RLock, Thread
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Callable, Optional, List, Tuple, Dict, Any

import pandas as pd
import numpy as np
from src.data.stock_index_loader import get_index_stock_name
from src.data.stock_mapping import get_static_stock_name, is_meaningful_stock_name
from src.core.market_registry import MARKET_CODES
from src.services.market_symbol_utils import get_suffix_market
from src.services.run_diagnostics import record_provider_run, record_provider_run_started
from src.services.stock_list_parser import ParseStatus, parse_analysis_target
from .yfinance_fundamental_adapter import YfinanceFundamentalAdapter
from .realtime_types import CircuitBreaker

# Logging configuration
logger = logging.getLogger(__name__)


# === Standard column-name definitions ===
STANDARD_COLUMNS = ['date', 'open', 'high', 'low', 'close', 'volume', 'amount', 'pct_chg']


def unwrap_exception(exc: Exception) -> Exception:
    """
    Follow chained exceptions and return the deepest non-cyclic cause.
    """
    current = exc
    visited = set()

    while current is not None and id(current) not in visited:
        visited.add(id(current))
        next_exc = current.__cause__ or current.__context__
        if next_exc is None:
            break
        current = next_exc

    return current


def summarize_exception(exc: Exception) -> Tuple[str, str]:
    """
    Build a stable summary for logs while preserving the application-layer message.
    """
    root = unwrap_exception(exc)
    error_type = type(root).__name__
    message = str(exc).strip() or str(root).strip() or error_type
    return error_type, " ".join(message.split())


def normalize_stock_code(stock_code: str) -> str:
    """
    Normalize stock code by stripping exchange prefixes/suffixes.

    Accepted formats and their normalized results:
    - '600519'      -> '600519'   (already clean)
    - 'SH600519'    -> '600519'   (strip SH prefix)
    - 'SH.600519'   -> '600519'   (strip SH. prefix)
    - 'SZ000001'    -> '000001'   (strip SZ prefix)
    - 'SS600519'    -> '600519'   (strip legacy Yahoo Shanghai prefix)
    - 'SZ.000001'   -> '000001'   (strip SZ. prefix)
    - 'BJ920748'    -> '920748'   (strip BJ prefix, BSE)
    - 'BJ.920748'   -> '920748'   (strip BJ. prefix, BSE)
    - 'sh600519'    -> '600519'   (case-insensitive)
    - '600519.SH'   -> '600519'   (strip .SH suffix)
    - '000001.SZ'   -> '000001'   (strip .SZ suffix)
    - '920748.BJ'   -> '920748'   (strip .BJ suffix, BSE)
    - 'HK00700'     -> 'HK00700'  (keep HK prefix for HK stocks)
    - '1810.HK'     -> 'HK01810'  (normalize HK suffix to canonical prefix form)
    - explicit Yahoo suffix forms of the registered suffix markets are kept as-is
    - 'AAPL'        -> 'AAPL'     (keep US stock ticker as-is)

    This function is applied at the DataProviderManager layer so that
    all individual fetchers receive a clean 6-digit code (for A-shares/ETFs).
    """
    code = stock_code.strip()
    upper = code.upper()

    # Normalize HK prefix to a canonical 5-digit form (e.g. hk1810 -> HK01810)
    if upper.startswith('HK') and not upper.startswith('HK.'):
        candidate = upper[2:]
        if candidate.isdigit() and 1 <= len(candidate) <= 5:
            return f"HK{candidate.zfill(5)}"

    # Strip SH/SZ/SS prefix (e.g. SH600519 -> 600519, SS600519 -> 600519)
    if upper.startswith(('SH', 'SZ', 'SS')) and not upper.startswith(('SH.', 'SZ.', 'SS.')):
        candidate = code[2:]
        # Only strip if the remainder looks like a valid numeric code
        if candidate.isdigit() and len(candidate) in (5, 6):
            return candidate

    # Strip dotted SH/SZ/SS prefix (e.g. SH.600519 -> 600519)
    if upper.startswith(('SH.', 'SZ.', 'SS.')):
        candidate = code[3:]
        if candidate.isdigit() and len(candidate) in (5, 6):
            return candidate

    # Strip BJ prefix (e.g. BJ920748 -> 920748)
    if upper.startswith('BJ') and not upper.startswith('BJ.'):
        candidate = code[2:]
        if candidate.isdigit() and len(candidate) == 6:
            return candidate

    # Strip dotted BJ prefix (e.g. BJ.920748 -> 920748)
    if upper.startswith('BJ.'):
        candidate = code[3:]
        if candidate.isdigit() and len(candidate) == 6:
            return candidate

    # Strip .SH/.SZ/.BJ suffix (e.g. 600519.SH -> 600519, 920748.BJ -> 920748)
    # while preserving explicit Yahoo suffix forms of the registered suffix markets.
    if '.' in code:
        base, suffix = code.rsplit('.', 1)
        if get_suffix_market(code) is not None:
            return f"{base.upper()}.{suffix.upper()}"
        if suffix.upper() == 'HK' and base.isdigit() and 1 <= len(base) <= 5:
            return f"HK{base.zfill(5)}"
        if base.upper() in ('SH', 'SS', 'SZ', 'BJ') and suffix.isdigit():
            return suffix
        if suffix.upper() in ('SH', 'SZ', 'SS', 'BJ') and base.isdigit():
            return base

    return code


def _is_us_market(code: str) -> bool:
    """Decide whether a code is a US stock or US index code (no Chinese affixes)."""
    from .us_index_mapping import is_us_stock_code, is_us_index_code

    normalized = (code or "").strip().upper()
    return is_us_index_code(normalized) or is_us_stock_code(normalized)


def _is_hk_market(code: str) -> bool:
    """
    Decide whether a code is a HK-equity code.

    Hong Kong is not currently supported; this recognizer stays so HK codes are refused
    instead of being fetched as US tickers.

    Accepts the ``.HK`` suffix, the ``HK00700`` prefix form, and bare 4-5 digit codes
    (A-share stocks and ETFs are 6 digits, so they never clash with bare 4-5 digit HK codes).
    ``YfinanceFetcher``, ``AkshareFetcher`` and ``LongbridgeFetcher`` implement ``_is_hk_code``
    with the same digit range for bare HK codes as this function.
    """
    normalized = (code or "").strip().upper()
    if normalized.endswith(".HK"):
        base = normalized[:-3]
        return base.isdigit() and 1 <= len(base) <= 5
    if normalized.startswith("HK"):
        digits = normalized[2:]
        return digits.isdigit() and 1 <= len(digits) <= 5
    if normalized.isdigit() and 4 <= len(normalized) <= 5:
        return True
    return False


def _market_tag(code: str) -> str:
    """Return the market tag: us, hk (recognized but not currently supported), or a registered
    suffix market. Unknown codes default to us."""
    if _is_us_market(code):
        return "us"
    if _is_hk_market(code):
        return "hk"
    suffix_market = get_suffix_market(code)
    if suffix_market:
        return suffix_market
    return "us"


def canonical_stock_code(code: str) -> str:
    """
    Return the canonical (uppercase) form of a stock code.

    This is a display/storage layer concern, distinct from normalize_stock_code
    which strips exchange prefixes. Apply at system input boundaries to ensure
    consistent case across BOT, WEB UI, API, and CLI paths (Issue #355).

    Examples:
        'aapl'    -> 'AAPL'
        'AAPL'    -> 'AAPL'
        '600519'  -> '600519'  (digits are unchanged)
        'hk00700' -> 'HK00700'
    """
    return (code or "").strip().upper()


class DataFetchError(Exception):
    """Base class for data-fetch exceptions"""
    pass


class RateLimitError(DataFetchError):
    """API rate-limit exception"""
    pass


class DataSourceUnavailableError(DataFetchError):
    """Data-source-unavailable exception"""
    pass


class BaseFetcher(ABC):
    """
    Abstract base class for data sources
    
    Responsibilities:
    1. Define the shared data-fetch interface
    2. Provide the data normalisation hook
    3. Implement the common technical-indicator calculations
    
    Implemented by subclasses:
    - _fetch_raw_data(): fetch raw data from the concrete data source
    - _normalize_data(): convert raw data into the standard format
    """
    
    name: str = "BaseFetcher"
    priority: int = 99  # lower numbers rank higher
    allow_empty_daily_data: bool = False
    
    @abstractmethod
    def _fetch_raw_data(self, stock_code: str, start_date: str, end_date: str) -> pd.DataFrame:
        """
        Fetch raw data from the data source (subclasses must implement this)
        
        Args:
            stock_code: stock code, e.g. '600519', '000001'
            start_date: start date, format 'YYYY-MM-DD'
            end_date: end date, format 'YYYY-MM-DD'
            
        Returns:
            The raw DataFrame (column names vary by data source)
        """
        pass
    
    @abstractmethod
    def _normalize_data(self, df: pd.DataFrame, stock_code: str) -> pd.DataFrame:
        """
        Normalise the column names (subclasses must implement this)

        Unifies the column names across data sources into:
        ['date', 'open', 'high', 'low', 'close', 'volume', 'amount', 'pct_chg']
        """
        pass

    def get_main_indices(self, region: str = "us") -> Optional[List[Dict[str, Any]]]:
        """
        Fetch main index real-time quotes

        Args:
            region: market region, us = US equities, ca = Canada

        Returns:
            List[Dict]: index list, each element a dict containing:
                - code: index code
                - name: index name
                - current: current level
                - change: point change
                - change_pct: percentage change (%)
                - volume: trading volume
                - amount: turnover
        """
        return None

    def get_daily_data(
        self,
        stock_code: str, 
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        days: int = 30
    ) -> pd.DataFrame:
        """
        Fetch daily data (the shared entry point)
        
        Flow:
        1. Work out the date range
        2. Call the subclass to fetch raw data
        3. Normalise the column names
        4. Compute the technical indicators
        
        Args:
            stock_code: stock code
            start_date: start date (optional)
            end_date: end date (optional, defaults to today)
            days: number of days to fetch (used when start_date is omitted)
            
        Returns:
            A normalised DataFrame including the technical indicators
        """
        # Work out the date range
        if end_date is None:
            end_date = datetime.now().strftime('%Y-%m-%d')
        
        if start_date is None:
        # Default to the last 30 trading days (estimated in calendar days, with headroom)
            from datetime import timedelta
            start_dt = datetime.strptime(end_date, '%Y-%m-%d') - timedelta(days=days * 2)
            start_date = start_dt.strftime('%Y-%m-%d')

        request_start = time.time()
        logger.info(f"[{self.name}] start fetching {stock_code} daily data: range={start_date} ~ {end_date}")
        
        try:
            # Step 1: fetch the raw data
            raw_df = self._fetch_raw_data(stock_code, start_date, end_date)
            
            if raw_df is None:
                raise DataFetchError(f"[{self.name}] No data returned for {stock_code}")
            if raw_df.empty:
                elapsed = time.time() - request_start
                logger.info(
                    f"[{self.name}] {stock_code} returned an empty daily result: range={start_date} ~ {end_date}, "
                    f"elapsed={elapsed:.2f}s"
                )
                if self.allow_empty_daily_data:
                    return pd.DataFrame(columns=STANDARD_COLUMNS)
                raise DataFetchError(f"[{self.name}] No data returned for {stock_code}")
            
            # Step 2: normalise the column names
            df = self._normalize_data(raw_df, stock_code)
            
            # Step 3: clean the data
            df = self._clean_data(df)
            
            # Step 4: compute the technical indicators
            df = self._calculate_indicators(df)

            elapsed = time.time() - request_start
            logger.info(
                f"[{self.name}] {stock_code} fetched: range={start_date} ~ {end_date}, "
                f"rows={len(df)}, elapsed={elapsed:.2f}s"
            )
            return df
            
        except Exception as e:
            elapsed = time.time() - request_start
            error_type, error_reason = summarize_exception(e)
            logger.error(
                f"[{self.name}] {stock_code} fetch failed: range={start_date} ~ {end_date}, "
                f"error_type={error_type}, elapsed={elapsed:.2f}s, reason={error_reason}"
            )
            raise DataFetchError(f"[{self.name}] {stock_code}: {error_reason}") from e
    
    def _clean_data(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Clean the data
        
        Handles:
        1. Making sure the date column has the right format
        2. Numeric type conversion
        3. Dropping rows with missing values
        4. Sorting by date
        """
        df = df.copy()
        
        # Make sure the date column is a datetime
        if 'date' in df.columns:
            df['date'] = pd.to_datetime(df['date'])
        
        # Numeric column conversion
        numeric_cols = ['open', 'high', 'low', 'close', 'volume', 'amount', 'pct_chg']
        for col in numeric_cols:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors='coerce')
        
        # Drop rows whose key columns are empty
        df = df.dropna(subset=['close', 'volume'])
        
        # Sort by ascending date
        df = df.sort_values('date', ascending=True).reset_index(drop=True)
        
        return df
    
    def _calculate_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Compute the technical indicators
        
        Indicators computed:
        - MA5, MA10, MA20: moving averages
        - Volume_Ratio: volume ratio (today's volume / 5-day average volume)
        """
        df = df.copy()
        
        # Moving averages
        df['ma5'] = df['close'].rolling(window=5, min_periods=1).mean()
        df['ma10'] = df['close'].rolling(window=10, min_periods=1).mean()
        df['ma20'] = df['close'].rolling(window=20, min_periods=1).mean()
        
        # Volume ratio: today's volume / 5-day average volume
        # Note: this volume_ratio is the relative multiple of "daily volume / 5-day average (shift 1)",
        # which differs from the intraday volume ratio some trading platforms show (same-moment comparison);
        # it is closer to a "volume surge multiple". The behaviour is kept as-is by requirement.
        avg_volume_5 = df['volume'].rolling(window=5, min_periods=1).mean()
        df['volume_ratio'] = df['volume'] / avg_volume_5.shift(1)
        df['volume_ratio'] = df['volume_ratio'].fillna(1.0)
        
        # Round to 2 decimals
        for col in ['ma5', 'ma10', 'ma20', 'volume_ratio']:
            if col in df.columns:
                df[col] = df[col].round(2)
        
        return df
    
    @staticmethod
    def random_sleep(min_seconds: float = 1.0, max_seconds: float = 3.0) -> None:
        """
        Smart random sleep (jitter)
        
        Anti-ban strategy: a random delay that mimics human behaviour
        by inserting an irregular wait between requests
        """
        sleep_time = random.uniform(min_seconds, max_seconds)
        logger.debug(f"random sleep {sleep_time:.2f} seconds...")
        time.sleep(sleep_time)


class DataFetcherManager:
    """
    Data source strategy manager
    
    Responsibilities:
    1. Manage several data sources (ordered by priority)
    2. Automatic failover
    3. Provide the shared data-fetch interface
    
    Failover strategy:
    - Prefer the highest-priority data source
    - Move to the next one on failure
    - Raise once every data source has failed
    """

    _DAILY_MARKET_FETCHER_SUPPORT = {
        "YfinanceFetcher": set(MARKET_CODES),
        "LongbridgeFetcher": {"us"},
        "FinnhubFetcher": {"us"},
        "AlphaVantageFetcher": {"us"},
    }
    _daily_source_health = CircuitBreaker(failure_threshold=3, cooldown_seconds=300.0)

    def __init__(self, fetchers: Optional[List[BaseFetcher]] = None):
        """
        Initialise the manager
        
        Args:
            fetchers: data source list (optional; created automatically by priority when omitted)
        """
        self._fetchers: List[BaseFetcher] = []
        self._fetchers_lock = RLock()
        self._fetchers_by_name: Dict[str, BaseFetcher] = {}
        self._fetcher_call_locks: Dict[int, RLock] = {}
        self._fetcher_call_locks_lock = RLock()
        self._stock_name_cache: Dict[str, str] = {}
        self._stock_name_cache_lock = RLock()
        
        if fetchers:
            # Sort by priority
            self._fetchers = sorted(fetchers, key=lambda f: f.priority)
            self._refresh_fetcher_indexes_locked()
        else:
            # The default data sources are loaded lazily on first use
            self._init_default_fetchers()
        self._yfinance_fundamental_adapter = YfinanceFundamentalAdapter()
        self._fundamental_cache: Dict[str, Dict[str, Any]] = {}
        self._fundamental_cache_lock = RLock()
        self._fundamental_timeout_worker_limit = 8
        self._fundamental_timeout_slots = BoundedSemaphore(self._fundamental_timeout_worker_limit)

    def _ensure_concurrency_guards(self) -> None:
        """Lazily initialize thread-safety primitives for test scaffolds using __new__."""
        if not hasattr(self, "_fetchers_lock") or self._fetchers_lock is None:
            self._fetchers_lock = RLock()
        if not hasattr(self, "_fetchers_by_name") or self._fetchers_by_name is None:
            self._fetchers_by_name = {}
        if not hasattr(self, "_fetcher_call_locks") or self._fetcher_call_locks is None:
            self._fetcher_call_locks = {}
        if not hasattr(self, "_fetcher_call_locks_lock") or self._fetcher_call_locks_lock is None:
            self._fetcher_call_locks_lock = RLock()
        if not hasattr(self, "_stock_name_cache") or self._stock_name_cache is None:
            self._stock_name_cache = {}
        if not hasattr(self, "_stock_name_cache_lock") or self._stock_name_cache_lock is None:
            self._stock_name_cache_lock = RLock()

    def _get_fetchers_snapshot(self) -> List[BaseFetcher]:
        self._ensure_concurrency_guards()
        with self._fetchers_lock:
            return list(getattr(self, "_fetchers", []))

    def _refresh_fetcher_indexes_locked(self) -> None:
        self._fetchers_by_name = {fetcher.name: fetcher for fetcher in self._fetchers}

    def _get_fetcher_by_name(self, fetcher_name: str, capability: str = "") -> Optional[BaseFetcher]:
        self._ensure_concurrency_guards()
        with self._fetchers_lock:
            fetcher = self._fetchers_by_name.get(fetcher_name)
            if fetcher is None and self._fetchers:
                self._refresh_fetcher_indexes_locked()
                fetcher = self._fetchers_by_name.get(fetcher_name)
        if fetcher is None:
            return None
        if not self._is_fetcher_available(fetcher, capability=capability):
            return None
        return fetcher

    @staticmethod
    def _call_availability_probe(fetcher: BaseFetcher, probe_name: str, capability: str) -> Optional[bool]:
        probe = getattr(fetcher, probe_name, None)
        if not callable(probe):
            return None
        try:
            if probe_name == "is_available_for_request":
                return bool(probe(capability))
            return bool(probe())
        except TypeError:
            return bool(probe())
        except Exception as exc:
            logger.debug(
                "[data source availability] %s.%s check failed (capability=%s): %s",
                fetcher.name,
                probe_name,
                capability or "default",
                exc,
            )
            return False

    @classmethod
    def _is_fetcher_available(cls, fetcher: BaseFetcher, capability: str = "") -> bool:
        for probe_name in ("is_available_for_request", "is_available", "_is_available"):
            result = cls._call_availability_probe(fetcher, probe_name, capability)
            if result is not None:
                return result
        return True

    def _get_fetcher_call_lock(self, fetcher: BaseFetcher) -> RLock:
        self._ensure_concurrency_guards()
        fetcher_id = id(fetcher)
        with self._fetcher_call_locks_lock:
            lock = self._fetcher_call_locks.get(fetcher_id)
            if lock is None:
                lock = RLock()
                self._fetcher_call_locks[fetcher_id] = lock
            return lock

    def _call_fetcher_method(self, fetcher: BaseFetcher, method_name: str, *args, **kwargs):
        """Serialize shared fetcher state access through manager-owned per-instance locks."""
        method = getattr(fetcher, method_name)
        with self._get_fetcher_call_lock(fetcher):
            return method(*args, **kwargs)

    @classmethod
    def _filter_daily_fetchers_for_market(
        cls,
        fetchers: List[BaseFetcher],
        market: str,
    ) -> List[BaseFetcher]:
        """Skip built-in daily fetchers that are known not to support a market."""

        kept: List[BaseFetcher] = []
        skipped: List[str] = []
        for fetcher in fetchers:
            supported = cls._DAILY_MARKET_FETCHER_SUPPORT.get(fetcher.name)
            if supported is not None and market not in supported:
                skipped.append(fetcher.name)
            else:
                kept.append(fetcher)

        if skipped:
            logger.info(
                "[data source routing] %s daily: skipping unsupported data source: %s",
                market,
                ", ".join(skipped),
            )
        return kept

    @classmethod
    def _filter_fetchers_by_capability(
        cls,
        fetchers: List[BaseFetcher],
        capability: str,
    ) -> List[BaseFetcher]:
        """Skip request-time unavailable fetchers before entering route-specific loops."""
        kept: List[BaseFetcher] = []
        skipped: List[str] = []

        for fetcher in fetchers:
            if cls._is_fetcher_available(fetcher, capability=capability):
                kept.append(fetcher)
            else:
                skipped.append(fetcher.name)

        if skipped:
            logger.info(
                "[data source routing] %s skipping temporarily unavailable data source: %s",
                capability or "request",
                ", ".join(skipped),
            )

        return kept

    @classmethod
    def _daily_health_key(cls, fetcher: BaseFetcher, market: str) -> str:
        return f"daily_data:{market}:{fetcher.name}"

    @classmethod
    def _is_daily_source_available(
        cls,
        fetcher: BaseFetcher,
        market: str,
    ) -> bool:
        key = cls._daily_health_key(fetcher, market)
        if cls._daily_source_health.is_available(key):
            return True
        logger.info(
            "[data source health] %s daily: skipping data source in a short-term circuit break: %s",
            market,
            fetcher.name,
        )
        return False

    @staticmethod
    def _daily_source_unavailable_error(fetcher: BaseFetcher) -> str:
        return f"[{fetcher.name}] (CircuitOpen) data source is in a short-term circuit break"

    @classmethod
    def _record_daily_source_success(cls, fetcher: BaseFetcher, market: str) -> None:
        cls._daily_source_health.record_success(cls._daily_health_key(fetcher, market))

    @classmethod
    def _record_daily_source_failure(cls, fetcher: BaseFetcher, market: str, error: str) -> None:
        cls._daily_source_health.record_failure(cls._daily_health_key(fetcher, market), error=error)

    @classmethod
    def reset_daily_source_health(cls) -> None:
        """Reset daily source health state for tests/admin diagnostics."""
        cls._daily_source_health.reset()

    def _get_cached_stock_name(self, stock_code: str) -> Optional[str]:
        self._ensure_concurrency_guards()
        with self._stock_name_cache_lock:
            return self._stock_name_cache.get(stock_code)

    def _cache_stock_name(self, stock_code: str, name: Optional[str]) -> Optional[str]:
        if name is None:
            return None
        self._ensure_concurrency_guards()
        with self._stock_name_cache_lock:
            self._stock_name_cache[stock_code] = name
        return name

    def _discard_cached_stock_name(self, stock_code: str) -> None:
        self._ensure_concurrency_guards()
        with self._stock_name_cache_lock:
            self._stock_name_cache.pop(stock_code, None)

    def close(self) -> None:
        """Best-effort release of manager-owned resources."""

        for fetcher in self._get_fetchers_snapshot():
            close = getattr(fetcher, "close", None)
            if callable(close):
                try:
                    close()
                except Exception as exc:
                    logger.debug("[%s] close failed: %s", fetcher.name, exc)

    def __del__(self) -> None:
        try:
            self.close()
        except Exception:
            # Best-effort cleanup during interpreter shutdown.
            pass

    def _get_fundamental_cache_key(self, stock_code: str, budget_seconds: Optional[float] = None) -> str:
        """Build the fundamentals cache key (budget bucketing keeps low-budget results from polluting high-budget requests)."""
        normalized_code = normalize_stock_code(stock_code)
        if budget_seconds is None:
            return f"{normalized_code}|budget=default"
        try:
            budget = max(0.0, float(budget_seconds))
        except (TypeError, ValueError):
            budget = 0.0
        # 100ms bucket to balance cache reuse and scenario isolation.
        budget_bucket = int(round(budget * 10))
        return f"{normalized_code}|budget={budget_bucket}"

    def _prune_fundamental_cache(self, ttl_seconds: int, max_entries: int) -> None:
        """Prune expired and overflow fundamental cache items."""
        with self._fundamental_cache_lock:
            if not self._fundamental_cache:
                return

            now_ts = time.time()
            if ttl_seconds > 0:
                cache_items = list(self._fundamental_cache.items())
                expired_keys = [
                    key
                    for key, value in cache_items
                    if now_ts - float(value.get("ts", 0)) > ttl_seconds
                ]
                for key in expired_keys:
                    self._fundamental_cache.pop(key, None)

            if max_entries > 0 and len(self._fundamental_cache) > max_entries:
                overflow = len(self._fundamental_cache) - max_entries
                sorted_items = sorted(
                    list(self._fundamental_cache.items()),
                    key=lambda item: float(item[1].get("ts", 0)),
                )
                for key, _ in sorted_items[:overflow]:
                    self._fundamental_cache.pop(key, None)

    @staticmethod
    def _try_scalar_isna(value: Any, context: str) -> Optional[bool]:
        """Return scalar ``pd.isna`` result, or ``None`` when callers should use fallback logic."""
        if isinstance(value, (dict, list, tuple, set, pd.DataFrame, pd.Series, pd.Index)):
            return None

        if isinstance(value, np.ndarray):
            if value.ndim != 0:
                return None
            value = value.item()

        try:
            isna_result = pd.isna(value)
        except (TypeError, ValueError) as exc:
            if hasattr(value, "__array__"):
                logger.debug(
                    "[%s] pd.isna failed for array-like object; re-raise: value_type=%s error_type=%s",
                    context,
                    type(value).__name__,
                    type(exc).__name__,
                )
                raise
            logger.debug(
                "[%s] pd.isna fallback: value_type=%s error_type=%s",
                context,
                type(value).__name__,
                type(exc).__name__,
            )
            return None

        if isinstance(isna_result, (bool, np.bool_)):
            return bool(isna_result)

        if isinstance(isna_result, np.ndarray):
            if isna_result.ndim == 0:
                return bool(isna_result.item())
            logger.debug(
                "[%s] pd.isna returned non-scalar result: value_type=%s result_type=%s",
                context,
                type(value).__name__,
                type(isna_result).__name__,
            )
            return None

        logger.debug(
            "[%s] pd.isna returned unexpected result type: value_type=%s result_type=%s",
            context,
            type(value).__name__,
            type(isna_result).__name__,
        )
        return None

    @staticmethod
    def _is_missing_board_value(value: Any) -> bool:
        """Return True when a board field value should be treated as missing."""
        if value is None:
            return True
        is_missing = DataFetcherManager._try_scalar_isna(value, "board_value")
        if is_missing is True:
            return True
        text = str(value).strip()
        return text == "" or text.lower() in {"nan", "none", "null", "na", "n/a"}

    
    def _init_default_fetchers(self) -> None:
        """
        Initialise the default data source list (the registered markets)

        - YfinanceFetcher is always instantiated and is the default daily source
        - Unconfigured optional sources are not instantiated, so batch fetches do not probe dead sources repeatedly
        - Optional sources: Longbridge (OAuth or legacy credentials),
          Finnhub and Alpha Vantage (API keys)
        """
        from src.config import get_config
        from .yfinance_fetcher import YfinanceFetcher
        from .longbridge_fetcher import LongbridgeFetcher
        config = get_config()
        yfinance = YfinanceFetcher()
        optional_fetchers: List[BaseFetcher] = []

        if LongbridgeFetcher.has_configured_credentials(config):
            optional_fetchers.append(LongbridgeFetcher())  # Longbridge (US fallback, lazily loaded)
        else:
            logger.debug("[data source init] skipping the unconfigured LongbridgeFetcher")

        finnhub_api_key = (getattr(config, "finnhub_api_key", None) or "").strip()
        if finnhub_api_key:
            from .finnhub_fetcher import FinnhubFetcher
            optional_fetchers.append(FinnhubFetcher())
        else:
            logger.debug("[data source init] skipping the unconfigured FinnhubFetcher")

        alphavantage_api_key = (getattr(config, "alphavantage_api_key", None) or "").strip()
        if alphavantage_api_key:
            from .alphavantage_fetcher import AlphaVantageFetcher
            optional_fetchers.append(AlphaVantageFetcher())
        else:
            logger.debug("[data source init] skipping the unconfigured AlphaVantageFetcher")

        # Initialise the data source list
        self._ensure_concurrency_guards()
        with self._fetchers_lock:
            self._fetchers = [yfinance, *optional_fetchers]
            self._fetchers.sort(key=lambda f: f.priority)
            self._refresh_fetcher_indexes_locked()

        # Build the priority description
        priority_info = ", ".join([f"{f.name}(P{f.priority})" for f in self._get_fetchers_snapshot()])
        logger.info(f"initialized {len(self._fetchers)} data sources (by priority): {priority_info}")

    def add_fetcher(self, fetcher: BaseFetcher) -> None:
        """Add a data source and re-sort"""
        self._ensure_concurrency_guards()
        with self._fetchers_lock:
            self._fetchers.append(fetcher)
            self._fetchers.sort(key=lambda f: f.priority)
            self._refresh_fetcher_indexes_locked()
    
    def get_daily_data(
        self, 
        stock_code: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        days: int = 30
    ) -> Tuple[pd.DataFrame, str]:
        """
        Fetch daily data (with automatic data source failover)
        
        Failover strategy:
        1. US indices and US stocks route straight to YfinanceFetcher
        2. A-share indices already in the registry use the fixed index data source chain
        3. Every other code starts from the highest-priority data source
        4. Exceptions switch to the next source and the failure reason is recorded
        5. Indices return the standard empty result when every source fails; non-indices raise a detailed exception
        
        Args:
            stock_code: stock code
            start_date: start date
            end_date: end date
            days: number of days to fetch
            
        Returns:
            Tuple[DataFrame, str]: (data, name of the data source that succeeded)
            
        Raises:
            DataFetchError: raised when every data source fails for a non-index code
        """
        from .us_index_mapping import is_us_index_code, is_us_stock_code

        raw_stock_code = (stock_code or "").strip()
        target = parse_analysis_target(raw_stock_code)
        if target.asset_type in (ParseStatus.UNSUPPORTED, ParseStatus.INDEX):
            reason = target.unsupported_reason or "unsupported analysis target"
            raise DataFetchError(f"{raw_stock_code}: {reason}")

        # Normalize code (strip SH/SZ prefix etc.)
        stock_code = normalize_stock_code(stock_code)

        fetchers = self._get_fetchers_snapshot()
        errors = []
        request_start = time.time()

        # Fast path: US equities use the dedicated routing
        #   - With Longbridge credentials: Longbridge first, YFinance as fallback
        #   - Without Longbridge:         YFinance first
        #   - US indices:                 always YFinance first (Longbridge has no index candlesticks)
        is_us_index = is_us_index_code(stock_code)
        is_us = is_us_index or is_us_stock_code(stock_code)
        if not is_us and _is_hk_market(stock_code):
            raise DataFetchError(f"Hong Kong code {stock_code} is not currently supported")
        suffix_market = None if is_us else get_suffix_market(stock_code)
        market = "us" if is_us else suffix_market
        if market:
            fetchers = self._filter_daily_fetchers_for_market(fetchers, market)
        fetchers = self._filter_fetchers_by_capability(fetchers, capability="daily_data")
        total_fetchers = len(fetchers)

        if total_fetchers == 0:
            market_label = "US index" if is_us_index else "US" if is_us else "unknown market"
            error_summary = f"{market_label} {stock_code} fetch failed:\nno data source available at the moment"
            logger.error(f"[data source aborted] {stock_code} fetch failed: {error_summary}")
            raise DataFetchError(error_summary)

        # US equities (indices included) use the dedicated routing; suffix markets use the generic loop below
        # Failover chain: Finnhub(P2) -> AlphaVantage(P3) -> Yfinance(P4) -> Longbridge(P5)
        # When Longbridge preferred: Longbridge -> Finnhub -> AlphaVantage -> Yfinance
        if is_us:
            prefer_lb = self._longbridge_preferred(capability="daily_data") and not is_us_index
            if is_us_index:
                # Indices always prefer YFinance (Longbridge has no index candlesticks)
                source_order = ["YfinanceFetcher", "FinnhubFetcher"]
            elif prefer_lb:
                source_order = ["LongbridgeFetcher", "FinnhubFetcher", "AlphaVantageFetcher", "YfinanceFetcher"]
            else:
                source_order = ["FinnhubFetcher", "AlphaVantageFetcher", "YfinanceFetcher", "LongbridgeFetcher"]
            # Consume each source's current priority (including the *_PRIORITY env vars): the defaults match the built-in chain,
            # and a single override (e.g. YFINANCE_PRIORITY=0) takes effect immediately; the pinned index/Longbridge-preferred head is never overridden by ordinary priorities
            pin_first = bool(is_us_index or prefer_lb)
            source_order = self._order_us_sources_by_priority(source_order, pin_first=pin_first)
            market_label = "US index" if is_us_index else "US"

            for order_index, src_name in enumerate(source_order):
                fallback_to = (
                    source_order[order_index + 1]
                    if order_index + 1 < len(source_order)
                    else None
                )
                for attempt, fetcher in enumerate(fetchers, start=1):
                    if fetcher.name != src_name:
                        continue
                    if not self._is_daily_source_available(fetcher, market):
                        errors.append(self._daily_source_unavailable_error(fetcher))
                        break
                    attempt_start = time.time()
                    try:
                        role = "primary" if src_name == source_order[0] else "fallback"
                        logger.info(
                            f"[data source attempt {attempt}/{total_fetchers}] [{fetcher.name}] "
                            f"{market_label} {stock_code} {role} routing..."
                        )
                        record_provider_run_started(
                            data_type="daily_data",
                            provider=fetcher.name,
                            operation="get_daily_data",
                        )
                        df = self._call_fetcher_method(
                            fetcher,
                            "get_daily_data",
                            stock_code=stock_code,
                            start_date=start_date,
                            end_date=end_date,
                            days=days,
                        )
                        if df is not None and not df.empty:
                            duration_ms = int((time.time() - attempt_start) * 1000)
                            record_provider_run(
                                data_type="daily_data",
                                provider=fetcher.name,
                                operation="get_daily_data",
                                success=True,
                                latency_ms=duration_ms,
                                record_count=len(df),
                            )
                            elapsed = time.time() - request_start
                            logger.info(
                                f"[data source done] {stock_code} fetched using [{fetcher.name}]: "
                                f"rows={len(df)}, elapsed={elapsed:.2f}s"
                            )
                            self._record_daily_source_success(fetcher, market)
                            return df, fetcher.name
                        duration_ms = int((time.time() - attempt_start) * 1000)
                        record_provider_run(
                            data_type="daily_data",
                            provider=fetcher.name,
                            operation="get_daily_data",
                            success=False,
                            latency_ms=duration_ms,
                            error_type="empty",
                            error_message="empty result",
                            fallback_to=fallback_to,
                            record_count=0,
                        )
                        if df is not None and df.empty:
                            self._record_daily_source_success(fetcher, market)
                    except Exception as e:
                        error_type, error_reason = summarize_exception(e)
                        error_msg = f"[{fetcher.name}] ({error_type}) {error_reason}"
                        duration_ms = int((time.time() - attempt_start) * 1000)
                        record_provider_run(
                            data_type="daily_data",
                            provider=fetcher.name,
                            operation="get_daily_data",
                            success=False,
                            latency_ms=duration_ms,
                            error_type=error_type,
                            error_message=error_reason,
                            fallback_to=fallback_to,
                        )
                        logger.warning(
                            f"[data source failed {attempt}/{total_fetchers}] [{fetcher.name}] {stock_code}: "
                            f"error_type={error_type}, reason={error_reason}"
                        )
                        self._record_daily_source_failure(fetcher, market, error_reason)
                        errors.append(error_msg)
                    break

            error_summary = f"{market_label} {stock_code} fetch failed:\n" + "\n".join(errors)
            elapsed = time.time() - request_start
            logger.error(f"[data source aborted] {stock_code} fetch failed: elapsed={elapsed:.2f}s\n{error_summary}")
            raise DataFetchError(error_summary)

        for attempt, fetcher in enumerate(fetchers, start=1):
            if not self._is_daily_source_available(fetcher, market):
                errors.append(self._daily_source_unavailable_error(fetcher))
                continue
            attempt_start = time.time()
            fallback_to = fetchers[attempt].name if attempt < total_fetchers else None
            try:
                logger.info(f"[data source attempt {attempt}/{total_fetchers}] [{fetcher.name}] fetching {stock_code}...")
                record_provider_run_started(
                    data_type="daily_data",
                    provider=fetcher.name,
                    operation="get_daily_data",
                )
                df = self._call_fetcher_method(
                    fetcher,
                    "get_daily_data",
                    stock_code=stock_code,
                    start_date=start_date,
                    end_date=end_date,
                    days=days
                )
                
                if df is not None and not df.empty:
                    duration_ms = int((time.time() - attempt_start) * 1000)
                    record_provider_run(
                        data_type="daily_data",
                        provider=fetcher.name,
                        operation="get_daily_data",
                        success=True,
                        latency_ms=duration_ms,
                        record_count=len(df),
                    )
                    elapsed = time.time() - request_start
                    logger.info(
                        f"[data source done] {stock_code} fetched using [{fetcher.name}]: "
                        f"rows={len(df)}, elapsed={elapsed:.2f}s"
                    )
                    self._record_daily_source_success(fetcher, market)
                    return df, fetcher.name
                duration_ms = int((time.time() - attempt_start) * 1000)
                record_provider_run(
                    data_type="daily_data",
                    provider=fetcher.name,
                    operation="get_daily_data",
                    success=False,
                    latency_ms=duration_ms,
                    error_type="empty",
                    error_message="empty result",
                    fallback_to=fallback_to,
                    record_count=0,
                )
                if df is not None and df.empty:
                    self._record_daily_source_success(fetcher, market)

            except Exception as e:
                error_type, error_reason = summarize_exception(e)
                error_msg = f"[{fetcher.name}] ({error_type}) {error_reason}"
                duration_ms = int((time.time() - attempt_start) * 1000)
                record_provider_run(
                    data_type="daily_data",
                    provider=fetcher.name,
                    operation="get_daily_data",
                    success=False,
                    latency_ms=duration_ms,
                    error_type=error_type,
                    error_message=error_reason,
                    fallback_to=fallback_to,
                )
                logger.warning(
                    f"[data source failed {attempt}/{total_fetchers}] [{fetcher.name}] {stock_code}: "
                    f"error_type={error_type}, reason={error_reason}"
                )
                self._record_daily_source_failure(fetcher, market, error_reason)
                errors.append(error_msg)
                if attempt < total_fetchers:
                    next_fetcher = fetchers[attempt]
                    logger.info(f"[data source switch] {stock_code}: [{fetcher.name}] -> [{next_fetcher.name}]")
                # Move on to the next data source
                continue
        
        # Every data source failed
        error_summary = f"all data sources failed to fetch {stock_code}:\n" + "\n".join(errors)
        elapsed = time.time() - request_start
        logger.error(f"[data source aborted] {stock_code} fetch failed: elapsed={elapsed:.2f}s\n{error_summary}")
        raise DataFetchError(error_summary)
    
    @property
    def available_fetchers(self) -> List[str]:
        """Return the list of available data source names"""
        return [f.name for f in self._get_fetchers_snapshot()]
    
    @staticmethod
    def _utc_now_iso() -> str:
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _parse_realtime_timestamp(value: Any) -> Optional[datetime]:
        if value in (None, ""):
            return None
        if isinstance(value, datetime):
            parsed = value
        else:
            text = str(value).strip()
            if not text:
                return None
            if text.endswith("Z"):
                text = text[:-1] + "+00:00"
            try:
                parsed = datetime.fromisoformat(text)
            except ValueError:
                return None
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)

    @staticmethod
    def _realtime_fetcher_token(fetcher_name: str, **kw) -> str:
        mapping = {
            "LongbridgeFetcher": "longbridge",
            "YfinanceFetcher": "yfinance",
            "FinnhubFetcher": "finnhub",
            "AlphaVantageFetcher": "alphavantage",
        }
        return mapping.get(fetcher_name, fetcher_name.replace("Fetcher", "").lower())

    def _enrich_realtime_quote(
        self,
        quote,
        *,
        fallback_from: Optional[str] = None,
        realtime_cache_ttl: Optional[int] = None,
    ):
        """Attach runtime metadata without inventing provider-side timestamps."""
        if quote is None:
            return None

        fetched_at = self._utc_now_iso()
        setattr(quote, "fetched_at", fetched_at)
        if fallback_from:
            setattr(quote, "fallback_from", str(fallback_from))

        provider_dt = self._parse_realtime_timestamp(
            getattr(quote, "provider_timestamp", None)
        )
        if provider_dt is None:
            setattr(quote, "provider_timestamp", None)
            setattr(quote, "stale_seconds", None)
            setattr(quote, "is_stale", None)
            return quote

        setattr(quote, "provider_timestamp", provider_dt.isoformat())
        fetched_dt = self._parse_realtime_timestamp(fetched_at) or datetime.now(timezone.utc)
        stale_seconds = max(0, int((fetched_dt - provider_dt).total_seconds()))
        ttl = realtime_cache_ttl if realtime_cache_ttl is not None else 600
        setattr(quote, "stale_seconds", stale_seconds)
        setattr(quote, "is_stale", stale_seconds > int(ttl))
        return quote
    
    def get_realtime_quote(self, stock_code: str, *, log_final_failure: bool = True):
        """
        Fetch real-time quote data (with automatic failover)
        
        Failover strategy:
        1. US equities: Longbridge / YfinanceFetcher, supplemented by Finnhub and Alpha Vantage
        2. Suffix markets: YfinanceFetcher
        3. Hong Kong codes (not currently supported) and everything else: return None
        
        Args:
            stock_code: stock code
            log_final_failure: Whether to emit the final "all sources failed"
                summary log when no realtime quote is available.
            
        Returns:
            A UnifiedRealtimeQuote object, or None when every data source fails
        """
        # Normalize code (strip SH/SZ prefix etc.)
        stock_code = normalize_stock_code(stock_code)

        from .market_codes import is_us_code as _is_us_code
        from .us_index_mapping import is_us_index_code
        from src.config import get_config

        config = get_config()

        # Return None immediately when real-time quotes are disabled
        if not config.enable_realtime_quote:
            logger.debug(f"[realtime quote] feature disabled, skipping {stock_code}")
            return None

        # ----------------------------------------------------------
        # US equities (indices + single stocks) - dedicated dual-source routing
        #   With Longbridge:    Longbridge first, YFinance supplementing
        #   Without Longbridge: YFinance first, Longbridge supplementing
        #   US indices:         always YFinance first (Longbridge has no index quotes)
        # ----------------------------------------------------------
        is_us_index = is_us_index_code(stock_code)
        is_us = is_us_index or _is_us_code(stock_code)
        if not is_us and _is_hk_market(stock_code):
            # Hong Kong is not currently supported; stored HK positions get no quote.
            logger.debug("[realtime quote] Hong Kong code %s is not supported, skipping", stock_code)
            return None
        suffix_market = None if is_us else get_suffix_market(stock_code)

        if suffix_market:
            market_label = suffix_market.upper()
            quote = self._try_fetcher_quote(stock_code, "YfinanceFetcher")
            if quote is not None:
                logger.info(f"[realtime quote] {market_label} {stock_code} fetched (source: YfinanceFetcher)")
                return self._enrich_realtime_quote(
                    quote,
                    realtime_cache_ttl=getattr(config, "realtime_cache_ttl", None),
                )
            if log_final_failure:
                logger.info(f"[realtime quote] {market_label} {stock_code} no data source available")
            return None

        if is_us:
            prefer_lb = self._longbridge_preferred() and not is_us_index
            primary_src = "LongbridgeFetcher" if prefer_lb else "YfinanceFetcher"
            secondary_src = "YfinanceFetcher" if prefer_lb else "LongbridgeFetcher"
            market_label = "US index" if is_us_index else "US"
            primary_kw: dict = {}
            secondary_kw: dict = {}
            primary_token = self._realtime_fetcher_token(primary_src, **primary_kw)
            primary_quote = self._try_fetcher_quote(stock_code, primary_src, **primary_kw)
            fallback_from = primary_token if primary_quote is None else None
            if primary_quote is not None:
                logger.info(f"[realtime quote] {market_label} {stock_code} fetched (source: {primary_src})")
            # US index quotes are YFinance-only. Longbridge accepts index-like
            # symbols syntactically, but does not provide the index quote
            # contract used by this manager, so it must not be used as either
            # fallback or field supplement here.
            if not is_us_index:
                primary_quote = self._supplement_quote(
                    stock_code, primary_quote, secondary_src, **secondary_kw,
                )
            if is_us and not is_us_index and primary_quote is not None:
                for extra_src in ["FinnhubFetcher", "AlphaVantageFetcher"]:
                    primary_quote = self._supplement_quote(
                        stock_code, primary_quote, extra_src,
                    )
            if primary_quote is not None:
                return self._enrich_realtime_quote(
                    primary_quote,
                    fallback_from=fallback_from,
                    realtime_cache_ttl=getattr(config, "realtime_cache_ttl", None),
                )
            if log_final_failure:
                logger.info(f"[realtime quote] {market_label} {stock_code} no data source available")
            return None
        
        # Only US, HK and registered suffix markets have realtime sources.
        if log_final_failure:
            logger.info(f"[realtime quote] {stock_code} no data source available")
        return None

    # Fields worth supplementing from secondary sources when the primary
    # source returns None for them. Ordered by importance.
    _SUPPLEMENT_FIELDS = [
        'volume_ratio', 'turnover_rate',
        'pe_ratio', 'pb_ratio', 'total_mv', 'circ_mv',
        'amplitude',
    ]

    @classmethod
    def _quote_needs_supplement(cls, quote) -> bool:
        """Check if any key supplementary field is still None."""
        for f in cls._SUPPLEMENT_FIELDS:
            if getattr(quote, f, None) is None:
                return True
        return False

    @classmethod
    def _merge_quote_fields(cls, primary, secondary) -> list:
        """
        Copy non-None fields from *secondary* into *primary* where
        *primary* has None. Returns list of field names that were filled.
        """
        filled = []
        for f in cls._SUPPLEMENT_FIELDS:
            if getattr(primary, f, None) is None:
                val = getattr(secondary, f, None)
                if val is not None:
                    setattr(primary, f, val)
                    filled.append(f)
        return filled

    def _order_us_sources_by_priority(self, source_order: List[str], *, pin_first: bool) -> List[str]:
        """Re-order the US daily routing by each source's current priority (consuming the existing *_PRIORITY config).

        Stable sort: the per-source defaults (Finnhub=2/AlphaVantage=3/Yfinance=4/Longbridge=5)
        match the built-in chain, so the default behaviour is unchanged; a single *_PRIORITY override takes effect immediately.
        With pin_first=True the head of the chain is preserved (Yfinance pinned for indices, Longbridge when preferred),
        and the remaining members are sorted by priority.
        """
        self._ensure_concurrency_guards()
        if not source_order:
            return source_order
        priority_by_name = {f.name: f.priority for f in self._get_fetchers_snapshot()}
        if pin_first:
            pinned, rest = source_order[0], source_order[1:]
            return [pinned] + sorted(rest, key=lambda name: priority_by_name.get(name, 10 ** 9))
        return sorted(source_order, key=lambda name: priority_by_name.get(name, 10 ** 9))

    def _longbridge_preferred(self, capability: str = "realtime_quote") -> bool:
        """Return True when Longbridge keys are configured and available.

        When True, non-A-share routing (US & HK) uses Longbridge as the
        primary data source with Yfinance as fallback.
        """
        return self._get_fetcher_by_name(
            "LongbridgeFetcher",
            capability=capability,
        ) is not None

    def _try_fetcher_quote(self, stock_code: str, fetcher_name: str, **kw):
        """Try to get a realtime quote from a named fetcher; returns quote or None."""
        fetcher = self._get_fetcher_by_name(fetcher_name, capability="realtime_quote")
        if fetcher is None or not hasattr(fetcher, 'get_realtime_quote'):
            record_provider_run(
                data_type="realtime_quote",
                provider=fetcher_name,
                operation="get_realtime_quote",
                success=False,
                error_type="unavailable",
                error_message="fetcher unavailable",
            )
            return None
        attempt_start = time.time()
        try:
            record_provider_run_started(
                data_type="realtime_quote",
                provider=fetcher.name,
                operation="get_realtime_quote",
            )
            q = self._call_fetcher_method(fetcher, 'get_realtime_quote', stock_code, **kw)
            if q is not None and q.has_basic_data():
                record_provider_run(
                    data_type="realtime_quote",
                    provider=fetcher.name,
                    operation="get_realtime_quote",
                    success=True,
                    latency_ms=int((time.time() - attempt_start) * 1000),
                    record_count=1,
                )
                return q
            record_provider_run(
                data_type="realtime_quote",
                provider=fetcher.name,
                operation="get_realtime_quote",
                success=False,
                latency_ms=int((time.time() - attempt_start) * 1000),
                error_type="empty",
                error_message="empty or incomplete quote",
                record_count=0,
            )
        except Exception as e:
            error_type, error_reason = summarize_exception(e)
            record_provider_run(
                data_type="realtime_quote",
                provider=fetcher.name,
                operation="get_realtime_quote",
                success=False,
                latency_ms=int((time.time() - attempt_start) * 1000),
                error_type=error_type,
                error_message=error_reason,
            )
            logger.debug(f"[realtime quote] {stock_code} {fetcher_name} fetch failed: {e}")
        return None

    def _supplement_quote(self, stock_code: str, primary_quote, fetcher_name: str, **kw):
        """Supplement *primary_quote* with data from *fetcher_name*.

        If *primary_quote* is None, try *fetcher_name* as the sole source.
        Returns the (potentially enriched) quote, or None.
        """
        if primary_quote is not None:
            if not self._quote_needs_supplement(primary_quote):
                return primary_quote
            try:
                secondary = self._try_fetcher_quote(stock_code, fetcher_name, **kw)
                if secondary is not None:
                    filled = self._merge_quote_fields(primary_quote, secondary)
                    if filled:
                        logger.info(f"[realtime quote] {stock_code} from {fetcher_name} filled in: {filled}")
            except Exception as e:
                logger.debug(f"[realtime quote] {stock_code} {fetcher_name} fill-in failed: {e}")
            return primary_quote

        q = self._try_fetcher_quote(stock_code, fetcher_name, **kw)
        if q is not None:
            logger.info(f"[realtime quote] {stock_code} from {fetcher_name} fetched (standalone data source)")
        return q

    def _supplement_from_longbridge(self, stock_code: str, primary_quote):
        """Shortcut kept for backward-compat with A-share general loop."""
        return self._supplement_quote(stock_code, primary_quote, "LongbridgeFetcher")

    def get_stock_name(self, stock_code: str, allow_realtime: bool = True) -> Optional[str]:
        """
        Fetch the stock's Chinese name (with automatic data source failover)
        
        Tries several data sources in turn:
        1. The in-memory cache first (when present)
        2. Then the locally maintained mapping and the stocks.index.json index
        3. Then the real-time quote, on demand
        4. Then each data source's get_stock_name method in turn
        
        Args:
            stock_code: stock code
            allow_realtime: Whether to query realtime quote first. Set False when
                caller only wants lightweight prefetch without triggering heavy
                realtime source calls.
            
        Returns:
            The stock's Chinese name, or None when every data source fails
        """
        raw_stock_code = (stock_code or "").strip()
        target = parse_analysis_target(raw_stock_code)
        if target.asset_type in (ParseStatus.UNSUPPORTED, ParseStatus.INDEX):
            logger.warning(
                "[stock name] skipping unsupported input %s: %s",
                raw_stock_code,
                target.unsupported_reason or "unsupported analysis target",
            )
            return ""

        # Normalize code (strip SH/SZ prefix etc.)
        stock_code = normalize_stock_code(stock_code)
        static_name = get_static_stock_name(stock_code) or None

        # 1. Check the cache first
        cached_name = self._get_cached_stock_name(stock_code)
        if cached_name is not None:
            return cached_name
        
        if is_meaningful_stock_name(static_name, stock_code):
            return self._cache_stock_name(stock_code, static_name) or static_name

        index_name = get_index_stock_name(stock_code)
        if is_meaningful_stock_name(index_name, stock_code):
            return self._cache_stock_name(stock_code, index_name) or index_name

        # 2. Try the real-time quote (fastest; can be disabled on demand)
        if allow_realtime:
            quote = self.get_realtime_quote(raw_stock_code or stock_code, log_final_failure=False)
            if quote and hasattr(quote, 'name') and is_meaningful_stock_name(getattr(quote, 'name', ''), stock_code):
                name = quote.name
                self._cache_stock_name(stock_code, name)
                logger.info(f"[stock name] from realtime quote: {stock_code} -> {name}")
                return name

        # 3. Try each data source in turn
        from .market_codes import is_us_code as _is_us_code
        is_us = _is_us_code(stock_code)
        is_hk = (not is_us) and _is_hk_market(stock_code)
        _US_CAPABLE_FETCHERS = {"YfinanceFetcher", "LongbridgeFetcher", "FinnhubFetcher", "AlphaVantageFetcher"}
        for fetcher in self._get_fetchers_snapshot():
            if not hasattr(fetcher, 'get_stock_name'):
                continue
            if is_us and fetcher.name not in _US_CAPABLE_FETCHERS:
                continue
            if is_hk:
                # Hong Kong is not currently supported: no source is asked for HK names.
                break
            if not self._is_fetcher_available(fetcher, capability="stock_name"):
                continue
            try:
                name = self._call_fetcher_method(fetcher, 'get_stock_name', stock_code)
                if is_meaningful_stock_name(name, stock_code):
                    self._cache_stock_name(stock_code, name)
                    logger.info(f"[stock name] from {fetcher.name} fetching: {stock_code} -> {name}")
                    return name
            except Exception as e:
                logger.debug(f"[stock name] {fetcher.name} fetch failed: {e}")
                continue

        # 4. Every data source failed
        logger.warning(f"[stock name] no data source could fetch {stock_code} name")
        return ""

    def prefetch_stock_names(self, stock_codes: List[str], use_bulk: bool = False) -> None:
        """
        Pre-fetch stock names into cache before parallel analysis (Issue #455).

        When use_bulk=False, only calls get_stock_name per code (no get_stock_list),
        avoiding full-market fetch. Sequential execution to avoid rate limits.

        Args:
            stock_codes: Stock codes to prefetch.
            use_bulk: If True, may use get_stock_list (full fetch). Default False.
        """
        if not stock_codes:
            return
        normalized_codes: List[str] = []
        for code in stock_codes:
            target = parse_analysis_target(code)
            if target.asset_type == ParseStatus.UNSUPPORTED:
                logger.warning(
                    "[stock name] prefetch skipping unsupported input %s: %s",
                    code,
                    target.unsupported_reason or "unsupported analysis target",
                )
                continue
            normalized_codes.append(
                target.canonical_id
                if target.asset_type == ParseStatus.INDEX
                else normalize_stock_code(code)
            )
        stock_codes = normalized_codes
        if use_bulk:
            self.batch_get_stock_names(stock_codes)
            return
        for code in stock_codes:
            # Skip realtime lookup to avoid triggering expensive full-market quote
            # requests during the prefetch phase.
            self.get_stock_name(code, allow_realtime=False)

    def batch_get_stock_names(self, stock_codes: List[str]) -> Dict[str, str]:
        """
        Fetch Chinese stock names in bulk
        
        Tries the stock list from data sources that support bulk queries first,
        then queries the remaining names one by one.
        
        Args:
            stock_codes: list of stock codes
            
        Returns:
            A {stock code: stock name} dict
        """
        result = {}
        missing_codes = set(stock_codes)
        
        # 1. Check the cache first
        self._ensure_concurrency_guards()
        with self._stock_name_cache_lock:
            for code in stock_codes:
                cached_name = self._stock_name_cache.get(code)
                if cached_name is not None:
                    result[code] = cached_name
                    missing_codes.discard(code)
        
        if not missing_codes:
            return result
        
        # 2. Try the bulk stock-list fetch
        for fetcher in self._get_fetchers_snapshot():
            if not hasattr(fetcher, 'get_stock_list') or not missing_codes:
                continue
            if not self._is_fetcher_available(fetcher, capability="stock_list"):
                continue
            try:
                stock_list = self._call_fetcher_method(fetcher, 'get_stock_list')
                if stock_list is not None and not stock_list.empty:
                    cache_updates: Dict[str, str] = {}
                    for _, row in stock_list.iterrows():
                        code = row.get('code')
                        name = row.get('name')
                        if code and name:
                            cache_updates[code] = name
                            if code in missing_codes:
                                result[code] = name
                                missing_codes.discard(code)

                    if cache_updates:
                        with self._stock_name_cache_lock:
                            self._stock_name_cache.update(cache_updates)
                    
                    if not missing_codes:
                        break
                    
                    logger.info(f"[stock name] from {fetcher.name} batch fetch finished, remaining {len(missing_codes)} pending lookups")
            except Exception as e:
                logger.debug(f"[stock name] {fetcher.name} batch fetch failed: {e}")
                continue
        
        # 3. Fetch the rest one by one
        for code in list(missing_codes):
            name = self.get_stock_name(code)
            if name:
                result[code] = name
                missing_codes.discard(code)
        
        logger.info(f"[stock name] batch fetch finished, succeeded {len(result)}/{len(stock_codes)}")
        return result

    def get_main_indices(self, region: str = "us") -> List[Dict[str, Any]]:
        """Fetch main index real-time quotes (with automatic data source failover)"""
        for fetcher in self._fetchers:
            try:
                data = fetcher.get_main_indices(region=region)
                if data:
                    logger.info(f"[{fetcher.name}] index quotes fetched")
                    return data
            except Exception as e:
                logger.warning(f"[{fetcher.name}] fetching index quotes failed: {e}")
                continue
        return []

    def _run_with_timeout(
        self,
        task: Callable[[], Any],
        timeout_seconds: float,
        task_name: str,
    ) -> Tuple[Optional[Any], Optional[str], int]:
        """
        Execute a task in a short-lived thread and enforce a timeout.

        Returns:
            (result, error, duration_ms)
        """
        start = time.time()
        timeout_value = max(0.0, timeout_seconds)
        if timeout_value <= 0:
            return None, f"{task_name} timeout", 0
        result_holder: Dict[str, Any] = {}
        error_holder: Dict[str, Exception] = {}

        if not self._fundamental_timeout_slots.acquire(blocking=False):
            return None, f"{task_name} timeout worker pool exhausted", int(timeout_value * 1000)

        def runner() -> None:
            try:
                result_holder["value"] = task()
            except Exception as exc:
                error_holder["value"] = exc
            finally:
                try:
                    self._fundamental_timeout_slots.release()
                except ValueError:
                    pass

        worker = Thread(target=runner, daemon=True, name=f"fundamental-{task_name}")
        try:
            worker.start()
        except Exception as exc:
            try:
                self._fundamental_timeout_slots.release()
            except ValueError:
                pass
            return None, str(exc), int((time.time() - start) * 1000)
        worker.join(timeout=timeout_value)
        if worker.is_alive():
            return None, f"{task_name} timeout", int(timeout_value * 1000)
        if "value" in error_holder:
            return None, str(error_holder["value"]), int((time.time() - start) * 1000)
        return result_holder.get("value"), None, int((time.time() - start) * 1000)

    def _run_with_retry(
        self,
        task: Callable[[], Any],
        timeout_seconds: float,
        task_name: str,
    ) -> Tuple[Optional[Any], Optional[str], int]:
        """
        Execute a task with bounded budget and best-effort retries.

        Returns:
            (result, error, total_duration_ms)
        """
        config = self._get_fundamental_config()
        attempts = max(1, int(config.fundamental_retry_max))
        remaining_seconds = max(0.0, float(timeout_seconds))
        total_cost_ms = 0
        last_error: Optional[str] = None

        for _ in range(attempts):
            if remaining_seconds <= 0:
                break
            result, err, cost_ms = self._run_with_timeout(task, remaining_seconds, task_name)
            total_cost_ms += cost_ms
            remaining_seconds = max(0.0, remaining_seconds - cost_ms / 1000)
            if err is None:
                return result, None, total_cost_ms
            last_error = err
            if remaining_seconds <= 0:
                break

        return None, last_error, total_cost_ms

    def _get_fundamental_config(self):
        from src.config import get_config
        return get_config()

    @staticmethod
    def _normalize_source_chain(
        entries: Any,
        provider: str,
        result: str,
        duration_ms: int,
    ) -> List[Dict[str, Any]]:
        """Normalize free-form source chain entries to structured dict list."""
        if entries is None:
            return [{"provider": provider, "result": result, "duration_ms": duration_ms}]

        normalized: List[Dict[str, Any]] = []
        if not isinstance(entries, (list, tuple)):
            entries = [entries]

        for item in entries:
            if isinstance(item, dict):
                normalized.append({
                    "provider": str(item.get("provider") or provider),
                    "result": str(item.get("result") or result),
                    "duration_ms": int(item.get("duration_ms", duration_ms)),
                })
                continue

            if item is None:
                continue

            provider_name = str(item)
            normalized.append({
                "provider": provider_name,
                "result": result,
                "duration_ms": duration_ms,
            })

        if not normalized:
            return [{"provider": provider, "result": result, "duration_ms": duration_ms}]

        return normalized

    @staticmethod
    def _block_status(payload: Dict[str, Any], available: bool = True) -> str:
        if not available:
            return "not_supported"
        if not payload:
            return "partial"
        return "ok"

    @staticmethod
    def _build_fundamental_block(
        status: str,
        payload: Optional[Dict[str, Any]] = None,
        source_chain: Optional[List[Dict[str, Any]]] = None,
        errors: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        return {
            "status": status,
            "coverage": {"status": status},
            "source_chain": source_chain or [],
            "errors": errors or [],
            "data": payload or {},
        }

    @staticmethod
    def _has_meaningful_payload(payload: Any) -> bool:
        if payload is None:
            return False
        if isinstance(payload, str):
            normalized = payload.strip().lower()
            return normalized not in ("", "-", "nan", "none", "null", "n/a", "na")
        if isinstance(payload, dict):
            return any(DataFetcherManager._has_meaningful_payload(v) for v in payload.values())
        if isinstance(payload, pd.DataFrame):
            if payload.empty:
                return False
            return any(
                DataFetcherManager._has_meaningful_payload(v)
                for v in payload.to_numpy().flat
            )
        if isinstance(payload, (pd.Series, pd.Index)):
            return any(DataFetcherManager._has_meaningful_payload(v) for v in payload.tolist())
        if isinstance(payload, np.ndarray):
            if payload.ndim == 0:
                payload = payload.item()
            else:
                return any(
                    DataFetcherManager._has_meaningful_payload(v)
                    for v in payload.flat
                )
        if isinstance(payload, (list, tuple, set)):
            return any(DataFetcherManager._has_meaningful_payload(v) for v in payload)
        if DataFetcherManager._try_scalar_isna(payload, "fundamental_payload") is True:
            return False
        return True

    @staticmethod
    def _earnings_block_has_values(payload: Any) -> bool:
        """Field-level check for the earnings block.

        A truthy dict with only metadata (report_date/period/currency) is a
        shell, not usable earnings. Require a core numeric field (revenue /
        net_profit_parent / basic_eps / gross_profit) or a populated dividend
        section before treating the block as usable.
        """
        if not isinstance(payload, dict):
            return DataFetcherManager._has_meaningful_payload(payload)
        report = payload.get("financial_report")
        if isinstance(report, dict):
            for key in ("revenue", "net_profit_parent", "basic_eps", "gross_profit"):
                if DataFetcherManager._has_meaningful_payload(report.get(key)):
                    return True
        dividend = payload.get("dividend")
        if DataFetcherManager._has_meaningful_payload(dividend):
            return True
        # Fall back to the generic check for other earnings sub-blocks.
        for key in ("financial_reports", "indicators"):
            if key in payload and DataFetcherManager._has_meaningful_payload(payload.get(key)):
                return True
        return False

    @staticmethod
    def _infer_block_status(payload: Any, fallback_status: str) -> str:
        if DataFetcherManager._has_meaningful_payload(payload):
            return "ok"
        if fallback_status in ("failed", "partial", "not_supported"):
            return fallback_status
        return "partial"

    @staticmethod
    def _should_cache_fundamental_context(context: Any) -> bool:
        if not isinstance(context, dict):
            return False
        status = str(context.get("status", "")).strip().lower()
        if status == "ok":
            return True
        if status == "failed":
            return False
        for block in (
            "valuation",
            "growth",
            "earnings",
            "institution",
            "capital_flow",
            "dragon_tiger",
            "boards",
        ):
            payload = context.get(block, {})
            if isinstance(payload, dict) and DataFetcherManager._has_meaningful_payload(payload.get("data")):
                return True
        return False

    def _build_market_not_supported(self, market: str, reason: str) -> Dict[str, Any]:
        blocks = {
            "valuation": self._build_fundamental_block(
                "partial" if market == "etf" else "not_supported",
                {},
                [{"provider": "fundamental_pipeline", "result": "not_supported", "duration_ms": 0}],
                [reason],
            ),
            "growth": self._build_fundamental_block(
                "not_supported",
                {},
                [{"provider": "fundamental_pipeline", "result": "not_supported", "duration_ms": 0}],
                [reason],
            ),
            "earnings": self._build_fundamental_block(
                "not_supported",
                {},
                [{"provider": "fundamental_pipeline", "result": "not_supported", "duration_ms": 0}],
                [reason],
            ),
            "institution": self._build_fundamental_block(
                "not_supported",
                {},
                [{"provider": "fundamental_pipeline", "result": "not_supported", "duration_ms": 0}],
                [reason],
            ),
            "capital_flow": self._build_fundamental_block(
                "not_supported",
                {},
                [{"provider": "fundamental_pipeline", "result": "not_supported", "duration_ms": 0}],
                [reason],
            ),
            "dragon_tiger": self._build_fundamental_block(
                "not_supported",
                {},
                [{"provider": "fundamental_pipeline", "result": "not_supported", "duration_ms": 0}],
                [reason],
            ),
            "boards": self._build_fundamental_block(
                "not_supported",
                {},
                [{"provider": "fundamental_pipeline", "result": "not_supported", "duration_ms": 0}],
                [reason],
            ),
        }
        return {
            "market": market,
            "status": "partial" if market == "etf" else "not_supported",
            "coverage": {
                block: blocks[block]["status"] for block in blocks
            },
            "source_chain": [{"provider": "fundamental_pipeline", "result": "not_supported", "duration_ms": 0}],
            "errors": [reason],
            **blocks,
        }

    def _fetch_offshore_fundamental_bundle(
        self,
        stock_code: str,
        market: str,
        bundle_timeout: float,
    ) -> Tuple[Dict[str, Any], Optional[str], int, str]:
        """Fetch the fundamental bundle for offshore markets from yfinance.

        Returns (payload, error, duration_ms, provider_name).
        """
        payload, err, ms = self._run_with_retry(
            lambda: self._yfinance_fundamental_adapter.get_fundamental_bundle(stock_code),
            bundle_timeout,
            "fundamental_bundle_yfinance",
        )
        return payload or {}, err, ms, "fundamental_bundle_yfinance"

    def _build_offshore_fundamental_context(
        self,
        stock_code: str,
        market: str,
        budget_seconds: Optional[float] = None,
    ) -> Dict[str, Any]:
        """HK/US fundamental aggregation via yfinance.

        Mirrors :meth:`get_fundamental_context` but skips A-share-specific
        blocks (capital_flow, dragon_tiger, sector rankings). belong_boards is
        sourced from yfinance ``info.sector`` / ``info.industry``.

        Cache, retry and fail-open semantics intentionally match the CN path so
        upstream callers see the same shape regardless of market.
        """
        from src.config import get_config

        config = get_config()
        stage_timeout = float(
            budget_seconds if budget_seconds is not None else config.fundamental_stage_timeout_seconds
        )
        stage_timeout = max(0.0, stage_timeout)
        fetch_timeout = float(config.fundamental_fetch_timeout_seconds)
        fetch_timeout = max(0.0, fetch_timeout)

        cache_ttl = int(config.fundamental_cache_ttl_seconds)
        cache_max_entries = max(0, int(getattr(config, "fundamental_cache_max_entries", 256)))
        cache_key = self._get_fundamental_cache_key(stock_code, stage_timeout)
        if cache_ttl > 0:
            self._prune_fundamental_cache(cache_ttl, cache_max_entries)
            with self._fundamental_cache_lock:
                cache_item = self._fundamental_cache.get(cache_key)
                if cache_item:
                    age = time.time() - float(cache_item.get("ts", 0))
                    if age <= cache_ttl:
                        return cache_item.get("context", {})

        result_ctx: Dict[str, Any] = {
            "market": market,
            "provider": "yfinance",
            "as_of": datetime.now(timezone.utc).isoformat(),
            "data_quality": "unavailable",
            "missing_fields": [],
            "valuation": {},
            "growth": {},
            "earnings": {},
            "institution": {},
            "capital_flow": {},
            "dragon_tiger": {},
            "boards": {},
            "belong_boards": [],
            "coverage": {},
            "source_chain": [],
            "errors": [],
        }
        start_ts = time.time()

        # Valuation: reuse realtime quote payload — yfinance returns pe/pb in the
        # same shape as AkShare, so the existing block formatter still works.
        valuation_timeout = min(fetch_timeout, stage_timeout) if stage_timeout > 0 else 0
        if valuation_timeout > 0:
            quote_payload, valuation_err, valuation_ms = self._run_with_retry(
                lambda: self.get_realtime_quote(stock_code),
                valuation_timeout,
                "fundamental_valuation",
            )
        else:
            quote_payload, valuation_err, valuation_ms = None, "fundamental stage timeout", 0
        valuation_payload = {
            "pe_ratio": getattr(quote_payload, "pe_ratio", None) if quote_payload else None,
            "pb_ratio": getattr(quote_payload, "pb_ratio", None) if quote_payload else None,
            "total_mv": getattr(quote_payload, "total_mv", None) if quote_payload else None,
            "circ_mv": getattr(quote_payload, "circ_mv", None) if quote_payload else None,
        }
        valuation_status = self._infer_block_status(
            valuation_payload,
            "partial" if quote_payload is not None else "not_supported",
        )
        if valuation_status == "partial" and valuation_err and not self._has_meaningful_payload(valuation_payload):
            valuation_status = "failed"
        result_ctx["valuation"] = self._build_fundamental_block(
            valuation_status,
            valuation_payload,
            self._normalize_source_chain(
                [{"provider": "realtime_quote", "result": valuation_status, "duration_ms": valuation_ms}],
                "realtime_quote",
                valuation_status,
                valuation_ms,
            ),
            [valuation_err] if valuation_err else [],
        )

        # Fundamental bundle via yfinance.
        bundle_timeout = min(fetch_timeout, max(stage_timeout - (time.time() - start_ts), 0.0))
        if bundle_timeout <= 0:
            bundle_payload, bundle_err, bundle_ms = {}, "fundamental stage timeout", 0
            bundle_provider = "fundamental_bundle_yfinance"
        else:
            bundle_payload, bundle_err, bundle_ms, bundle_provider = (
                self._fetch_offshore_fundamental_bundle(
                    stock_code,
                    market,
                    bundle_timeout,
                )
            )
        if not isinstance(bundle_payload, dict):
            bundle_payload = {}

        bundle_chain = self._normalize_source_chain(
            bundle_payload.get("source_chain", []),
            bundle_provider,
            str(bundle_payload.get("status", "not_supported")),
            bundle_ms,
        )
        adapter_errors = list(bundle_payload.get("errors", []))
        if bundle_err:
            adapter_errors.append(bundle_err)

        growth_payload = bundle_payload.get("growth", {}) if isinstance(bundle_payload.get("growth"), dict) else {}
        earnings_payload = bundle_payload.get("earnings", {}) if isinstance(bundle_payload.get("earnings"), dict) else {}
        belong_boards = bundle_payload.get("belong_boards") if isinstance(bundle_payload.get("belong_boards"), list) else []

        growth_status = self._infer_block_status(growth_payload, str(bundle_payload.get("status", "not_supported")))
        earnings_status = self._infer_block_status(earnings_payload, str(bundle_payload.get("status", "not_supported")))

        result_ctx["growth"] = self._build_fundamental_block(
            growth_status,
            growth_payload,
            bundle_chain,
            list(adapter_errors),
        )
        result_ctx["earnings"] = self._build_fundamental_block(
            earnings_status,
            earnings_payload,
            bundle_chain,
            list(adapter_errors),
        )

        # capital_flow / dragon_tiger / boards: filled only when the bundle carries
        # them; everything else keeps not_supported (fail-open).
        bundle_capital_flow = (
            bundle_payload.get("capital_flow")
            if isinstance(bundle_payload.get("capital_flow"), dict) and bundle_payload.get("capital_flow")
            else {}
        )
        if bundle_capital_flow:
            result_ctx["capital_flow"] = self._build_fundamental_block(
                "ok" if bundle_capital_flow.get("latest") or bundle_capital_flow.get("rows") else "partial",
                bundle_capital_flow,
                bundle_chain,
                [],
            )
        else:
            result_ctx["capital_flow"] = self._build_fundamental_block(
                "not_supported",
                {},
                [{"provider": "fundamental_pipeline", "result": "not_supported", "duration_ms": 0}],
                ["not supported for this source"],
            )
        result_ctx["dragon_tiger"] = self._build_fundamental_block(
            "not_supported",
            {},
            [{"provider": "fundamental_pipeline", "result": "not_supported", "duration_ms": 0}],
            ["not supported for offshore market"],
        )
        bundle_boards = (
            bundle_payload.get("belong_boards")
            if isinstance(bundle_payload.get("belong_boards"), list) and bundle_payload.get("belong_boards")
            else []
        )
        if bundle_boards:
            result_ctx["boards"] = self._build_fundamental_block(
                "ok",
                {"boards": bundle_boards},
                bundle_chain,
                [],
            )
        else:
            result_ctx["boards"] = self._build_fundamental_block(
                "not_supported",
                {},
                [{"provider": "fundamental_pipeline", "result": "not_supported", "duration_ms": 0}],
                ["not supported for offshore market"],
            )

        # institution: no offshore market provides this block.
        institution_status = "not_supported"
        result_ctx["institution"] = self._build_fundamental_block(
            "not_supported",
            {},
            [{"provider": "fundamental_pipeline", "result": "not_supported", "duration_ms": 0}],
            ["not supported for offshore market"],
        )

        result_ctx["belong_boards"] = belong_boards or bundle_boards

        capital_flow_status = result_ctx["capital_flow"].get("status", "not_supported")
        boards_status = result_ctx["boards"].get("status", "not_supported")
        block_statuses = {
            "valuation": result_ctx["valuation"].get("status", "not_supported"),
            "growth": growth_status,
            "earnings": earnings_status,
            "institution": institution_status,
            "capital_flow": capital_flow_status,
            "dragon_tiger": "not_supported",
            "boards": boards_status,
        }
        result_ctx["coverage"] = block_statuses
        for block in ("valuation", "growth", "earnings", "institution", "capital_flow", "dragon_tiger", "boards"):
            result_ctx["errors"].extend(result_ctx[block].get("errors", []))
            result_ctx["source_chain"].extend(result_ctx[block].get("source_chain", []))

        active_statuses = {
            "valuation": valuation_status,
            "growth": growth_status,
            "earnings": earnings_status,
            "capital_flow": capital_flow_status,
            "boards": boards_status,
        }
        # Bundle capital_flow / boards count toward the overall status when they are available.
        status_values = list(active_statuses.values())
        if all(value == "not_supported" for value in status_values):
            result_ctx["status"] = "not_supported"
            result_ctx["data_quality"] = "unavailable"
        elif "failed" in status_values or "partial" in status_values:
            result_ctx["status"] = "partial"
            result_ctx["data_quality"] = "partial"
        else:
            result_ctx["status"] = "ok"
            result_ctx["data_quality"] = "ok"
        result_ctx["missing_fields"] = [
            block for block, status in active_statuses.items() if status != "ok"
        ]

        result_ctx["elapsed_ms"] = int((time.time() - start_ts) * 1000)
        if cache_ttl > 0 and self._should_cache_fundamental_context(result_ctx):
            with self._fundamental_cache_lock:
                self._fundamental_cache[cache_key] = {
                    "ts": time.time(),
                    "context": result_ctx,
                }
            self._prune_fundamental_cache(cache_ttl, cache_max_entries)
        return result_ctx

    def build_failed_fundamental_context(self, stock_code: str, reason: str) -> Dict[str, Any]:
        """Build a consistent failed-context payload for caller-side fallback."""
        market = _market_tag(stock_code)
        block_names = (
            "valuation",
            "growth",
            "earnings",
            "institution",
            "capital_flow",
            "dragon_tiger",
            "boards",
        )
        blocks = {
            block: self._build_fundamental_block(
                "failed",
                {},
                [{"provider": "fundamental_pipeline", "result": "failed", "duration_ms": 0}],
                [reason],
            )
            for block in block_names
        }
        return {
            "market": market,
            "status": "failed",
            "coverage": {block: "failed" for block in block_names},
            "source_chain": [{"provider": "fundamental_pipeline", "result": "failed", "duration_ms": 0}],
            "errors": [reason],
            **blocks,
        }

    def build_not_supported_fundamental_context(
        self, stock_code: str, reason: str
    ) -> Dict[str, Any]:
        """Build a consistent not-supported payload without calling providers."""
        return self._build_market_not_supported(_market_tag(stock_code), reason)

    def get_fundamental_context(
        self,
        stock_code: str,
        budget_seconds: Optional[float] = None
    ) -> Dict[str, Any]:
        """
        Aggregate fundamental blocks with fail-open semantics.
        """
        from src.config import get_config

        config = get_config()
        if not config.enable_fundamental_pipeline:
            return self._build_market_not_supported(
                market=_market_tag(stock_code),
                reason="fundamental pipeline disabled",
            )

        stock_code = normalize_stock_code(stock_code)
        market = _market_tag(stock_code)
        return self._build_offshore_fundamental_context(
            stock_code,
            market=market,
            budget_seconds=budget_seconds,
        )

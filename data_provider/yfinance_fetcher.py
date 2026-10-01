# -*- coding: utf-8 -*-
"""
===================================
YfinanceFetcher - Fallback data source (Priority 4)
===================================

Data source: Yahoo Finance (via the yfinance library)
Strengths: international coverage, though data may lag or be missing
Role: the last safety net when every domestic data source has failed

Key strategies:
1. Convert HK codes to yfinance format automatically (.HK); US and suffix-market codes pass through
2. Absorb Yahoo Finance data-format differences
3. Retry with exponential backoff on failure
"""

import csv
import logging
from datetime import datetime
from io import StringIO
from typing import Optional, List, Dict, Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import pandas as pd
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
    before_sleep_log,
)

from .base import BaseFetcher, DataFetchError, STANDARD_COLUMNS, _is_hk_market
from .realtime_types import UnifiedRealtimeQuote, RealtimeSource
from .us_index_mapping import get_us_index_yf_symbol, is_us_stock_code
from .yfinance_fundamental_adapter import _safe_float
from src.services.market_symbol_utils import get_suffix_market, is_suffix_market_symbol

# Optional import of the local stock mapping patch; fall back to an empty dict when absent
try:
    from src.data.stock_mapping import STOCK_NAME_MAP, is_meaningful_stock_name
except (ImportError, ModuleNotFoundError):
    STOCK_NAME_MAP = {}

    def is_meaningful_stock_name(name: str | None, stock_code: str) -> bool:
        """Simple fallback check that a name looks valid"""
        if not name:
            return False
        n = str(name).strip()
        return bool(n and n.upper() != str(stock_code).strip().upper())

import os

logger = logging.getLogger(__name__)


class YfinanceFetcher(BaseFetcher):
    """
    Yahoo Finance data source implementation

    Priority: 4 (lowest, used as the fallback)
    Data source: Yahoo Finance

    Key strategies:
    - Convert the stock code format automatically
    - Absorb time-zone and data-format differences
    - Retry with exponential backoff on failure

    Caveats:
    - A-share data may lag
    - Some stocks may have no data at all
    - Precision may differ slightly from domestic sources
    """

    name = "YfinanceFetcher"
    priority = int(os.getenv("YFINANCE_PRIORITY", "4"))

    def __init__(self):
        """Initialise YfinanceFetcher"""
        pass

    @staticmethod
    def _is_suffix_market_stock(stock_code: str) -> bool:
        """Return True for supported suffix-only Yahoo symbols of any registered suffix market."""
        return is_suffix_market_symbol(stock_code)

    def _convert_stock_code(self, stock_code: str) -> str:
        """
        Convert a stock code to Yahoo Finance format

        Yahoo Finance code formats:
        - HK stocks: 0700.HK (Hong Kong Stock Exchange)
        - US stocks: AAPL, TSLA, GOOGL (no suffix needed)
        - Canadian stocks: RY.TO, ABX.V (Yahoo suffix passes through)

        Args:
            stock_code: raw code, e.g. 'hk00700', 'AAPL', 'RY.TO'

        Returns:
            The Yahoo Finance-formatted code

        Examples:
            >>> fetcher._convert_stock_code('hk00700')
            '0700.HK'
            >>> fetcher._convert_stock_code('AAPL')
            'AAPL'
        """
        code = stock_code.strip().upper()

        # US indices: map to the Yahoo Finance symbol (e.g. SPX -> ^GSPC)
        yf_symbol, _ = get_us_index_yf_symbol(code)
        if yf_symbol:
            logger.debug(f"recognized as a US index: {code} -> {yf_symbol}")
            return yf_symbol

        # US stocks: 1-5 uppercase letters (optional .X suffix), returned unchanged
        if is_us_stock_code(code):
            logger.debug(f"recognized as a US stock code: {code}")
            return code

        # Explicit Yahoo Finance suffix-only codes of registered suffix markets are passed through as-is.
        if self._is_suffix_market_stock(code):
            logger.debug(f"recognized as a Yahoo suffix-market code: {code}")
            return code

        # HK stocks: hk prefix -> .HK suffix
        if code.startswith('HK'):
            hk_code = code[2:].lstrip('0') or '0'  # strip leading zeros, but keep at least one
            hk_code = hk_code.zfill(4)  # pad back out to 4 digits
            logger.debug(f"converted HK code: {stock_code} -> {hk_code}.HK")
            return f"{hk_code}.HK"

        # Bare HK codes: 4-5 pure digits (e.g. 00700, 02513, 0001) are treated as HK stocks. See issue #2091.
        if code.isdigit() and 4 <= len(code) <= 5:
            hk_code = code.lstrip('0') or '0'
            hk_code = hk_code.zfill(4)
            logger.debug(f"recognized a bare HK stock code: {stock_code} -> {hk_code}.HK")
            return f"{hk_code}.HK"

        # Codes that already carry the HK suffix pass through
        if '.HK' in code:
            return code

        # Anything else (for example a mainland China code, which is no longer supported) is passed
        # through unchanged so Yahoo Finance reports it as not found instead of guessing an exchange.
        logger.warning(f"[Yfinance] cannot determine the Yahoo Finance symbol for {code}; passing it through unchanged")
        return code

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=30),
        retry=retry_if_exception_type((ConnectionError, TimeoutError)),
        before_sleep=before_sleep_log(logger, logging.WARNING),
    )
    def _fetch_raw_data(self, stock_code: str, start_date: str, end_date: str) -> pd.DataFrame:
        """
        Fetch raw data from Yahoo Finance

        Uses yfinance.download() to fetch history

        Flow:
        1. Convert the stock code format
        2. Call the yfinance API
        3. Post-process the returned data
        """
        import yfinance as yf

        # Convert the code format
        yf_code = self._convert_stock_code(stock_code)

        logger.debug(f"calling yfinance.download({yf_code}, {start_date}, {end_date})")

        try:
            # Download the data through yfinance
            df = yf.download(
                tickers=yf_code,
                start=start_date,
                end=end_date,
                progress=False,  # suppress the progress bar
                auto_adjust=True,  # auto-adjust prices (corporate actions)
                multi_level_index=True
            )

            # Select only the yf_code columns to avoid mixing several stocks together
            if isinstance(df.columns, pd.MultiIndex) and len(df.columns) > 1:
                ticker_level = df.columns.get_level_values(1)
                mask = ticker_level == yf_code
                if mask.any():
                    df = df.loc[:, mask].copy()

            if df.empty:
                raise DataFetchError(f"Yahoo Finance 未查询到 {stock_code} 的数据")

            return df

        except Exception as e:
            if isinstance(e, DataFetchError):
                raise
            raise DataFetchError(f"Yahoo Finance 获取数据失败: {e}") from e

    def _normalize_data(self, df: pd.DataFrame, stock_code: str) -> pd.DataFrame:
        """
        Normalise Yahoo Finance data

        Column names returned by yfinance:
        Open, High, Low, Close, Volume (the index is the date)

        Note: recent yfinance versions return MultiIndex columns, e.g. ('Close', 'AMD')
        which must be flattened before further processing

        Mapped onto the standard column names:
        date, open, high, low, close, volume, amount, pct_chg
        """
        df = df.copy()

        # Handle MultiIndex columns (the format newer yfinance returns)
        # e.g. ('Close', 'AMD') -> 'Close'
        if isinstance(df.columns, pd.MultiIndex):
            logger.debug("MultiIndex columns detected, flattening")
            # Take the first level (Price level: Close, High, Low, etc.)
            df.columns = df.columns.get_level_values(0)

        # Reset the index so the date becomes a column
        df = df.reset_index()

        # Column mapping (yfinance capitalises the first letter)
        column_mapping = {
            'Date': 'date',
            'Datetime': 'date',
            'datetime': 'date',
            'Open': 'open',
            'High': 'high',
            'Low': 'low',
            'Close': 'close',
            'Volume': 'volume',
        }

        df = df.rename(columns=column_mapping)
        if 'date' not in df.columns:
            index_col = df.columns[0] if len(df.columns) else None
            if index_col is not None:
                candidate = df[index_col]
                if pd.api.types.is_datetime64_any_dtype(candidate):
                    df = df.rename(columns={index_col: 'date'})
                elif not pd.api.types.is_numeric_dtype(candidate):
                    parsed_dates = pd.to_datetime(candidate, errors='coerce')
                    if parsed_dates.notna().any():
                        df = df.rename(columns={index_col: 'date'})
                        df['date'] = parsed_dates

        # Compute the percentage change (yfinance does not supply it)
        if 'close' in df.columns:
            df['pct_chg'] = df['close'].pct_change() * 100
            df['pct_chg'] = df['pct_chg'].fillna(0).round(2)

        # Compute turnover (yfinance does not supply it, so estimate)
        # turnover ~= volume * average price
        if 'volume' in df.columns and 'close' in df.columns:
            df['amount'] = df['volume'] * df['close']
        else:
            df['amount'] = 0

        # Add the stock code column
        df['code'] = stock_code

        # Keep only the columns we need
        keep_cols = ['code'] + STANDARD_COLUMNS
        existing_cols = [col for col in keep_cols if col in df.columns]
        df = df[existing_cols]

        return df

    def _fetch_yf_ticker_data(self, yf, yf_code: str, name: str, return_code: str) -> Optional[Dict[str, Any]]:
        """
        Fetch quote data for a single index or stock through yfinance.

        Args:
            yf: reference to the yfinance module
            yf_code: the code yfinance uses (e.g. '000001.SS', '^GSPC')
            name: display name of the index
            return_code: the code field written into the result dict (e.g. 'sh000001', 'SPX')

        Returns:
            A quote dict, or None on failure
        """
        ticker = yf.Ticker(yf_code)
        # Take the last two days so the percentage change can be computed
        hist = ticker.history(period='2d')
        if hist.empty:
            return None
        today_row = hist.iloc[-1]
        prev_row = hist.iloc[-2] if len(hist) > 1 else today_row
        price = float(today_row['Close'])
        prev_close = float(prev_row['Close'])
        change = price - prev_close
        change_pct = (change / prev_close) * 100 if prev_close else 0
        high = float(today_row['High'])
        low = float(today_row['Low'])
        # amplitude = (high - low) / previous close * 100
        amplitude = ((high - low) / prev_close * 100) if prev_close else 0
        return {
            'code': return_code,
            'name': name,
            'current': price,
            'change': change,
            'change_pct': change_pct,
            'open': float(today_row['Open']),
            'high': high,
            'low': low,
            'prev_close': prev_close,
            'volume': float(today_row['Volume']),
            'amount': 0.0,  # Yahoo Finance does not provide an accurate turnover
            'amplitude': amplitude,
        }

    def get_main_indices(self, region: str = "us") -> Optional[List[Dict[str, Any]]]:
        """
        Fetch the main index quotes (Yahoo Finance) for the US, HK and Canadian markets.
        region=us delegates to _get_us_main_indices.
        region=hk delegates to _get_hk_main_indices.
        region=ca delegates to _get_ca_main_indices.
        """
        import yfinance as yf

        if region == "us":
            return self._get_us_main_indices(yf)
        if region == "hk":
            return self._get_hk_main_indices(yf)
        if region == "ca":
            return self._get_ca_main_indices(yf)

        return None

    def _get_us_main_indices(self, yf) -> Optional[List[Dict[str, Any]]]:
        """Fetch the main US index quotes (SPX, IXIC, DJI, VIX) by reusing _fetch_yf_ticker_data"""
        # Core US indices needed for the broad-market review
        us_indices = ['SPX', 'IXIC', 'DJI', 'VIX']
        results = []
        try:
            for code in us_indices:
                yf_symbol, name = get_us_index_yf_symbol(code)
                if not yf_symbol:
                    continue
                try:
                    item = self._fetch_yf_ticker_data(yf, yf_symbol, name, code)
                    if item:
                        results.append(item)
                        logger.debug(f"[Yfinance] fetching US index {name} succeeded")
                except Exception as e:
                    logger.warning(f"[Yfinance] fetching US index {name} failed: {e}")

            if results:
                logger.info(f"[Yfinance] fetched {len(results)} US index quotes")
                return results

        except Exception as e:
            logger.error(f"[Yfinance] fetching US index quotes failed: {e}")

        return None

    def _get_ca_main_indices(self, yf) -> Optional[List[Dict[str, Any]]]:
        """Fetch the main Canadian index quotes (S&P/TSX Composite, TSX Venture) via _fetch_yf_ticker_data"""
        # Yahoo Finance symbols: ^GSPTSE is the S&P/TSX Composite and ^SPCDNX the S&P/TSX Venture
        # Composite. Codes are what MarketProfile.mood_index_code (CA_PROFILE: TSX) matches against.
        ca_indices = {
            'TSX': ('^GSPTSE', 'S&P/TSX Composite'),
            'TSXV': ('^SPCDNX', 'S&P/TSX Venture Composite'),
        }
        results = []
        try:
            for code, (yf_symbol, name) in ca_indices.items():
                try:
                    item = self._fetch_yf_ticker_data(yf, yf_symbol, name, code)
                    if item:
                        results.append(item)
                        logger.debug(f"[Yfinance] fetching CA index {name} succeeded")
                except Exception as e:
                    logger.warning(f"[Yfinance] fetching CA index {name} failed: {e}")

            if results:
                logger.info(f"[Yfinance] fetched {len(results)} CA index quotes")
                return results

        except Exception as e:
            logger.error(f"[Yfinance] fetching CA index quotes failed: {e}")

        return None

    def _get_hk_main_indices(self, yf) -> Optional[List[Dict[str, Any]]]:
        """Fetch the main HK index quotes (HSI, HSTECH, HSCEI) by reusing _fetch_yf_ticker_data"""
        # Yahoo Finance HK index symbol mapping:
        # - HSI -> ^HSI
        # - HSTECH -> HSTECH.HK (not ^HSTECH)
        # - HSCEI -> ^HSCE (not ^HSCEI)
        # Pinned by the offline unit test tests/test_yfinance_hk_indices.py so no online dependency makes it flaky.
        hk_indices = {
            'HSI': ('^HSI', '恒生指数'),
            'HSTECH': ('HSTECH.HK', '恒生科技指数'),
            'HSCEI': ('^HSCE', '国企指数'),
        }
        results = []
        try:
            for code, (yf_symbol, name) in hk_indices.items():
                try:
                    item = self._fetch_yf_ticker_data(yf, yf_symbol, name, code)
                    if item:
                        results.append(item)
                        logger.debug(f"[Yfinance] fetching HK index {name} succeeded")
                except Exception as e:
                    logger.warning(f"[Yfinance] fetching HK index {name} failed: {e}")

            if results:
                logger.info(f"[Yfinance] fetched {len(results)} HK index quotes")
                return results

        except Exception as e:
            logger.error(f"[Yfinance] fetching HK index quotes failed: {e}")

        return None

    def _is_us_stock(self, stock_code: str) -> bool:
        """
        Decide whether a code is a US stock (US indices excluded).

        Delegates to is_us_stock_code() in the us_index_mapping module.
        """
        return is_us_stock_code(stock_code)

    def _get_us_stock_quote_from_stooq(self, stock_code: str) -> Optional[UnifiedRealtimeQuote]:
        """
        Use Stooq as a key-free fallback for US real-time quotes.

        Stooq returns the latest trading day rather than intraday ticks, so it is less precise,
        but when Yahoo / yfinance is rate-limited it at least gives the web UI a usable price; derived metrics such as the percentage change follow when a previous close is available.
        """
        symbol = stock_code.strip().upper()
        stooq_symbol = f"{symbol.lower()}.us"
        url = f"https://stooq.com/q/l/?s={stooq_symbol}"
        request = Request(
            url,
            headers={
                "User-Agent": "Mozilla/5.0 (compatible; DSA/1.0; +https://github.com/ZhuLinsen/daily_stock_analysis)",
                "Accept": "text/plain,text/csv,*/*",
            },
        )

        try:
            with urlopen(request, timeout=15) as response:
                payload = response.read().decode("utf-8", "ignore").strip()
        except (HTTPError, URLError, TimeoutError) as exc:
            logger.warning(f"[Stooq] fetching US stock {symbol} realtime quote failed: {exc}")
            return None

        if not payload or payload.upper().startswith("NO DATA"):
            logger.warning(f"[Stooq] cannot fetch {symbol} quote data")
            return None

        def _fetch_prev_close() -> Optional[float]:
            history_url = f"https://stooq.com/q/d/l/?s={stooq_symbol}&i=d"
            history_request = Request(
                history_url,
                headers={
                    "User-Agent": "Mozilla/5.0 (compatible; DSA/1.0; +https://github.com/ZhuLinsen/daily_stock_analysis)",
                    "Accept": "text/plain,text/csv,*/*",
                },
            )
            try:
                with urlopen(history_request, timeout=15) as response:
                    history_payload = response.read().decode("utf-8", "ignore").strip()
            except (HTTPError, URLError, TimeoutError) as exc:
                logger.debug(f"[Stooq] fetching US stock {symbol} daily history failed: {exc}")
                return None

            if not history_payload or history_payload.upper().startswith("NO DATA"):
                return None

            try:
                reader = csv.reader(StringIO(history_payload))
                header = next(reader, None)
                if not header:
                    return None

                header_tokens = [cell.strip().lower() for cell in header]
                has_header = "close" in header_tokens and "date" in header_tokens
                if not has_header:
                    return None

                date_index = header_tokens.index("date")
                close_index = header_tokens.index("close")

                daily_rows: list[tuple[datetime, float]] = []
                for row in reader:
                    if not row:
                        continue
                    date_text = row[date_index].strip() if len(row) > date_index else ""
                    close_text = row[close_index].strip() if len(row) > close_index else ""
                    if not date_text or not close_text:
                        continue
                    try:
                        dt = datetime.strptime(date_text, "%Y-%m-%d")
                        close_val = float(close_text)
                    except Exception:
                        continue
                    daily_rows.append((dt, close_val))

                if len(daily_rows) < 2:
                    return None

                daily_rows.sort(key=lambda item: item[0])
                return daily_rows[-2][1]
            except Exception:
                return None

        try:
            reader = csv.reader(StringIO(payload))
            first_row = next(reader, None)
            if first_row is None:
                raise ValueError(f"unexpected Stooq payload: {payload}")

            normalized_first_row = [cell.strip() for cell in first_row]
            header_tokens = {cell.lower() for cell in normalized_first_row if cell}
            has_header = 'open' in header_tokens and 'close' in header_tokens
            row = next(reader, None) if has_header else first_row
            if row is None:
                raise ValueError(f"unexpected Stooq payload: {payload}")

            normalized_row = [cell.strip() for cell in row]
            while normalized_row and normalized_row[-1] == '':
                normalized_row.pop()

            if len(normalized_row) >= 8:
                open_index, high_index, low_index, price_index, volume_index = 3, 4, 5, 6, 7
            elif len(normalized_row) >= 7:
                open_index, high_index, low_index, price_index, volume_index = 2, 3, 4, 5, 6
            else:
                raise ValueError(f"unexpected Stooq payload: {payload}")

            open_price = float(normalized_row[open_index])
            high = float(normalized_row[high_index])
            low = float(normalized_row[low_index])
            price = float(normalized_row[price_index])
            volume = int(float(normalized_row[volume_index]))

            prev_close = _fetch_prev_close()
            change_amount = None
            change_pct = None
            amplitude = None
            if prev_close is not None and prev_close > 0:
                change_amount = price - prev_close
                change_pct = (change_amount / prev_close) * 100
                amplitude = ((high - low) / prev_close) * 100

            quote = UnifiedRealtimeQuote(
                code=symbol,
                name=STOCK_NAME_MAP.get(symbol, ''),
                source=RealtimeSource.STOOQ,
                price=price,
                change_pct=round(change_pct, 2) if change_pct is not None else None,
                change_amount=round(change_amount, 4) if change_amount is not None else None,
                volume=volume,
                amount=None,
                volume_ratio=None,
                turnover_rate=None,
                amplitude=round(amplitude, 2) if amplitude is not None else None,
                open_price=open_price,
                high=high,
                low=low,
                pre_close=prev_close,
                pe_ratio=None,
                pb_ratio=None,
                total_mv=None,
                circ_mv=None,
            )
            logger.info(f"[Stooq] fetching US stock {symbol} fallback quote succeeded: price={price}")
            return quote
        except Exception as exc:
            logger.warning(f"[Stooq] parsing US stock {symbol} quotes failed: {exc}")
            return None

    def _get_us_index_realtime_quote(
        self,
        user_code: str,
        yf_symbol: str,
        index_name: str,
    ) -> Optional[UnifiedRealtimeQuote]:
        """
        Get realtime quote for US index (e.g. SPX -> ^GSPC).

        Args:
            user_code: User input code (e.g. SPX)
            yf_symbol: Yahoo Finance symbol (e.g. ^GSPC)
            index_name: Chinese name for the index

        Returns:
            UnifiedRealtimeQuote or None
        """
        import yfinance as yf

        try:
            logger.debug(f"[Yfinance] fetching US index {user_code} ({yf_symbol}) realtime quote")
            ticker = yf.Ticker(yf_symbol)

            try:
                info = ticker.fast_info
                if info is None:
                    raise ValueError("fast_info is None")
                price = getattr(info, 'lastPrice', None) or getattr(info, 'last_price', None)
                prev_close = getattr(info, 'previousClose', None) or getattr(info, 'previous_close', None)
                open_price = getattr(info, 'open', None)
                high = getattr(info, 'dayHigh', None) or getattr(info, 'day_high', None)
                low = getattr(info, 'dayLow', None) or getattr(info, 'day_low', None)
                volume = getattr(info, 'lastVolume', None) or getattr(info, 'last_volume', None)
            except Exception:
                logger.debug("[Yfinance] fast_info failed, trying the history method")
                hist = ticker.history(period='2d')
                if hist.empty:
                    logger.warning(f"[Yfinance] cannot fetch {yf_symbol} data")
                    return None
                today = hist.iloc[-1]
                prev = hist.iloc[-2] if len(hist) > 1 else today
                price = float(today['Close'])
                prev_close = float(prev['Close'])
                open_price = float(today['Open'])
                high = float(today['High'])
                low = float(today['Low'])
                volume = int(today['Volume'])

            change_amount = None
            change_pct = None
            if price is not None and prev_close is not None and prev_close > 0:
                change_amount = price - prev_close
                change_pct = (change_amount / prev_close) * 100

            amplitude = None
            if high is not None and low is not None and prev_close is not None and prev_close > 0:
                amplitude = ((high - low) / prev_close) * 100

            try:
                ticker_info = ticker.info or {}
            except Exception:
                ticker_info = {}
            missing_fields = [
                field
                for field, value in {
                    "price": price,
                    "prev_close": prev_close,
                    "volume": volume,
                    "amount": None,
                    "pe_ratio": None,
                    "pb_ratio": None,
                }.items()
                if value is None
            ]

            quote = UnifiedRealtimeQuote(
                code=user_code,
                name=index_name or user_code,
                source=RealtimeSource.FALLBACK,
                market="us",
                currency=str(ticker_info.get("currency") or "").upper() or None,
                data_quality="partial" if missing_fields else "ok",
                missing_fields=missing_fields or None,
                price=price,
                change_pct=round(change_pct, 2) if change_pct is not None else None,
                change_amount=round(change_amount, 4) if change_amount is not None else None,
                volume=volume,
                amount=None,
                volume_ratio=None,
                turnover_rate=None,
                amplitude=round(amplitude, 2) if amplitude is not None else None,
                open_price=open_price,
                high=high,
                low=low,
                pre_close=prev_close,
                pe_ratio=None,
                pb_ratio=None,
                total_mv=None,
                circ_mv=None,
            )
            logger.info(f"[Yfinance] fetching US index {user_code} realtime quote succeeded: price={price}")
            return quote
        except Exception as e:
            logger.warning(f"[Yfinance] fetching US index {user_code} realtime quote failed: {e}")
            return None

    def get_realtime_quote(self, stock_code: str) -> Optional[UnifiedRealtimeQuote]:
        """
        Fetch real-time quote data for US and HK stocks or US indices

        Supports US stocks (AAPL, TSLA) and US indices (SPX, DJI, and so on).
        Data source: yfinance Ticker.info

        Args:
            stock_code: a US stock or index code, e.g. 'AMD', 'AAPL', 'SPX', 'DJI'

        Returns:
            A UnifiedRealtimeQuote object, or None on failure
        """
        import yfinance as yf

        # US indices: use the mapping (SPX -> ^GSPC)
        yf_symbol, index_name = get_us_index_yf_symbol(stock_code)
        if yf_symbol:
            return self._get_us_index_realtime_quote(
                user_code=stock_code.strip().upper(),
                yf_symbol=yf_symbol,
                index_name=index_name,
            )

        # Only handle US, HK or registered suffix-market stocks
        if not (
            self._is_us_stock(stock_code)
            or _is_hk_market(stock_code)
            or self._is_suffix_market_stock(stock_code)
        ):
            logger.debug(f"[Yfinance] {stock_code} is not a supported US, HK or suffix-market code, skipping")
            return None

        try:
            symbol = self._convert_stock_code(stock_code)
            is_us_symbol = self._is_us_stock(symbol)
            suffix_market = get_suffix_market(symbol)
            logger.debug(f"[Yfinance] fetching {symbol} realtime quote")

            ticker = yf.Ticker(symbol)

            # Try fast_info first (faster, but fewer fields)
            try:
                info = ticker.fast_info
                if info is None:
                    raise ValueError("fast_info is None")

                price = getattr(info, 'lastPrice', None) or getattr(info, 'last_price', None)
                prev_close = getattr(info, 'previousClose', None) or getattr(info, 'previous_close', None)
                open_price = getattr(info, 'open', None)
                high = getattr(info, 'dayHigh', None) or getattr(info, 'day_high', None)
                low = getattr(info, 'dayLow', None) or getattr(info, 'day_low', None)
                volume = getattr(info, 'lastVolume', None) or getattr(info, 'last_volume', None)
                market_cap = getattr(info, 'marketCap', None) or getattr(info, 'market_cap', None)

            except Exception:
                # Fall back to the history method for the latest data
                logger.debug("[Yfinance] fast_info failed, trying the history method")
                hist = ticker.history(period='2d')
                if hist.empty:
                    if is_us_symbol:
                        logger.warning(f"[Yfinance] cannot fetch {symbol} data, trying the Stooq fallback")
                        return self._get_us_stock_quote_from_stooq(symbol)
                    logger.warning(f"[Yfinance] cannot fetch {symbol} data")
                    return None

                today = hist.iloc[-1]
                prev = hist.iloc[-2] if len(hist) > 1 else today

                price = float(today['Close'])
                prev_close = float(prev['Close'])
                open_price = float(today['Open'])
                high = float(today['High'])
                low = float(today['Low'])
                volume = int(today['Volume'])
                market_cap = None

            # Compute the percentage change
            change_amount = None
            change_pct = None
            if price is not None and prev_close is not None and prev_close > 0:
                change_amount = price - prev_close
                change_pct = (change_amount / prev_close) * 100

            # Compute the amplitude
            amplitude = None
            if high is not None and low is not None and prev_close is not None and prev_close > 0:
                amplitude = ((high - low) / prev_close) * 100

            # Fetch the stock name and provider metadata
            try:
                ticker_info = ticker.info or {}
            except Exception:
                ticker_info = {}
            try:
                info_name = ticker_info.get('shortName', '') or ticker_info.get('longName', '') or ''
                name = info_name if is_meaningful_stock_name(info_name, symbol) else STOCK_NAME_MAP.get(symbol, '')
            except Exception:
                name = STOCK_NAME_MAP.get(symbol, '')

            # Reuse the ticker_info fetched above; no extra request
            pe_ratio = _safe_float(ticker_info.get('trailingPE'))
            pb_ratio = _safe_float(ticker_info.get('priceToBook'))

            missing_fields = [
                field
                for field, value in {
                    "price": price,
                    "prev_close": prev_close,
                    "volume": volume,
                    "amount": None,
                    "pe_ratio": pe_ratio,
                    "pb_ratio": pb_ratio,
                }.items()
                if value is None
            ]
            quote = UnifiedRealtimeQuote(
                code=symbol,
                name=name,
                source=RealtimeSource.FALLBACK,
                market=suffix_market or ("hk" if _is_hk_market(stock_code) else "us" if is_us_symbol else None),
                currency=str(ticker_info.get("currency") or "").upper() or None,
                data_quality="partial" if missing_fields else "ok",
                missing_fields=missing_fields or None,
                price=price,
                change_pct=round(change_pct, 2) if change_pct is not None else None,
                change_amount=round(change_amount, 4) if change_amount is not None else None,
                volume=volume,
                amount=None,  # yfinance does not provide turnover directly
                volume_ratio=None,
                turnover_rate=None,
                amplitude=round(amplitude, 2) if amplitude is not None else None,
                open_price=open_price,
                high=high,
                low=low,
                pre_close=prev_close,
                pe_ratio=pe_ratio,
                pb_ratio=pb_ratio,
                total_mv=market_cap,
                circ_mv=None,
            )

            logger.info(f"[Yfinance] fetching {symbol} realtime quote succeeded: price={price}")
            return quote

        except Exception as e:
            if self._is_us_stock(stock_code):
                logger.warning(f"[Yfinance] fetching US stock {stock_code} realtime quote failed: {e}, trying the Stooq fallback")
                return self._get_us_stock_quote_from_stooq(stock_code)
            logger.warning(f"[Yfinance] fetching {stock_code} realtime quote failed: {e}")
            return None


if __name__ == "__main__":
    # Manual test harness
    logging.basicConfig(level=logging.DEBUG)

    fetcher = YfinanceFetcher()

    try:
        df = fetcher.get_daily_data('600519')  # 茅台
        print(f"获取成功，共 {len(df)} 条数据")
        print(df.tail())
    except Exception as e:
        print(f"获取失败: {e}")

# -*- coding: utf-8 -*-
"""
===================================
Unified real-time quote types and the circuit breaker
===================================

Design goals:
1. Unify the real-time quote structure returned by every data source
2. Provide a circuit-breaker and cooldown so repeated failures stop re-requesting
3. Support failover across multiple data sources

Usage:
- Every fetcher's get_realtime_quote() returns a UnifiedRealtimeQuote
- CircuitBreaker manages the breaker state of each data source
"""

import logging
import time
from threading import RLock
from dataclasses import dataclass, field
from typing import Optional, Dict, Any, Union
from enum import Enum

logger = logging.getLogger(__name__)


# ============================================
# Generic type conversion helpers
# ============================================
# Design note:
# Data sources return inconsistent raw types (str/float/int/NaN), so these helpers convert them
# uniformly instead of each fetcher redefining its own.

def safe_float(val: Any, default: Optional[float] = None) -> Optional[float]:
    """
    Safely convert to a float
    
    Cases handled:
    - None or an empty string -> default
    - pandas NaN / numpy NaN → default
    - A numeric string -> float
    - Already numeric -> float
    
    Args:
        val: the value to convert
        default: the value used when conversion fails
        
    Returns:
        The converted float, or the default
    """
    try:
        if val is None:
            return default
        
        # Handle strings
        if isinstance(val, str):
            val = val.strip()
            if val == "" or val == "-" or val == "--":
                return default
        
        # Handle pandas/numpy NaN
        # Use math.isnan rather than pd.isna, so pandas is not a hard dependency
        import math
        try:
            if math.isnan(float(val)):
                return default
        except (ValueError, TypeError):
            pass
        
        return float(val)
    except (ValueError, TypeError):
        return default


def safe_int(val: Any, default: Optional[int] = None) -> Optional[int]:
    """
    Safely convert to an integer
    
    Converts to float first and then truncates, so values like "123.0" work
    
    Args:
        val: the value to convert
        default: the value used when conversion fails
        
    Returns:
        The converted integer, or the default
    """
    f_val = safe_float(val, default=None)
    if f_val is not None:
        return int(f_val)
    return default


class RealtimeSource(Enum):
    """Real-time quote data sources"""
    EFINANCE = "efinance"           # East Money (efinance library)
    AKSHARE_EM = "akshare_em"       # East Money (akshare library)
    AKSHARE_SINA = "akshare_sina"   # Sina Finance
    AKSHARE_QQ = "akshare_qq"       # Tencent Finance
    TUSHARE = "tushare"             # Tushare Pro
    TICKFLOW = "tickflow"           # TickFlow
    TENCENT = "tencent"             # Tencent direct
    SINA = "sina"                   # Sina direct
    STOOQ = "stooq"                 # Stooq, the US fallback
    LONGBRIDGE = "longbridge"       # Longbridge (US/HK fallback)
    FUTU = "futu"                   # Futu OpenD (HK)
    FALLBACK = "fallback"           # Degraded fallback


@dataclass
class UnifiedRealtimeQuote:
    """
    Unified real-time quote structure
    
    Design principles:
    - Data sources return different fields; a missing field is None
    - The main flow reads via getattr(quote, field, None) to stay compatible
    - The source field records where the data came from, which helps debugging
    """
    code: str
    name: str = ""
    source: RealtimeSource = RealtimeSource.FALLBACK

    # === Data quality metadata (filled in by DataFetcherManager) ===
    fetched_at: Optional[str] = None             # When this system fetched it (ISO 8601 datetime)
    provider_timestamp: Optional[str] = None     # The provider's actual quote time (ISO 8601 datetime)
    is_stale: Optional[bool] = None              # True when provider_timestamp exceeds the minimum TTL threshold
    stale_seconds: Optional[int] = None          # Seconds between provider_timestamp and fetched_at
    fallback_from: Optional[str] = None          # Token of the preferred source that failed, triggering a whole-source fallback
    market: Optional[str] = None                 # Market label (cn/hk/us/jp/kr/tw)
    currency: Optional[str] = None               # Quote currency (JPY/KRW/TWD/USD/HKD/CNY and so on)
    data_quality: Optional[str] = None           # ok/partial/unavailable
    missing_fields: Optional[list[str]] = None   # Key fields the provider did not supply
    
    # === Core price data (available from almost every source) ===
    price: Optional[float] = None           # Latest price
    change_pct: Optional[float] = None      # Change (%)
    change_amount: Optional[float] = None   # Change amount
    
    # === Volume and price metrics (some sources omit these) ===
    volume: Optional[int] = None            # Trading volume (shares, matching the historical daily-bar definition)
    amount: Optional[float] = None          # Turnover (CNY)
    volume_ratio: Optional[float] = None    # Volume ratio
    turnover_rate: Optional[float] = None   # Turnover rate (%)
    amplitude: Optional[float] = None       # Amplitude (%)
    
    # === Price range ===
    open_price: Optional[float] = None      # Open
    high: Optional[float] = None            # High
    low: Optional[float] = None             # Low
    pre_close: Optional[float] = None       # Previous close
    
    # === Valuation metrics (only from full endpoints such as East Money) ===
    pe_ratio: Optional[float] = None        # Price-to-earnings ratio (dynamic)
    pb_ratio: Optional[float] = None        # Price-to-book ratio
    total_mv: Optional[float] = None        # Total market cap (CNY)
    circ_mv: Optional[float] = None         # Free-float market cap (CNY)
    
    # === Other metrics ===
    change_60d: Optional[float] = None      # 60-day change (%)
    high_52w: Optional[float] = None        # 52-week high
    low_52w: Optional[float] = None         # 52-week low
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to a dictionary (dropping None values)"""
        result = {
            'code': self.code,
            'name': self.name,
            'source': self.source.value,
        }
        # Only include fields that are not None
        optional_fields = [
            'fetched_at', 'provider_timestamp', 'is_stale', 'stale_seconds',
            'fallback_from', 'market', 'currency', 'data_quality', 'missing_fields',
            'price', 'change_pct', 'change_amount', 'volume', 'amount',
            'volume_ratio', 'turnover_rate', 'amplitude',
            'open_price', 'high', 'low', 'pre_close',
            'pe_ratio', 'pb_ratio', 'total_mv', 'circ_mv',
            'change_60d', 'high_52w', 'low_52w'
        ]
        for f in optional_fields:
            val = getattr(self, f, None)
            if val is not None:
                result[f] = val
        return result
    
    def has_basic_data(self) -> bool:
        """Check whether basic price data is present"""
        return self.price is not None and self.price > 0
    
    def has_volume_data(self) -> bool:
        """Check whether volume and price data is present"""
        return self.volume_ratio is not None or self.turnover_rate is not None


@dataclass
class ChipDistribution:
    """
    Chip distribution data
    
    Reflects the distribution of holding costs and the profit position
    """
    code: str
    date: str = ""
    source: str = "akshare"
    
    # Profit position
    profit_ratio: float = 0.0     # Profitable share ratio (0-1)
    avg_cost: float = 0.0         # Average cost
    
    # Chip concentration
    cost_90_low: float = 0.0      # Lower bound of the 90% chip cost range
    cost_90_high: float = 0.0     # Upper bound of the 90% chip cost range
    concentration_90: float = 0.0  # 90% chip concentration (smaller means more concentrated)
    
    cost_70_low: float = 0.0      # Lower bound of the 70% chip cost range
    cost_70_high: float = 0.0     # Upper bound of the 70% chip cost range
    concentration_70: float = 0.0  # 70% chip concentration
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to a dictionary"""
        return {
            'code': self.code,
            'date': self.date,
            'source': self.source,
            'profit_ratio': self.profit_ratio,
            'avg_cost': self.avg_cost,
            'cost_90_low': self.cost_90_low,
            'cost_90_high': self.cost_90_high,
            'concentration_90': self.concentration_90,
            'concentration_70': self.concentration_70,
        }
    
    def get_chip_status(self, current_price: float) -> str:
        """
        Get a description of the chip state
        
        Args:
            current_price: the current share price
            
        Returns:
            A description of the chip state
        """
        status_parts = []
        
        # Profit ratio analysis
        if self.profit_ratio >= 0.9:
            status_parts.append("获利盘极高(获利盘>90%)")
        elif self.profit_ratio >= 0.7:
            status_parts.append("获利盘较高(获利盘70-90%)")
        elif self.profit_ratio >= 0.5:
            status_parts.append("获利盘中等(获利盘50-70%)")
        elif self.profit_ratio >= 0.3:
            status_parts.append("套牢盘中等(套牢盘50-70%)")
        elif self.profit_ratio >= 0.1:
            status_parts.append("套牢盘较高(套牢盘70-90%)")
        else:
            status_parts.append("套牢盘极高(套牢盘>90%)")
        
        # Chip concentration analysis (a 90% concentration below 10% means concentrated)
        if self.concentration_90 < 0.08:
            status_parts.append("筹码高度集中")
        elif self.concentration_90 < 0.15:
            status_parts.append("筹码较集中")
        elif self.concentration_90 < 0.25:
            status_parts.append("筹码分散度中等")
        else:
            status_parts.append("筹码较分散")
        
        # Relationship between cost and current price
        if current_price > 0 and self.avg_cost > 0:
            cost_diff = (current_price - self.avg_cost) / self.avg_cost * 100
            if cost_diff > 20:
                status_parts.append(f"现价高于平均成本{cost_diff:.1f}%")
            elif cost_diff > 5:
                status_parts.append(f"现价略高于成本{cost_diff:.1f}%")
            elif cost_diff > -5:
                status_parts.append("现价接近平均成本")
            else:
                status_parts.append(f"现价低于平均成本{abs(cost_diff):.1f}%")
        
        return "，".join(status_parts)


class CircuitBreaker:
    """
    Circuit breaker - manages the breaker and cooldown state of each data source
    
    Strategy:
    - After N consecutive failures the breaker opens
    - While open, that data source is skipped
    - After the cooldown it moves automatically to half-open
    - In half-open, one success fully restores it and a failure reopens the breaker
    
    State machine:
    CLOSED (normal) --N failures--> OPEN (tripped) --cooldown elapsed--> HALF_OPEN
    HALF_OPEN --success--> CLOSED
    HALF_OPEN --failure--> OPEN
    """
    
    # State constants
    CLOSED = "closed"      # Normal
    OPEN = "open"          # Tripped (unavailable)
    HALF_OPEN = "half_open"  # Half-open (probe requests)
    
    def __init__(
        self,
        failure_threshold: int = 3,       # Consecutive failure threshold
        cooldown_seconds: float = 300.0,  # Cooldown in seconds, 5 minutes by default
        half_open_max_calls: int = 1      # Maximum probe attempts while half-open
    ):
        self.failure_threshold = failure_threshold
        self.cooldown_seconds = cooldown_seconds
        self.half_open_max_calls = half_open_max_calls
        
        # Per-source state {source_name: {state, failures, last_failure_time, half_open_calls}}
        self._states: Dict[str, Dict[str, Any]] = {}
        self._lock = RLock()
    
    def _get_state_locked(self, source: str) -> Dict[str, Any]:
        """Get or initialize the state of a data source (the caller must hold the lock)."""
        if source not in self._states:
            self._states[source] = {
                'state': self.CLOSED,
                'failures': 0,
                'last_failure_time': 0.0,
                'half_open_calls': 0
            }
        return self._states[source]
    
    def is_available(self, source: str) -> bool:
        """
        Check whether the data source is available
        
        True means a request may be attempted
        False means the data source should be skipped
        """
        with self._lock:
            state = self._get_state_locked(source)
            current_time = time.time()

            if state['state'] == self.CLOSED:
                return True

            if state['state'] == self.OPEN:
                # Check the cooldown
                time_since_failure = current_time - state['last_failure_time']
                if time_since_failure >= self.cooldown_seconds:
                    # Cooldown finished, move to half-open (no slot is reserved here; the HALF_OPEN branch manages them)
                    state['state'] = self.HALF_OPEN
                    state['half_open_calls'] = 0
                    state['last_failure_time'] = current_time
                    logger.info(f"[circuit breaker] {source} cooldown finished, entering half-open state")
                    # Fall through to HALF_OPEN check below
                else:
                    remaining = self.cooldown_seconds - time_since_failure
                    logger.debug(f"[circuit breaker] {source} circuit is open, remaining cooldown: {remaining:.0f}s")
                    return False

            if state['state'] == self.HALF_OPEN:
                if state['half_open_calls'] < self.half_open_max_calls:
                    state['half_open_calls'] += 1
                    return True
                # Every probe slot is used. If the cooldown expires again without a
                # record_success/record_failure callback, reset the slots to allow probing again
                # and avoid getting stuck in HALF_OPEN forever.
                time_since_failure = current_time - state['last_failure_time']
                if time_since_failure >= self.cooldown_seconds:
                    state['half_open_calls'] = 1
                    state['last_failure_time'] = current_time
                    logger.info(f"[circuit breaker] {source} half-open probe timed out, probing again")
                    return True
                return False

            return True
    
    def record_inconclusive(self, source: str) -> None:
        """Record an inconclusive probe result (such as a None return).

        This affects HALF_OPEN only, moving it back to OPEN so it can be probed again after the cooldown.
        In CLOSED it is a no-op and does not affect the failure count.
        """
        with self._lock:
            state = self._get_state_locked(source)
            if state['state'] == self.HALF_OPEN:
                state['state'] = self.OPEN
                state['half_open_calls'] = 0
                state['last_failure_time'] = time.time()
                logger.info(f"[circuit breaker] {source} half-open probe inconclusive, re-entering cooldown")

    def record_success(self, source: str) -> None:
        """Record a successful request"""
        with self._lock:
            state = self._get_state_locked(source)

            if state['state'] == self.HALF_OPEN:
                # Success while half-open: fully restore
                logger.info(f"[circuit breaker] {source} half-open request succeeded, back to normal")

            # Reset the state
            state['state'] = self.CLOSED
            state['failures'] = 0
            state['half_open_calls'] = 0
    
    def record_failure(self, source: str, error: Optional[str] = None) -> None:
        """Record a failed request"""
        with self._lock:
            state = self._get_state_locked(source)
            current_time = time.time()

            state['failures'] += 1
            state['last_failure_time'] = current_time

            if state['state'] == self.HALF_OPEN:
                # Failure while half-open: keep the breaker open
                state['state'] = self.OPEN
                state['half_open_calls'] = 0
                logger.warning(f"[circuit breaker] {source} half-open request failed, keeping the circuit open {self.cooldown_seconds}s")
            elif state['failures'] >= self.failure_threshold:
                # Threshold reached: trip the breaker
                state['state'] = self.OPEN
                logger.warning(f"[circuit breaker] {source} consecutive failures {state['failures']} times, entering the open-circuit state "
                              f"(cooldown {self.cooldown_seconds}s)")
                if error:
                    logger.warning(f"[circuit breaker] last error: {error}")
    
    def get_status(self) -> Dict[str, str]:
        """Get the state of every data source"""
        with self._lock:
            return {source: info['state'] for source, info in self._states.items()}
    
    def reset(self, source: Optional[str] = None) -> None:
        """Reset the circuit breaker state"""
        with self._lock:
            if source:
                if source in self._states:
                    del self._states[source]
            else:
                self._states.clear()


# Global circuit breaker instance (for real-time quotes)
_realtime_circuit_breaker = CircuitBreaker(
    failure_threshold=3,      # Trip after 3 consecutive failures
    cooldown_seconds=300.0,   # 5 minute cooldown
    half_open_max_calls=1
)

# Circuit breaker for the chip-distribution endpoint (a more conservative policy, since it is less stable)
_chip_circuit_breaker = CircuitBreaker(
    failure_threshold=2,      # Trip after 2 consecutive failures
    cooldown_seconds=600.0,   # 10 minute cooldown
    half_open_max_calls=1
)


def get_realtime_circuit_breaker() -> CircuitBreaker:
    """Get the real-time quote circuit breaker"""
    return _realtime_circuit_breaker


def get_chip_circuit_breaker() -> CircuitBreaker:
    """Get the chip-distribution circuit breaker"""
    return _chip_circuit_breaker

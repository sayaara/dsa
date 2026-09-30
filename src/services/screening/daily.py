# -*- coding: utf-8 -*-
# Derived from AlphaSift revision 9f522747caafd3c0b1ddb7e14d5cf44c8580b6cf.
# Licensed under Apache-2.0 and modified for daily_stock_analysis.
"""Lightweight daily K-line enrichment for narrowed candidate pools."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
import hashlib
import json
from pathlib import Path
import threading
import time
from typing import Callable

import pandas as pd

from src.services.screening.source_guard import call_with_timeout, parse_source_timeout_seconds

_DAILY_FEATURE_DEFAULTS = {
    "daily_data_points": pd.NA,
    "change_60d": pd.NA,
    "ma5": pd.NA,
    "ma20": pd.NA,
    "ma60": pd.NA,
    "ma_bullish": pd.NA,
    "price_above_ma20": pd.NA,
    "macd_status": "",
    "rsi_status": "",
    "rsi14": pd.NA,
    "signal_score": pd.NA,
    "prev_high_20d": pd.NA,
    "range_20d_pct": pd.NA,
    "breakout_20d_pct": pd.NA,
    "volume_ratio_20d": pd.NA,
    "body_pct": pd.NA,
    "pullback_to_ma20_pct": pd.NA,
    "consolidation_days_20d": pd.NA,
    "volatility_20d_pct": pd.NA,
    "max_drawdown_20d_pct": pd.NA,
    "atr_20_pct": pd.NA,
    "daily_quality_score": pd.NA,
    "daily_quality_flags": "",
    "daily_source": "",
}
_DAILY_ENRICH_MAX_WORKERS = 1
_DAILY_HISTORY_CACHE_VERSION = 1
_DAILY_HISTORY_CACHE_TTL_SECONDS = 24 * 60 * 60
_SOURCE_HEALTH_FAILURE_THRESHOLD = 3
_SOURCE_HEALTH_COOLDOWN_SECONDS = 5 * 60
_DAILY_CALL_TIMEOUT_SECONDS = 20.0
_SOURCE_HEALTH: dict[str, dict[str, object]] = {}
_SOURCE_HEALTH_LOCK = threading.Lock()


def enrich_daily_features(
    df: pd.DataFrame,
    *,
    max_rows: int = 100,
    lookback_days: int = 120,
    source: str = "yfinance",
    fetch_retries: int = 2,
    cache_dir: str | Path | None = None,
    cache_ttl_seconds: float | None = None,
    max_workers: int | None = None,
    history_fetcher: Callable[..., pd.DataFrame] | None = None,
) -> pd.DataFrame:
    """Attach daily technical features to the first ``max_rows`` candidates.

    This intentionally runs after broad snapshot filtering; it is not a full
    market historical-data pass. ``history_fetcher`` is a request-scoped
    override; callers can reuse host data capabilities without replacing this
    module's process-global ``fetch_daily_history`` function.
    """
    if df.empty or max_rows <= 0:
        return df.copy()

    result = df.copy()
    daily_errors: list[str] = []
    daily_source_counts: dict[str, int] = {}
    daily_quality_flag_counts: dict[str, int] = {}
    daily_source_order_notes: list[str] = []
    daily_source_health: dict[str, object] = {}
    success_count = 0
    fetch_history = history_fetcher or fetch_daily_history
    selected_index = list(result.index[:max_rows])
    fetch_requests: list[tuple[object, str]] = []
    for idx in selected_index:
        raw_code = str(result.at[idx, "code"] if "code" in result.columns else "").strip()
        if not raw_code:
            continue
        fetch_requests.append((idx, raw_code.upper()))

    def fetch_one(request: tuple[object, str]) -> tuple[object, dict[str, object], str | None, dict[str, object]]:
        idx, code = request
        try:
            hist = fetch_history(
                code,
                lookback_days=lookback_days,
                source=source,
                retries=fetch_retries,
                cache_dir=cache_dir,
                cache_ttl_seconds=cache_ttl_seconds,
            )
            features = compute_daily_features(hist)
            features["daily_source"] = str(hist.attrs.get("daily_source", ""))
            metadata = {
                "daily_source": features["daily_source"],
                "daily_quality_flags": features.get("daily_quality_flags", ""),
                "daily_source_order_notes": list(hist.attrs.get("daily_source_order_notes", []) or []),
                "daily_source_health": dict(hist.attrs.get("daily_source_health", {}) or {}),
            }
            return idx, features, None, metadata
        except Exception as exc:
            features = dict(_DAILY_FEATURE_DEFAULTS)
            features["daily_quality_score"] = 0.0
            features["daily_quality_flags"] = "fetch_failed"
            return idx, features, f"{code}: {exc}", {"daily_quality_flags": "fetch_failed"}

    if len(fetch_requests) <= 1:
        fetched_rows = [fetch_one(request) for request in fetch_requests]
    else:
        worker_limit = min(_normalize_max_workers(max_workers), len(fetch_requests))
        with ThreadPoolExecutor(max_workers=worker_limit) as executor:
            fetched_rows = list(executor.map(fetch_one, fetch_requests))

    for idx, features, error, metadata in fetched_rows:
        for flag in str(metadata.get("daily_quality_flags") or "").split(";"):
            if flag:
                daily_quality_flag_counts[flag] = daily_quality_flag_counts.get(flag, 0) + 1
        if error:
            daily_errors.append(error)
        else:
            success_count += 1
            source_name = str(metadata.get("daily_source") or "unknown")
            daily_source_counts[source_name] = daily_source_counts.get(source_name, 0) + 1
            order_notes = metadata.get("daily_source_order_notes", [])
            if not isinstance(order_notes, list):
                order_notes = []
            for note in order_notes:
                note_text = str(note)
                if note_text and note_text not in daily_source_order_notes:
                    daily_source_order_notes.append(note_text)
            source_health = metadata.get("daily_source_health")
            if isinstance(source_health, dict):
                daily_source_health.update(source_health)
        for key, value in features.items():
            result.at[idx, key] = value

    result.attrs["daily_errors"] = daily_errors
    result.attrs["daily_success_count"] = success_count
    result.attrs["daily_source_counts"] = daily_source_counts
    result.attrs["daily_quality_flag_counts"] = daily_quality_flag_counts
    result.attrs["daily_source_order_notes"] = daily_source_order_notes
    result.attrs["daily_source_health"] = daily_source_health
    return result


def fetch_daily_history(
    code: str,
    *,
    lookback_days: int = 120,
    source: str = "yfinance",
    retries: int = 2,
    cache_dir: str | Path | None = None,
    cache_ttl_seconds: float | None = None,
) -> pd.DataFrame:
    """Fetch daily history for one US ticker.

    ``source`` accepts ``yfinance`` or ``auto`` (an alias for ``yfinance``).
    """
    normalized_code = _normalize_daily_code(code)
    normalized_lookback_days = int(lookback_days)
    src = _normalize_daily_source(source)
    if src in ("auto", "yfinance"):
        src = "yfinance"
        sources: tuple[str, ...] = ("yfinance",)
        source_order_notes: list[str] = []
    else:
        raise ValueError(f"Unsupported daily source: {source}")

    cache_path = None
    if cache_dir is not None:
        cache_path = _daily_history_cache_path(
            cache_dir,
            code=normalized_code,
            source=src,
            lookback_days=normalized_lookback_days,
        )
        cached = _read_daily_history_cache(cache_path, ttl_seconds=cache_ttl_seconds)
        if cached is not None:
            return cached

    attempts = max(int(retries), 0) + 1
    errors: list[str] = []
    for current in sources:
        disabled_reason = _source_disabled_reason(current)
        if disabled_reason:
            errors.append(f"{current}: {disabled_reason}")
            continue
        last_error: Exception | None = None
        for attempt in range(attempts):
            try:
                from src.services.screening.snapshot_us import fetch_daily_history_yfinance
                result = _call_daily_wrapper(
                    fetch_daily_history_yfinance,
                    current,
                    normalized_code,
                    lookback_days=lookback_days,
                )
                _record_source_success(current, rows=len(result))
                result.attrs["daily_source"] = current
                result.attrs["daily_requested_source"] = src
                result.attrs["daily_source_order"] = list(sources)
                result.attrs["daily_source_order_notes"] = list(source_order_notes)
                result.attrs["source_errors"] = list(errors)
                result.attrs["daily_source_health"] = _daily_source_health_snapshot(sources)
                if cache_path is not None:
                    _write_daily_history_cache(
                        cache_path,
                        result,
                        code=normalized_code,
                        source=src,
                        lookback_days=normalized_lookback_days,
                    )
                return result
            except Exception as exc:  # noqa: BLE001 - aggregated below
                last_error = exc
                if attempt >= attempts - 1:
                    break
                time.sleep(min(0.5 * (attempt + 1), 2.0))
        errors.append(f"{current} after {attempts} attempts: {last_error}")
        _record_source_failure(current, last_error)

    if cache_path is not None:
        stale = _read_daily_history_cache(
            cache_path,
            ttl_seconds=cache_ttl_seconds,
            allow_stale=True,
        )
        if stale is not None:
            stale.attrs["daily_stale"] = True
            stale.attrs["daily_source_order"] = list(sources)
            stale.attrs["daily_source_order_notes"] = list(source_order_notes)
            stale.attrs["source_errors"] = list(errors)
            stale.attrs["daily_source_health"] = _daily_source_health_snapshot(sources)
            return stale

    raise RuntimeError(
        f"daily history fetch failed for {normalized_code}: {'; '.join(errors)}"
    )


def _normalize_daily_code(value: object) -> str:
    text = "" if value is None else str(value).strip()
    if not text or text.lower() in {"nan", "none", "<na>"}:
        return ""
    return text.upper()


def _normalize_daily_source(source: str | None) -> str:
    return (source or "yfinance").strip().lower()


def _normalize_max_workers(value: int | None) -> int:
    if value is None:
        return _DAILY_ENRICH_MAX_WORKERS
    return max(1, int(value))


def _call_daily_wrapper(fetcher, source: str, *args, **kwargs) -> pd.DataFrame:
    return call_with_timeout(
        fetcher,
        *args,
        timeout_sec=_daily_call_timeout_seconds(),
        label=f"daily source {source}",
        **kwargs,
    )


def _daily_call_timeout_seconds() -> float | None:
    return parse_source_timeout_seconds(
        "SCREENING_DAILY_CALL_TIMEOUT_SEC",
        default=_DAILY_CALL_TIMEOUT_SECONDS,
    )


def _rank_daily_sources_by_health(sources: tuple[str, ...]) -> tuple[tuple[str, ...], list[str]]:
    """Move unhealthy daily sources later while preserving default order ties."""
    now = time.monotonic()
    with _SOURCE_HEALTH_LOCK:
        health = {source: dict(_SOURCE_HEALTH.get(source, {})) for source in sources}
    default_rank = {source: idx for idx, source in enumerate(sources)}

    def rank_key(source: str) -> tuple[int, float, int]:
        state = health.get(source, {})
        disabled_until = float(state.get("disabled_until", 0.0))
        disabled = disabled_until > now
        failures = float(state.get("failures", 0.0))
        return (1 if disabled else 0, failures, default_rank[source])

    ranked = tuple(sorted(sources, key=rank_key))
    if ranked == sources:
        return sources, []
    return ranked, [f"daily source order adjusted by health: {','.join(ranked)}"]


def _source_disabled_reason(source: str) -> str | None:
    now = time.monotonic()
    with _SOURCE_HEALTH_LOCK:
        state = _SOURCE_HEALTH.get(source)
        if not state:
            return None
        disabled_until = float(state.get("disabled_until", 0.0))
        if disabled_until <= now:
            if disabled_until:
                state["disabled_until"] = 0.0
            return None
        return f"temporarily disabled for {disabled_until - now:.1f}s after repeated failures"


def _record_source_success(source: str, *, rows: int | None = None) -> None:
    with _SOURCE_HEALTH_LOCK:
        state = _SOURCE_HEALTH.setdefault(source, {"failures": 0.0, "disabled_until": 0.0})
        successes = float(state.get("successes", 0.0)) + 1.0
        state["successes"] = successes
        state["failures"] = 0.0
        state["disabled_until"] = 0.0
        state["last_success_at"] = time.time()
        if rows is not None:
            state["last_rows"] = float(rows)
            previous_avg = float(state.get("avg_rows", rows))
            state["avg_rows"] = previous_avg + (float(rows) - previous_avg) / successes


def _record_source_failure(source: str, error: object | None = None) -> None:
    now = time.monotonic()
    with _SOURCE_HEALTH_LOCK:
        state = _SOURCE_HEALTH.setdefault(source, {"failures": 0.0, "disabled_until": 0.0})
        failures = float(state.get("failures", 0.0)) + 1.0
        state["failures"] = failures
        state["total_failures"] = float(state.get("total_failures", 0.0)) + 1.0
        state["last_failure_at"] = time.time()
        if error is not None:
            state["last_error"] = " ".join(str(error).split())
        if failures >= _SOURCE_HEALTH_FAILURE_THRESHOLD:
            state["disabled_until"] = now + _SOURCE_HEALTH_COOLDOWN_SECONDS


def daily_source_health_snapshot() -> dict[str, dict[str, float | bool | str]]:
    """Return a copy of in-process daily-source health statistics."""
    return _daily_source_health_snapshot(tuple(_SOURCE_HEALTH))


def _daily_source_health_snapshot(sources: tuple[str, ...]) -> dict[str, dict[str, float | bool | str]]:
    now = time.monotonic()
    snapshot: dict[str, dict[str, float | bool | str]] = {}
    with _SOURCE_HEALTH_LOCK:
        for source in sources:
            state = dict(_SOURCE_HEALTH.get(source, {}))
            disabled_until = float(state.get("disabled_until", 0.0))
            cooldown_remaining = max(disabled_until - now, 0.0)
            snapshot[source] = {
                "successes": float(state.get("successes", 0.0)),
                "failures": float(state.get("failures", 0.0)),
                "total_failures": float(state.get("total_failures", 0.0)),
                "last_rows": float(state.get("last_rows", 0.0)),
                "avg_rows": float(state.get("avg_rows", 0.0)),
                "disabled": disabled_until > now,
                "cooldown_remaining_seconds": round(cooldown_remaining, 4),
                "last_success_at": float(state.get("last_success_at", 0.0)),
                "last_failure_at": float(state.get("last_failure_at", 0.0)),
                "last_error": str(state.get("last_error", "")),
            }
    return snapshot


def _daily_history_cache_path(
    cache_dir: str | Path,
    *,
    code: str,
    source: str,
    lookback_days: int,
) -> Path:
    key = f"{code}|{source}|{int(lookback_days)}"
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]
    safe_source = "".join(ch if ch.isalnum() else "-" for ch in source).strip("-") or "source"
    safe_code = "".join(ch if ch.isalnum() else "-" for ch in code).strip("-") or "code"
    return Path(cache_dir) / f"{safe_code}_{safe_source}_{int(lookback_days)}_{digest}.json"


def _read_daily_history_cache(
    path: Path,
    *,
    ttl_seconds: float | None,
    allow_stale: bool = False,
) -> pd.DataFrame | None:
    try:
        stat = path.stat()
    except FileNotFoundError:
        return None

    ttl = _DAILY_HISTORY_CACHE_TTL_SECONDS if ttl_seconds is None else float(ttl_seconds)
    is_stale = ttl <= 0 or time.time() - stat.st_mtime > ttl
    if is_stale and not allow_stale:
        return None

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if payload.get("version") != _DAILY_HISTORY_CACHE_VERSION:
            return None
        frame = payload.get("frame")
        if not isinstance(frame, dict):
            return None
        columns = frame.get("columns")
        data = frame.get("data")
        if not isinstance(columns, list) or not isinstance(data, list):
            return None
        df = pd.DataFrame(data, columns=columns)
        metadata = payload.get("metadata")
        if isinstance(metadata, dict):
            for key in ("daily_source", "daily_requested_source", "daily_source_order", "daily_source_order_notes", "source_errors", "daily_source_health"):
                if key in metadata:
                    df.attrs[key] = metadata[key]
        if is_stale:
            df.attrs["daily_stale"] = True
        return df
    except Exception:
        return None


def _write_daily_history_cache(
    path: Path,
    df: pd.DataFrame,
    *,
    code: str,
    source: str,
    lookback_days: int,
) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": _DAILY_HISTORY_CACHE_VERSION,
            "key": {
                "code": code,
                "source": source,
                "lookback_days": int(lookback_days),
            },
            "metadata": {
                "daily_source": df.attrs.get("daily_source", source),
                "daily_requested_source": df.attrs.get("daily_requested_source", source),
                "daily_source_order": list(df.attrs.get("daily_source_order", [])),
                "daily_source_order_notes": list(df.attrs.get("daily_source_order_notes", [])),
                "source_errors": list(df.attrs.get("source_errors", [])),
                "daily_source_health": df.attrs.get("daily_source_health", {}),
            },
            "created_at": datetime.now().isoformat(),
            "frame": json.loads(df.to_json(orient="split", date_format="iso", force_ascii=False)),
        }
        tmp_path = path.with_name(f".{path.name}.{time.time_ns()}.tmp")
        tmp_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        tmp_path.replace(path)
    except Exception:
        return


def compute_daily_features(hist: pd.DataFrame) -> dict[str, object]:
    """Compute compact trend/reversal features from a daily K-line DataFrame."""
    df = _normalize_daily_history(hist)
    if df.empty:
        raise RuntimeError("daily history is empty after normalization")

    close = pd.to_numeric(df["close"], errors="coerce").dropna()
    if close.empty:
        raise RuntimeError("daily history has no valid close price")

    ma5 = close.rolling(5).mean()
    ma20 = close.rolling(20).mean()
    ma60 = close.rolling(60).mean()
    last_close = float(close.iloc[-1])
    last_ma5 = _last_float(ma5)
    last_ma20 = _last_float(ma20)
    last_ma60 = _last_float(ma60)
    shape = _compute_shape_features(df, last_close=last_close, last_ma20=last_ma20)
    quality = _compute_daily_quality(hist, df)

    lookback_idx = max(0, len(close) - 61)
    base_close = float(close.iloc[lookback_idx])
    change_60d = (last_close / base_close - 1.0) * 100 if base_close > 0 else None

    macd_status = _compute_macd_status(close)
    rsi_value = _compute_rsi(close)
    rsi_status = _classify_rsi(rsi_value)
    ma_bullish = _is_true(last_ma5 is not None and last_ma20 is not None and last_ma60 is not None
                          and last_ma5 >= last_ma20 >= last_ma60)
    price_above_ma20 = _is_true(last_ma20 is not None and last_close >= last_ma20)
    signal_score = _compute_signal_score(
        change_60d=change_60d,
        ma_bullish=ma_bullish,
        price_above_ma20=price_above_ma20,
        macd_status=macd_status,
        rsi_status=rsi_status,
    )

    return {
        "daily_data_points": int(len(close)),
        "change_60d": None if change_60d is None else round(float(change_60d), 4),
        "ma5": last_ma5,
        "ma20": last_ma20,
        "ma60": last_ma60,
        "ma_bullish": ma_bullish,
        "price_above_ma20": price_above_ma20,
        "macd_status": macd_status,
        "rsi_status": rsi_status,
        "rsi14": None if rsi_value is None else round(float(rsi_value), 4),
        "signal_score": round(float(signal_score), 4),
        **shape,
        **quality,
    }


def _normalize_daily_history(hist: pd.DataFrame) -> pd.DataFrame:
    rename_map = {
        "日期": "date",
        "收盘": "close",
        "开盘": "open",
        "最高": "high",
        "最低": "low",
        "成交量": "volume",
        "成交额": "amount",
    }
    df = hist.rename(columns=rename_map).copy()
    if "date" in df.columns:
        df = df.sort_values("date")
    if "close" not in df.columns:
        raise RuntimeError("daily history has no close column")
    for col in ("open", "high", "low", "close", "volume"):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    df = df.dropna(subset=["close"]).copy()
    for col in ("open", "high", "low"):
        if col not in df.columns:
            df[col] = df["close"]
        else:
            df[col] = df[col].fillna(df["close"])
    return df


def _compute_daily_quality(raw: pd.DataFrame, normalized: pd.DataFrame) -> dict[str, object]:
    """Score daily-history quality and expose compact audit flags."""
    score = 100.0
    flags: list[str] = []
    points = len(normalized)
    if points < 30:
        score -= 35
        flags.append("short_history_lt30")
    elif points < 60:
        score -= 15
        flags.append("short_history_lt60")

    for col in ("open", "high", "low", "close"):
        if col not in normalized.columns:
            score -= 20
            flags.append(f"missing_{col}")
            continue
        missing_ratio = float(pd.to_numeric(normalized[col], errors="coerce").isna().mean())
        if missing_ratio > 0:
            score -= min(missing_ratio * 40, 20)
            flags.append(f"incomplete_{col}")

    if "volume" not in normalized.columns:
        score -= 12
        flags.append("missing_volume")
    else:
        volume = pd.to_numeric(normalized["volume"], errors="coerce")
        missing_volume_ratio = float(volume.isna().mean())
        if missing_volume_ratio > 0:
            score -= min(missing_volume_ratio * 20, 10)
            flags.append("incomplete_volume")
        if (volume.dropna() < 0).any():
            score -= 20
            flags.append("negative_volume")

    if {"open", "high", "low", "close"}.issubset(normalized.columns):
        open_ = pd.to_numeric(normalized["open"], errors="coerce")
        high = pd.to_numeric(normalized["high"], errors="coerce")
        low = pd.to_numeric(normalized["low"], errors="coerce")
        close = pd.to_numeric(normalized["close"], errors="coerce")
        invalid_ohlc = (high < low) | (high < open_) | (high < close) | (low > open_) | (low > close)
        if invalid_ohlc.fillna(False).any():
            score -= 30
            flags.append("invalid_ohlc")
        if ((open_ <= 0) | (high <= 0) | (low <= 0) | (close <= 0)).fillna(False).any():
            score -= 35
            flags.append("non_positive_price")

    if bool(raw.attrs.get("daily_stale")):
        score -= 25
        flags.append("stale_cache")

    source_errors = list(raw.attrs.get("source_errors", []) or [])
    if source_errors:
        score -= min(len(source_errors) * 5, 20)
        flags.append("fallback_errors")

    return {
        "daily_quality_score": round(max(score, 0.0), 4),
        "daily_quality_flags": ";".join(flags),
    }


def _compute_shape_features(
    df: pd.DataFrame,
    *,
    last_close: float,
    last_ma20: float | None,
) -> dict[str, object]:
    previous = df.iloc[:-1].tail(20)
    recent = df.tail(20)
    last = df.iloc[-1]

    prev_high_20d = _series_max(previous["high"]) if "high" in previous.columns else None
    range_20d_pct = _range_pct(recent)
    breakout_20d_pct = (
        (last_close / prev_high_20d - 1.0) * 100
        if prev_high_20d is not None and prev_high_20d > 0
        else None
    )
    volume_ratio_20d = _volume_ratio_20d(df)
    body_pct = _body_pct(last)
    pullback_to_ma20_pct = (
        (last_close / last_ma20 - 1.0) * 100
        if last_ma20 is not None and last_ma20 > 0
        else None
    )
    volatility_20d_pct = _volatility_20d_pct(recent["close"])
    max_drawdown_20d_pct = _max_drawdown_pct(recent["close"])
    atr_20_pct = _atr_20_pct(df)

    return {
        "prev_high_20d": _round_or_none(prev_high_20d),
        "range_20d_pct": _round_or_none(range_20d_pct),
        "breakout_20d_pct": _round_or_none(breakout_20d_pct),
        "volume_ratio_20d": _round_or_none(volume_ratio_20d),
        "body_pct": _round_or_none(body_pct),
        "pullback_to_ma20_pct": _round_or_none(pullback_to_ma20_pct),
        "consolidation_days_20d": _consolidation_days(previous),
        "volatility_20d_pct": _round_or_none(volatility_20d_pct),
        "max_drawdown_20d_pct": _round_or_none(max_drawdown_20d_pct),
        "atr_20_pct": _round_or_none(atr_20_pct),
    }


def _series_max(series: pd.Series) -> float | None:
    values = pd.to_numeric(series, errors="coerce").dropna()
    if values.empty:
        return None
    return float(values.max())


def _range_pct(df: pd.DataFrame) -> float | None:
    if "high" not in df.columns or "low" not in df.columns:
        return None
    high = pd.to_numeric(df["high"], errors="coerce").dropna()
    low = pd.to_numeric(df["low"], errors="coerce").dropna()
    if high.empty or low.empty:
        return None
    low_min = float(low.min())
    if low_min <= 0:
        return None
    return (float(high.max()) / low_min - 1.0) * 100


def _volume_ratio_20d(df: pd.DataFrame) -> float | None:
    if "volume" not in df.columns:
        return None
    volume = pd.to_numeric(df["volume"], errors="coerce")
    if len(volume) < 2 or pd.isna(volume.iloc[-1]):
        return None
    previous = volume.iloc[:-1].tail(20).dropna()
    if previous.empty:
        return None
    base = float(previous.mean())
    if base <= 0:
        return None
    return float(volume.iloc[-1]) / base


def _volatility_20d_pct(close: pd.Series) -> float | None:
    values = pd.to_numeric(close, errors="coerce").dropna()
    returns = values.pct_change().dropna()
    if len(returns) < 2:
        return None
    return float(returns.std()) * (252 ** 0.5) * 100


def _max_drawdown_pct(close: pd.Series) -> float | None:
    values = pd.to_numeric(close, errors="coerce").dropna()
    if values.empty:
        return None
    running_high = values.cummax()
    drawdowns = values / running_high - 1.0
    return min(float(drawdowns.min()) * 100, 0.0)


def _atr_20_pct(df: pd.DataFrame) -> float | None:
    if not {"high", "low", "close"}.issubset(df.columns):
        return None
    high = pd.to_numeric(df["high"], errors="coerce")
    low = pd.to_numeric(df["low"], errors="coerce")
    close = pd.to_numeric(df["close"], errors="coerce")
    previous_close = close.shift(1)
    true_range = pd.concat([
        high - low,
        (high - previous_close).abs(),
        (low - previous_close).abs(),
    ], axis=1).max(axis=1)
    atr = true_range.tail(20).dropna().mean()
    valid_close = close.dropna()
    if valid_close.empty:
        return None
    last_close = float(valid_close.iloc[-1])
    if pd.isna(atr) or last_close <= 0:
        return None
    return float(atr) / last_close * 100


def _consolidation_days(previous: pd.DataFrame, *, max_range_pct: float = 12.0) -> int | None:
    if previous.empty or "high" not in previous.columns or "low" not in previous.columns:
        return None
    for days in range(min(len(previous), 20), 1, -1):
        window = previous.tail(days)
        range_pct = _range_pct(window)
        if range_pct is not None and range_pct <= max_range_pct:
            return int(days)
    return 0


def _body_pct(row: pd.Series) -> float | None:
    open_price = row.get("open")
    close_price = row.get("close")
    if pd.isna(open_price) or pd.isna(close_price) or float(open_price) <= 0:
        return None
    return (float(close_price) / float(open_price) - 1.0) * 100


def _round_or_none(value: float | None) -> float | None:
    if value is None or pd.isna(value):
        return None
    return round(float(value), 4)


def _compute_macd_status(close: pd.Series) -> str:
    if len(close) < 35:
        return "neutral"
    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    diff = ema12 - ema26
    dea = diff.ewm(span=9, adjust=False).mean()
    last_diff = float(diff.iloc[-1])
    last_dea = float(dea.iloc[-1])
    if last_diff > last_dea and last_diff > 0:
        return "bullish"
    if last_diff < last_dea and last_diff < 0:
        return "bearish"
    return "neutral"


def _compute_rsi(close: pd.Series, period: int = 14) -> float | None:
    if len(close) <= period:
        return None
    delta = close.diff()
    gain = delta.clip(lower=0).rolling(period).mean()
    loss = (-delta.clip(upper=0)).rolling(period).mean()
    rs = gain / loss.replace(0, pd.NA)
    rsi = 100 - (100 / (1 + rs))
    value = rsi.iloc[-1]
    if pd.isna(value):
        return None
    return float(value)


def _classify_rsi(value: float | None) -> str:
    if value is None:
        return "neutral"
    if value <= 35:
        return "oversold"
    if value >= 70:
        return "overbought"
    return "neutral"


def _compute_signal_score(
    *,
    change_60d: float | None,
    ma_bullish: bool,
    price_above_ma20: bool,
    macd_status: str,
    rsi_status: str,
) -> float:
    score = 50.0
    if ma_bullish:
        score += 14
    if price_above_ma20:
        score += 10
    if macd_status == "bullish":
        score += 12
    elif macd_status == "bearish":
        score -= 12
    if change_60d is not None:
        if 0 <= change_60d <= 35:
            score += min(change_60d * 0.35, 12)
        elif change_60d > 60:
            score -= min((change_60d - 60) * 0.20, 12)
        elif change_60d < -25:
            score -= min(abs(change_60d + 25) * 0.25, 10)
    if rsi_status == "oversold":
        score += 4
    elif rsi_status == "overbought":
        score -= 6
    return max(0.0, min(score, 100.0))


def _last_float(series: pd.Series) -> float | None:
    value = series.iloc[-1]
    if pd.isna(value):
        return None
    return round(float(value), 4)


def _is_true(value: bool) -> bool:
    return bool(value)

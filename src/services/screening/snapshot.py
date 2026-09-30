# -*- coding: utf-8 -*-
# Derived from AlphaSift revision 9f522747caafd3c0b1ddb7e14d5cf44c8580b6cf.
# Licensed under Apache-2.0 and modified for daily_stock_analysis.
"""Market snapshot fetcher.

Fetches full-market real-time snapshots for screening.
This is separate from single-stock realtime quotes.
"""

import logging
import json
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from src.services.screening.source_guard import call_with_timeout, parse_source_timeout_seconds

logger = logging.getLogger(__name__)

_SNAPSHOT_CACHE_VERSION = 1
_SOURCE_HEALTH_FAILURE_THRESHOLD = 3
_SOURCE_HEALTH_COOLDOWN_SECONDS = 5 * 60
_SNAPSHOT_CALL_TIMEOUT_SECONDS = 60.0
_SOURCE_HEALTH: dict[str, dict[str, object]] = {}
_SOURCE_HEALTH_LOCK = threading.Lock()


def fetch_snapshot_source(source: str = "yfinance") -> pd.DataFrame:
    """Fetch a full-market snapshot from one named source.

    Returns a DataFrame with columns:
        code, name, price, change_pct, amount, total_mv, circ_mv,
        pe_ratio, pb_ratio, volume_ratio, turnover_rate, industry

    Raises RuntimeError if the source is unavailable.
    """
    if source == "yfinance":
        return _call_snapshot_wrapper(_fetch_yfinance, source=source)
    raise ValueError(f"Unknown snapshot source: {source}")


def _fetch_yfinance() -> pd.DataFrame:
    from src.services.screening.snapshot_us import fetch_us_snapshot

    return fetch_us_snapshot()


def fetch_snapshot_with_fallback(
    sources: list[str],
    *,
    required_columns: list[str] | None = None,
    fallback_snapshot_path: str | Path | None = None,
    fallback_max_age_hours: float | None = None,
    cache_ttl_seconds: float = 0.0,
    market: str = "us",
) -> pd.DataFrame:
    """Try live sources, optionally falling back to the last-good snapshot."""
    if market != "us":
        raise ValueError(f"Unsupported market: {market!r} (supported: us)")

    errors = []
    required = required_columns or []
    if cache_ttl_seconds > 0:
        cached = _read_last_good_snapshot(
            fallback_snapshot_path,
            required_columns=required,
            source_errors=[],
            max_age_hours=cache_ttl_seconds / 3600.0,
            fresh=True,
            requested_snapshot_sources=sources,
        )
        if cached is not None:
            return cached

    for source in sources:
        disabled_reason = _source_disabled_reason(source)
        if disabled_reason:
            errors.append(f"{source}: {disabled_reason}")
            continue
        try:
            df = fetch_snapshot_source(source)
            if not df.empty:
                missing = _missing_required_columns(df, required)
                if missing:
                    error = f"missing required columns {','.join(missing)}"
                    errors.append(f"{source}: {error}")
                    _record_source_failure(source, error)
                    continue
                df.attrs.setdefault("snapshot_source", source)
                df.attrs["source_errors"] = list(errors)
                df.attrs["fallback_used"] = False
                df.attrs["stale"] = False
                df.attrs["stale_age_hours"] = None
                _write_last_good_snapshot(
                    fallback_snapshot_path,
                    df,
                    source_priority=sources,
                )
                _record_source_success(source, rows=len(df))
                logger.info("Snapshot fetched from %s: %d rows", source, len(df))
                return df
            errors.append(f"{source}: returned empty data")
            _record_source_failure(source, "returned empty data")
        except Exception as e:
            errors.append(f"{source}: {e}")
            _record_source_failure(source, e)
            logger.warning("Snapshot source %s failed: %s", source, e)

    cached = _read_last_good_snapshot(
        fallback_snapshot_path,
        required_columns=required,
        source_errors=errors,
        max_age_hours=fallback_max_age_hours,
    )
    if cached is not None:
        return cached

    raise RuntimeError(f"All snapshot sources failed: {'; '.join(errors)}")


def _missing_required_columns(df: pd.DataFrame, required_columns: list[str]) -> list[str]:
    missing: list[str] = []
    for col in required_columns:
        if col not in df.columns:
            missing.append(col)
            continue
        if df[col].dropna().empty:
            missing.append(col)
    return missing


def _call_snapshot_wrapper(fetcher, *, source: str) -> pd.DataFrame:
    return call_with_timeout(
        fetcher,
        timeout_sec=_snapshot_call_timeout_seconds(),
        label=f"snapshot source {source}",
    )


def _snapshot_call_timeout_seconds() -> float | None:
    return parse_source_timeout_seconds(
        "SCREENING_SNAPSHOT_CALL_TIMEOUT_SEC",
        default=_SNAPSHOT_CALL_TIMEOUT_SECONDS,
    )


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


def snapshot_source_health_snapshot(
    sources: list[str] | tuple[str, ...] | None = None,
) -> dict[str, dict[str, float | bool | str]]:
    """Return in-process snapshot-source health without exposing credentials."""
    now = time.monotonic()
    requested = tuple(sources or tuple(_SOURCE_HEALTH))
    with _SOURCE_HEALTH_LOCK:
        snapshot: dict[str, dict[str, float | bool | str]] = {}
        for source in requested:
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


def _write_last_good_snapshot(
    path_like: str | Path | None,
    df: pd.DataFrame,
    *,
    source_priority: list[str] | None = None,
) -> None:
    if path_like is None:
        return
    path = Path(path_like)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": _SNAPSHOT_CACHE_VERSION,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "metadata": {
                "snapshot_source": str(df.attrs.get("snapshot_source", "")),
                "source_priority": [
                    str(source).strip()
                    for source in (source_priority or [])
                    if str(source).strip()
                ],
                "row_count": int(len(df)),
                "columns": list(df.columns),
            },
            "frame": json.loads(
                df.to_json(orient="split", date_format="iso", force_ascii=False)
            ),
        }
        tmp_path = path.with_name(f".{path.name}.{time.time_ns()}.tmp")
        tmp_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        tmp_path.replace(path)
    except Exception as exc:  # noqa: BLE001 - live snapshot should remain usable.
        logger.warning("Failed to write last-good snapshot cache %s: %s", path, exc)


def _read_last_good_snapshot(
    path_like: str | Path | None,
    *,
    required_columns: list[str],
    source_errors: list[str],
    max_age_hours: float | None = None,
    fresh: bool = False,
    requested_snapshot_sources: list[str] | None = None,
) -> pd.DataFrame | None:
    if path_like is None:
        return None
    path = Path(path_like)
    try:
        stat = path.stat()
    except FileNotFoundError:
        return None

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if payload.get("version") != _SNAPSHOT_CACHE_VERSION:
            raise ValueError("unsupported cache version")
        metadata = payload.get("metadata")
        if not isinstance(metadata, dict):
            raise ValueError("missing cache metadata")
        cached_snapshot_source = str(metadata.get("snapshot_source", "")).strip()
        if fresh and requested_snapshot_sources is not None:
            requested_priority = [
                str(source).strip()
                for source in requested_snapshot_sources
                if str(source).strip()
            ]
            cached_priority_raw = metadata.get("source_priority")
            cached_priority = (
                [str(source).strip() for source in cached_priority_raw if str(source).strip()]
                if isinstance(cached_priority_raw, list)
                else []
            )
            if cached_priority:
                if cached_priority != requested_priority:
                    raise ValueError(
                        "cached snapshot priority "
                        f"{','.join(cached_priority)} does not match requested priority "
                        f"{','.join(requested_priority)}"
                    )
            elif not requested_priority or cached_snapshot_source != requested_priority[0]:
                # Legacy cache entries did not persist the configured chain.
                # Reuse them only when their actual provider is still the
                # current primary source; a new live fetch will upgrade the
                # metadata and allow same-chain fallback reuse afterwards.
                raise ValueError(
                    "legacy cached snapshot source "
                    f"{cached_snapshot_source or '<missing>'} does not match requested primary "
                    f"{requested_priority[0] if requested_priority else '<missing>'}"
                )
        frame = payload.get("frame")
        if not isinstance(frame, dict):
            raise ValueError("missing cached frame")
        columns = frame.get("columns")
        data = frame.get("data")
        if not isinstance(columns, list) or not isinstance(data, list):
            raise ValueError("malformed cached frame")
        stale_age_hours = _cache_stale_age_hours(
            stat.st_mtime,
            created_at=str(payload.get("created_at", "")),
        )
        if max_age_hours is not None and max_age_hours >= 0 and stale_age_hours > max_age_hours:
            raise ValueError(
                f"cache stale_age_hours={stale_age_hours:.4g} exceeds max_age_hours={max_age_hours:.4g}"
            )
        cached = pd.DataFrame(data, columns=columns)
        if cached.empty:
            raise ValueError("cached snapshot is empty")
        missing = _missing_required_columns(cached, required_columns)
        if missing:
            raise ValueError(f"missing required columns {','.join(missing)}")
    except Exception as exc:  # noqa: BLE001 - invalid cache should not mask live errors.
        source_errors.append(f"last_good_cache: {exc}")
        return None

    cached.attrs["snapshot_source"] = "last_good_cache"
    cached.attrs["fallback_used"] = not fresh
    cached.attrs["cache_used"] = True
    cached.attrs["stale"] = not fresh
    cached.attrs["stale_age_hours"] = stale_age_hours
    cached.attrs["source_errors"] = list(source_errors)
    cached.attrs["last_good_snapshot_source"] = str(
        metadata.get("snapshot_source", "")
    )
    if isinstance(metadata, dict):
        cached.attrs["last_good_created_at"] = str(payload.get("created_at", ""))
    if fresh:
        logger.info(
            "Using fresh snapshot cache %s: age_hours=%s rows=%d",
            path,
            stale_age_hours,
            len(cached),
        )
    else:
        logger.warning(
            "Using last-good snapshot cache %s after live source failures: %s",
            path,
            "; ".join(source_errors),
        )
    return cached


def _cache_stale_age_hours(mtime: float, *, created_at: str = "") -> float:
    modified = _parse_created_at(created_at) or datetime.fromtimestamp(mtime, tz=timezone.utc)
    age_hours = (datetime.now(timezone.utc) - modified).total_seconds() / 3600.0
    return round(max(age_hours, 0.0), 4)


def _parse_created_at(value: str) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)

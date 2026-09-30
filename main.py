# -*- coding: utf-8 -*-
"""
===================================
A-share watchlist intelligent analysis system - main orchestrator
===================================

Responsibilities:
1. Coordinate the modules through the stock analysis pipeline
2. Run a low-concurrency thread pool
3. Handle exceptions globally so one failed stock cannot break the run
4. Provide the command-line entry point

Usage:
    python main.py              # normal run
    python main.py --debug      # debug mode
    python main.py --dry-run    # fetch the data without analysing

Trading philosophy (already built into the analysis):
- Strict entry: never chase; skip anything with a bias above 5%
- Trend trading: only take MA5 > MA10 > MA20 bullish alignments
- Efficiency first: favour stocks with good chip concentration
- Entry preference: a shrinking-volume pullback onto MA5/MA10 support
"""
from __future__ import annotations

import json
import multiprocessing
import os
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple, Union

from dotenv import dotenv_values
from src.config import setup_env

_INITIAL_PROCESS_ENV = dict(os.environ)
setup_env()

# Proxy configuration - controlled by the USE_PROXY environment variable, off by default
# The GitHub Actions environment skips the proxy configuration automatically
if os.getenv("GITHUB_ACTIONS") != "true" and os.getenv("USE_PROXY", "false").lower() == "true":
    # Local development: enable the proxy (PROXY_HOST and PROXY_PORT can be set in .env)
    proxy_host = os.getenv("PROXY_HOST", "127.0.0.1")
    proxy_port = os.getenv("PROXY_PORT", "10809")
    proxy_url = f"http://{proxy_host}:{proxy_port}"
    os.environ["http_proxy"] = proxy_url
    os.environ["https_proxy"] = proxy_url

_packaged_import_probe = os.getenv("DSA_PACKAGED_IMPORT_PROBE")
if _packaged_import_probe:
    import importlib
    import sys

    try:
        importlib.import_module(_packaged_import_probe)
    except Exception as exc:
        print(
            f"ERROR: packaged import failed for {_packaged_import_probe}: {exc}",
            file=sys.stderr,
        )
        sys.exit(1)

    print(f"OK: packaged import succeeded for {_packaged_import_probe}")
    sys.exit(0)

import argparse
import logging
import sys
import time
import uuid
from datetime import date, datetime, timezone

from src.webui_frontend import prepare_webui_frontend_assets
from src.config import get_config, Config
from src.report_language import resolve_report_language
from src.logging_config import setup_logging
from src.brokers.futu.portfolio import FutuPortfolioError
from data_provider.base import canonical_stock_code
from src.services.stock_list_parser import (
    AnalysisTarget,
    ParseStatus,
    parse_analysis_target,
    split_stock_list,
)
from src.services.stock_code_utils import resolve_index_stock_code_for_analysis


logger = logging.getLogger(__name__)
_RUNTIME_ENV_FILE_KEYS = set()
_PUBLIC_BIND_HOSTS = frozenset({"0.0.0.0", "::", "[::]", "*"})
_LAST_ANALYSIS_FAILURE_REASON: Optional[str] = None


def _get_active_env_path() -> Path:
    env_file = os.getenv("ENV_FILE")
    if env_file:
        return Path(env_file)
    return Path(__file__).resolve().parent / ".env"


def _is_public_bind_host(host: str) -> bool:
    return (host or "").strip().lower() in _PUBLIC_BIND_HOSTS


def _warn_if_public_webui_without_auth(host: str) -> None:
    if not _is_public_bind_host(host):
        return

    from src.auth import is_auth_enabled

    if is_auth_enabled():
        return
    logger.warning(
        "WEBUI_HOST=%s binds the Web UI to a public interface while "
        "ADMIN_AUTH_ENABLED=false. Keep this service behind a trusted network "
        "boundary or enable admin authentication before exposing it.",
        host,
    )


def _resolve_web_service_bind(args: argparse.Namespace, config: Config) -> Tuple[str, int]:
    """Resolve the effective Web/API bind address from CLI first, then config."""
    host = args.host if args.host is not None else (config.webui_host or "127.0.0.1")
    port = args.port if args.port is not None else config.webui_port
    return host, port


def _read_active_env_values() -> Optional[Dict[str, str]]:
    env_path = _get_active_env_path()
    if not env_path.exists():
        return {}

    try:
        values = dotenv_values(env_path)
    except Exception as exc:  # pragma: no cover - defensive branch
        logger.warning("Failed to read config file %s; keeping the current environment variables: %s", env_path, exc)
        return None

    return {
        str(key): "" if value is None else str(value)
        for key, value in values.items()
        if key is not None
    }


_ACTIVE_ENV_FILE_VALUES = _read_active_env_values() or {}
_RUNTIME_ENV_FILE_KEYS = {
    key for key in _ACTIVE_ENV_FILE_VALUES
    if key not in _INITIAL_PROCESS_ENV
}

# setup_env() already ran at import time above.
_env_bootstrapped = True


def _bootstrap_environment() -> None:
    """Load .env and apply optional local proxy settings.

    Guarded to be idempotent so it can safely be called from lazy-import
    paths used by API / bot consumers.
    """
    global _env_bootstrapped
    if _env_bootstrapped:
        return

    from src.config import setup_env

    setup_env()

    if os.getenv("GITHUB_ACTIONS") != "true" and os.getenv("USE_PROXY", "false").lower() == "true":
        proxy_host = os.getenv("PROXY_HOST", "127.0.0.1")
        proxy_port = os.getenv("PROXY_PORT", "10809")
        proxy_url = f"http://{proxy_host}:{proxy_port}"
        os.environ["http_proxy"] = proxy_url
        os.environ["https_proxy"] = proxy_url

    _env_bootstrapped = True


def _setup_bootstrap_logging(debug: bool = False) -> None:
    """Initialize stderr-only logging before config is loaded.

    File handlers are deferred until ``config.log_dir`` is known (via the
    subsequent ``setup_logging()`` call) so that healthy runs never create
    log files in a hard-coded directory.
    """
    level = logging.DEBUG if debug else logging.INFO
    root = logging.getLogger()
    root.setLevel(level)
    if not any(
        isinstance(h, logging.StreamHandler) and getattr(h, "stream", None) is sys.stderr
        for h in root.handlers
    ):
        handler = logging.StreamHandler(sys.stderr)
        handler.setLevel(level)
        handler.setFormatter(
            logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
        )
        root.addHandler(handler)


def _setup_runtime_logging(log_dir: str, debug: bool = False) -> bool:
    """Switch to configured logging, falling back to console on file I/O errors."""
    try:
        setup_logging(log_prefix="stock_analysis", debug=debug, log_dir=log_dir)
        return True
    except OSError as exc:
        logger.warning(
            "File logging initialization failed, falling back to console logging; log directory %r is not writable or cannot be created: %s. "
            "The official Docker image entrypoint repairs permissions on the default mounted directories; if it still fails, "
            "check for write-restricting setups such as --user, read-only mounts, rootless Docker or NFS.",
            log_dir,
            exc,
        )
        return False


def _get_stock_analysis_pipeline():
    """Lazily import StockAnalysisPipeline for external consumers.

    Also ensures env/proxy bootstrap has run so that API / bot consumers
    that never call ``main()`` still get ``USE_PROXY`` applied.
    """
    _bootstrap_environment()
    from src.core.pipeline import StockAnalysisPipeline as _Pipeline

    return _Pipeline


class _LazyPipelineDescriptor:
    """Descriptor that resolves StockAnalysisPipeline on first attribute access."""

    _resolved = None

    def __set_name__(self, owner, name):
        self._name = name

    def __get__(self, obj, objtype=None):
        if self._resolved is None:
            self._resolved = _get_stock_analysis_pipeline()
        return self._resolved


class _ModuleExports:
    StockAnalysisPipeline = _LazyPipelineDescriptor()


_exports = _ModuleExports()


def __getattr__(name: str):
    if name == "StockAnalysisPipeline":
        return _exports.StockAnalysisPipeline
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def _reload_env_file_values_preserving_overrides() -> None:
    """Refresh `.env`-managed env vars without clobbering process env overrides."""
    global _RUNTIME_ENV_FILE_KEYS

    latest_values = _read_active_env_values()
    if latest_values is None:
        return

    managed_keys = {
        key for key in latest_values
        if key not in _INITIAL_PROCESS_ENV
    }

    for key in _RUNTIME_ENV_FILE_KEYS - managed_keys:
        os.environ.pop(key, None)

    for key in managed_keys:
        os.environ[key] = latest_values[key]

    _RUNTIME_ENV_FILE_KEYS = managed_keys


def parse_arguments() -> argparse.Namespace:
    """Parse the command-line arguments"""
    parser = argparse.ArgumentParser(
        description='AI stock analysis system for your watchlist',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='''
Examples:
  python main.py                    # normal run
  python main.py --debug            # debug mode
  python main.py --dry-run          # fetch data only, no AI analysis
  python main.py --stocks 600519,000001  # analyze specific stocks
  python main.py --stocks sh000016,000300.CSI,930955.CSI  # analyze registered indices (sh/sz prefix or .CSI alias)
  python main.py --portfolio futu   # use real Futu stock holdings (overrides --stocks)
  python main.py --no-notify        # do not send notifications
  python main.py --check-notify     # check notification config without sending
  python main.py --single-notify    # single-stock push mode (push after each stock)
  python main.py --schedule         # scheduled mode
  python main.py --market-review    # run the market review only
        '''
    )

    parser.add_argument(
        '--debug',
        action='store_true',
        help='Enable debug mode with verbose logging'
    )

    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Fetch data only, without AI analysis'
    )

    parser.add_argument(
        '--stocks',
        type=str,
        help='Comma-separated stock codes to analyze (overrides the config file); registered indices are supported via sh/sz prefixes (e.g. sh000016) or .CSI aliases (e.g. 000300.CSI, 930955.CSI)'
    )

    parser.add_argument(
        '--portfolio',
        type=str.lower,
        choices=('futu',),
        help='Use real broker holdings as the stock list; currently supports futu and overrides --stocks/STOCK_LIST'
    )

    parser.add_argument(
        '--no-notify',
        action='store_true',
        help='Do not send notifications'
    )

    parser.add_argument(
        '--check-notify',
        action='store_true',
        help='Check notification channel configuration read-only, without sending'
    )

    parser.add_argument(
        '--single-notify',
        action='store_true',
        help='Single-stock push mode: push each stock as soon as it is analyzed instead of a summary'
    )

    parser.add_argument(
        '--workers',
        type=int,
        default=None,
        help='Number of worker threads (defaults to the configured value)'
    )

    parser.add_argument(
        '--schedule',
        action='store_true',
        help='Enable scheduled mode (runs daily at the configured time)'
    )

    parser.add_argument(
        '--no-run-immediately',
        action='store_true',
        help='Do not run once immediately when the scheduler starts'
    )

    parser.add_argument(
        '--market-review',
        action='store_true',
        help='Run the market review only'
    )

    parser.add_argument(
        '--no-market-review',
        action='store_true',
        help='Skip the market review'
    )

    parser.add_argument(
        '--force-run',
        action='store_true',
        help='Skip the trading-day check and force a full analysis (Issue #373)'
    )

    parser.add_argument(
        '--webui',
        action='store_true',
        help='Start the web management UI'
    )

    parser.add_argument(
        '--webui-only',
        action='store_true',
        help='Start the web service only, without automatic analysis'
    )

    parser.add_argument(
        '--serve',
        action='store_true',
        help='Start the FastAPI backend (and run the analysis)'
    )

    parser.add_argument(
        '--serve-only',
        action='store_true',
        help='Start the FastAPI backend only, without automatic analysis'
    )

    parser.add_argument(
        '--port',
        type=int,
        default=None,
        help='FastAPI port (defaults to WEBUI_PORT, or 8000 when unset)'
    )

    parser.add_argument(
        '--host',
        type=str,
        default=None,
        help='FastAPI listen address (defaults to WEBUI_HOST, or 127.0.0.1 when unset)'
    )

    parser.add_argument(
        '--no-context-snapshot',
        action='store_true',
        help='Do not save analysis context snapshots'
    )

    # === Backtest ===
    parser.add_argument(
        '--backtest',
        action='store_true',
        help='Run a backtest (evaluate historical analysis results)'
    )

    parser.add_argument(
        '--backtest-code',
        type=str,
        default=None,
        help='Backtest only this stock code'
    )

    parser.add_argument(
        '--backtest-days',
        type=int,
        default=None,
        help='Backtest evaluation window in trading days (defaults to the config)'
    )

    parser.add_argument(
        '--backtest-force',
        action='store_true',
        help='Force the backtest (recompute even when results already exist)'
    )

    return parser.parse_args()


def _compute_trading_day_filter(
    config: Config,
    args: argparse.Namespace,
    stock_codes: List[str],
) -> Tuple[List[str], Optional[str], bool]:
    """
    Compute filtered stock list and effective market review region (Issue #373).

    Returns:
        (filtered_codes, effective_region, should_skip_all)
        - effective_region None = use config default (check disabled)
        - effective_region '' = all relevant markets closed, skip market review
        - should_skip_all: skip entire run when no stocks and no market review to run
    """
    force_run = getattr(args, 'force_run', False)
    if force_run or not getattr(config, 'trading_day_check_enabled', True):
        return (stock_codes, None, False)

    from src.core.trading_calendar import (
        get_market_for_stock,
        get_open_markets_today,
        compute_effective_region,
    )

    open_markets = get_open_markets_today()
    filtered_codes = []
    for code in stock_codes:
        mkt = get_market_for_stock(code)
        if mkt is None:
            # get_market_for_stock returns None for an index code (sh000016/csi930955/930955.CSI);
            # keeping a plain fail-open would leave indices unfiltered on A-share holidays, breaking
            # the per-stock trading-day contract. Codes with an unknown market go through parse_analysis_target,
            # so registered indices join the CN trading-day filter as market=cn; non-index codes that stay
            # unknown keep failing open.
            target = parse_analysis_target(code)
            if target.asset_type == ParseStatus.INDEX:
                mkt = "cn"
        if mkt in open_markets or mkt is None:
            filtered_codes.append(code)

    if config.market_review_enabled and not getattr(args, 'no_market_review', False):
        effective_region = compute_effective_region(
            getattr(config, 'market_review_region', 'cn') or 'cn', open_markets
        )
    else:
        effective_region = None

    should_skip_all = (not filtered_codes) and (effective_region or '') == ''
    return (filtered_codes, effective_region, should_skip_all)


def _classify_stock_list_tokens(
    tokens: List[str],
    *,
    entry_label: str,
) -> Optional[Tuple[List[str], List[AnalysisTarget]]]:
    """Classify stock-list tokens into aligned ``(stock_codes, analysis_targets)``.

    Shared by the one-shot ``--stocks`` entry and the GitHub Actions
    ``STOCK_LIST`` entry: explicit index tokens resolve through
    ``parse_analysis_target`` and keep their index canonical, while every
    other token keeps the legacy ``resolve_index_stock_code_for_analysis``
    path. ``unsupported`` tokens (e.g. an unregistered ``.CSI``) reject the
    whole run up-front with an explicit error — provider calls are never
    reached for any token in the batch. Returns ``None`` after logging the
    rejection, so callers exit without running analysis.
    """
    targets = [parse_analysis_target(t) for t in tokens]
    unsupported = [
        (token, target.unsupported_reason or "unsupported target")
        for token, target in zip(tokens, targets)
        if target.asset_type == ParseStatus.UNSUPPORTED
    ]
    if unsupported:
        token, reason = unsupported[0]
        logger.error(
            "%s contains an unsupported target %r: %s; no analysis will run this round.",
            entry_label,
            token,
            reason,
        )
        return None
    stock_codes = [
        t.canonical_id
        if t.asset_type == ParseStatus.INDEX
        else resolve_index_stock_code_for_analysis(raw)
        for t, raw in zip(targets, tokens)
    ]
    return stock_codes, targets


def _run_market_review_with_shared_lock(
    config: Config,
    run_market_review_func: Callable[..., Any],
    **kwargs: Any,
) -> Any:
    from src.core.market_review_lock import (
        release_market_review_lock,
        try_acquire_market_review_lock,
    )

    lock_token = try_acquire_market_review_lock(config)
    if lock_token is None:
        logger.warning("A market review is already running; skipping this market review")
        return None

    try:
        params = dict(kwargs)
        params.setdefault("config", config)
        return run_market_review_func(**params)
    finally:
        release_market_review_lock(lock_token)


def _is_multi_market_region(region: str) -> bool:
    normalized = str(region or "").strip().lower()
    if not normalized:
        return False
    if normalized == "both":
        return True
    parts = {item.strip() for item in normalized.split(",") if item.strip()}
    return len(parts) > 1


def _refresh_stock_index_cache_for_analysis(config: Config) -> None:
    """Best-effort stock-index refresh for CLI/scheduled analysis paths."""
    try:
        from src.services.stock_index_remote_service import (
            refresh_remote_stock_index_cache,
            settings_from_config,
        )

        result = refresh_remote_stock_index_cache(settings_from_config(config))
        if result.refreshed:
            logger.info("[stock-index] Stock index cache refreshed before analysis: %s", result.cache_path)
        elif result.error:
            logger.debug("[stock-index] Pre-analysis refresh incomplete, using the local index: %s", result.error)
    except Exception as exc:  # noqa: BLE001 - stock index freshness must not block analysis.
        logger.warning("[stock-index] Pre-analysis stock index refresh failed; continuing: %s", exc)


def _resolve_portfolio_stock_codes(args: argparse.Namespace) -> Optional[List[str]]:
    """Resolve an optional broker portfolio into the analysis stock list."""
    portfolio = str(getattr(args, "portfolio", "") or "").strip().lower()
    if not portfolio:
        return None
    if portfolio != "futu":  # argparse prevents this for CLI callers; keep API callers safe.
        raise ValueError(f"Unsupported portfolio: {portfolio}")

    from src.brokers.futu.portfolio import load_futu_stock_codes

    stock_codes = [
        canonical_stock_code(code)
        for code in load_futu_stock_codes()
        if (code or "").strip()
    ]
    logger.info("portfolio=futu overrides stocks/STOCK_LIST, using %d real stock holding(s)", len(stock_codes))
    return stock_codes


def _prime_daily_market_context(
    config: Config,
    pipeline: Any,
    *,
    region: str,
    no_market_review: bool,
    allow_generate: bool,
    force_refresh: bool = False,
    target_date: Optional[date] = None,
    return_full_report: bool = False,
    require_current_query_match: bool = False,
) -> Union[str, Tuple[str, str]]:
    """Load/reuse the run's market context, avoiding unbounded background generation."""
    if no_market_review or not region:
        return ("", "") if return_full_report else ""

    from src.services.daily_market_context import DailyMarketContextService

    if not _is_multi_market_region(region):
        service = getattr(pipeline, "_daily_market_context_service", None)
        if service is None:
            service = DailyMarketContextService(db_manager=pipeline.db)
            pipeline._daily_market_context_service = service
    else:
        service = DailyMarketContextService(db_manager=pipeline.db)

    get_context_kwargs = {
        "region": region,
        "config": config,
        "notifier": pipeline.notifier,
        "analyzer": pipeline.analyzer,
        "search_service": pipeline.search_service,
        "force_refresh": force_refresh,
        "allow_generate": allow_generate,
        "persist_market_review_history": False,
        "target_date": target_date,
        "require_query_id_match": require_current_query_match,
    }
    current_query_id = getattr(pipeline, "query_id", None)
    if isinstance(current_query_id, str) and current_query_id.strip():
        get_context_kwargs["current_query_id"] = current_query_id

    context = service.get_context(**get_context_kwargs)
    if context is None:
        return ("", "") if return_full_report else ""

    # Runtime context generation is preload-only and must not replace the full
    # market review run, except the query-scoped fallback after that run fails.
    if context.source != "analysis_history" and not (
        require_current_query_match and context.source == "market_review_runtime"
    ):
        return ("", "") if return_full_report else ""

    summary = str(getattr(context, "summary", ""))
    full_report = str(getattr(context, "full_report", "") or "")
    if return_full_report:
        return summary, full_report
    return summary


def _can_reuse_market_context_for_review(summary: str, region: str) -> bool:
    if not summary:
        return False
    normalized = str(region or "").strip().lower()
    if normalized == "both":
        return False
    parts = {item.strip() for item in normalized.split(",") if item.strip()}
    return len(parts) <= 1


def _resolve_daily_market_context_market(market: str, normalized_region: str) -> str:
    if "," not in normalized_region:
        return market
    parts = [item.strip() for item in normalized_region.split(",") if item.strip()]
    if parts and all(item in {"jp", "kr"} for item in parts):
        return parts[0]
    return market


def _resolve_daily_market_context_target_date(
    region: str,
    current_time: datetime,
) -> date:
    normalized_region = str(region or "cn").strip().lower()
    market = normalized_region if normalized_region in {"cn", "hk", "us", "jp", "kr"} else "cn"

    from src.core.trading_calendar import get_effective_trading_date

    return get_effective_trading_date(
        _resolve_daily_market_context_market(market, normalized_region),
        current_time=current_time,
    )


def _market_review_report_text(review_result: Any) -> str:
    if review_result is None:
        return ""
    report = getattr(review_result, "report", None)
    if isinstance(report, str):
        return report
    return review_result if isinstance(review_result, str) else ""


_MERGED_REPORT_HEADINGS: Dict[str, Dict[str, str]] = {
    "en": {
        "market_review": "# 📈 Market Review",
        "dashboard": "# 🚀 Stock Decision Dashboard",
    },
    "zh": {
        "market_review": "# 📈 大盘复盘",
        "dashboard": "# 🚀 个股决策仪表盘",
    },
}


def _merged_report_headings(config: Any) -> Dict[str, str]:
    """Return the section headings for merged notifications.

    Follows ``REPORT_LANGUAGE``; languages without their own entry (``ko``) use English.
    """
    language = resolve_report_language(getattr(config, "report_language", None))
    return _MERGED_REPORT_HEADINGS.get(language, _MERGED_REPORT_HEADINGS["en"])


def _save_reused_market_review_report(
    notifier: Any,
    market_report: str,
    *,
    config: Config,
    trigger_source: str,
    region: str,
) -> None:
    body = str(market_report or "").strip()
    if not body:
        return
    title = (
        "# 🎯 Market Review"
        if resolve_report_language(getattr(config, "report_language", None)) != "zh"
        else "# 🎯 大盘复盘"
    )
    if not any(body.startswith(item) for item in ("# 🎯 大盘复盘", "# 🎯 Market Review")):
        body = f"{title}\n\n{body}"
    try:
        date_str = datetime.now().strftime('%Y%m%d')
        report_filename = f"market_review_{date_str}.md"
        filepath = notifier.save_report_to_file(body, report_filename)
        logger.info(
            "[MarketReview] component=market_review action=save_reused_report "
            "trigger_source=%s region=%s path=%s",
            trigger_source,
            region,
            filepath,
        )
    except Exception as exc:
        logger.warning("Failed to save the market review report from the reused market context: %s", exc)


def _run_auto_backtest(config: Config) -> None:
    """Run the independently configured auto-backtest without failing analysis."""

    try:
        if not getattr(config, 'backtest_enabled', False):
            return

        from src.services.backtest_service import BacktestService

        logger.info("Starting automatic backtest...")
        service = BacktestService()
        stats = service.run_backtest(
            force=False,
            eval_window_days=getattr(config, 'backtest_eval_window_days', 10),
            min_age_days=getattr(config, 'backtest_min_age_days', 14),
            limit=200,
        )
        logger.info(
            f"Automatic backtest finished: processed={stats.get('processed')} "
            f"saved={stats.get('saved')} completed={stats.get('completed')} "
            f"insufficient={stats.get('insufficient')} errors={stats.get('errors')}"
        )
    except Exception as exc:
        logger.warning(f"Automatic backtest failed (ignored): {exc}")


def run_full_analysis(
    config: Config,
    args: argparse.Namespace,
    stock_codes: Optional[List[str]] = None,
    *,
    raise_errors: bool = False,
    analysis_targets: Optional[List[AnalysisTarget]] = None,
) -> bool:
    """
    Run the full analysis pipeline (single stocks plus the broad-market review)

    This is the main entry the scheduled job calls. A Futu position-parsing failure always propagates
    to the caller; ``raise_errors`` only governs the exception semantics after parsing succeeds.
    ``analysis_targets`` lines up with ``stock_codes`` and carries the structured analysis targets
    (index targets drive market=cn and the capability matrix).
    """
    # Portfolio resolution is its own CLI contract boundary. A broker import
    # failure must reach the one-shot caller, while all later work keeps the
    # existing run_full_analysis return-value semantics.
    portfolio_stock_codes = _resolve_portfolio_stock_codes(args)
    portfolio_is_empty = portfolio_stock_codes == []
    market_review_requested = (
        getattr(config, 'market_review_enabled', False)
        and not getattr(args, 'no_market_review', False)
    )
    if portfolio_is_empty and not market_review_requested:
        logger.info(
            "No eligible Futu holdings in the real account; "
            "skipping stock analysis and the market review this round."
        )
        _run_auto_backtest(config)
        return True

    # Import pipeline modules outside the broad try/except so that import-time
    # failures propagate to the caller instead of being silently swallowed.
    from src.core.market_review import run_market_review
    from src.core.pipeline import StockAnalysisPipeline

    global _LAST_ANALYSIS_FAILURE_REASON
    _LAST_ANALYSIS_FAILURE_REASON = None

    def _return_with_auto_backtest(result: bool) -> bool:
        _run_auto_backtest(config)
        return result

    try:
        _refresh_stock_index_cache_for_analysis(config)
        if portfolio_stock_codes is not None:
            stock_codes = portfolio_stock_codes
            analysis_targets = None

        # Issue #529: Hot-reload STOCK_LIST from .env on each scheduled run
        if stock_codes is None and portfolio_stock_codes is None:
            config.refresh_stock_list()

        using_config_stock_list = stock_codes is None and portfolio_stock_codes is None
        effective_codes = stock_codes if stock_codes is not None else config.stock_list
        # Fail fast on an empty persisted watchlist before trading-day filtering.
        # Otherwise should_skip=True would mask the configuration error as success.
        if (
            not getattr(args, "dry_run", False)
            and using_config_stock_list
            and not effective_codes
            and not market_review_requested
        ):
            _LAST_ANALYSIS_FAILURE_REASON = "empty_stock_list"
            logger.error(
                "No report was generated this round: STOCK_LIST is empty and the market review is disabled."
            )
            return _return_with_auto_backtest(False)

        # Issue #373: Trading day filter (per-stock, per-market)
        filtered_codes, effective_region, should_skip = _compute_trading_day_filter(
            config, args, effective_codes
        )
        if should_skip:
            if portfolio_is_empty:
                logger.info(
                    "No eligible Futu holdings in the real account; "
                    "no stock analysis or market review is needed this round; skipping."
                )
            else:
                logger.info(
                    "All relevant markets are closed today; skipping. "
                    "Use --force-run to run anyway."
                )
            return True
        if set(filtered_codes) != set(effective_codes):
            skipped = set(effective_codes) - set(filtered_codes)
            logger.info("Skipped stocks whose markets are closed today: %s", skipped)
        if analysis_targets is not None:
            if len(analysis_targets) != len(effective_codes):
                raise ValueError("analysis_targets must align with stock_codes")
            remaining_pairs = list(zip(effective_codes, analysis_targets))
            filtered_targets = []
            for filtered_code in filtered_codes:
                for index, (code, target) in enumerate(remaining_pairs):
                    if code == filtered_code:
                        filtered_targets.append(target)
                        remaining_pairs.pop(index)
                        break
            analysis_targets = filtered_targets
        stock_codes = filtered_codes
        skip_futu_stock_analysis = (
            portfolio_stock_codes is not None and not stock_codes
        )

        # The --single-notify command-line flag overrides the configuration (#55)
        if getattr(args, 'single_notify', False):
            config.single_stock_notify = True

        # Issue #190: combine the single-stock and broad-market pushes
        merge_notification = (
            getattr(config, 'merge_email_notification', False)
            and config.market_review_enabled
            and not getattr(args, 'no_market_review', False)
            and not config.single_stock_notify
        )

        # Create the scheduler
        save_context_snapshot = None
        if getattr(args, 'no_context_snapshot', False):
            save_context_snapshot = False
        query_id = uuid.uuid4().hex
        market_review_region = (
            effective_region
            if effective_region is not None
            else (getattr(config, 'market_review_region', 'cn') or 'cn')
        )
        should_run_market_review = (
            config.market_review_enabled
            and not args.no_market_review
            and (market_review_region or '') != ''
        )
        if (
            not getattr(args, "dry_run", False)
            and not stock_codes
            and using_config_stock_list
            and not should_run_market_review
        ):
            _LAST_ANALYSIS_FAILURE_REASON = "empty_stock_list"
            logger.error(
                "No report was generated this round: STOCK_LIST is empty and the market review is disabled."
            )
            return _return_with_auto_backtest(False)
        should_use_daily_market_context = (
            should_run_market_review
            and getattr(config, 'daily_market_context_enabled', True)
        )
        analysis_reference_time = datetime.now(timezone.utc)
        daily_market_context_target_date = None
        if should_use_daily_market_context:
            daily_market_context_target_date = _resolve_daily_market_context_target_date(
                market_review_region,
                analysis_reference_time,
            )
        market_report = ""
        market_context_summary = ""
        market_context_full_report = ""
        market_context_generated_during_stock = False
        pipeline = StockAnalysisPipeline(
            config=config,
            max_workers=args.workers,
            query_id=query_id,
            query_source="cli",
            save_context_snapshot=save_context_snapshot,
            daily_market_context_enabled=should_use_daily_market_context,
            daily_market_context_allow_generate=should_use_daily_market_context,
        )
        if should_use_daily_market_context:
            # Prompt-side context can reuse historical summaries, while full-merge
            # content must avoid silently reusing unrelated historical reports.
            _prime_daily_market_context(
                config,
                pipeline=pipeline,
                region=market_review_region,
                no_market_review=args.no_market_review,
                allow_generate=False,
                target_date=daily_market_context_target_date,
                return_full_report=False,
            )
            (
                market_context_summary,
                market_context_full_report,
            ) = _prime_daily_market_context(
                config,
                pipeline=pipeline,
                region=market_review_region,
                no_market_review=args.no_market_review,
                allow_generate=False,
                target_date=daily_market_context_target_date,
                return_full_report=True,
                require_current_query_match=True,
            )

        # 1. Run the single-stock analysis
        if skip_futu_stock_analysis:
            if portfolio_is_empty:
                logger.info("No eligible Futu holdings in the real account; skipping stock analysis.")
            else:
                logger.info("No Futu holdings left to analyze after the trading-day filter; skipping stock analysis.")
            results = []
        else:
            results = pipeline.run(
                stock_codes=stock_codes,
                dry_run=args.dry_run,
                send_notification=not args.no_notify,
                merge_notification=merge_notification,
                current_time=analysis_reference_time,
                analysis_targets=analysis_targets,
            )

        if should_use_daily_market_context and not market_context_summary:
            (
                market_context_summary,
                market_context_full_report,
            ) = _prime_daily_market_context(
                config,
                pipeline=pipeline,
                region=market_review_region,
                no_market_review=args.no_market_review,
                allow_generate=False,
                target_date=daily_market_context_target_date,
                return_full_report=True,
                require_current_query_match=True,
            )
            market_context_generated_during_stock = bool(market_context_summary)

        # Issue #128: analysis interval - wait between the single-stock and broad-market analyses
        analysis_delay = getattr(config, 'analysis_delay', 0)

        # 2. Run the broad-market review (when enabled and not in single-stock-only mode)
        if should_run_market_review:
            schedule_mode = bool(
                getattr(args, 'schedule', False)
                or getattr(config, 'schedule_enabled', False)
            )
            review_trigger_source = "schedule" if schedule_mode else "cli"
            can_reuse_market_context = (
                _can_reuse_market_context_for_review(
                    market_context_summary,
                    market_review_region,
                )
                if should_use_daily_market_context
                else False
            )

            can_skip_market_review = (
                (merge_notification or market_context_generated_during_stock)
                and can_reuse_market_context
                and bool(market_context_full_report or market_context_summary)
            )
            if can_skip_market_review:
                market_report = market_context_full_report or market_context_summary
                logger.info(
                    "Market review context is reusable; skipping the duplicate market review and reusing the context."
                )
                _save_reused_market_review_report(
                    pipeline.notifier,
                    market_report,
                    config=config,
                    trigger_source=review_trigger_source,
                    region=market_review_region,
                )
                if (
                    market_context_generated_during_stock
                    and not merge_notification
                    and not args.no_notify
                    and pipeline.notifier.is_available()
                ):
                    if pipeline.notifier.send(
                        f"{_merged_report_headings(config)['market_review']}\n\n{market_report}",
                        email_send_to_all=True,
                        route_type="report",
                    ):
                        logger.info("Pushed the market review from this round's reused market context")
                    else:
                        logger.warning("Failed to push the market review from this round's reused market context")

            review_result = None
            if not can_skip_market_review:
                if analysis_delay > 0:
                    logger.info(f"Waiting {analysis_delay} s before the market review (to avoid API rate limits)...")
                    time.sleep(analysis_delay)

                review_result = _run_market_review_with_shared_lock(
                    config,
                    run_market_review,
                    notifier=pipeline.notifier,
                    analyzer=pipeline.analyzer,
                    search_service=pipeline.search_service,
                    send_notification=not args.no_notify,
                    merge_notification=merge_notification,
                    override_region=market_review_region,
                    query_id=query_id,
                    trigger_source=review_trigger_source,
                )
                # If the review still has not succeeded, retry the history/cache reuse once (guarding against a race with a concurrent run).
                if not review_result and should_use_daily_market_context:
                    (
                        market_context_summary,
                        market_context_full_report,
                    ) = _prime_daily_market_context(
                        config,
                        pipeline=pipeline,
                        region=market_review_region,
                        no_market_review=args.no_market_review,
                        allow_generate=False,
                        target_date=daily_market_context_target_date,
                        return_full_report=True,
                        require_current_query_match=True,
                    )
                    can_reuse_market_context = _can_reuse_market_context_for_review(
                        market_context_summary,
                        market_review_region,
                    )
                elif not review_result:
                    can_reuse_market_context = False

            # When there is a result, assign it to market_report for the merged notification
            if review_result:
                market_report = _market_review_report_text(review_result)
            elif can_reuse_market_context:
                market_report = market_context_full_report or market_context_summary

        expected_stock_report = (
            not getattr(args, "dry_run", False)
            and bool(stock_codes)
            and not skip_futu_stock_analysis
        )
        deferred_failure_result = None
        if expected_stock_report and results and not getattr(
            pipeline, "_last_local_report_path", None
        ):
            _LAST_ANALYSIS_FAILURE_REASON = "report_save_failed"
            save_error = getattr(pipeline, "_last_local_report_error", None) or "unknown error"
            logger.error(
                "Stock results were generated this round, but saving the summary report failed and no local report file was written: %s",
                save_error,
            )
            deferred_failure_result = False
        expected_market_report = (
            not getattr(args, "dry_run", False)
            and should_run_market_review
        )
        if (expected_stock_report or expected_market_report) and not results and not market_report:
            _LAST_ANALYSIS_FAILURE_REASON = "no_report"
            logger.error(
                "No report was generated this round: neither the expected stock analysis nor the market review produced results."
            )
            return _return_with_auto_backtest(False)

        # Issue #190: combined push (single stocks plus broad-market review)
        if merge_notification and (results or market_report) and not args.no_notify:
            headings = _merged_report_headings(config)
            parts = []
            if market_report:
                parts.append(f"{headings['market_review']}\n\n{market_report}")
            if results:
                dashboard_content = pipeline.notifier.generate_aggregate_report(
                    results,
                    getattr(config, 'report_type', 'simple'),
                )
                parts.append(f"{headings['dashboard']}\n\n{dashboard_content}")
            if parts:
                combined_content = "\n\n---\n\n".join(parts)
                if pipeline.notifier.is_available():
                    if pipeline.notifier.send(combined_content, email_send_to_all=True, route_type="report"):
                        logger.info("Merged push sent (stocks + market review)")
                    else:
                        logger.warning("Merged push failed")

        # Print the summary
        if results:
            logger.info("\n===== Analysis summary =====")
            for r in sorted(results, key=lambda x: x.sentiment_score, reverse=True):
                emoji = r.get_emoji()
                logger.info(
                    f"{emoji} {r.name}({r.code}): {r.operation_advice} | "
                    f"score {r.sentiment_score} | {r.trend_prediction}"
                )

        logger.info("\nRun finished")

        return _return_with_auto_backtest(
            deferred_failure_result
            if deferred_failure_result is not None
            else True
        )

    except Exception as e:
        if _LAST_ANALYSIS_FAILURE_REASON is None:
            _LAST_ANALYSIS_FAILURE_REASON = "runtime_error"
        logger.exception(f"Analysis run failed: {e}")
        if raise_errors:
            raise
        return False


def run_scheduled_analysis(
    config: Config,
    args: argparse.Namespace,
    stock_codes: Optional[List[str]] = None,
) -> bool:
    """Run scheduled analysis with failures propagated to the scheduler."""
    return run_full_analysis(config, args, stock_codes, raise_errors=True)


def _run_analysis_with_runtime_scheduler_lock(
    config: Config,
    args: argparse.Namespace,
    stock_codes: Optional[List[str]] = None,
    analysis_targets: Optional[List[AnalysisTarget]] = None,
) -> bool:
    from src.services.runtime_scheduler import run_with_global_analysis_lock

    task_result: Dict[str, bool] = {"ok": True}

    def _locked_task_runner(
        locked_config: Config,
        locked_args: argparse.Namespace,
        locked_stock_codes: Optional[List[str]] = None,
    ) -> bool:
        if analysis_targets is None:
            result = run_full_analysis(locked_config, locked_args, locked_stock_codes)
        else:
            result = run_full_analysis(
                locked_config,
                locked_args,
                locked_stock_codes,
                analysis_targets=analysis_targets,
            )
        task_result["ok"] = bool(result)
        return task_result["ok"]

    # Keep startup/triggered analysis in sync with API runtime scheduler and
    # run-now entrypoint. Blocking is expected here because startup paths should
    # wait for an in-flight job before returning a response.
    lock_acquired = run_with_global_analysis_lock(
        task_runner=_locked_task_runner,
        config=config,
        args=args,
        stock_codes=stock_codes,
        blocking=True,
    )
    return bool(lock_acquired and task_result["ok"])


def start_api_server(host: str, port: int, config: Config) -> None:
    """
    Start the FastAPI service on a background thread

    Args:
        host: the listen address
        port: the listen port
        config: the configuration object
    """
    import socket
    import threading
    import uvicorn

    probe = socket.socket(socket.AF_INET6 if ":" in host else socket.AF_INET, socket.SOCK_STREAM)
    try:
        probe.bind((host, port))
    except OSError as exc:
        raise RuntimeError(f"FastAPI port is not available: {host}:{port}") from exc
    finally:
        probe.close()

    level_name = (config.log_level or "INFO").lower()
    use_config_signal_handlers = True
    uvicorn_kwargs = {
        "host": host,
        "port": port,
        "log_level": level_name,
        "log_config": None,
    }
    # Import the ASGI app object in the calling thread instead of handing uvicorn
    # the "api.app:app" import string. With the string, uvicorn imports the app
    # lazily inside the server thread, and that import (litellm + the full app
    # tree, ~10s+ on constrained hosts) runs inside the startup probe window
    # below, tripping the 3.0s timeout and causing a restart loop on slower
    # machines. Importing first keeps the heavy work out of the probe window;
    # genuine import failures still surface immediately to the caller.
    from api.app import app as fastapi_app

    try:
        uvicorn_config = uvicorn.Config(
            fastapi_app,
            install_signal_handlers=False,
            **uvicorn_kwargs,
        )
    except TypeError:
        # Older uvicorn versions do not accept install_signal_handlers in
        # Config; fall back and only disable signal handling via Server attribute
        # when it's a boolean flag.
        use_config_signal_handlers = False
        uvicorn_config = uvicorn.Config(
            fastapi_app,
            **uvicorn_kwargs,
        )
    uvicorn_server = uvicorn.Server(config=uvicorn_config)
    if not use_config_signal_handlers:
        install_signal_handlers = getattr(uvicorn_server, "install_signal_handlers", None)
        if isinstance(install_signal_handlers, bool):
            uvicorn_server.install_signal_handlers = False

    startup_error: list[BaseException] = []

    def run_server():
        try:
            uvicorn_server.run()
        except Exception as exc:  # noqa: BLE001 - surface startup issues to caller promptly
            startup_error.append(exc)

    thread = threading.Thread(target=run_server, daemon=True)
    thread.start()

    timeout_seconds = 3.0
    wait_deadline = time.time() + timeout_seconds
    while time.time() < wait_deadline:
        if startup_error:
            raise RuntimeError(
                f"FastAPI server failed to start: {host}:{port}; {startup_error[0]}"
            )
        if uvicorn_server.started:
            logger.info(f"FastAPI service started: http://{host}:{port}")
            return
        if not thread.is_alive():
            break
        time.sleep(0.05)

    if startup_error:
        raise RuntimeError(f"FastAPI server failed to start: {host}:{port}; {startup_error[0]}")
    if uvicorn_server.started:
        logger.info(f"FastAPI service started: http://{host}:{port}")
        return
    if not thread.is_alive():
        raise RuntimeError(f"FastAPI server exited immediately after starting: {host}:{port}")

    raise RuntimeError(f"FastAPI service did not finish starting within {timeout_seconds:.1f}s: {host}:{port}")


def _is_truthy_env(var_name: str, default: str = "true") -> bool:
    """Parse common truthy / falsy environment values."""
    value = os.getenv(var_name, default).strip().lower()
    return value not in {"0", "false", "no", "off"}


def _resolve_scheduled_stock_codes(stock_codes: Optional[List[str]]) -> Optional[List[str]]:
    """Scheduled runs should always read the latest persisted watchlist."""
    if stock_codes is not None:
        logger.warning(
            "--stocks was given in scheduled mode; scheduled runs ignore the startup stock snapshot and re-read the latest STOCK_LIST before each run."
        )
    return None


def _skips_stock_entry(args: argparse.Namespace, config: Config) -> bool:
    """Whether the active mode consumes a stock list at all.

    Modes that do not analyze the watchlist must not parse/classify
    ``--stocks``/``STOCK_LIST`` tokens nor refresh the stock-index registry
    before the mode dispatch, otherwise an unsupported index token would
    wrongly block a run that never consumes it. Covered modes:
    ``--backtest``, ``--market-review``, ``--serve-only``/``--webui-only``,
    ``--portfolio`` (any value) and ``--schedule``/``config.schedule_enabled``.
    ``--serve`` (not serve-only) and plain one-shot runs still consume the
    stock list and stay outside the guard. The webui-only flag is read
    directly here because the webui -> serve mapping happens only later in
    ``main()``.
    """
    return bool(
        getattr(args, "backtest", False)
        or getattr(args, "market_review", False)
        or getattr(args, "serve_only", False)
        or getattr(args, "webui_only", False)
        or bool(getattr(args, "portfolio", None))
        or getattr(args, "schedule", False)
        or getattr(config, "schedule_enabled", False)
    )


def _reload_runtime_config() -> Config:
    """Reload config from the latest persisted `.env` values for scheduled runs."""
    _reload_env_file_values_preserving_overrides()
    Config.reset_instance()
    new_config = get_config()

    # Drop the module-level ToolRegistry so the next
    # ``build_agent_executor`` / ``build_agent_chat_executor`` call rebuilds
    # it against the freshly-loaded Config and picks up new
    # ``AGENT_*_TOOL_TIMEOUT_S`` overrides (Issue #1890). Wrap in try/except
    # so a future runtime reset helper cannot crash scheduled-job bootstrap.
    try:
        from src.agent.factory import reset_tool_registry

        reset_tool_registry()
    except Exception as exc:  # pragma: no cover - defensive guard
        logger.warning("Failed to reset tool registry during config reload: %s", exc)

    return new_config


def _build_schedule_time_provider(default_schedule_time: str):
    """Read the latest schedule time directly from the active config file.

    Fallback order:
    1. Process-level env override (set before launch) → honour it.
    2. Persisted config file value (written by WebUI) → use it.
    3. Documented system default ``"18:00"`` → always fall back here so
       that clearing SCHEDULE_TIME in WebUI correctly resets the schedule.
    """
    from src.core.config_manager import ConfigManager

    _SYSTEM_DEFAULT_SCHEDULE_TIME = "18:00"
    manager = ConfigManager()

    def _provider() -> str:
        if "SCHEDULE_TIME" in _INITIAL_PROCESS_ENV:
            return os.getenv("SCHEDULE_TIME", default_schedule_time)

        config_map = manager.read_config_map()
        schedule_time = (config_map.get("SCHEDULE_TIME", "") or "").strip()
        if schedule_time:
            return schedule_time
        return _SYSTEM_DEFAULT_SCHEDULE_TIME

    return _provider


def _build_schedule_times_provider(default_schedule_time: str):
    """Read the latest SCHEDULE_TIMES with SCHEDULE_TIME fallback."""
    from src.core.config_manager import ConfigManager
    from src.scheduler import normalize_schedule_times

    _SYSTEM_DEFAULT_SCHEDULE_TIME = "18:00"
    manager = ConfigManager()

    def _provider():
        if "SCHEDULE_TIMES" in _INITIAL_PROCESS_ENV:
            return normalize_schedule_times(
                os.getenv("SCHEDULE_TIMES", ""),
                fallback_time=os.getenv("SCHEDULE_TIME", default_schedule_time),
            )
        if "SCHEDULE_TIME" in _INITIAL_PROCESS_ENV:
            return normalize_schedule_times(
                os.getenv("SCHEDULE_TIMES", ""),
                fallback_time=os.getenv("SCHEDULE_TIME", default_schedule_time),
            )

        config_map = manager.read_config_map()
        schedule_time = (config_map.get("SCHEDULE_TIME", "") or "").strip() or _SYSTEM_DEFAULT_SCHEDULE_TIME
        return normalize_schedule_times(
            config_map.get("SCHEDULE_TIMES", ""),
            fallback_time=schedule_time,
        )

    return _provider


def main() -> int:
    """
    Main entry point

    Returns:
        The exit code (0 means success)
    """
    # Parse the command-line arguments
    args = parse_arguments()

    # Initialise bootstrap logging before loading the config, so even an early failure is written to disk
    try:
        _setup_bootstrap_logging(debug=args.debug)
    except Exception as exc:
        logging.basicConfig(
            level=logging.DEBUG if getattr(args, "debug", False) else logging.INFO,
            format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            stream=sys.stderr,
        )
        logger.warning("Bootstrap logging initialization failed, falling back to stderr: %s", exc)

    # Load the configuration (after bootstrap logging, so exceptions are logged)
    try:
        config = get_config()
    except Exception as exc:
        logger.exception("Failed to load configuration: %s", exc)
        return 1

    # Configure logging (to the console and to files)
    try:
        _setup_runtime_logging(config.log_dir, debug=args.debug)
    except Exception as exc:
        logger.exception("Failed to switch to the configured log directory: %s", exc)
        return 1

    logger.info("=" * 60)
    logger.info("AI stock analysis system starting")
    logger.info(f"Run time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    logger.info("=" * 60)

    # Validate the configuration
    warnings = config.validate()
    for warning in warnings:
        logger.warning(warning)

    if getattr(args, "check_notify", False):
        from src.services.notification_diagnostics import (
            format_notification_diagnostics,
            run_notification_diagnostics,
        )

        result = run_notification_diagnostics(config)
        print(format_notification_diagnostics(result))
        return 0 if result.ok else 1

    # Parse the stock list (uppercased for consistency, Issue #355)
    # Story 1.5: the one-off --stocks entry builds a structured AnalysisTarget list via
    # parse_analysis_target, so index targets (the sh/sz/csi prefixes and the .CSI alias) keep their
    # identity at the entry point; unsupported targets (an unregistered .CSI, say) are rejected there and never reach a provider.
    # Modes that do not consume the stock list (backtest, broad-market review, serve-only, portfolio, scheduled)
    # skip classification and index refresh entirely (_skips_stock_entry), so an unrelated bad token cannot block them.
    _skip_stock_entry = _skips_stock_entry(args, config)
    if args.stocks and getattr(args, "portfolio", None):
        logger.info("--portfolio was also given; the portfolio overrides --stocks during analysis")
    stock_codes = None
    analysis_targets = None
    if args.stocks and not _skip_stock_entry:
        # Best-effort refresh of the stock index registry before parsing --stocks, so the first run already sees
        # the refreshed aliases and identities; a failure, timeout or disabled refresh never blocks the analysis. Only
        # the --stocks entry needs this; other modes are covered by the existing refresh inside run_full_analysis.
        _refresh_stock_index_cache_for_analysis(config)
        tokens = [c for c in split_stock_list(args.stocks) if (c or "").strip()]
        resolved = _classify_stock_list_tokens(tokens, entry_label="--stocks")
        if resolved is None:
            return 1
        stock_codes, analysis_targets = resolved
        logger.info(f"Using the stock list from the command line: {stock_codes}")
    elif (
        os.getenv("GITHUB_ACTIONS") == "true"
        and not _skip_stock_entry
    ):
    # The daily workflow (GITHUB_ACTIONS=true) runs `python main.py` without arguments (full or
    # stocks-only mode): STOCK_LIST tokens are classified into structured targets equivalent to a one-off
    # --stocks, so explicit index tokens take the index path and stock tokens keep the existing one.
    # Modes that do not consume the stock list are skipped wholesale by _skips_stock_entry (no refresh, no classification),
    # and the local default path does not build targets at this entry point.
        raw_value = config.stock_list or []
        raw_tokens = (
            split_stock_list(raw_value)
            if isinstance(raw_value, str)
            else [str(c).strip() for c in raw_value if str(c or "").strip()]
        )
        raw_tokens = [c for c in raw_tokens if (c or "").strip()]
        if raw_tokens:
            _refresh_stock_index_cache_for_analysis(config)
            resolved = _classify_stock_list_tokens(
                raw_tokens, entry_label="GitHub Actions STOCK_LIST"
            )
            if resolved is None:
                return 1
            stock_codes, analysis_targets = resolved
            logger.info(f"GitHub Actions default STOCK_LIST: {stock_codes}")

    # === Handle --webui / --webui-only, mapping them onto --serve / --serve-only ===
    if args.webui:
        args.serve = True
    if args.webui_only:
        args.serve_only = True

    # Backward compatibility with the legacy WEBUI_ENABLED environment variable
    if config.webui_enabled and not (args.serve or args.serve_only):
        args.serve = True

    # === Start the web service (when enabled) ===
    start_serve = (args.serve or args.serve_only) and os.getenv("GITHUB_ACTIONS") != "true"

    if start_serve:
        args.host, args.port = _resolve_web_service_bind(args, config)
        _warn_if_public_webui_without_auth(args.host)

    if start_serve:
        from src.services.runtime_scheduler import (
            CLI_SCHEDULER_OWNER_ENV,
            RUNTIME_SCHEDULER_ARGS_ENV,
            RUNTIME_SCHEDULER_FORCE_ENABLED_ENV,
            RUNTIME_SCHEDULER_RUN_IMMEDIATELY_ENV,
            RUNTIME_SCHEDULER_SUPPRESS_START_ENV,
        )

        # The API runtime scheduler owns schedules once the Web/API service starts.
        # This keeps Web settings, status, and run-now actions attached to the real
        # scheduler instead of a separate CLI loop.
        os.environ.pop(CLI_SCHEDULER_OWNER_ENV, None)
        os.environ.pop(RUNTIME_SCHEDULER_SUPPRESS_START_ENV, None)
        runtime_schedule_requested = args.schedule or config.schedule_enabled
        if args.schedule:
            os.environ[RUNTIME_SCHEDULER_FORCE_ENABLED_ENV] = "true"
        else:
            os.environ.pop(RUNTIME_SCHEDULER_FORCE_ENABLED_ENV, None)
        if runtime_schedule_requested:
            # ``--serve-only`` must restore persisted schedules, but it must not
            # turn service/Desktop startup into an immediate analysis run.
            runtime_run_immediately = (
                False if args.serve_only else config.schedule_run_immediately
            )
            if getattr(args, 'no_run_immediately', False):
                runtime_run_immediately = False
            os.environ[RUNTIME_SCHEDULER_RUN_IMMEDIATELY_ENV] = (
                "true" if runtime_run_immediately else "false"
            )
        else:
            os.environ.pop(RUNTIME_SCHEDULER_RUN_IMMEDIATELY_ENV, None)
        runtime_scheduler_args = {
            "no_notify": bool(getattr(args, "no_notify", False)),
            "no_market_review": bool(getattr(args, "no_market_review", False)),
            "dry_run": bool(getattr(args, "dry_run", False)),
            "force_run": bool(getattr(args, "force_run", False)),
            "single_notify": bool(getattr(args, "single_notify", False)),
            "no_context_snapshot": bool(getattr(args, "no_context_snapshot", False)),
            "workers": getattr(args, "workers", None),
        }
        if getattr(args, "portfolio", None):
            runtime_scheduler_args["portfolio"] = args.portfolio
        os.environ[RUNTIME_SCHEDULER_ARGS_ENV] = json.dumps(runtime_scheduler_args)
        if not prepare_webui_frontend_assets():
            logger.warning("Frontend static assets are not ready; starting FastAPI anyway (the web pages may be unavailable)")
        try:
            start_api_server(host=args.host, port=args.port, config=config)
        except Exception as e:
            logger.error(f"Failed to start the FastAPI service: {e}")
            if args.serve_only:
                return 1
            start_serve = False

    # === Serve-only mode: no analysis is run automatically ===
    if args.serve_only:
        logger.info("Mode: web service only")
        logger.info(f"Web service running: http://{args.host}:{args.port}")
        logger.info("Trigger analysis via /api/v1/analysis/analyze")
        logger.info(f"API docs: http://{args.host}:{args.port}/docs")
        logger.info("Press Ctrl+C to exit...")
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            logger.info("\nInterrupted by user, exiting")
        return 0

    try:
        # Mode 0: backtest
        if getattr(args, 'backtest', False):
            logger.info("Mode: backtest")
            from src.services.backtest_service import BacktestService

            service = BacktestService()
            stats = service.run_backtest(
                code=getattr(args, 'backtest_code', None),
                force=getattr(args, 'backtest_force', False),
                eval_window_days=getattr(args, 'backtest_days', None),
            )
            logger.info(
                f"Backtest finished: processed={stats.get('processed')} saved={stats.get('saved')} "
                f"completed={stats.get('completed')} insufficient={stats.get('insufficient')} errors={stats.get('errors')}"
            )
            return 0

        # Mode 1: broad-market review only
        if args.market_review:
            from src.core.market_review import run_market_review
            from src.core.market_review_runtime import build_market_review_runtime

            # Issue #373: Trading day check for market-review-only mode.
            # Do NOT use _compute_trading_day_filter here: that helper checks
            # config.market_review_enabled, which would wrongly block an
            # explicit --market-review invocation when the flag is disabled.
            effective_region = None
            if not getattr(args, 'force_run', False) and getattr(config, 'trading_day_check_enabled', True):
                from src.core.trading_calendar import get_open_markets_today, compute_effective_region as _compute_region
                open_markets = get_open_markets_today()
                effective_region = _compute_region(
                    getattr(config, 'market_review_region', 'cn') or 'cn', open_markets
                )
                if effective_region == '':
                    logger.info("All markets for today's market review are closed; skipping. Use --force-run to run anyway.")
                    return 0

            logger.info("Mode: market review only")
            notifier, analyzer, search_service = build_market_review_runtime(config)

            market_review_result = _run_market_review_with_shared_lock(
                config,
                run_market_review,
                notifier=notifier,
                analyzer=analyzer,
                search_service=search_service,
                send_notification=not args.no_notify,
                override_region=effective_region,
                trigger_source="cli",
            )
            return 0 if market_review_result else 1

        # Mode 2: scheduled-job mode
        if args.schedule or config.schedule_enabled:
            if start_serve:
                # Mode 2 plus the web service: this path comes from combining --schedule/--webui/--serve with
                # config.schedule_enabled (both already guarded), and the API runtime scheduler takes over;
                # --serve-only already returned from the serve_only branch above.
                logger.info("Mode: Web/API runtime scheduler")
                logger.info(f"Web service running: http://{args.host}:{args.port}")
                logger.info("The Web/API runtime scheduler owns scheduled runs; saved settings apply to this process")
                logger.info("Press Ctrl+C to exit...")
                try:
                    while True:
                        time.sleep(1)
                except KeyboardInterrupt:
                    logger.info("\nInterrupted by user, exiting")
                return 0

            logger.info("Mode: scheduled")
            logger.info(f"Daily run time: {config.schedule_time}")

            # Determine whether to run immediately:
            # Command line arg --no-run-immediately overrides config if present.
            # Otherwise use config (defaults to True).
            should_run_immediately = config.schedule_run_immediately
            if getattr(args, 'no_run_immediately', False):
                should_run_immediately = False

            logger.info(f"Run immediately on start: {should_run_immediately}")

            from src.scheduler import run_with_schedule
            scheduled_stock_codes = _resolve_scheduled_stock_codes(args.stocks or None)
            schedule_time_provider = _build_schedule_time_provider(config.schedule_time)
            schedule_times_provider = _build_schedule_times_provider(config.schedule_time)

            def scheduled_task():
                runtime_config = _reload_runtime_config()
                result = run_full_analysis(runtime_config, args, scheduled_stock_codes)
                if result is False:
                    reason = _LAST_ANALYSIS_FAILURE_REASON or "unknown"
                    raise RuntimeError(
                        f"scheduled analysis reported failure: {reason}"
                    )

            background_tasks = []
            if getattr(config, 'agent_event_monitor_enabled', False):
                from src.services.alert_worker import AlertWorker

                interval_minutes = max(1, getattr(config, 'agent_event_monitor_interval_minutes', 5))
                alert_worker = AlertWorker(config_provider=_reload_runtime_config)

                def event_monitor_task():
                    stats = alert_worker.run_once()
                    triggered_count = stats.get("triggered", 0)
                    if triggered_count:
                        logger.info("[EventMonitor] %d alert(s) triggered this round", triggered_count)

                background_tasks.append({
                    "task": event_monitor_task,
                    "interval_seconds": interval_minutes * 60,
                    "run_immediately": True,
                    "name": "agent_event_monitor",
                })

            schedule_kwargs = {
                "task": scheduled_task,
                "schedule_time": config.schedule_time,
                "run_immediately": should_run_immediately,
                "background_tasks": background_tasks,
                "schedule_time_provider": schedule_time_provider,
            }
            if hasattr(config, "schedule_times"):
                schedule_kwargs["schedule_times"] = config.schedule_times
                schedule_kwargs["schedule_times_provider"] = schedule_times_provider
            run_with_schedule(**schedule_kwargs)
            return 0

        # Mode 3: a normal one-off run
        if config.run_immediately:
            try:
                analysis_ok = _run_analysis_with_runtime_scheduler_lock(
                    config, args, stock_codes, analysis_targets
                )
            except FutuPortfolioError as exc:
                if not start_serve:
                    raise
                logger.exception(
                    "Futu holdings import failed; the Web/API service keeps running: %s",
                    exc,
                )
            else:
                if analysis_ok is False:
                    if start_serve:
                        logger.error("Startup analysis failed; the Web/API service keeps running.")
                    elif _LAST_ANALYSIS_FAILURE_REASON in {
                        "no_report",
                        "empty_stock_list",
                        "report_save_failed",
                    }:
                        return 1
        else:
            logger.info("Configured not to run analysis immediately (RUN_IMMEDIATELY=false)")

        logger.info("\nProgram finished")

        # Keep the process alive when the service is enabled outside scheduled-job mode
        keep_running = start_serve and not (args.schedule or config.schedule_enabled)
        if keep_running:
            logger.info("API service running (press Ctrl+C to exit)...")
            try:
                while True:
                    time.sleep(1)
            except KeyboardInterrupt:
                pass

        return 0

    except KeyboardInterrupt:
        logger.info("\nInterrupted by user, exiting")
        return 130

    except Exception as e:
        logger.exception(f"Program failed: {e}")
        return 1


if __name__ == "__main__":
    multiprocessing.freeze_support()
    sys.exit(main())

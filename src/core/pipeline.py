# -*- coding: utf-8 -*-
"""
===================================
A-share watchlist intelligence system - core analysis pipeline
===================================

Responsibilities:
1. Manage the end-to-end analysis flow
2. Coordinate the data fetching, storage, search, analysis and notification modules
3. Implement concurrency control and exception handling
4. Provide the core stock analysis capabilities
"""

import logging
import inspect
import threading
import time
from pathlib import Path
import uuid
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace
from typing import List, Dict, Any, Optional, Tuple, Callable

import pandas as pd

from src.config import FUNDAMENTAL_STAGE_TIMEOUT_SECONDS_DEFAULT, get_config, Config
from src.storage import get_db
from data_provider import DataFetcherManager
from data_provider.base import is_bse_code, normalize_stock_code
from data_provider.realtime_types import ChipDistribution
from src.analyzer import (
    GeminiAnalyzer,
    AnalysisResult,
    fill_price_position_if_needed,
    normalize_chip_structure_availability,
    populate_decision_action_fields,
    stabilize_decision_with_structure,
)
from src.notification import NotificationService, NotificationChannel
from src.schemas.decision_action import normalize_decision_action
from src.report_language import (
    get_placeholder_text,
    get_unknown_text,
    infer_decision_type_from_advice,
    localize_confidence_level,
    localize_operation_advice,
    localize_trend_prediction,
    resolve_report_language,
)
from src.search_service import SearchService
from src.analysis_context_pack_prompt import format_analysis_context_pack_prompt_section
from src.analysis_context_pack_overview import render_analysis_context_pack_overview
from src.market_phase_summary import MARKET_PHASE_SUMMARY_KEY, render_market_phase_summary
from src.daily_market_context_guardrail import apply_daily_market_context_guardrail
from src.agent.final_explanation import (
    PipelineActionAdjustment,
    build_pipeline_final_explanation,
    capture_pipeline_action_adjustment,
)
from src.agent.news_evidence import (
    activate_news_evidence_scope,
    get_current_news_evidence,
    reset_news_evidence_scope,
)
from src.services.empty_news import news_evidence_present
from src.formatters import strip_hidden_markdown_metadata
from src.phase_decision_guardrail import apply_phase_decision_guardrails
from src.services.daily_market_context import (
    DailyMarketContext,
    DailyMarketContextService,
    format_daily_market_context_prompt_section,
)
from src.services.social_sentiment_service import SocialSentimentService
from src.services.intelligence_service import IntelligenceService
from src.services.market_hotspot_service import MarketHotspotService
from src.services.analysis_context_builder import (
    AnalysisContextBuilder,
    PipelineAnalysisArtifacts,
)
from src.services.market_structure_service import MarketStructureService
from src.services.run_diagnostics import (
    activate_run_diagnostic_context,
    current_diagnostic_snapshot,
    get_current_diagnostic_context,
    record_history_run,
    record_llm_run,
    record_llm_run_started,
    record_notification_run,
    reset_run_diagnostic_context,
    sanitize_diagnostic_text,
)
from src.services.decision_signal_extractor import (
    extract_and_persist_from_analysis_result,
    resolve_decision_signal_action_fields,
)
from src.services.stock_list_parser import AnalysisTarget, ParseStatus
from src.services.decision_signal_summary import summarize_decision_signal
from src.enums import ReportType
from src.stock_analyzer import StockTrendAnalyzer, TrendAnalysisResult
from src.core.trading_calendar import (
    build_market_phase_context,
    get_effective_trading_date,
    get_market_for_stock,
    get_market_now,
    is_market_open,
)
from data_provider.us_index_mapping import is_us_stock_code
from bot.models import BotMessage


logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Index capability matrix — the single authority for which analysis modules
# are skipped for index targets (Story 1.5). Skipping must happen before any
# composite service, snapshot persistence, or the traditional/Agent branch
# split, so the underlying provider calls are never reached.
# ---------------------------------------------------------------------------
INDEX_SKIP_MODULES = frozenset({
    "chip_distribution",
    "fundamental",
    "belong_boards",
    "capital_flow",
    "lhb",
    "corporate_events",
})


def _share_image_payload(result: Any) -> Optional[Dict[str, Any]]:
    """Return structured poster data when the result exposes the real contract."""

    to_dict = getattr(result, "to_dict", None)
    if not callable(to_dict):
        return None
    try:
        payload = to_dict()
    except Exception as exc:
        logger.debug("Failed to build structured share-image data, falling back to Markdown: %s", exc)
        return None
    return payload if isinstance(payload, dict) and payload else None


def _supports_explicit_keyword(callable_obj: Any, keyword: str) -> bool:
    """Avoid breaking custom notifier overrides that predate an optional kwarg."""

    try:
        return keyword in inspect.signature(callable_obj).parameters
    except (TypeError, ValueError):
        return False


# Defensive guard: when an instance is constructed bypassing __init__ (for example
# via __new__ in tests), double-checked initialization of _single_stock_notify_lock stays thread-safe.
_SINGLE_STOCK_NOTIFY_LOCK_INIT_GUARD = threading.Lock()
_DAILY_MARKET_CONTEXT_SERVICE_LOCK_INIT_GUARD = threading.Lock()


def _symbol_scope_lookup_values(code: str, market: str) -> List[str]:
    """Return accepted persisted-intelligence symbol spellings for lookup."""
    raw = str(code or "").strip()
    normalized = normalize_stock_code(raw) if raw else ""
    values: List[str] = []
    seen: set[str] = set()

    def add(value: str) -> None:
        text = str(value or "").strip()
        if text and text not in seen:
            seen.add(text)
            values.append(text)

    def add_case_variants(value: str) -> None:
        text = str(value or "").strip()
        if not text:
            return
        add(text)
        add(text.upper())
        add(text.lower())

    add_case_variants(normalized)
    add_case_variants(raw)

    normalized_upper = normalized.upper()
    if normalized_upper.startswith("HK") and normalized_upper[2:].isdigit():
        digits = normalized_upper[2:]
        trimmed_digits = digits.lstrip("0") or digits
        add_case_variants(normalized_upper)
        add_case_variants(digits)
        add_case_variants(trimmed_digits)
        add_case_variants(f"HK{trimmed_digits}")
        add_case_variants(f"{trimmed_digits}.HK")
        add_case_variants(f"{digits}.HK")
        return values

    if (market or "").strip().lower() != "cn":
        return values
    if not (normalized.isdigit() and len(normalized) == 6):
        return values

    raw_upper = raw.upper()
    exchange = ""
    if raw_upper.startswith(("SH", "SS")) or raw_upper.endswith((".SH", ".SS")):
        exchange = "SH"
    elif raw_upper.startswith("SZ") or raw_upper.endswith(".SZ"):
        exchange = "SZ"
    elif raw_upper.startswith("BJ") or raw_upper.endswith(".BJ"):
        exchange = "BJ"
    elif is_bse_code(normalized):
        exchange = "BJ"
    elif normalized.startswith(("5", "6", "9")):
        exchange = "SH"
    else:
        exchange = "SZ"

    add_case_variants(f"{exchange}{normalized}")
    add_case_variants(f"{exchange}.{normalized}")
    add_case_variants(f"{normalized}.{exchange}")
    if exchange == "SH":
        add_case_variants(f"SS.{normalized}")
        add_case_variants(f"{normalized}.SS")
    return values


class StockAnalysisPipeline:
    """
    Scheduler for the main stock analysis flow
    
    Responsibilities:
    1. Manage the end-to-end analysis flow
    2. Coordinate the data fetching, storage, search, analysis and notification modules
    3. Implement concurrency control and exception handling
    """
    
    def __init__(
        self,
        config: Optional[Config] = None,
        max_workers: Optional[int] = None,
        source_message: Optional[BotMessage] = None,
        query_id: Optional[str] = None,
        trace_id: Optional[str] = None,
        query_source: Optional[str] = None,
        save_context_snapshot: Optional[bool] = None,
        progress_callback: Optional[Callable[[int, str], None]] = None,
        analysis_skills: Optional[List[str]] = None,
        analysis_phase: str = "auto",
        portfolio_context: Optional[Dict[str, Any]] = None,
        daily_market_context_enabled: Optional[bool] = None,
        daily_market_context_allow_generate: bool = True,
    ):
        """
        Initialize the scheduler
        
        Args:
            config: the configuration object (optional; defaults to the global configuration)
            max_workers: maximum worker threads (optional; read from configuration by default)
        """
        self.config = config or get_config()
        self.max_workers = max_workers or self.config.max_workers
        self.source_message = source_message
        self.query_id = query_id
        self.trace_id = trace_id or query_id
        self.query_source = self._resolve_query_source(query_source)
        self.save_context_snapshot = (
            self.config.save_context_snapshot if save_context_snapshot is None else save_context_snapshot
        )
        self.progress_callback = progress_callback
        self.analysis_skills = list(analysis_skills) if analysis_skills is not None else None
        self.analysis_phase = analysis_phase or "auto"
        self.portfolio_context = dict(portfolio_context) if isinstance(portfolio_context, dict) else None
        self.daily_market_context_enabled = (
            bool(getattr(self.config, "daily_market_context_enabled", True))
            if daily_market_context_enabled is None
            else bool(daily_market_context_enabled)
        )
        self.daily_market_context_allow_generate = daily_market_context_allow_generate
        
        # Initialize the individual modules
        self.db = get_db()
        self.fetcher_manager = DataFetcherManager()
        # No longer create akshare_fetcher separately; use fetcher_manager for all enhanced data
        self.trend_analyzer = StockTrendAnalyzer()  # Technical analyzer
        self.analyzer = GeminiAnalyzer(config=self.config, skills=self.analysis_skills)
        self.notifier = NotificationService(source_message=source_message)
        self.market_structure_service = MarketStructureService(fetcher_manager=self.fetcher_manager)
        self.market_hotspot_service: Optional[MarketHotspotService] = None
        try:
            self.market_hotspot_service = MarketHotspotService(
                fetcher_manager=self.fetcher_manager,
            )
        except Exception as exc:
            logger.debug("market hotspot service init failed (fail-open): %s", exc)
        self._single_stock_notify_lock = threading.Lock()
        self._daily_market_context_service_lock = threading.Lock()
        self._concept_rankings_cache_lock = threading.Lock()
        self._concept_rankings_cache: Dict[str, Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]] = {}
        self._last_local_report_path: Optional[str] = None
        self._last_local_report_error: Optional[str] = None
        
        # Initialize the search service (optional; a failure here must not block the main analysis flow)
        try:
            self.search_service = SearchService(
                bocha_keys=self.config.bocha_api_keys,
                tavily_keys=self.config.tavily_api_keys,
                anspire_keys=self.config.anspire_api_keys,
                brave_keys=self.config.brave_api_keys,
                serpapi_keys=self.config.serpapi_keys,
                minimax_keys=self.config.minimax_api_keys,
                searxng_base_urls=self.config.searxng_base_urls,
                searxng_public_instances_enabled=self.config.searxng_public_instances_enabled,
                searxng_timeout_seconds=getattr(self.config, "searxng_timeout_seconds", None),
                news_max_age_days=self.config.news_max_age_days,
                news_strategy_profile=getattr(self.config, "news_strategy_profile", "short"),
            )
        except Exception as exc:
            logger.warning("Search service initialization failed, running without search: %s", exc, exc_info=True)
            self.search_service = None
        
        logger.info(f"Scheduler initialized, max concurrency: {self.max_workers}")
        logger.info("Technical analysis engine enabled (moving averages / trend / volume-price indicators)")
        # Log the real-time quote and chip-distribution configuration state
        if self.config.enable_realtime_quote:
            logger.info(f"Real-time quotes enabled (priority: {self.config.realtime_source_priority})")
        else:
            logger.info("Real-time quotes disabled; historical close prices will be used")
        if self.config.enable_chip_distribution:
            logger.info("Chip distribution analysis enabled")
        else:
            logger.info("Chip distribution analysis disabled")
        if self.search_service is None:
            logger.warning("Search service not enabled (initialization failed or dependency missing)")
        elif self.search_service.is_available:
            logger.info("Search service enabled")
        else:
            logger.warning("Search service not enabled (no search provider configured)")

        # Initialize the social sentiment service (US stocks only, optional)
        try:
            self.social_sentiment_service = SocialSentimentService(
                api_key=self.config.social_sentiment_api_key,
                api_url=self.config.social_sentiment_api_url,
            )
            if self.social_sentiment_service.is_available:
                logger.info("Social sentiment service enabled (Reddit/X/Polymarket, US stocks only)")
        except Exception as exc:
            logger.warning(
                "Social sentiment service initialization failed, skipping sentiment analysis: %s",
                exc,
                exc_info=True,
            )
            self.social_sentiment_service = None

    def _emit_progress(self, progress: int, message: str) -> None:
        """Best-effort bridge from pipeline stages to task SSE progress."""
        callback = getattr(self, "progress_callback", None)
        if callback is None:
            return
        try:
            callback(progress, message)
        except Exception as exc:
            query_id = getattr(self, "query_id", None)
            logger.warning(
                "[pipeline] progress callback failed: %s (progress=%s, message=%r, query_id=%s)",
                exc,
                progress,
                message,
                query_id,
                extra={
                    "progress": progress,
                    "progress_message": message,
                    "query_id": query_id,
                },
            )

    def fetch_and_save_stock_data(
        self, 
        code: str,
        force_refresh: bool = False,
        current_time: Optional[datetime] = None,
        analysis_target: Optional[AnalysisTarget] = None,
    ) -> Tuple[bool, Optional[str]]:
        """
        Fetch and persist data for a single stock
        
        Resume logic:
        1. Check whether the database already holds data for the latest reusable trading day
        2. If it does and no forced refresh is requested, skip the network call
        3. Otherwise fetch from the data source and persist
        
        Args:
            code: the stock code
            force_refresh: whether to force a refresh (ignoring the local cache)
            current_time: the reference time frozen for this run, so the resume target trading day is judged consistently
            analysis_target: the structured analysis target (an index target drives market=cn and date semantics)
            
        Returns:
            Tuple[success flag, error message]
        """
        stock_name = code
        try:
            # Resolve the stock name first
            stock_name = self.fetcher_manager.get_stock_name(code, allow_realtime=False)

            target_date = self._resolve_resume_target_date(
                code, current_time=current_time, analysis_target=analysis_target
            )

            # Resume check: skip when data for the latest reusable trading day already exists
            if not force_refresh and self.db.has_today_data(code, target_date):
                logger.info(
                    f"{stock_name}({code}) {target_date} data already exists, skipping fetch (resume)"
                )
                return True, None

            # Fetch data from the data source
            logger.info(f"{stock_name}({code}) fetching data from data sources...")
            df, source_name = self.fetcher_manager.get_daily_data(code, days=30)

            if df is None or df.empty:
                return False, "Fetched data is empty"

            # Persist to the database
            saved_count = self.db.save_daily_data(df, code, source_name)
            logger.info(f"{stock_name}({code}) data saved (source: {source_name}, {saved_count} new rows)")

            return True, None

        except Exception as e:
            error_msg = f"Failed to fetch/save data: {str(e)}"
            logger.error(f"{stock_name}({code}) {error_msg}")
            return False, error_msg
    
    def analyze_stock(
        self,
        code: str,
        report_type: ReportType,
        query_id: str,
        current_time: Optional[datetime] = None,
        analysis_target: Optional[AnalysisTarget] = None,
    ) -> Optional[AnalysisResult]:
        """
        Analyze a single stock (enhanced: volume ratio, turnover rate, chip distribution, multi-dimensional intelligence)
        
        Flow:
        1. Fetch the real-time quote (volume ratio, turnover rate) via DataFetcherManager with automatic failover
        2. Fetch the chip distribution via DataFetcherManager with circuit-breaker protection
        3. Run the trend analysis (based on the trading philosophy)
        4. Multi-dimensional intelligence search (latest news + risk screening + earnings expectations)
        5. Load the analysis context from the database
        6. Call the AI for the combined analysis
        
        Args:
            query_id: the correlation id for this query chain
            code: the stock code
            report_type: the report type
            current_time: the reference time frozen for this run, used to keep the market phase context consistent
            analysis_target: the structured analysis target (an index target drives market=cn and the capability matrix)
            
        Returns:
            An AnalysisResult, or None when the analysis fails
        """
        stock_name = code
        try:
            portfolio_context = getattr(self, "portfolio_context", None)
            if not isinstance(portfolio_context, dict):
                portfolio_context = None
            is_index = (
                analysis_target is not None
                and analysis_target.asset_type == ParseStatus.INDEX
            )
            market = (
                "cn"
                if is_index
                else get_market_for_stock(normalize_stock_code(code))
            )
            market_phase_context = build_market_phase_context(
                market=market,
                current_time=current_time,
                trigger_source=self.query_source,
                analysis_phase=getattr(self, "analysis_phase", "auto"),
            )
            market_phase_context_dict = market_phase_context.to_dict()
            market_phase_summary = render_market_phase_summary(market_phase_context_dict)
            report_language = resolve_report_language(getattr(self.config, "report_language", None))
            daily_market_target_date = self._coerce_daily_market_context_date(
                getattr(market_phase_context, "effective_daily_bar_date", None)
                or market_phase_context_dict.get("effective_daily_bar_date")
            )
            if daily_market_target_date is None:
                daily_market_target_date = get_effective_trading_date(
                    market,
                    current_time=current_time,
                )
            daily_market_context = self._load_daily_market_context(
                market,
                target_date=daily_market_target_date,
            )

            self._emit_progress(18, f"{code}: fetching quotes and chip data")
            # Resolve the stock name (take the lightweight name path first; override later if realtime_quote carries a name)
            # An index target uses the registry display name (matched_index.display_name), so that
            # a raw alias, canonical code or six-digit machine code never leaks into the search query (Story 1.5 V7).
            if is_index and analysis_target is not None:
                index_name = getattr(
                    getattr(analysis_target, "matched_index", None),
                    "display_name",
                    None,
                )
                stock_name = index_name or analysis_target.display_code or code
            else:
                stock_name = self.fetcher_manager.get_stock_name(code, allow_realtime=False)

            # Step 1: fetch the real-time quote (volume ratio, turnover rate, and so on) through the unified entry point with automatic failover
            realtime_quote = None
            try:
                if self.config.enable_realtime_quote:
                    realtime_quote = self.fetcher_manager.get_realtime_quote(code, log_final_failure=False)
                    if realtime_quote:
                        # Stocks use the real-time quote name; indices keep the registry name as the authoritative display name.
                        if realtime_quote.name and not is_index:
                            stock_name = realtime_quote.name
                        # Tolerate field differences across data sources (some may not provide volume_ratio)
                        volume_ratio = getattr(realtime_quote, 'volume_ratio', None)
                        turnover_rate = getattr(realtime_quote, 'turnover_rate', None)
                        logger.info(f"{stock_name}({code}) real-time quote: price={realtime_quote.price}, "
                                  f"volume_ratio={volume_ratio}, turnover_rate={turnover_rate}% "
                                  f"(source: {realtime_quote.source.value if hasattr(realtime_quote, 'source') else 'unknown'})")
                    else:
                        logger.warning(f"{stock_name}({code}) all real-time quote sources unavailable; continuing with historical close prices")
                else:
                    logger.info(f"{stock_name}({code}) real-time quotes disabled; continuing with historical close prices")
            except Exception as e:
                logger.warning(f"{stock_name}({code}) real-time quote pipeline error; continuing with historical close prices: {e}")

            # If there is still no name, fall back to the code as the name
            if not stock_name:
                stock_name = f'股票{code}'

            # Step 2: fetch the chip distribution through the unified entry point, with circuit-breaker protection
            # Index targets skip the chip distribution (INDEX_SKIP_MODULES capability matrix)
            chip_data = None
            if is_index and "chip_distribution" in INDEX_SKIP_MODULES:
                logger.debug(f"{stock_name}({code}) index target, skipping chip distribution")
            else:
                try:
                    chip_data = self.fetcher_manager.get_chip_distribution(code)
                    if chip_data:
                        logger.info(f"{stock_name}({code}) chip distribution: profit_ratio={chip_data.profit_ratio:.1%}, "
                                  f"concentration_90={chip_data.concentration_90:.2%}")
                    else:
                        logger.debug(f"{stock_name}({code}) chip distribution unavailable or disabled")
                except Exception as e:
                    logger.warning(f"{stock_name}({code}) failed to fetch chip distribution: {e}")

            # If agent mode is explicitly enabled, or specific agent skills are configured, use the Agent analysis pipeline.
            # NOTE: use config.agent_mode (explicit opt-in) instead of
            # config.is_agent_available() so that users who only configured an
            # API Key for the traditional analysis path are not silently
            # switched to Agent mode (which is slower and more expensive).
            use_agent = getattr(self.config, 'agent_mode', False)
            if not use_agent:
                if self.analysis_skills:
                    use_agent = True
                    logger.info(f"{stock_name}({code}) Auto-enabled agent mode due to request skills: {self.analysis_skills}")
            if not use_agent:
                # Auto-enable agent mode when specific skills are configured (e.g., scheduled task with strategy)
                configured_skills = getattr(self.config, 'agent_skills', [])
                if configured_skills and configured_skills != ['all']:
                    use_agent = True
                    logger.info(f"{stock_name}({code}) Auto-enabled agent mode due to configured skills: {configured_skills}")

            self._emit_progress(32, f"{stock_name}: aggregating fundamentals and trend data")

            # Step 2.5: fundamentals capability aggregation (unified entry point, degrades on error)
            # - Returns partial/failed on error, leaving the existing technical and news paths unaffected
            # - Still returns a not_supported structure when the feature is switched off
            # - Index targets skip fundamentals, sectors, fund flow, top-list disclosure and company events (INDEX_SKIP_MODULES)
            fundamental_context = None
            fundamental_modules = {
                "fundamental",
                "belong_boards",
                "capital_flow",
                "lhb",
                "corporate_events",
            }
            if is_index and INDEX_SKIP_MODULES.intersection(fundamental_modules):
                logger.debug(f"{stock_name}({code}) index target, skipping fundamentals aggregation")
                fundamental_context = self.fetcher_manager.build_not_supported_fundamental_context(
                    code,
                    "index target: fundamental modules skipped",
                )
            else:
                try:
                    fundamental_context = self.fetcher_manager.get_fundamental_context(
                        code,
                        budget_seconds=getattr(
                            self.config,
                            'fundamental_stage_timeout_seconds',
                            FUNDAMENTAL_STAGE_TIMEOUT_SECONDS_DEFAULT,
                        ),
                    )
                except Exception as e:
                    logger.warning(f"{stock_name}({code}) fundamentals aggregation failed: {e}")
                    fundamental_context = self.fetcher_manager.build_failed_fundamental_context(code, str(e))

            if is_index and "belong_boards" in INDEX_SKIP_MODULES:
                logger.debug(f"{stock_name}({code}) index target, skipping sector membership")
                if isinstance(fundamental_context, dict):
                    fundamental_context = dict(fundamental_context)
                    fundamental_context["belong_boards"] = []
            else:
                fundamental_context = self._attach_belong_boards_to_fundamental_context(
                    code,
                    fundamental_context,
                )
            market_structure_context = self._build_market_structure_context(
                code=code,
                stock_name=stock_name,
                market=market,
                fundamental_context=fundamental_context,
                trade_date=daily_market_target_date,
                market_phase_summary=market_phase_summary,
            )

            # P0: write-only snapshot, fail-open, no read dependency on this table.
            if not is_index:
                try:
                    self.db.save_fundamental_snapshot(
                        query_id=query_id,
                        code=code,
                        payload=fundamental_context,
                        source_chain=fundamental_context.get("source_chain", []),
                        coverage=fundamental_context.get("coverage", {}),
                    )
                except Exception as e:
                    logger.debug(f"{stock_name}({code}) failed to write fundamentals snapshot: {e}")

            # Step 3: trend analysis (based on the trading philosophy) - run before the Agent branch so both paths share it
            trend_result: Optional[TrendAnalysisResult] = None
            try:
                from src.services.history_loader import get_frozen_target_date
                _mkt = get_market_for_stock(normalize_stock_code(code))
                frozen = get_frozen_target_date()
                end_date = frozen if frozen else get_market_now(_mkt).date()
                start_date = end_date - timedelta(days=89)  # ~60 trading days for MA60
                historical_bars = self.db.get_data_range(code, start_date, end_date)
                if historical_bars:
                    df = pd.DataFrame([bar.to_dict() for bar in historical_bars])
                    # Issue #234: Augment with realtime for intraday MA calculation
                    if self.config.enable_realtime_quote and realtime_quote:
                        df = self._augment_historical_with_realtime(
                            df, realtime_quote, code, market=market
                        )
                    trend_result = self.trend_analyzer.analyze(df, code)
                    logger.info(f"{stock_name}({code}) trend analysis: {trend_result.trend_status.value}, "
                              f"buy_signal={trend_result.buy_signal.value}, score={trend_result.signal_score}")
            except Exception as e:
                logger.warning(f"{stock_name}({code}) trend analysis failed: {e}", exc_info=True)

            if use_agent:
                logger.info(f"{stock_name}({code}) analyzing in Agent mode")
                self._emit_progress(58, f"{stock_name}: switching to the Agent analysis pipeline")
                return self._analyze_with_agent(
                    code,
                    report_type,
                    query_id,
                    stock_name,
                    realtime_quote,
                    chip_data,
                    fundamental_context,
                    trend_result,
                    market_phase_context=market_phase_context_dict,
                    market_phase_summary=market_phase_summary,
                    daily_market_context=daily_market_context,
                    portfolio_context=portfolio_context,
                    market_structure_context=market_structure_context,
                    analysis_target=analysis_target,
                )

            # Step 4: multi-dimensional intelligence search (latest news + risk screening + earnings expectations)
            news_context = None
            persisted_intelligence_context = self._load_persisted_intelligence_context(
                code=code,
                stock_name=stock_name,
                market=market or "cn",
            )
            news_result_count: Optional[int] = None
            self._emit_progress(46, f"{stock_name}: searching news and sentiment")
            if self.search_service is not None and self.search_service.is_available:
                logger.info(f"{stock_name}({code}) starting multi-dimensional intelligence search...")

                # Search issued: from here on, no results means "ran, zero hits",
                # not "no search performed". Staying None would silence the case
                # that most needs a warning: every search source failing.
                news_result_count = 0

                # Multi-dimensional search (at most 5 searches)
                # Index targets: query subject uses only the registry name, so the
                # canonical and six-digit codes stay out of it (Story 1.5 V7).
                intel_results = self.search_service.search_comprehensive_intel(
                    stock_code=("" if is_index else code),
                    stock_name=stock_name,
                    max_searches=5
                )

                # Format the intelligence report
                if intel_results:
                    news_context = self.search_service.format_intel_report(intel_results, stock_name)
                    total_results = sum(
                        len(r.results) for r in intel_results.values() if r.success
                    )
                    news_result_count = total_results
                    logger.info(f"{stock_name}({code}) intelligence search completed: {total_results} result(s)")
                    logger.debug(f"{stock_name}({code}) intelligence search results:\n{news_context}")

                    # Persist the news intelligence to the database (for later review and queries)
                    try:
                        query_context = self._build_query_context(query_id=query_id)
                        for dim_name, response in intel_results.items():
                            if response and response.success and response.results:
                                self.db.save_news_intel(
                                    code=code,
                                    name=stock_name,
                                    dimension=dim_name,
                                    query=response.query,
                                    response=response,
                                    query_context=query_context
                                )
                    except Exception as e:
                        logger.warning(f"{stock_name}({code}) failed to save news intelligence: {e}")
            else:
                logger.info(f"{stock_name}({code}) search service unavailable, skipping intelligence search")

            # Step 4.5: Social sentiment intelligence (US stocks only)
            social_evidence_context: Optional[str] = None
            if self.social_sentiment_service is not None and self.social_sentiment_service.is_available and is_us_stock_code(code):
                try:
                    social_context = self.social_sentiment_service.get_social_context(code)
                    if social_context:
                        logger.info(f"{stock_name}({code}) Social sentiment data retrieved")
                        social_evidence_context = social_context
                        if news_context:
                            news_context = news_context + "\n\n" + social_context
                        else:
                            news_context = social_context
                except Exception as e:
                    logger.warning(f"{stock_name}({code}) Social sentiment fetch failed: {e}")

            if persisted_intelligence_context:
                news_context = (
                    f"{news_context}\n\n{persisted_intelligence_context}"
                    if news_context
                    else persisted_intelligence_context
                )

            # Step 5: load the analysis context (technical data)
            self._emit_progress(58, f"{stock_name}: assembling analysis context")
            context = self._get_analysis_context_with_market_fallback(
                code, analysis_target=analysis_target
            )

            if context is None:
                logger.warning(f"{stock_name}({code}) historical price data unavailable; analyzing from news and real-time quotes only")
                _mkt_date = get_market_now(
                    get_market_for_stock(normalize_stock_code(code))
                ).date()
                context = {
                    'code': code,
                    'stock_name': stock_name,
                    'date': _mkt_date.isoformat(),
                    'data_missing': True,
                    'today': {},
                    'yesterday': {}
                }
            
            # Step 6: enrich the context (add the real-time quote, chip distribution, trend result and stock name)
            enhanced_context = self._enhance_context(
                context, 
                realtime_quote, 
                chip_data,
                trend_result,
                stock_name,  # Pass the stock name
                fundamental_context,
                market_phase_context=market_phase_context_dict,
                portfolio_context=portfolio_context,
            )
            enhanced_context["market_phase_context"] = market_phase_context_dict
            self._attach_daily_market_context(
                enhanced_context,
                daily_market_context,
                report_language=report_language,
            )
            if portfolio_context is not None:
                enhanced_context["portfolio_context"] = dict(portfolio_context)
            if isinstance(market_structure_context, dict):
                enhanced_context["market_structure_context"] = market_structure_context
            
            # Step 7: call the AI analysis (passing the enriched context and the news)
            (
                analysis_context_pack_summary,
                analysis_context_pack_overview,
            ) = self._build_analysis_context_pack_outputs(
                self._build_legacy_analysis_artifacts(
                    code=code,
                    stock_name=stock_name,
                    market=market,
                    phase=market_phase_context_dict,
                    context=context,
                    enhanced_context=enhanced_context,
                    realtime_quote=realtime_quote,
                    trend_result=trend_result,
                    chip_data=chip_data,
                    fundamental_context=fundamental_context,
                    news_context=news_context,
                    news_result_count=news_result_count,
                    query_id=query_id,
                    portfolio_context=portfolio_context,
                ),
                report_language=report_language,
                code=code,
                query_id=query_id,
            )
            llm_progress_state = {"last_progress": 64}

            def _on_llm_stream(chars_received: int) -> None:
                dynamic_progress = min(92, 64 + min(chars_received // 80, 28))
                if dynamic_progress <= llm_progress_state["last_progress"]:
                    return
                llm_progress_state["last_progress"] = dynamic_progress
                self._emit_progress(
                    dynamic_progress,
                    f"{stock_name}: LLM is generating the analysis ({chars_received} characters received)",
                )

            self._emit_progress(64, f"{stock_name}: requesting the LLM report")
            llm_started_at = time.monotonic()
            try:
                record_llm_run_started(
                    model=getattr(self.config, "litellm_model", None),
                    call_type="analysis",
                )
                result = self.analyzer.analyze(
                    enhanced_context,
                    news_context=news_context,
                    progress_callback=self._emit_progress,
                    stream_progress_callback=_on_llm_stream,
                    analysis_context_pack_summary=analysis_context_pack_summary,
                )
                llm_duration_ms = int((time.monotonic() - llm_started_at) * 1000)
                if result is not None:
                    # Let the presentation layer distinguish "no channel configured", "search returned zero hits" and "normal hits".
                    # This value previously only reached the diagnostic snapshot and was invisible to the report layer.
                    result.news_result_count = news_result_count
                    # Register each of the three sources individually rather than inspecting the assembled news_context:
                    # format_intel_report() still emits placeholder text on zero hits, so the assembled block is never empty,
                    # and judging by it would mistake "searched but retrieved nothing" for having evidence.
                    result.news_evidence_present = news_evidence_present(
                        news_result_count,
                        social_evidence_context,
                        persisted_intelligence_context,
                    )
                record_llm_run(
                    success=bool(result and getattr(result, "success", True)),
                    model=getattr(result, "model_used", None) if result else None,
                    call_type="analysis",
                    duration_ms=llm_duration_ms,
                    error_type=(
                        None
                        if result and getattr(result, "success", True)
                        else "AnalysisResultError"
                    ),
                    error_message=(
                        getattr(result, "error_message", None)
                        if result and not getattr(result, "success", True)
                        else ("LLM returned empty result" if result is None else None)
                    ),
                )
            except Exception as exc:
                record_llm_run(
                    success=False,
                    model=getattr(self.config, "litellm_model", None),
                    call_type="analysis",
                    duration_ms=int((time.monotonic() - llm_started_at) * 1000),
                    error_type=type(exc).__name__,
                    error_message=exc,
                )
                raise

            # Step 7.5: populate the result with the price information captured at analysis time
            if result:
                self._emit_progress(94, f"{stock_name}: validating and organizing the analysis")
                result.query_id = query_id
                realtime_data = enhanced_context.get('realtime', {})
                result.current_price = realtime_data.get('price')
                result.change_pct = realtime_data.get('change_pct')

            # Step 7.6: chip_structure fallback (Issue #589) and unavailable collapse
            if result:
                normalize_chip_structure_availability(result, chip_data)

            # Step 7.7: price_position fallback
            if result:
                fill_price_position_if_needed(result, trend_result, realtime_quote)
                action_source_advice = getattr(result, "operation_advice", None)
                stabilize_decision_with_structure(result, trend_result, fundamental_context)
                adjustments = apply_phase_decision_guardrails(
                    result,
                    market_phase_summary=market_phase_summary,
                    analysis_context_pack_overview=analysis_context_pack_overview,
                    report_language=getattr(result, "report_language", None)
                    or resolve_report_language(getattr(self.config, "report_language", None)),
                )
                if adjustments:
                    logger.info("[phase_decision_guardrail] Applied adjustments for %s: %s", code, adjustments)
                market_context_adjustments = apply_daily_market_context_guardrail(
                    result,
                    daily_market_context=enhanced_context.get("daily_market_context"),
                    report_language=getattr(result, "report_language", None)
                    or resolve_report_language(getattr(self.config, "report_language", None)),
                )
                if market_context_adjustments:
                    logger.info(
                        "[daily_market_context_guardrail] Applied adjustments for %s: %s",
                        code,
                        market_context_adjustments,
                    )
                if isinstance(fundamental_context, dict):
                    result.fundamental_context = fundamental_context
                if isinstance(market_structure_context, dict):
                    result.market_structure_context = market_structure_context
                result.market_phase_summary = market_phase_summary
                result.analysis_context_pack_overview = analysis_context_pack_overview
                self._refresh_decision_action_for_final_result(
                    result,
                    report_type=report_type.value,
                    previous_operation_advice=action_source_advice,
                )

            if result:
                self._append_daily_data_source(result, context, analysis_target)

            # Step 8: persist the analysis history record
            if result and result.success:
                try:
                    self._emit_progress(97, f"{stock_name}: saving the analysis report")
                    context_snapshot = self._build_context_snapshot(
                        enhanced_context=enhanced_context,
                        news_content=news_context,
                        news_result_count=news_result_count,
                        realtime_quote=realtime_quote,
                        chip_data=chip_data,
                        analysis_context_pack_overview=analysis_context_pack_overview,
                        market_phase_summary=market_phase_summary,
                    )
                    result.diagnostic_context_snapshot = context_snapshot
                    saved_history_id = self.db.save_analysis_history(
                        result=result,
                        query_id=query_id,
                        report_type=report_type.value,
                        news_content=news_context,
                        context_snapshot=context_snapshot,
                        save_snapshot=self.save_context_snapshot
                    )
                    valid_saved_history_id = (
                        isinstance(saved_history_id, int)
                        and not isinstance(saved_history_id, bool)
                        and saved_history_id > 0
                    )
                    record_history_run(
                        report_saved=bool(saved_history_id),
                        metadata_saved=bool(saved_history_id),
                        analysis_history_id=(
                            saved_history_id if valid_saved_history_id else None
                        ),
                    )
                    if valid_saved_history_id:
                        self._extract_decision_signal_after_history_save(
                            result=result,
                            query_id=query_id,
                            source_report_id=saved_history_id,
                            report_type=report_type.value,
                            context_snapshot=context_snapshot,
                            portfolio_context=portfolio_context,
                            analysis_target=analysis_target,
                        )
                except Exception as e:
                    record_history_run(
                        report_saved=False,
                        metadata_saved=False,
                        error_message=e,
                    )
                    logger.warning(f"{stock_name}({code}) failed to save analysis history: {e}")

            return result

        except Exception as e:
            logger.error(f"{stock_name}({code}) analysis failed: {e}")
            logger.exception(f"{stock_name}({code}) error details:")
            return None
    
    def _enhance_context(
        self,
        context: Dict[str, Any],
        realtime_quote,
        chip_data: Optional[ChipDistribution],
        trend_result: Optional[TrendAnalysisResult],
        stock_name: str = "",
        fundamental_context: Optional[Dict[str, Any]] = None,
        market_phase_context: Optional[Dict[str, Any]] = None,
        portfolio_context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Enrich the analysis context
        
        Adds the real-time quote, chip distribution, trend result and stock name to the context
        
        Args:
            context: the original context
            realtime_quote: the real-time quote data (UnifiedRealtimeQuote or None)
            chip_data: the chip distribution data
            trend_result: the trend analysis result
            stock_name: the stock name
            market_phase_context: the already-built market phase context, used to flag an intraday partial bar
            
        Returns:
            The enriched context
        """
        enhanced = context.copy()
        enhanced["report_language"] = resolve_report_language(getattr(self.config, "report_language", None))
        
        # Add the stock name
        if stock_name:
            enhanced['stock_name'] = stock_name
        elif realtime_quote and getattr(realtime_quote, 'name', None):
            enhanced['stock_name'] = realtime_quote.name
        if isinstance(portfolio_context, dict):
            enhanced["portfolio_context"] = dict(portfolio_context)

        # Pass the runtime search window through to the analyzer, so re-reading the global configuration cannot produce an inconsistent window
        enhanced['news_window_days'] = getattr(self.search_service, "news_window_days", 3)
        
        # Add the real-time quote (tolerating field differences across data sources)
        if realtime_quote:
            # Read fields safely with getattr; missing fields yield None or a default
            volume_ratio = getattr(realtime_quote, 'volume_ratio', None)
            quote_source = getattr(realtime_quote, 'source', None)
            quote_source_name = getattr(quote_source, 'value', quote_source)
            quote_source_name = str(quote_source_name) if quote_source_name is not None else None
            enhanced['realtime'] = {
                'name': getattr(realtime_quote, 'name', ''),
                'price': getattr(realtime_quote, 'price', None),
                'change_pct': getattr(realtime_quote, 'change_pct', None),
                'volume_ratio': volume_ratio,
                'volume_ratio_desc': self._describe_volume_ratio(volume_ratio) if volume_ratio else '无数据',
                'turnover_rate': getattr(realtime_quote, 'turnover_rate', None),
                'pe_ratio': getattr(realtime_quote, 'pe_ratio', None),
                'pb_ratio': getattr(realtime_quote, 'pb_ratio', None),
                'total_mv': getattr(realtime_quote, 'total_mv', None),
                'circ_mv': getattr(realtime_quote, 'circ_mv', None),
                'change_60d': getattr(realtime_quote, 'change_60d', None),
                'source': quote_source_name,
                'fetched_at': getattr(realtime_quote, 'fetched_at', None),
                'provider_timestamp': getattr(realtime_quote, 'provider_timestamp', None),
                'is_stale': getattr(realtime_quote, 'is_stale', None),
                'stale_seconds': getattr(realtime_quote, 'stale_seconds', None),
                'fallback_from': getattr(realtime_quote, 'fallback_from', None),
            }
            # Drop None values to keep the context smaller
            enhanced['realtime'] = {k: v for k, v in enhanced['realtime'].items() if v is not None}
        
        # Add the chip distribution
        if chip_data:
            current_price = getattr(realtime_quote, 'price', 0) if realtime_quote else 0
            enhanced['chip'] = {
                'profit_ratio': chip_data.profit_ratio,
                'avg_cost': chip_data.avg_cost,
                'concentration_90': chip_data.concentration_90,
                'concentration_70': chip_data.concentration_70,
                'chip_status': chip_data.get_chip_status(current_price or 0),
            }
        
        # Add the trend analysis result
        if trend_result:
            enhanced['trend_analysis'] = {
                'trend_status': trend_result.trend_status.value,
                'ma_alignment': trend_result.ma_alignment,
                'trend_strength': trend_result.trend_strength,
                'bias_ma5': trend_result.bias_ma5,
                'bias_ma10': trend_result.bias_ma10,
                'volume_status': trend_result.volume_status.value,
                'volume_trend': trend_result.volume_trend,
                'buy_signal': trend_result.buy_signal.value,
                'signal_score': trend_result.signal_score,
                'signal_reasons': trend_result.signal_reasons,
                'risk_factors': trend_result.risk_factors,
            }

        # Issue #234: intraday analysis overrides today with the real-time OHLC and trend MA.
        # Guard condition: trend_result.ma5 > 0 means the MA calculation succeeded with enough data.
        if realtime_quote and trend_result and trend_result.ma5 > 0:
            price = getattr(realtime_quote, 'price', None)
            if price is not None and price > 0:
                yesterday_close = None
                if enhanced.get('yesterday') and isinstance(enhanced['yesterday'], dict):
                    yesterday_close = enhanced['yesterday'].get('close')
                orig_today = enhanced.get('today') or {}
                market_today = get_market_now(
                    get_market_for_stock(normalize_stock_code(enhanced.get('code', '')))
                ).date().isoformat()
                source = getattr(realtime_quote, 'source', None)
                source_name = getattr(source, 'value', source)
                source_name = str(source_name) if source_name is not None else 'unknown'
                open_p = getattr(realtime_quote, 'open_price', None) or getattr(
                    realtime_quote, 'pre_close', None
                ) or yesterday_close or orig_today.get('open') or price
                high_p = getattr(realtime_quote, 'high', None) or price
                low_p = getattr(realtime_quote, 'low', None) or price
                vol = getattr(realtime_quote, 'volume', None)
                amt = getattr(realtime_quote, 'amount', None)
                pct = getattr(realtime_quote, 'change_pct', None)
                fetched_at = getattr(realtime_quote, 'fetched_at', None)
                provider_timestamp = getattr(realtime_quote, 'provider_timestamp', None)
                fallback_from = getattr(realtime_quote, 'fallback_from', None)
                realtime_today = {
                    'close': price,
                    'open': open_p,
                    'high': high_p,
                    'low': low_p,
                    'ma5': trend_result.ma5,
                    'ma10': trend_result.ma10,
                    'ma20': trend_result.ma20,
                    'date': market_today,
                    'data_source': f"realtime:{source_name}",
                    'realtime_source': source_name,
                    'is_estimated': True,
                }
                estimated_fields = [
                    'close', 'open', 'high', 'low', 'ma5', 'ma10', 'ma20',
                ]
                if vol is not None:
                    realtime_today['volume'] = vol
                    estimated_fields.append('volume')
                if amt is not None:
                    realtime_today['amount'] = amt
                    estimated_fields.append('amount')
                if pct is not None:
                    realtime_today['pct_chg'] = pct
                    estimated_fields.append('pct_chg')
                realtime_today['estimated_fields'] = estimated_fields
                if isinstance(market_phase_context, dict) and "is_partial_bar" in market_phase_context:
                    realtime_today['is_partial_bar'] = market_phase_context.get("is_partial_bar")
                if fetched_at is not None:
                    realtime_today['fetched_at'] = fetched_at
                if provider_timestamp is not None:
                    realtime_today['provider_timestamp'] = provider_timestamp
                if fallback_from is not None:
                    realtime_today['fallback_from'] = fallback_from
                realtime_owned_fields = {
                    'open', 'high', 'low', 'close',
                    'volume', 'amount', 'pct_chg', 'pctChg',
                    'date', 'data_source', 'dataSource', 'source',
                    'realtime_source', 'realtimeSource',
                    'is_partial_bar', 'isPartialBar', 'is_estimated',
                    'isEstimated', 'estimated_fields', 'estimatedFields',
                    'fetched_at', 'fetchedAt', 'provider_timestamp',
                    'providerTimestamp', 'fallback_from', 'fallbackFrom',
                }
                for k, v in orig_today.items():
                    if k not in realtime_today and k not in realtime_owned_fields and v is not None:
                        realtime_today[k] = v
                enhanced['today'] = realtime_today
                enhanced['ma_status'] = self._compute_ma_status(
                    price, trend_result.ma5, trend_result.ma10, trend_result.ma20
                )
                enhanced['date'] = market_today
                if yesterday_close is not None:
                    try:
                        yc = float(yesterday_close)
                        if yc > 0:
                            enhanced['price_change_ratio'] = round(
                                (price - yc) / yc * 100, 2
                            )
                    except (TypeError, ValueError):
                        pass
                if vol is not None and enhanced.get('yesterday'):
                    yest_vol = enhanced['yesterday'].get('volume') if isinstance(
                        enhanced['yesterday'], dict
                    ) else None
                    if yest_vol is not None:
                        try:
                            yv = float(yest_vol)
                            if yv > 0:
                                enhanced['volume_change_ratio'] = round(
                                    float(vol) / yv, 2
                                )
                        except (TypeError, ValueError):
                            pass

        # ETF/index flag for analyzer prompt (Fixes #274)
        enhanced['is_index_etf'] = SearchService.is_index_or_etf(
            context.get('code', ''), enhanced.get('stock_name', stock_name)
        )

        # P0: append unified fundamental block; keep as additional context only
        enhanced["fundamental_context"] = (
            fundamental_context
            if isinstance(fundamental_context, dict)
            else self.fetcher_manager.build_failed_fundamental_context(
                context.get("code", ""),
                "invalid fundamental context",
            )
        )

        return enhanced

    def _attach_belong_boards_to_fundamental_context(
        self,
        code: str,
        fundamental_context: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """
        Attach A-share board membership as a top-level supplemental field.

        Keep this as a shallow copy so cached fundamental contexts are not
        mutated in place after retrieval.
        """
        if isinstance(fundamental_context, dict):
            enriched_context = dict(fundamental_context)
        else:
            enriched_context = self.fetcher_manager.build_failed_fundamental_context(
                code,
                "invalid fundamental context",
            )

        market = enriched_context.get("market")
        if not isinstance(market, str) or not market.strip():
            market = get_market_for_stock(normalize_stock_code(code))

        existing_boards = enriched_context.get("belong_boards")
        existing_board_list = list(existing_boards) if isinstance(existing_boards, list) else None
        if existing_board_list:
            enriched_context["belong_boards"] = existing_board_list
            self._attach_concept_rankings_to_fundamental_context(code, enriched_context, market)
            return enriched_context

        boards_block = enriched_context.get("boards")
        boards_status = boards_block.get("status") if isinstance(boards_block, dict) else None
        coverage = enriched_context.get("coverage")
        boards_coverage = coverage.get("boards") if isinstance(coverage, dict) else None

        # For HK/US: the offshore adapter already populates belong_boards from
        # yfinance sector/industry. Don't overwrite it (and we have no AkShare
        # sector endpoint for those markets anyway). Default to [] when callers
        # pass a minimal context without the key.
        if market != "cn":
            enriched_context["belong_boards"] = existing_board_list or []
            return enriched_context

        if boards_status == "not_supported" or boards_coverage == "not_supported":
            enriched_context["belong_boards"] = existing_board_list or []
            return enriched_context

        boards: List[Dict[str, Any]] = []
        try:
            raw_boards = self.fetcher_manager.get_belong_boards(code)
            if isinstance(raw_boards, list):
                boards = raw_boards
        except Exception as e:
            logger.debug("%s attach belong_boards failed (fail-open): %s", code, e)

        enriched_context["belong_boards"] = boards or existing_board_list or []
        self._attach_concept_rankings_to_fundamental_context(code, enriched_context, market)
        return enriched_context

    def _attach_concept_rankings_to_fundamental_context(
        self,
        code: str,
        enriched_context: Dict[str, Any],
        market: str,
    ) -> None:
        """Attach concept/theme rankings for A-share related-board signals."""
        if market != "cn" or isinstance(enriched_context.get("concept_boards"), dict):
            return

        top_concepts, bottom_concepts = self._get_concept_rankings_for_market(market)

        concept_data: Dict[str, Any] = {
            "top": top_concepts,
            "bottom": bottom_concepts,
        }
        if not top_concepts and not bottom_concepts:
            # Empty lists are removed while fundamental contexts are merged.
            # Keep a non-empty internal marker so downstream consumers can
            # distinguish an attempted empty result from a missing preload.
            concept_data["fetch_attempted"] = True
        enriched_context["concept_boards"] = {
            "status": "ok" if top_concepts and bottom_concepts else "partial",
            "data": concept_data,
        }

    def _get_concept_rankings_for_market(
        self,
        market: str,
    ) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        """Fetch market-wide concept rankings once per pipeline run."""
        if market != "cn":
            return [], []

        service = getattr(self, "market_hotspot_service", None)
        if service is None:
            try:
                service = MarketHotspotService(fetcher_manager=self.fetcher_manager)
            except Exception as exc:
                logger.debug(
                    "market hotspot service init failed in concept ranking path (fail-open): %s",
                    exc,
                )
                service = None
            else:
                self.market_hotspot_service = service

        cache = getattr(self, "_concept_rankings_cache", None)
        if not isinstance(cache, dict):
            cache = {}
            self._concept_rankings_cache = cache

        lock = getattr(self, "_concept_rankings_cache_lock", None)
        if lock is None:
            lock = threading.Lock()
            self._concept_rankings_cache_lock = lock

        with lock:
            if market in cache:
                top_concepts, bottom_concepts = cache[market]
                return list(top_concepts), list(bottom_concepts)

            top_concepts: List[Dict[str, Any]] = []
            bottom_concepts: List[Dict[str, Any]] = []
            try:
                if service is None:
                    fetch_rankings = getattr(self.fetcher_manager, "get_concept_rankings", None)
                    if callable(fetch_rankings):
                        rankings = fetch_rankings(5)
                        if isinstance(rankings, tuple) and len(rankings) == 2:
                            raw_top, raw_bottom = rankings
                            if isinstance(raw_top, list):
                                top_concepts = list(raw_top)
                            if isinstance(raw_bottom, list):
                                bottom_concepts = list(raw_bottom)
                else:
                    top_concepts, bottom_concepts = service.get_concept_rankings(5)
            except Exception as e:
                logger.debug("attach concept_rankings failed (fail-open): %s", e)

            cache[market] = (top_concepts, bottom_concepts)
            return list(top_concepts), list(bottom_concepts)

    def _build_market_structure_context(
        self,
        *,
        code: str,
        stock_name: str,
        market: str,
        fundamental_context: Optional[Dict[str, Any]],
        trade_date: Any = None,
        market_phase_summary: Optional[Dict[str, Any]] = None,
    ) -> Optional[Dict[str, Any]]:
        """Build market structure context without blocking the main analysis."""
        service = getattr(self, "market_structure_service", None)
        if service is None:
            try:
                service = MarketStructureService(fetcher_manager=self.fetcher_manager)
                self.market_structure_service = service
            except Exception as exc:
                logger.debug("market structure service init failed (fail-open): %s", exc)
                return None
        try:
            return service.build_context(
                code=code,
                stock_name=stock_name,
                market=market,
                fundamental_context=fundamental_context,
                trade_date=trade_date,
                market_phase_summary=market_phase_summary,
            )
        except Exception as exc:
            logger.debug(
                "%s market structure context build failed (fail-open): %s",
                code,
                exc,
                exc_info=True,
            )
            return None

    def _ensure_agent_history(
        self,
        code: str,
        min_days: int = 240,
        analysis_target: Optional[AnalysisTarget] = None,
    ) -> None:
        """Ensure at least *min_days* of K-line history is in DB for agent tools."""
        from src.services.history_loader import get_frozen_target_date

        target = get_frozen_target_date()
        if target is None:
            target = self._resolve_resume_target_date(
                code, analysis_target=analysis_target
            )
        start = target - timedelta(days=int(min_days * 1.8))
        bars = self.db.get_data_range(code, start, target)
        if bars and len(bars) >= min(min_days, 200):
            logger.debug("[%s] Agent history: %d bars in DB, sufficient", code, len(bars))
            return
        try:
            df, source = self.fetcher_manager.get_daily_data(code, days=min_days)
            if df is not None and not df.empty:
                self.db.save_daily_data(df, code, source)
                logger.info("[%s] Prefetched %d rows of history for agent (source: %s)", code, len(df), source)
        except Exception as e:
            logger.warning("[%s] Agent history prefetch failed: %s", code, e)

    def _filter_agent_tools_for_index(self, executor: Any) -> Any:
        """Return an executor whose tool registry excludes index-incompatible tools.

        Maps ``INDEX_SKIP_MODULES`` to the agent tool names that would otherwise
        invoke the skipped bottom-layer providers (chip distribution, fundamental
        aggregation, capital flow). The filtered registry carries the source
        category-timeout map so per-category ceilings survive the subset copy.
        """
        tool_modules = {
            "get_chip_distribution": {"chip_distribution"},
            "get_stock_info": {
                "fundamental",
                "belong_boards",
                "lhb",
                "corporate_events",
            },
            "get_capital_flow": {"capital_flow"},
        }
        index_skip_tool_names = {
            name
            for name, modules in tool_modules.items()
            if INDEX_SKIP_MODULES.intersection(modules)
        }
        registry = getattr(executor, "tool_registry", None)
        if registry is None:
            return executor
        from src.agent.tools.registry import ToolRegistry as _TR
        filtered = _TR(category_timeout_map=registry.category_timeout_map)
        for name in registry.list_names():
            if name in index_skip_tool_names:
                continue
            tool_def = registry.get(name)
            if tool_def is not None:
                filtered.register(tool_def)
        executor.tool_registry = filtered
        return executor

    def _analyze_with_agent(
        self, 
        code: str, 
        report_type: ReportType, 
        query_id: str,
        stock_name: str,
        realtime_quote: Any,
        chip_data: Optional[ChipDistribution],
        fundamental_context: Optional[Dict[str, Any]] = None,
        trend_result: Optional[TrendAnalysisResult] = None,
        *,
        market_phase_context: Optional[Dict[str, Any]] = None,
        market_phase_summary: Optional[Dict[str, Any]] = None,
        daily_market_context: Optional[DailyMarketContext] = None,
        portfolio_context: Optional[Dict[str, Any]] = None,
        market_structure_context: Optional[Dict[str, Any]] = None,
        analysis_target: Optional[AnalysisTarget] = None,
    ) -> Optional[AnalysisResult]:
        """
        Analyze a single stock using Agent mode.
        """
        try:
            from src.agent.factory import build_agent_executor
            report_language = resolve_report_language(getattr(self.config, "report_language", None))

            is_index = (
                analysis_target is not None
                and analysis_target.asset_type == ParseStatus.INDEX
            )

            requested_skills = (
                self.analysis_skills
                if self.analysis_skills is not None
                else (getattr(self.config, 'agent_skills', None) or None)
            )
            # Build executor from shared factory (ToolRegistry and SkillManager prototype are cached)
            executor = build_agent_executor(self.config, requested_skills)

            # Index targets: drop the provider tools matching INDEX_SKIP_MODULES from the Agent
            # tool surface (chip distribution, fundamentals, fund flow), so the Agent branch also makes zero calls (Story 1.5 V6).
            if is_index:
                executor = self._filter_agent_tools_for_index(executor)

            # Build initial context to avoid redundant tool calls
            initial_context = {
                "stock_code": code,
                "stock_name": stock_name,
                "report_type": report_type.value,
                "report_language": report_language,
                "fundamental_context": fundamental_context,
            }
            if isinstance(portfolio_context, dict):
                initial_context["portfolio_context"] = dict(portfolio_context)
            if self.analysis_skills is not None:
                initial_context["skills"] = self.analysis_skills
            if market_phase_context is not None:
                initial_context["market_phase_context"] = market_phase_context
            if isinstance(market_structure_context, dict):
                initial_context["market_structure_context"] = market_structure_context
            self._attach_daily_market_context(
                initial_context,
                daily_market_context,
                report_language=report_language,
            )
            
            if realtime_quote:
                initial_context["realtime_quote"] = self._safe_to_dict(realtime_quote)
            if chip_data:
                initial_context["chip_distribution"] = self._safe_to_dict(chip_data)
            if trend_result:
                initial_context["trend_result"] = self._safe_to_dict(trend_result)

            # Agent path: inject social sentiment as news_context so both
            # executor (_build_user_message) and orchestrator (ctx.set_data)
            # can consume it through the existing news_context channel
            social_evidence_context: Optional[str] = None
            if self.social_sentiment_service is not None and self.social_sentiment_service.is_available and is_us_stock_code(code):
                try:
                    social_context = self.social_sentiment_service.get_social_context(code)
                    if social_context:
                        social_evidence_context = social_context
                        existing = initial_context.get("news_context")
                        if existing:
                            initial_context["news_context"] = existing + "\n\n" + social_context
                        else:
                            initial_context["news_context"] = social_context
                        logger.info(f"[{code}] Agent mode: social sentiment data injected into news_context")
                except Exception as e:
                    logger.warning(f"[{code}] Agent mode: social sentiment fetch failed: {e}")

            persisted_intelligence_context = self._load_persisted_intelligence_context(
                code=code,
                stock_name=stock_name,
                market=("cn" if is_index else get_market_for_stock(normalize_stock_code(code)) or "cn"),
            )
            if persisted_intelligence_context:
                existing = initial_context.get("news_context")
                initial_context["news_context"] = (
                    f"{existing}\n\n{persisted_intelligence_context}"
                    if existing
                    else persisted_intelligence_context
                )
                logger.info(f"[{code}] Agent mode: local intelligence evidence injected into news_context")

            # Issue #1066: ensure deep history is in DB before agent tools run
            if analysis_target is None:
                self._ensure_agent_history(code)
            else:
                self._ensure_agent_history(code, analysis_target=analysis_target)

            analysis_context = self._load_agent_analysis_context(
                code, stock_name, analysis_target=analysis_target
            )
            market = "cn" if is_index else get_market_for_stock(normalize_stock_code(code))
            (
                analysis_context_pack_summary,
                analysis_context_pack_overview,
            ) = self._build_analysis_context_pack_outputs(
                self._build_agent_analysis_artifacts(
                    code=code,
                    stock_name=stock_name,
                    market=market,
                    phase=market_phase_context,
                    initial_context=initial_context,
                    fundamental_context=fundamental_context,
                    query_id=query_id,
                    base_context=analysis_context,
                    portfolio_context=portfolio_context,
                ),
                report_language=report_language,
                code=code,
                query_id=query_id,
            )
            if analysis_context_pack_summary:
                initial_context["analysis_context_pack_summary"] = analysis_context_pack_summary

            # Run the Agent
            if report_language in ("en", "ko"):
                message = f"Analyze stock {code} ({stock_name}) and return the full decision dashboard JSON."
            else:
                message = f"请分析股票 {code} ({stock_name})，并生成决策仪表盘报告。"
            llm_started_at = time.monotonic()
            # The Agent calls the search tools itself to gather evidence, so the disclosure count can only come
            # from what those tools actually returned; a search_stock_news() call made after the analysis is unrelated to the evidence the Agent consumed.
            # The accumulator object is referenced here, so it stays safe to read after a reset.
            news_evidence_token = activate_news_evidence_scope()
            news_evidence = get_current_news_evidence()
            try:
                record_llm_run_started(
                    model=getattr(self.config, "agent_litellm_model", None),
                    call_type="agent_analysis",
                )
                agent_result = executor.run(message, context=initial_context)
            except Exception as exc:
                record_llm_run(
                    success=False,
                    model=getattr(self.config, "agent_litellm_model", None),
                    call_type="agent_analysis",
                    duration_ms=int((time.monotonic() - llm_started_at) * 1000),
                    error_type=type(exc).__name__,
                    error_message=exc,
                )
                raise
            finally:
                reset_news_evidence_scope(news_evidence_token)

            # Convert to an AnalysisResult
            result = self._agent_result_to_analysis_result(
                agent_result,
                code,
                stock_name,
                report_type,
                query_id,
                trend_result=trend_result,
            )

            # The tri-state count comes from the search tool results the Agent actually consumed: None when
            # no channel is available (no search performed), otherwise starting at 0 and counting whatever came back.
            if result is not None and news_evidence is not None:
                result.news_result_count = news_evidence.resolve(
                    search_available=bool(
                        self.search_service is not None
                        and self.search_service.is_available
                    ),
                )
                # As on the normal path, register each source individually: what the Agent found during the run,
                # the injected social sentiment, and the injected local intelligence pool. This path does not go
                # through format_intel_report(), but still avoids passing the assembled block, in case someone later adds a source that emits placeholder text.
                result.news_evidence_present = news_evidence_present(
                    result.news_result_count,
                    social_evidence_context,
                    persisted_intelligence_context,
                )
            record_llm_run(
                success=bool(result and getattr(result, "success", True)),
                model=getattr(result, "model_used", None) if result else getattr(agent_result, "model", None),
                call_type="agent_analysis",
                duration_ms=int((time.monotonic() - llm_started_at) * 1000),
                error_type=(
                    None
                    if result and getattr(result, "success", True)
                    else "AgentResultError"
                ),
                error_message=(
                    getattr(result, "error_message", None)
                    if result and not getattr(result, "success", True)
                    else ("Agent returned empty result" if result is None else None)
                ),
            )
            if result:
                result.query_id = query_id
            # Agent weak integrity: placeholder fill only, no LLM retry
            if result and getattr(self.config, "report_integrity_enabled", False):
                from src.analyzer import check_content_integrity, apply_placeholder_fill

                pass_integrity, missing = check_content_integrity(
                    result,
                    require_phase_decision=isinstance(market_phase_summary, dict),
                )
                if not pass_integrity:
                    apply_placeholder_fill(result, missing)
                    logger.info(
                        "[LLM integrity] integrity_mode=agent_weak required fields missing %s, filled with placeholders",
                        missing,
                    )
            # chip_structure fallback (Issue #589), before save_analysis_history
            if result and chip_data is not None:
                normalize_chip_structure_availability(result, chip_data)

            # price_position fallback (same as non-agent path Step 7.7)
            if result:
                pipeline_adjustments: list[PipelineActionAdjustment] = []
                runtime_facts = getattr(agent_result, "runtime_facts", None)
                pipeline_start_signal = getattr(result, "decision_type", "hold")
                risk_application = (
                    getattr(runtime_facts, "risk_override_application", None)
                    if runtime_facts is not None
                    else None
                )
                if risk_application is not None:
                    pipeline_start_signal = risk_application.post_risk_signal.value
                initial_action_advice = getattr(result, "operation_advice", None)
                self._refresh_decision_action_for_final_result(
                    result,
                    report_type=report_type.value,
                    previous_operation_advice=initial_action_advice,
                )
                pipeline_start_action = normalize_decision_action(
                    getattr(result, "action", None)
                )
                action_chain_valid = pipeline_start_action is not None
                fill_price_position_if_needed(result, trend_result, realtime_quote)
                realtime_data = initial_context.get("realtime_quote", {})
                if isinstance(realtime_data, dict):
                    result.current_price = realtime_data.get("price")
                    result.change_pct = realtime_data.get("change_pct")
                action_before_guardrail = getattr(result, "action", None)
                advice_before_guardrail = getattr(result, "operation_advice", None)
                stabilize_decision_with_structure(result, trend_result, fundamental_context)
                self._refresh_decision_action_for_final_result(
                    result,
                    report_type=report_type.value,
                    previous_operation_advice=advice_before_guardrail,
                )
                action_after_guardrail = normalize_decision_action(
                    getattr(result, "action", None)
                )
                if action_chain_valid and action_after_guardrail is not None:
                    capture_pipeline_action_adjustment(
                        pipeline_adjustments,
                        source="structure_and_fundamentals",
                        before=action_before_guardrail,
                        after=action_after_guardrail,
                    )
                else:
                    action_chain_valid = False
                action_before_guardrail = getattr(result, "action", None)
                advice_before_guardrail = getattr(result, "operation_advice", None)
                adjustments = apply_phase_decision_guardrails(
                    result,
                    market_phase_summary=market_phase_summary,
                    analysis_context_pack_overview=analysis_context_pack_overview,
                    report_language=getattr(result, "report_language", None)
                    or resolve_report_language(getattr(self.config, "report_language", None)),
                )
                if adjustments:
                    logger.info("[phase_decision_guardrail] Applied agent adjustments for %s: %s", code, adjustments)
                self._refresh_decision_action_for_final_result(
                    result,
                    report_type=report_type.value,
                    previous_operation_advice=advice_before_guardrail,
                )
                action_after_guardrail = normalize_decision_action(
                    getattr(result, "action", None)
                )
                if action_chain_valid and action_after_guardrail is not None:
                    capture_pipeline_action_adjustment(
                        pipeline_adjustments,
                        source="market_phase",
                        before=action_before_guardrail,
                        after=action_after_guardrail,
                    )
                else:
                    action_chain_valid = False
                action_before_guardrail = getattr(result, "action", None)
                advice_before_guardrail = getattr(result, "operation_advice", None)
                market_context_adjustments = apply_daily_market_context_guardrail(
                    result,
                    daily_market_context=initial_context.get("daily_market_context"),
                    report_language=getattr(result, "report_language", None)
                    or resolve_report_language(getattr(self.config, "report_language", None)),
                )
                if market_context_adjustments:
                    logger.info(
                        "[daily_market_context_guardrail] Applied agent adjustments for %s: %s",
                        code,
                        market_context_adjustments,
                    )
                self._refresh_decision_action_for_final_result(
                    result,
                    report_type=report_type.value,
                    previous_operation_advice=advice_before_guardrail,
                )
                action_after_guardrail = normalize_decision_action(
                    getattr(result, "action", None)
                )
                if action_chain_valid and action_after_guardrail is not None:
                    capture_pipeline_action_adjustment(
                        pipeline_adjustments,
                        source="daily_market_context",
                        before=action_before_guardrail,
                        after=action_after_guardrail,
                    )
                else:
                    action_chain_valid = False
                if isinstance(fundamental_context, dict):
                    result.fundamental_context = fundamental_context
                if isinstance(market_structure_context, dict):
                    result.market_structure_context = market_structure_context
                result.market_phase_summary = market_phase_summary
                result.analysis_context_pack_overview = analysis_context_pack_overview
                final_action = normalize_decision_action(getattr(result, "action", None))
                if isinstance(result.dashboard, dict):
                    result.dashboard.pop("agent_disagreement_explanation", None)
                if (
                    runtime_facts is not None
                    and action_chain_valid
                    and pipeline_start_action is not None
                    and final_action is not None
                ):
                    if not isinstance(result.dashboard, dict):
                        result.dashboard = {}
                    result.dashboard["agent_disagreement_explanation"] = (
                        build_pipeline_final_explanation(
                            runtime_facts=runtime_facts,
                            pipeline_start_signal=pipeline_start_signal,
                            pipeline_start_action=pipeline_start_action,
                            final_action=final_action,
                            pipeline_adjustments=pipeline_adjustments,
                            data_quality=(
                                analysis_context_pack_overview.get("data_quality")
                                if isinstance(analysis_context_pack_overview, dict)
                                else None
                            ),
                        )
                    )

            if result:
                self._append_daily_data_source(
                    result,
                    analysis_context,
                    analysis_target,
                )

            resolved_stock_name = result.name if result and result.name else stock_name

            # Persist the news intelligence to the database (Agent tool results only feed the LLM context and are not persisted, Fixes #396)
            # Use search_stock_news (matching the Agent tool call logic): a single API call with no extra latency
            if self.search_service is not None and self.search_service.is_available:
                try:
                    news_response = self.search_service.search_stock_news(
                        stock_code=("" if is_index else code),
                        stock_name=resolved_stock_name,
                        max_results=5
                    )
                    # This follow-up lookup exists only to persist news intelligence (Fixes #396) and deliberately does not write
                    # result.news_result_count: it happens after the analysis and is unrelated to the evidence the
                    # Agent actually consumed, so using it for the disclosure decision would distort it in both directions. The real count is
                    # collected in the evidence scope of executor.run() (see above).
                    if news_response.success and news_response.results:
                        query_context = self._build_query_context(query_id=query_id)
                        self.db.save_news_intel(
                            code=code,
                            name=resolved_stock_name,
                            dimension="latest_news",
                            query=news_response.query,
                            response=news_response,
                            query_context=query_context
                        )
                        logger.info(f"[{code}] Agent mode: saved {len(news_response.results)} news item(s)")
                except Exception as e:
                    logger.warning(f"[{code}] Agent mode failed to save news intelligence: {e}")

            # Persist the analysis history record
            if result and result.success:
                try:
                    agent_context_snapshot = self._build_context_snapshot(
                        enhanced_context={
                            **self._without_runtime_prompt_context(initial_context),
                            "stock_name": resolved_stock_name,
                        },
                        news_content=initial_context.get("news_context"),
                        realtime_quote=realtime_quote,
                        chip_data=chip_data,
                        analysis_context_pack_overview=analysis_context_pack_overview,
                        market_phase_summary=market_phase_summary,
                    )
                    result.diagnostic_context_snapshot = agent_context_snapshot
                    agent_context_snapshot["stock_name"] = resolved_stock_name
                    saved_history_id = self.db.save_analysis_history(
                        result=result,
                        query_id=query_id,
                        report_type=report_type.value,
                        news_content=None,
                        context_snapshot=agent_context_snapshot,
                        save_snapshot=self.save_context_snapshot,
                    )
                    valid_saved_history_id = (
                        isinstance(saved_history_id, int)
                        and not isinstance(saved_history_id, bool)
                        and saved_history_id > 0
                    )
                    record_history_run(
                        report_saved=bool(saved_history_id),
                        metadata_saved=bool(saved_history_id),
                        analysis_history_id=(
                            saved_history_id if valid_saved_history_id else None
                        ),
                    )
                    if valid_saved_history_id:
                        self._persist_skill_opinion_samples_after_history_save(
                            runtime_facts=getattr(agent_result, "runtime_facts", None),
                            analysis_history_id=saved_history_id,
                            stock_code=code,
                            analysis_context_pack_overview=analysis_context_pack_overview,
                        )
                        self._extract_decision_signal_after_history_save(
                            result=result,
                            query_id=query_id,
                            source_report_id=saved_history_id,
                            report_type=report_type.value,
                            context_snapshot=agent_context_snapshot,
                            portfolio_context=portfolio_context,
                            analysis_target=analysis_target,
                        )
                    latest_diagnostic_snapshot = current_diagnostic_snapshot()
                    if latest_diagnostic_snapshot is not None:
                        agent_context_snapshot["diagnostics"] = latest_diagnostic_snapshot
                        result.diagnostic_context_snapshot = agent_context_snapshot
                except Exception as e:
                    record_history_run(
                        report_saved=False,
                        metadata_saved=False,
                        error_message=e,
                    )
                    logger.warning(f"[{code}] failed to save Agent analysis history: {e}")

            return result

        except Exception as e:
            logger.error(f"[{code}] Agent analysis failed: {e}")
            logger.exception(f"[{code}] Agent error details:")
            return None

    def _load_agent_analysis_context(
        self, code: str, stock_name: str, analysis_target: Optional[AnalysisTarget] = None
    ) -> Dict[str, Any]:
        """Load daily-bar context for Agent pack summaries without blocking analysis."""
        try:
            context = self._get_analysis_context_with_market_fallback(
                code, analysis_target=analysis_target
            )
        except Exception as exc:
            logger.warning(
                "[%s] Agent analysis context load failed; daily_bars will be marked missing: %s",
                code,
                exc,
            )
            context = None

        if isinstance(context, dict) and context:
            enriched = dict(context)
            enriched.setdefault("code", code)
            if stock_name:
                enriched.setdefault("stock_name", stock_name)
            return enriched

        return {
            "code": code,
            "stock_name": stock_name,
            "data_missing": True,
            "today": {},
            "yesterday": {},
        }

    def _get_analysis_context_with_market_fallback(
        self, code: str, analysis_target: Optional[AnalysisTarget] = None
    ) -> Optional[Dict[str, Any]]:
        """Load analysis context, fetching JP/KR/TW daily bars when DB has no context."""
        context = self.db.get_analysis_context(code)
        if isinstance(context, dict) and context:
            return context

        if analysis_target is not None and analysis_target.asset_type == ParseStatus.INDEX:
            market = "cn"
        else:
            market = get_market_for_stock(normalize_stock_code(code))
        if market not in {"jp", "kr", "tw"}:
            return context

        try:
            df, source_name = self.fetcher_manager.get_daily_data(code, days=60)
        except Exception as exc:
            logger.warning("[%s] JP/KR daily fallback fetch failed: %s", code, exc)
            return context

        if df is None or df.empty:
            logger.warning("[%s] JP/KR daily fallback returned empty data", code)
            return context

        try:
            self.db.save_daily_data(df, code, source_name)
            refreshed = self.db.get_analysis_context(code)
            if isinstance(refreshed, dict) and refreshed:
                return refreshed
        except Exception as exc:
            logger.warning("[%s] JP/KR daily fallback persistence failed: %s", code, exc)

        return self._build_analysis_context_from_daily_df(code, df)

    def _build_analysis_context_from_daily_df(self, code: str, df: pd.DataFrame) -> Optional[Dict[str, Any]]:
        if df is None or df.empty:
            return None

        frame = df.copy()
        frame.columns = [str(column).lower() for column in frame.columns]
        if "date" in frame.columns:
            frame = frame.sort_values("date")
        frame = frame.tail(2)
        rows = frame.to_dict(orient="records")
        if not rows:
            return None

        def normalize_row(row: Dict[str, Any]) -> Dict[str, Any]:
            normalized: Dict[str, Any] = {"code": row.get("code") or code}
            for key in ("open", "high", "low", "close", "volume", "amount", "pct_chg", "ma5", "ma10", "ma20", "volume_ratio"):
                value = row.get(key)
                if pd.notna(value):
                    normalized[key] = float(value)
            row_date = row.get("date")
            if hasattr(row_date, "date"):
                row_date = row_date.date()
            normalized["date"] = row_date.isoformat() if hasattr(row_date, "isoformat") else str(row_date)
            return normalized

        today = normalize_row(rows[-1])
        context: Dict[str, Any] = {
            "code": code,
            "date": today.get("date"),
            "today": today,
        }
        if len(rows) > 1:
            yesterday = normalize_row(rows[-2])
            context["yesterday"] = yesterday
            yesterday_volume = yesterday.get("volume")
            if yesterday_volume:
                context["volume_change_ratio"] = round(float(today.get("volume", 0)) / float(yesterday_volume), 2)
            yesterday_close = yesterday.get("close")
            if yesterday_close:
                context["price_change_ratio"] = round(
                    (float(today.get("close", 0)) - float(yesterday_close)) / float(yesterday_close) * 100,
                    2,
                )
            context["ma_status"] = self.db._analyze_ma_status(SimpleNamespace(**today))

        return context

    def _load_daily_market_context(
        self,
        market: str,
        *,
        force_refresh: bool = False,
        target_date: Optional[date] = None,
    ) -> Optional[DailyMarketContext]:
        """Load/generate today's market context when market review is explicitly enabled."""
        if getattr(self, "daily_market_context_enabled", True) is not True:
            return None
        if getattr(self.config, "daily_market_context_enabled", True) is not True:
            return None
        if getattr(self.config, "market_review_enabled", None) is not True:
            return None

        try:
            service = getattr(self, "_daily_market_context_service", None)
            if service is None:
                service_lock = self._get_daily_market_context_service_lock()
                with service_lock:
                    service = getattr(self, "_daily_market_context_service", None)
                    if service is None:
                        service = DailyMarketContextService(db_manager=self.db)
                        self._daily_market_context_service = service
            get_context_kwargs = {
                "region": market,
                "config": self.config,
                "notifier": self.notifier,
                "analyzer": self.analyzer,
                "search_service": self.search_service,
                "force_refresh": force_refresh,
                "allow_generate": getattr(self, "daily_market_context_allow_generate", True),
                "target_date": target_date,
            }
            current_query_id = getattr(self, "query_id", None)
            if isinstance(current_query_id, str) and current_query_id.strip():
                get_context_kwargs["current_query_id"] = current_query_id
            return service.get_context(**get_context_kwargs)
        except Exception as exc:
            logger.warning("Failed to load daily market context; continuing stock analysis: %s", exc, exc_info=True)
            return None

    def _get_daily_market_context_service_lock(self) -> threading.Lock:
        service_lock = getattr(self, "_daily_market_context_service_lock", None)
        if service_lock is not None:
            return service_lock
        with _DAILY_MARKET_CONTEXT_SERVICE_LOCK_INIT_GUARD:
            service_lock = getattr(self, "_daily_market_context_service_lock", None)
            if service_lock is None:
                service_lock = threading.Lock()
                self._daily_market_context_service_lock = service_lock
            return service_lock

    @staticmethod
    def _coerce_daily_market_context_date(value: Any) -> Optional[date]:
        if isinstance(value, datetime):
            return value.date()
        if isinstance(value, date):
            return value
        if isinstance(value, str):
            try:
                return date.fromisoformat(value[:10])
            except ValueError:
                return None
        return None

    @staticmethod
    def _attach_daily_market_context(
        target_context: Dict[str, Any],
        daily_market_context: Optional[DailyMarketContext],
        *,
        report_language: str,
    ) -> None:
        """Attach only the safe daily market summary to runtime analysis context."""
        if daily_market_context is None:
            return
        safe_context = daily_market_context.to_safe_dict()
        prompt_section = format_daily_market_context_prompt_section(
            safe_context,
            report_language=report_language,
        )
        if not prompt_section:
            return
        target_context["daily_market_context"] = safe_context
        target_context["daily_market_context_summary"] = prompt_section

    def _agent_result_to_analysis_result(
        self,
        agent_result,
        code: str,
        stock_name: str,
        report_type: ReportType,
        query_id: str,
        trend_result: Optional[TrendAnalysisResult] = None,
    ) -> AnalysisResult:
        """
        Convert an AgentResult into an AnalysisResult.
        """
        report_language = resolve_report_language(getattr(self.config, "report_language", None))
        dash = None
        result = AnalysisResult(
            code=code,
            name=stock_name,
            sentiment_score=50,
            trend_prediction=get_unknown_text(report_language),
            operation_advice=localize_operation_advice("观望", report_language),
            confidence_level=localize_confidence_level("medium", report_language),
            report_language=report_language,
            success=agent_result.success,
            error_message=agent_result.error or None,
            data_sources=f"agent:{agent_result.provider}",
            model_used=agent_result.model or None,
        )

        if agent_result.success and agent_result.dashboard:
            dash = agent_result.dashboard
            ai_stock_name = str(dash.get("stock_name", "")).strip()
            if ai_stock_name and self._is_placeholder_stock_name(stock_name, code):
                result.name = ai_stock_name

            nested_dashboard = dash.get("dashboard") if isinstance(dash, dict) else None

            raw_score = self._agent_dashboard_value(
                dash,
                nested_dashboard,
                "sentiment_score",
                scalar=True,
            )
            if self._is_agent_field_missing(raw_score, scalar=True):
                fallback_score = self._trend_score_fallback(trend_result)
                if fallback_score is not None:
                    result.sentiment_score = fallback_score
                    self._mark_trend_fallback_source(result)
            else:
                result.sentiment_score = self._safe_int(raw_score, 50)

            raw_trend = self._agent_dashboard_value(
                dash,
                nested_dashboard,
                "trend_prediction",
                scalar=True,
                expect_text=True,
            )
            if self._is_agent_field_missing(raw_trend, scalar=True, expect_text=True):
                trend_label = self._trend_label_fallback(
                    trend_result,
                    report_language,
                )
                if trend_label:
                    result.trend_prediction = trend_label
                    self._mark_trend_fallback_source(result)
            else:
                result.trend_prediction = str(raw_trend)

            raw_advice = self._agent_dashboard_value(
                dash,
                nested_dashboard,
                "operation_advice",
                scalar=True,
                allow_dict=True,
                expect_text=True,
            )
            extracted_advice = ""
            if isinstance(raw_advice, dict):
                # LLM may return {"no_position": "...", "has_position": "..."}
                extracted_advice = self._extract_advice_text_from_dict(raw_advice)
                if extracted_advice:
                    result.operation_advice = localize_operation_advice(
                        extracted_advice,
                        report_language,
                    )
                else:
                    signal_label = self._trend_signal_fallback(
                        trend_result,
                        report_language,
                    )
                    if signal_label:
                        result.operation_advice = signal_label
                        self._mark_trend_fallback_source(result)
            elif not self._is_agent_field_missing(
                raw_advice,
                scalar=True,
                allow_dict=True,
                expect_text=True,
            ):
                result.operation_advice = str(raw_advice) if raw_advice else (localize_operation_advice("观望", report_language))
            else:
                signal_label = self._trend_signal_fallback(trend_result, report_language)
                if signal_label:
                    result.operation_advice = signal_label
                    self._mark_trend_fallback_source(result)
            from src.agent.protocols import normalize_decision_signal

            raw_decision = self._agent_dashboard_value(
                dash,
                nested_dashboard,
                "decision_type",
                scalar=True,
                expect_text=True,
            )
            if self._is_agent_field_missing(raw_decision, scalar=True, expect_text=True):
                trend_decision = self._trend_decision_fallback(trend_result)
                decision_from_advice = infer_decision_type_from_advice(
                    result.operation_advice,
                    default="",
                )
                if decision_from_advice:
                    result.decision_type = decision_from_advice
                    if (
                        self._is_agent_field_missing(
                            raw_advice,
                            scalar=True,
                            allow_dict=True,
                            expect_text=True,
                        )
                        and not extracted_advice
                        and trend_decision
                    ):
                        self._mark_trend_fallback_source(result)
                else:
                    result.decision_type = trend_decision or "hold"
                    if trend_decision:
                        self._mark_trend_fallback_source(result)
            else:
                result.decision_type = normalize_decision_signal(raw_decision)
            result.confidence_level = localize_confidence_level(
                self._agent_dashboard_value(dash, nested_dashboard, "confidence_level")
                or result.confidence_level,
                report_language,
            )
            raw_summary = self._agent_dashboard_value(
                dash,
                nested_dashboard,
                "analysis_summary",
                scalar=True,
                expect_text=True,
            )
            if not self._is_agent_field_missing(raw_summary, scalar=True, expect_text=True):
                result.analysis_summary = str(raw_summary)
            else:
                result.analysis_summary = self._summary_fallback_from_result(result, report_language)
            top_level_phase_decision = dash.get("phase_decision") if isinstance(dash, dict) else None
            if isinstance(nested_dashboard, dict) and isinstance(top_level_phase_decision, dict):
                nested_dashboard = dict(nested_dashboard)
                nested_dashboard.setdefault("phase_decision", top_level_phase_decision)

            # The AI returns a top-level dict that contains a nested 'dashboard' sub-key
            # with core_conclusion / battle_plan / intelligence.  AnalysisResult's helper
            # methods (get_sniper_points, get_core_conclusion, etc.) expect that inner
            # structure, so we unwrap it here.
            result.dashboard = nested_dashboard or dash
            self._backfill_agent_dashboard_fields(result, trend_result, report_language)
        else:
            self._apply_trend_fallback(result, trend_result, report_language)
            if trend_result is not None:
                result.analysis_summary = (
                    result.analysis_summary
                    or self._summary_fallback_from_result(result, report_language)
                )
                self._backfill_agent_dashboard_fields(result, trend_result, report_language)
            if not result.error_message:
                result.error_message = (
                    "Agent failed to generate a valid decision dashboard" if report_language == "en"
                    else "에이전트가 유효한 결정 대시보드를 생성하지 못했습니다" if report_language == "ko"
                    else "Agent 未能生成有效的决策仪表盘"
                )

        explicit_action = dash.get("action") if isinstance(dash, dict) else None
        if explicit_action is None and isinstance(getattr(result, "dashboard", None), dict):
            explicit_action = result.dashboard.get("action")
        return populate_decision_action_fields(result, explicit_action=explicit_action)

    @staticmethod
    def _refresh_decision_action_for_final_result(
        result: AnalysisResult,
        *,
        report_type: Any,
        previous_operation_advice: Any,
    ) -> AnalysisResult:
        # A guardrail may rewrite the advice after the Agent action was parsed;
        # discard that stale action before using the same resolver as the
        # downstream DecisionSignal builder.
        previous_advice = str(previous_operation_advice or "").strip()
        current_advice = str(getattr(result, "operation_advice", None) or "").strip()
        if previous_advice != current_advice:
            result.action = None
            result.action_label = None
        fields = resolve_decision_signal_action_fields(
            result,
            report_type=str(report_type or ""),
        )
        result.action = fields["action"]
        result.action_label = fields["action_label"]
        return result

    @staticmethod
    def _agent_dashboard_value(
        dash: Dict[str, Any],
        nested_dashboard: Any,
        key: str,
        *,
        scalar: bool = False,
        allow_dict: bool = False,
        expect_text: bool = False,
    ) -> Any:
        """Read a scalar from top-level agent payload, then nested dashboard fallback."""
        value = dash.get(key) if isinstance(dash, dict) else None
        if isinstance(nested_dashboard, dict) and StockAnalysisPipeline._is_agent_field_missing(
            value,
            scalar=scalar,
            allow_dict=allow_dict,
            expect_text=expect_text,
        ):
            nested_value = nested_dashboard.get(key)
            if not StockAnalysisPipeline._is_agent_field_missing(
                nested_value,
                scalar=scalar,
                allow_dict=allow_dict,
                expect_text=expect_text,
            ):
                value = nested_value
        return value

    @staticmethod
    def _extract_advice_text_from_dict(raw_advice: dict) -> str:
        for field in ("has_position", "no_position"):
            if isinstance(raw_advice.get(field), str):
                text = raw_advice[field].strip()
                if not StockAnalysisPipeline._is_agent_placeholder_text(text):
                    return text

        for value in raw_advice.values():
            if isinstance(value, str):
                text = value.strip()
                if not StockAnalysisPipeline._is_agent_placeholder_text(text):
                    return text

        return ""

    @staticmethod
    def _is_agent_placeholder_text(text: str) -> bool:
        if not text:
            return True
        return text.lower() in {"n/a", "na", "none", "null", "unknown", "tbd"} or text in {
            "未知",
            "待补充",
            "数据缺失",
            "无",
        }

    @staticmethod
    def _is_agent_field_missing(
        value: Any,
        *,
        scalar: bool = False,
        allow_dict: bool = False,
        expect_text: bool = False,
    ) -> bool:
        if scalar and isinstance(value, dict):
            if not allow_dict or not value:
                return True
            return not StockAnalysisPipeline._extract_advice_text_from_dict(value)
        if value is None:
            return True
        if expect_text and scalar:
            if not isinstance(value, str):
                return True
        if isinstance(value, str):
            text = value.strip()
            return StockAnalysisPipeline._is_agent_placeholder_text(text)
        if isinstance(value, dict):
            if scalar:
                return not allow_dict
            return not value
        if scalar and isinstance(value, (list, tuple, set)):
            return True
        return False

    @staticmethod
    def _trend_score_fallback(trend_result: Optional[TrendAnalysisResult]) -> Optional[int]:
        if trend_result is None:
            return None
        try:
            score = int(getattr(trend_result, "signal_score", 0))
        except (TypeError, ValueError):
            return None
        return score if score > 0 else None

    @staticmethod
    def _trend_label_fallback(
        trend_result: Optional[TrendAnalysisResult],
        report_language: Optional[str] = None,
    ) -> str:
        report_language = resolve_report_language(report_language)
        if trend_result is None:
            return ""
        trend_status = getattr(trend_result, "trend_status", None)
        value = getattr(trend_status, "value", None) or str(trend_status or "").strip()
        if report_language != "en":
            return value
        return localize_trend_prediction(value, report_language)

    @staticmethod
    def _trend_signal_fallback(
        trend_result: Optional[TrendAnalysisResult],
        report_language: Optional[str] = None,
    ) -> str:
        report_language = resolve_report_language(report_language)
        if trend_result is None:
            return ""
        buy_signal = getattr(trend_result, "buy_signal", None)
        value = getattr(buy_signal, "value", None) or str(buy_signal or "").strip()
        return localize_operation_advice(value, report_language)

    @staticmethod
    def _trend_decision_fallback(trend_result: Optional[TrendAnalysisResult]) -> Optional[str]:
        if trend_result is None:
            return None
        signal_name = getattr(getattr(trend_result, "buy_signal", None), "name", "").lower()
        return {
            "strong_buy": "buy",
            "buy": "buy",
            "hold": "hold",
            "wait": "hold",
            "sell": "sell",
            "strong_sell": "sell",
        }.get(signal_name)

    @staticmethod
    def _append_daily_data_source(
        result: AnalysisResult,
        context: Any,
        analysis_target: Optional[AnalysisTarget],
    ) -> None:
        """Append an index's persisted daily provider without inferring sources."""
        if (
            analysis_target is None
            or analysis_target.asset_type != ParseStatus.INDEX
        ):
            return
        if not isinstance(context, dict):
            return
        today = context.get("today")
        if not isinstance(today, dict):
            return
        source = today.get("data_source")
        if not isinstance(source, str):
            return
        source = source.strip()
        if (
            not source
            or source.casefold() == "unknown"
            or source.casefold().startswith("realtime:")
        ):
            return

        existing = result.data_sources
        if existing is None:
            existing_tokens = []
        elif isinstance(existing, str):
            existing_tokens = [
                item.strip() for item in existing.split(",") if item.strip()
            ]
        else:
            return
        token = f"daily:{source}"
        if token in existing_tokens:
            return
        result.data_sources = ",".join([*existing_tokens, token])

    @staticmethod
    def _mark_trend_fallback_source(result: AnalysisResult) -> None:
        if "trend:fallback" in (result.data_sources or ""):
            return
        result.data_sources = (
            f"{result.data_sources},trend:fallback"
            if result.data_sources
            else "trend:fallback"
        )

    @staticmethod
    def _summary_fallback_from_result(result: AnalysisResult, report_language: str) -> str:
        trend = (result.trend_prediction or "").strip()
        advice = (result.operation_advice or "").strip()
        if trend and advice:
            if report_language == "en":
                return f"Trend view: {trend}; action advice: {advice}."
            if report_language == "ko":
                return f"추세 결론: {trend}; 대응 전략: {advice}."
            return f"趋势结论：{trend}；操作建议：{advice}。"
        return ""

    def _backfill_agent_dashboard_fields(
        self,
        result: AnalysisResult,
        trend_result: Optional[TrendAnalysisResult],
        report_language: str,
    ) -> None:
        if not isinstance(result.dashboard, dict):
            result.dashboard = {}
        dashboard = result.dashboard

        for key in (
            "sentiment_score",
            "trend_prediction",
            "operation_advice",
            "decision_type",
            "confidence_level",
            "analysis_summary",
        ):
            current = dashboard.get(key)
            if key == "sentiment_score":
                if self._is_agent_field_missing(current, scalar=True):
                    dashboard[key] = getattr(result, key)
            elif self._is_agent_field_missing(current, scalar=True, expect_text=True):
                dashboard[key] = getattr(result, key)

        core = dashboard.get("core_conclusion")
        if not isinstance(core, dict):
            core = {}
            dashboard["core_conclusion"] = core
        if self._is_agent_field_missing(core.get("one_sentence"), scalar=True):
            core["one_sentence"] = result.analysis_summary or self._summary_fallback_from_result(
                result,
                report_language,
            ) or (
                "Analysis pending" if report_language == "en"
                else "분석 보완 예정" if report_language == "ko"
                else "分析待补充"
            )

        intelligence = dashboard.get("intelligence")
        if not isinstance(intelligence, dict):
            intelligence = {}
            dashboard["intelligence"] = intelligence
        risk_alerts = intelligence.get("risk_alerts")
        if (
            "risk_alerts" not in intelligence
            or self._is_agent_field_missing(risk_alerts)
            or not isinstance(risk_alerts, list)
        ):
            risk_factors = getattr(trend_result, "risk_factors", None) or []
            intelligence["risk_alerts"] = list(risk_factors)

        if result.decision_type in ("buy", "hold"):
            battle = dashboard.get("battle_plan")
            if not isinstance(battle, dict):
                battle = {}
                dashboard["battle_plan"] = battle
            sniper_points = battle.get("sniper_points")
            if not isinstance(sniper_points, dict):
                sniper_points = {}
                battle["sniper_points"] = sniper_points
            if self._is_agent_field_missing(sniper_points.get("stop_loss"), scalar=True):
                sniper_points["stop_loss"] = self._stop_loss_fallback_from_trend(
                    trend_result,
                    report_language,
                )

    @staticmethod
    def _stop_loss_fallback_from_trend(
        trend_result: Optional[TrendAnalysisResult],
        report_language: str,
    ) -> Any:
        levels = getattr(trend_result, "support_levels", None) if trend_result else None
        if levels:
            return levels[0]
        return get_placeholder_text(report_language)

    @staticmethod
    def _apply_trend_fallback(
        result: AnalysisResult,
        trend_result: Optional[TrendAnalysisResult],
        report_language: str,
    ) -> None:
        if trend_result is None:
            result.sentiment_score = 50
            result.operation_advice = localize_operation_advice("观望", report_language)
            return

        score = getattr(trend_result, "signal_score", None)
        try:
            numeric_score = int(score)
        except (TypeError, ValueError):
            numeric_score = 50
        result.sentiment_score = numeric_score if numeric_score > 0 else 50

        trend_label = StockAnalysisPipeline._trend_label_fallback(trend_result, report_language)
        if trend_label:
            result.trend_prediction = trend_label

        buy_signal = getattr(trend_result, "buy_signal", None)
        signal_label = StockAnalysisPipeline._trend_signal_fallback(
            trend_result,
            report_language,
        )
        if signal_label:
            result.operation_advice = signal_label
        else:
            result.operation_advice = localize_operation_advice("观望", report_language)

        from src.agent.protocols import normalize_decision_signal

        signal_name = getattr(buy_signal, "name", "").lower()
        signal_to_decision = {
            "strong_buy": "buy",
            "buy": "buy",
            "hold": "hold",
            "wait": "hold",
            "sell": "sell",
            "strong_sell": "sell",
        }
        result.decision_type = signal_to_decision.get(signal_name, result.decision_type or "hold")
        result.decision_type = normalize_decision_signal(result.decision_type)
        result.data_sources = f"{result.data_sources},trend:fallback" if result.data_sources else "trend:fallback"

    @staticmethod
    def _is_placeholder_stock_name(name: str, code: str) -> bool:
        """Return True when the stock name is missing or placeholder-like."""
        if not name:
            return True
        normalized = str(name).strip()
        if not normalized:
            return True
        if normalized == code:
            return True
        if normalized.startswith("股票"):
            return True
        if "Unknown" in normalized:
            return True
        return False

    @staticmethod
    def _safe_int(value: Any, default: int = 50) -> int:
        """Safely convert a value to an integer."""
        if value is None:
            return default
        if isinstance(value, int):
            return value
        if isinstance(value, float):
            return int(value)
        if isinstance(value, str):
            import re
            match = re.search(r'-?\d+', value)
            if match:
                return int(match.group())
        return default
    
    def _describe_volume_ratio(self, volume_ratio: float) -> str:
        """
        Volume ratio description
        
        Volume ratio = current volume / average volume over the past 5 days
        """
        if volume_ratio < 0.5:
            return "极度萎缩"
        elif volume_ratio < 0.8:
            return "明显萎缩"
        elif volume_ratio < 1.2:
            return "正常"
        elif volume_ratio < 2.0:
            return "温和放量"
        elif volume_ratio < 3.0:
            return "明显放量"
        else:
            return "巨量"

    @staticmethod
    def _compute_ma_status(close: float, ma5: float, ma10: float, ma20: float) -> str:
        """
        Compute MA alignment status from price and MA values.
        Logic mirrors storage._analyze_ma_status (Issue #234).
        """
        close = close or 0
        ma5 = ma5 or 0
        ma10 = ma10 or 0
        ma20 = ma20 or 0
        if close > ma5 > ma10 > ma20 > 0:
            return "多头排列 📈"
        elif close < ma5 < ma10 < ma20 and ma20 > 0:
            return "空头排列 📉"
        elif close > ma5 and ma5 > ma10:
            return "短期向好 🔼"
        elif close < ma5 and ma5 < ma10:
            return "短期走弱 🔽"
        else:
            return "震荡整理 ↔️"

    def _augment_historical_with_realtime(
        self,
        df: pd.DataFrame,
        realtime_quote: Any,
        code: str,
        market: Optional[str] = None,
    ) -> pd.DataFrame:
        """
        Complete the historical OHLCV with today's real-time quote, for intraday MA calculation.
        Issue #234: technical indicators use the live price instead of carrying over yesterday's close.
        """
        if df is None or df.empty or 'close' not in df.columns:
            return df
        if realtime_quote is None:
            return df
        price = getattr(realtime_quote, 'price', None)
        if price is None or not (isinstance(price, (int, float)) and price > 0):
            return df

        # The real-time completion can be skipped on non-trading days; fail open on error.
        enable_realtime_tech = getattr(
            self.config, 'enable_realtime_technical_indicators', True
        )
        if not enable_realtime_tech:
            return df
        if market is None:
            market = get_market_for_stock(code)
        market_today = get_market_now(market).date()
        if market and not is_market_open(market, market_today):
            return df

        last_val = df['date'].max()
        last_date = (
            last_val.date() if hasattr(last_val, 'date') else
            (last_val if isinstance(last_val, date) else pd.Timestamp(last_val).date())
        )
        yesterday_close = float(df.iloc[-1]['close']) if len(df) > 0 else price
        open_p = getattr(realtime_quote, 'open_price', None) or getattr(
            realtime_quote, 'pre_close', None
        ) or yesterday_close
        high_p = getattr(realtime_quote, 'high', None) or price
        low_p = getattr(realtime_quote, 'low', None) or price
        vol = getattr(realtime_quote, 'volume', None) or 0
        amt = getattr(realtime_quote, 'amount', None)
        pct = getattr(realtime_quote, 'change_pct', None)

        if last_date >= market_today:
            # Update the last row with the live close; copy first so the caller's df is not mutated.
            df = df.copy()
            idx = df.index[-1]
            df.loc[idx, 'close'] = price
            if open_p is not None:
                df.loc[idx, 'open'] = open_p
            if high_p is not None:
                df.loc[idx, 'high'] = high_p
            if low_p is not None:
                df.loc[idx, 'low'] = low_p
            if vol:
                df.loc[idx, 'volume'] = vol
            if amt is not None:
                df.loc[idx, 'amount'] = amt
            if pct is not None:
                df.loc[idx, 'pct_chg'] = pct
        else:
            # Append a synthetic real-time K-line row for today.
            new_row = {
                'code': code,
                'date': market_today,
                'open': open_p,
                'high': high_p,
                'low': low_p,
                'close': price,
                'volume': vol,
                'amount': amt if amt is not None else 0,
                'pct_chg': pct if pct is not None else 0,
            }
            new_df = pd.DataFrame([new_row])
            df = pd.concat([df, new_df], ignore_index=True)
        return df

    def _build_context_snapshot(
        self,
        enhanced_context: Dict[str, Any],
        news_content: Optional[str],
        realtime_quote: Any,
        chip_data: Optional[ChipDistribution],
        news_result_count: Optional[int] = None,
        analysis_context_pack_overview: Optional[Dict[str, Any]] = None,
        market_phase_summary: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Build the analysis context snapshot
        """
        snapshot = {
            "enhanced_context": self._without_runtime_prompt_context(enhanced_context),
            "news_content": news_content,
            "realtime_quote_raw": self._safe_to_dict(realtime_quote),
            "chip_distribution_raw": self._safe_to_dict(chip_data),
        }
        market_structure_context = enhanced_context.get("market_structure_context")
        if isinstance(market_structure_context, dict):
            snapshot["market_structure_context"] = market_structure_context
        if news_content is not None:
            snapshot["news_retrieval_content"] = news_content
        if news_result_count is not None:
            snapshot["news_result_count"] = news_result_count
        if analysis_context_pack_overview is not None:
            snapshot["analysis_context_pack_overview"] = analysis_context_pack_overview
        if market_phase_summary is not None:
            snapshot[MARKET_PHASE_SUMMARY_KEY] = market_phase_summary
        diagnostic_snapshot = current_diagnostic_snapshot()
        if diagnostic_snapshot is not None:
            snapshot["diagnostics"] = diagnostic_snapshot
        if self.analysis_skills is not None:
            snapshot["skills"] = list(self.analysis_skills)
        return snapshot

    def _persist_skill_opinion_samples_after_history_save(
        self,
        *,
        runtime_facts: Any,
        analysis_history_id: int,
        stock_code: str,
        analysis_context_pack_overview: Optional[Dict[str, Any]],
    ) -> None:
        """Best-effort persistence for valid individual skill opinions."""
        opinions = getattr(runtime_facts, "skill_opinions", ()) if runtime_facts else ()
        if not opinions:
            return

        quality_level = None
        if isinstance(analysis_context_pack_overview, dict):
            quality = analysis_context_pack_overview.get("data_quality")
            if isinstance(quality, dict):
                quality_level = quality.get("level")

        try:
            from src.services.skill_opinion_sample_service import SkillOpinionSampleService

            SkillOpinionSampleService(db_manager=self.db).persist(
                analysis_history_id=analysis_history_id,
                stock_code=stock_code,
                opinions=opinions,
                data_quality_level=quality_level,
            )
        except Exception as exc:
            logger.warning(
                "Skill opinion sample persistence skipped after history save: "
                "stock_code=%s error_type=%s",
                stock_code,
                type(exc).__name__,
            )

    def _extract_decision_signal_after_history_save(
        self,
        *,
        result: AnalysisResult,
        query_id: str,
        source_report_id: int,
        report_type: str,
        context_snapshot: Dict[str, Any],
        portfolio_context: Optional[Dict[str, Any]] = None,
        analysis_target: Optional[AnalysisTarget] = None,
    ) -> None:
        """Best-effort DecisionSignal extraction after analysis history is saved."""

        assert (
            isinstance(source_report_id, int)
            and not isinstance(source_report_id, bool)
            and source_report_id > 0
        )

        try:
            diagnostic_context = get_current_diagnostic_context()
            trace_id = (
                getattr(diagnostic_context, "trace_id", None)
                or getattr(self, "trace_id", None)
                or query_id
            )
            # Index targets: the signal is persisted with market=cn (the canonical code and display name travel on the result)
            market_override = (
                "cn"
                if analysis_target is not None
                and analysis_target.asset_type == ParseStatus.INDEX
                else None
            )
            signal_result = extract_and_persist_from_analysis_result(
                result,
                context_snapshot=context_snapshot,
                source_report_id=source_report_id,
                trace_id=str(trace_id),
                query_source=getattr(self, "query_source", None) or "system",
                report_type=report_type,
                portfolio_context=portfolio_context,
                profile_source="auto_default",
                market_override=market_override,
            )
            if isinstance(signal_result, dict):
                summary = summarize_decision_signal(signal_result.get("item"))
                if summary:
                    setattr(result, "decision_signal_summary", summary)
        except Exception as exc:
            logger.warning(
                "Decision signal extraction skipped after history save: query_id=%s stock_code=%s error=%s",
                query_id,
                getattr(result, "code", None),
                exc,
                exc_info=True,
            )

    @staticmethod
    def _build_notification_run_snapshot(
        *,
        channel: str,
        status: str,
        success: bool,
        attempts: int = 1,
        error_message: Optional[Any] = None,
    ) -> Dict[str, Any]:
        payload = {
            "channel": channel,
            "status": status,
            "success": success,
            "attempts": attempts,
            "created_at": datetime.now().isoformat(),
        }
        sanitized_error = sanitize_diagnostic_text(error_message)
        if sanitized_error:
            payload["error_message_sanitized"] = sanitized_error
        return payload

    def _refresh_saved_diagnostic_snapshot(
        self,
        *,
        result: Optional[AnalysisResult] = None,
        results: Optional[List[AnalysisResult]] = None,
        fallback_code: Optional[str] = None,
        notification_run: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Patch persisted history diagnostics with notification outcomes."""
        if not getattr(self, "save_context_snapshot", True):
            return

        db = getattr(self, "db", None)
        updater = getattr(db, "update_analysis_history_diagnostics", None)
        if not callable(updater):
            return

        diagnostic_snapshot = current_diagnostic_snapshot()
        if diagnostic_snapshot is not None:
            query_id = (
                diagnostic_snapshot.get("query_id")
                or getattr(result, "query_id", None)
                or getattr(self, "query_id", None)
            )
            code = (
                getattr(result, "code", None)
                or fallback_code
                or diagnostic_snapshot.get("stock_code")
            )
            if not query_id:
                return
            try:
                updater(query_id=query_id, code=code, diagnostics=diagnostic_snapshot)
            except Exception as exc:
                logger.warning("Failed to write back run diagnostics snapshot (fail-open): %s", exc)
            return

        if notification_run is None:
            return

        target_results = list(results or ([] if result is None else [result]))
        for item in target_results:
            query_id = getattr(item, "query_id", None) or getattr(self, "query_id", None)
            if not query_id:
                continue
            code = getattr(item, "code", None) or fallback_code
            try:
                updater(
                    query_id=query_id,
                    code=code,
                    notification_runs=[notification_run],
                )
            except Exception as exc:
                logger.warning("Failed to write back notification diagnostics snapshot (fail-open): %s", exc)

    def _load_persisted_intelligence_context(
        self,
        *,
        code: str,
        stock_name: str,
        market: str,
        limit: int = 6,
    ) -> Optional[str]:
        """Load locally persisted intelligence as fail-open evidence context."""
        try:
            service = IntelligenceService(config=self.config)
            service.refresh_auto_sources()
            days = max(1, int(self.config.get_effective_news_window_days() or 1))
            collected: list[Dict[str, Any]] = []
            seen_urls: set[str] = set()
            symbol_filters = [
                {"scope_type": "symbol", "scope_value": scope_value, "market": market}
                for scope_value in _symbol_scope_lookup_values(code, market)
            ]
            for filters in symbol_filters + [{"scope_type": "market", "market": market}]:
                payload = service.list_items(published_days=days, page=1, page_size=limit, **filters)
                for item in payload.get("items", []):
                    if not isinstance(item, dict):
                        continue
                    url = str(item.get("url") or "")
                    if url in seen_urls:
                        continue
                    seen_urls.add(url)
                    collected.append(item)
                    if len(collected) >= limit:
                        break
                if len(collected) >= limit:
                    break
            if not collected:
                return None
            lines = [f"## 本地资讯证据池（{stock_name}/{code}）"]
            for idx, item in enumerate(collected[:limit], 1):
                title = str(item.get("title") or "未命名资讯").strip()
                summary = str(item.get("summary") or "").strip()
                source = str(item.get("source") or item.get("source_name") or "local-intel").strip()
                published = str(item.get("published_at") or "").strip()
                url = str(item.get("url") or "").strip()
                meta = " / ".join(part for part in (source, published) if part)
                lines.append(f"{idx}. {title}" + (f"（{meta}）" if meta else ""))
                if summary:
                    lines.append(f"   摘要：{summary[:220]}")
                if url and not url.startswith("no-url:intel:"):
                    lines.append(f"   来源：{url}")
            return "\n".join(lines)
        except Exception as exc:
            logger.debug("Failed to read local news evidence (fail-open): %s", exc)
            return None

    def _build_legacy_analysis_artifacts(
        self,
        *,
        code: str,
        stock_name: str,
        market: str,
        phase: Optional[Dict[str, Any]],
        context: Dict[str, Any],
        enhanced_context: Dict[str, Any],
        realtime_quote: Any,
        trend_result: Optional[TrendAnalysisResult],
        chip_data: Optional[ChipDistribution],
        fundamental_context: Optional[Dict[str, Any]],
        news_context: Optional[str],
        news_result_count: Optional[int],
        query_id: str,
        portfolio_context: Optional[Dict[str, Any]] = None,
    ) -> PipelineAnalysisArtifacts:
        return PipelineAnalysisArtifacts(
            code=code,
            stock_name=stock_name,
            market=market,
            phase=phase,
            base_context=context,
            enhanced_context=enhanced_context,
            realtime_quote=realtime_quote,
            trend_result=trend_result,
            chip_data=chip_data,
            fundamental_context=fundamental_context,
            news_context=news_context,
            news_result_count=news_result_count,
            metadata={
                "query_id": query_id,
                "trigger_source": self.query_source,
            },
            portfolio_context=dict(portfolio_context) if isinstance(portfolio_context, dict) else None,
        )

    def _build_agent_analysis_artifacts(
        self,
        *,
        code: str,
        stock_name: str,
        market: str,
        phase: Optional[Dict[str, Any]],
        initial_context: Dict[str, Any],
        fundamental_context: Optional[Dict[str, Any]],
        query_id: str,
        base_context: Optional[Dict[str, Any]] = None,
        portfolio_context: Optional[Dict[str, Any]] = None,
    ) -> PipelineAnalysisArtifacts:
        context_candidate = base_context
        if not isinstance(context_candidate, dict):
            context_candidate = initial_context.get("analysis_context")
        if isinstance(context_candidate, dict) and context_candidate:
            daily_context = dict(context_candidate)
            daily_context.setdefault("code", code)
            if stock_name:
                daily_context.setdefault("stock_name", stock_name)
        else:
            daily_context = {
                "code": code,
                "stock_name": stock_name,
                "data_missing": True,
                "today": {},
                "yesterday": {},
            }

        return PipelineAnalysisArtifacts(
            code=code,
            stock_name=stock_name,
            market=market,
            phase=phase,
            base_context=daily_context,
            enhanced_context={},
            realtime_quote=initial_context.get("realtime_quote"),
            trend_result=initial_context.get("trend_result"),
            chip_data=initial_context.get("chip_distribution"),
            fundamental_context=fundamental_context,
            news_context=initial_context.get("news_context"),
            news_result_count=None,
            metadata={
                "query_id": query_id,
                "trigger_source": self.query_source,
            },
            portfolio_context=dict(portfolio_context) if isinstance(portfolio_context, dict) else None,
        )

    def _build_analysis_context_pack_outputs(
        self,
        artifacts: PipelineAnalysisArtifacts,
        *,
        report_language: str,
        code: str,
        query_id: str,
    ) -> Tuple[str, Optional[Dict[str, Any]]]:
        try:
            pack = AnalysisContextBuilder.build(artifacts)
            summary = format_analysis_context_pack_prompt_section(
                pack,
                report_language=report_language,
            )
            overview = render_analysis_context_pack_overview(
                pack,
                report_language=report_language,
            )
            return summary, overview
        except Exception as exc:
            logger.warning(
                "AnalysisContextPack output generation failed for %s query_id=%s: %s",
                code,
                query_id,
                exc,
            )
            return "", None

    @staticmethod
    def _without_runtime_prompt_context(context: Dict[str, Any]) -> Dict[str, Any]:
        """
        Return a shallow copy without runtime-only prompt context.

        Market phase and AnalysisContextPack summaries are prompt inputs only.
        P4 stores only the separately rendered public overview at snapshot top level.
        """
        sanitized = dict(context)
        sanitized.pop("market_phase_context", None)
        sanitized.pop("portfolio_context", None)
        sanitized.pop("analysis_context_pack", None)
        sanitized.pop("analysis_context_pack_summary", None)
        sanitized.pop("daily_market_context_summary", None)
        enhanced_context = sanitized.get("enhanced_context")
        if isinstance(enhanced_context, dict):
            enhanced_context = dict(enhanced_context)
            enhanced_context.pop("daily_market_context_summary", None)
            sanitized["enhanced_context"] = enhanced_context
        return sanitized

    _without_market_phase_context = _without_runtime_prompt_context

    @staticmethod
    def _resolve_resume_target_date(
        code: str, current_time: Optional[datetime] = None,
        analysis_target: Optional[AnalysisTarget] = None,
    ) -> date:
        """
        Resolve the trading date used by checkpoint/resume checks.

        For index targets the market is derived from the structured target
        (``market=cn``) rather than from ``get_market_for_stock`` on the
        canonical code, which would return ``None`` for CSI indices.
        """
        if analysis_target is not None and analysis_target.asset_type == ParseStatus.INDEX:
            market = "cn"
        else:
            market = get_market_for_stock(normalize_stock_code(code))
        return get_effective_trading_date(market, current_time=current_time)

    @staticmethod
    def _safe_to_dict(value: Any) -> Optional[Dict[str, Any]]:
        """
        Safely convert to a dictionary
        """
        if value is None:
            return None
        if hasattr(value, "to_dict"):
            try:
                return value.to_dict()
            except Exception:
                return None
        if hasattr(value, "__dict__"):
            try:
                return dict(value.__dict__)
            except Exception:
                return None
        return None

    def _resolve_query_source(self, query_source: Optional[str] = None) -> str:
        """
        Resolve the request source.

        Priority (highest first):
        1. An explicitly passed query_source: used first when the caller specifies one, allowing the inferred result to be overridden and leaving room for a future non-bot source_message
        2. Infer "bot" when source_message is present: by current convention this means a bot conversation context
        3. Infer "web" when query_id is present: web-triggered requests carry a query_id
        4. Default to "system": scheduled jobs, the CLI and anything else without the above context

        Args:
            query_source: the source explicitly given by the caller, such as "bot" / "web" / "cli" / "system"

        Returns:
            The normalized source identifier, such as "bot" / "web" / "cli" / "system"
        """
        if query_source:
            return query_source
        if getattr(self, "source_message", None):
            return "bot"
        if getattr(self, "query_id", None):
            return "web"
        return "system"

    def _build_query_context(self, query_id: Optional[str] = None) -> Dict[str, str]:
        """
        Build the user query correlation information
        """
        effective_query_id = query_id or self.query_id or ""

        context: Dict[str, str] = {
            "query_id": effective_query_id,
            "query_source": self.query_source or "",
        }

        if self.source_message:
            context.update({
                "requester_platform": self.source_message.platform or "",
                "requester_user_id": self.source_message.user_id or "",
                "requester_user_name": self.source_message.user_name or "",
                "requester_chat_id": self.source_message.chat_id or "",
                "requester_message_id": self.source_message.message_id or "",
                "requester_query": self.source_message.content or "",
            })

        return context
    
    def process_single_stock(
        self,
        code: str,
        skip_analysis: bool = False,
        single_stock_notify: bool = False,
        report_type: ReportType = ReportType.SIMPLE,
        analysis_query_id: Optional[str] = None,
        current_time: Optional[datetime] = None,
        analysis_target: Optional[AnalysisTarget] = None,
    ) -> Optional[AnalysisResult]:
        """
        Run the complete flow for a single stock

        This covers:
        1. Fetching the data
        2. Persisting the data
        3. Running the AI analysis
        4. Single-stock push (optional, #55)

        This method is invoked from the thread pool, so it must handle exceptions carefully

        Args:
            analysis_query_id: the correlation id for this query chain
            code: the stock code
            skip_analysis: whether to skip the AI analysis
            single_stock_notify: whether to enable single-stock push mode (push as soon as each stock finishes)
            report_type: the report type enum (read from configuration, Issue #119)
            current_time: the reference time frozen for this run, so the resume target trading day is judged consistently
            analysis_target: the structured analysis target (an index target drives market=cn and the capability matrix)

        Returns:
            An AnalysisResult, or None
        """
        logger.info(f"========== Processing {code} ==========")

        from src.services.history_loader import set_frozen_target_date, reset_frozen_target_date
        frozen_td = self._resolve_resume_target_date(
            code, current_time=current_time, analysis_target=analysis_target
        )
        token = set_frozen_target_date(frozen_td)
        effective_query_id = analysis_query_id or getattr(self, "query_id", None) or uuid.uuid4().hex
        effective_trace_id = getattr(self, "trace_id", None) or effective_query_id
        diag_token = None
        if get_current_diagnostic_context() is None:
            diag_token = activate_run_diagnostic_context(
                trace_id=effective_trace_id,
                query_id=effective_query_id,
                stock_code=code,
                trigger_source=getattr(self, "query_source", None),
            )
        try:
            self._emit_progress(12, f"{code}: preparing the analysis task")
            # Step 1: fetch and persist the data
            success, error = self.fetch_and_save_stock_data(
                code, current_time=current_time, analysis_target=analysis_target
            )
            
            if not success:
                logger.warning(f"[{code}] data fetch failed: {error}")
                # Even if the fetch failed, still try to analyze with whatever data exists
            else:
                self._emit_progress(16, f"{code}: market data ready")
            
            # Step 2: AI analysis
            if skip_analysis:
                logger.info(f"[{code}] skipping AI analysis (dry-run mode)")
                return None
            
            analyze_kwargs = {"query_id": effective_query_id}
            if current_time is not None:
                analyze_kwargs["current_time"] = current_time
            if analysis_target is not None:
                analyze_kwargs["analysis_target"] = analysis_target
            result = self.analyze_stock(code, report_type, **analyze_kwargs)
            
            if result and result.success:
                logger.info(
                    f"[{code}] analysis completed: {result.operation_advice}, "
                    f"score {result.sentiment_score}"
                )
                
                # Single-stock push mode (#55): push as soon as each stock finishes
                if single_stock_notify:
                    self._send_single_stock_notification(
                        result,
                        report_type=report_type,
                        fallback_code=code,
                    )
            elif result:
                logger.warning(
                    f"[{code}] analysis did not succeed: {result.error_message or 'unknown error'}"
                )
            
            return result
            
        except Exception as e:
            # Catch everything, so one failing stock does not affect the whole run
            logger.exception(f"[{code}] unexpected error during processing: {e}")
            return None
        finally:
            reset_run_diagnostic_context(diag_token)
            reset_frozen_target_date(token)
    
    def run(
        self,
        stock_codes: Optional[List[str]] = None,
        dry_run: bool = False,
        send_notification: bool = True,
        merge_notification: bool = False,
        current_time: Optional[datetime] = None,
        analysis_targets: Optional[List[AnalysisTarget]] = None,
    ) -> List[AnalysisResult]:
        """
        Run the complete analysis flow

        Flow:
        1. Build the list of stocks to analyze
        2. Process them concurrently with a thread pool
        3. Collect the analysis results
        4. Send notifications

        Args:
            stock_codes: the list of stock codes (optional; defaults to the configured watchlist)
            dry_run: whether to only fetch data without analyzing
            send_notification: whether to send push notifications
            merge_notification: whether to merge the push (skip sending here; the main layer combines individual stocks and the broad market and sends once, Issue #190)
            current_time: the reference time frozen for this run; generated inside run when empty
            analysis_targets: structured analysis targets aligned with stock_codes (optional; an index target drives market=cn and the capability matrix)

        Returns:
            The list of analysis results
        """
        start_time = time.time()
        
        # Use the stock list from the configuration
        if stock_codes is None:
            self.config.refresh_stock_list()
            stock_codes = self.config.stock_list
        
        if not stock_codes:
            logger.error("No watchlist configured; set STOCK_LIST in the .env file")
            return []
        
        # Filtering unsupported targets and de-duplicating by canonical identity both happen
        # before any prefetch/provider call; legacy entry points without a structured target keep their original behaviour.
        if analysis_targets is not None:
            if len(analysis_targets) != len(stock_codes):
                raise ValueError("analysis_targets must align with stock_codes")
            supported_codes = []
            supported_targets = []
            seen_identities = set()
            for code, target in zip(stock_codes, analysis_targets):
                if target is not None and target.asset_type == ParseStatus.UNSUPPORTED:
                    logger.warning(
                        "Skipping unsupported target %r (%s) without any network request",
                        code,
                        target.unsupported_reason or "unsupported",
                    )
                    continue
                identity = (
                    target.canonical_id
                    if target is not None and target.asset_type == ParseStatus.INDEX
                    else code
                )
                if identity in seen_identities:
                    logger.info("Skipping duplicate analysis target %s (canonical_id=%s)", code, identity)
                    continue
                seen_identities.add(identity)
                supported_codes.append(code)
                supported_targets.append(target)
            stock_codes = supported_codes
            analysis_targets = supported_targets
            if not stock_codes:
                logger.warning("Every target in the batch is unsupported; nothing to run")
                return []

        logger.info(f"===== Analyzing {len(stock_codes)} stock(s) =====")
        logger.info(f"Stock list: {', '.join(stock_codes)}")
        logger.info(f"Concurrency: {self.max_workers}, mode: {'data fetch only' if dry_run else 'full analysis'}")

        # Freeze a single reference time for this run, so a batch does not straddle a market close boundary and end up using different target trading days.
        resume_reference_time = current_time or datetime.now(timezone.utc)
        
        # === Batch-prefetch real-time quotes (optimization: avoid a full pull per stock) ===
        # Only prefetch when there are at least 5 stocks; for a handful, querying one by one is faster
        if len(stock_codes) >= 5:
            daily_prefetch_count = self.fetcher_manager.prefetch_daily_klines(stock_codes, days=30)
            if daily_prefetch_count > 0:
                logger.info(
                    "[prefetch] component=daily_kline_prefetch action=complete "
                    "provider=TickFlowFetcher cached=%d stock_count=%d",
                    daily_prefetch_count,
                    len(stock_codes),
                )

            prefetch_count = self.fetcher_manager.prefetch_realtime_quotes(stock_codes)
            if prefetch_count > 0:
                logger.info(f"Batch prefetch enabled: whole-market data fetched once and cached for {len(stock_codes)} stock(s)")

        # Issue #455: prefetch stock names, so concurrent analysis does not display a placeholder name
        # dry_run only pulls data and needs no name prefetch, avoiding extra network overhead
        if not dry_run:
            self.fetcher_manager.prefetch_stock_names(stock_codes, use_bulk=False)

        # Single-stock push mode (#55): read from configuration
        single_stock_notify = getattr(self.config, 'single_stock_notify', False)
        # Issue #119: read the report type from configuration
        report_type_str = getattr(self.config, 'report_type', 'simple').lower()
        if report_type_str == 'brief':
            report_type = ReportType.BRIEF
        elif report_type_str == 'full':
            report_type = ReportType.FULL
        else:
            report_type = ReportType.SIMPLE
        # Issue #128: read the analysis interval from configuration
        analysis_delay = getattr(self.config, 'analysis_delay', 0)

        if single_stock_notify:
            logger.info(
                "Single-stock push mode enabled: analysis still runs concurrently, notifications are sent serially as results are collected (report type: %s)",
                report_type_str,
            )
        
        results: List[AnalysisResult] = []
        
        # Process concurrently with a thread pool
        # Note: max_workers is kept low (3 by default) to avoid tripping anti-scraping defenses
        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            # Submit the tasks
            future_to_code = {}
            for idx, code in enumerate(stock_codes):
                target = (
                    analysis_targets[idx]
                    if analysis_targets is not None and idx < len(analysis_targets)
                    else None
                )
                submit_kwargs = {
                    "skip_analysis": dry_run,
                    "single_stock_notify": False,
                    "report_type": report_type,
                    "analysis_query_id": uuid.uuid4().hex,
                    "current_time": resume_reference_time,
                }
                if target is not None:
                    submit_kwargs["analysis_target"] = target
                future = executor.submit(
                    self.process_single_stock,
                    code,
                    **submit_kwargs,
                )
                future_to_code[future] = code
            
            # Collect the results
            for idx, future in enumerate(as_completed(future_to_code)):
                code = future_to_code[future]
                try:
                    result = future.result()
                    if result and result.success:
                        results.append(result)
                        if single_stock_notify and send_notification and not dry_run:
                            self._send_single_stock_notification(
                                result,
                                report_type=report_type,
                                fallback_code=code,
                            )
                    elif result and not result.success:
                        logger.warning(
                            f"[{code}] analysis result marked as failed and excluded from the summary: "
                            f"{result.error_message or 'unknown reason'}"
                        )

                    # Issue #128: analysis interval - add a delay between individual-stock and broad-market analysis
                    if idx < len(stock_codes) - 1 and analysis_delay > 0:
                        # Note: this sleep happens in the main thread's future-collection loop and
                        # does not stop thread-pool tasks from issuing network requests concurrently.
                        # Its effect on the concurrent request peak is therefore limited; the real peak is governed by max_workers.
                        # The behaviour is kept as is (the requirement is not to change the logic).
                        logger.debug(f"Waiting {analysis_delay} s before the next stock...")
                        time.sleep(analysis_delay)

                except Exception as e:
                    logger.error(f"[{code}] task failed: {e}")
        
        # Statistics
        elapsed_time = time.time() - start_time
        
        # In dry-run mode, a successful data fetch counts as success
        if dry_run:
            # Check which stocks already have data for the latest reusable trading day
            success_count = 0
            for idx, code in enumerate(stock_codes):
                target = (
                    analysis_targets[idx]
                    if analysis_targets is not None and idx < len(analysis_targets)
                    else None
                )
                if self.db.has_today_data(
                    code,
                    self._resolve_resume_target_date(
                        code,
                        current_time=resume_reference_time,
                        analysis_target=target,
                    ),
                ):
                    success_count += 1
            fail_count = len(stock_codes) - success_count
        else:
            success_count = len(results)
            fail_count = len(stock_codes) - success_count
        
        logger.info("===== Analysis finished =====")
        logger.info(f"Succeeded: {success_count}, failed: {fail_count}, elapsed: {elapsed_time:.2f} s")
        
        # Save the report to a local file (always, regardless of whether a notification is pushed)
        if results and not dry_run:
            self._save_local_report(results, report_type)

        # Send the notification (in single-stock push mode the summary push is skipped to avoid duplicates)
        if results and send_notification and not dry_run:
            if single_stock_notify:
                # Single-stock push mode: only save the summary report, do not push it again
                logger.info("Single-stock push mode: skipping the summary push, saving the report locally only")
                self._send_notifications(results, report_type, skip_push=True)
            elif merge_notification:
                # Merge mode (Issue #190): save only; the main layer combines individual stocks and the broad market and sends once
                logger.info("Merged push mode: skipping this push; everything is sent together after stocks and the market review")
                self._send_notifications(results, report_type, skip_push=True)
            else:
                self._send_notifications(results, report_type)
        
        return results

    def _send_single_stock_notification(
        self,
        result: AnalysisResult,
        report_type: ReportType = ReportType.SIMPLE,
        fallback_code: Optional[str] = None,
    ) -> None:
        """Send a single-stock notification, shared by the direct single-stock entry point and serial batch pushing."""
        stock_code = getattr(result, "code", None) or fallback_code or "unknown"
        notify_lock = getattr(self, "_single_stock_notify_lock", None)
        if notify_lock is None:
            with _SINGLE_STOCK_NOTIFY_LOCK_INIT_GUARD:
                notify_lock = getattr(self, "_single_stock_notify_lock", None)
                if notify_lock is None:
                    notify_lock = threading.Lock()
                    setattr(self, "_single_stock_notify_lock", notify_lock)

        with notify_lock:
            try:
                if report_type == ReportType.FULL:
                    report_content = self.notifier.generate_dashboard_report([result])
                    logger.info(f"[{stock_code}] using the full report format")
                elif report_type == ReportType.BRIEF:
                    report_content = self.notifier.generate_brief_report([result])
                    logger.info(f"[{stock_code}] using the brief report format")
                else:
                    report_content = self.notifier.generate_single_stock_report(result)
                    logger.info(f"[{stock_code}] using the simple report format")

                save_report = getattr(self.notifier, "save_report_to_file", None)
                if callable(save_report):
                    try:
                        date_str = datetime.now().strftime('%Y%m%d')
                        filename = f"report_{date_str}_{stock_code}.md"
                        filepath = save_report(report_content, filename=filename)
                        logger.info(f"[{stock_code}] single-stock report saved locally: {filepath}")
                    except Exception as exc:
                        logger.warning(f"[{stock_code}] failed to save single-stock report: {exc}")

                if not self.notifier.is_available():
                    notification_run = self._build_notification_run_snapshot(
                        channel="report",
                        status="not_configured",
                        success=False,
                        attempts=0,
                    )
                    record_notification_run(
                        channel="report",
                        status="not_configured",
                        success=False,
                        attempts=0,
                    )
                    self._refresh_saved_diagnostic_snapshot(
                        result=result,
                        fallback_code=fallback_code,
                        notification_run=notification_run,
                    )
                    return

                send_kwargs: Dict[str, Any] = {
                    "email_stock_codes": [stock_code],
                    "route_type": "report",
                    "severity": "info",
                    "dedup_key": f"report:single:{stock_code}:{report_type.value}",
                    "cooldown_key": f"report:single:{stock_code}:{report_type.value}",
                }
                if _supports_explicit_keyword(self.notifier.send, "structured_payload"):
                    send_kwargs["structured_payload"] = _share_image_payload(result)
                sent = self.notifier.send(report_content, **send_kwargs)
                notification_run = self._build_notification_run_snapshot(
                    channel="report",
                    status="success" if sent else "failed",
                    success=sent,
                )
                record_notification_run(
                    channel="report",
                    status="success" if sent else "failed",
                    success=sent,
                )
                self._refresh_saved_diagnostic_snapshot(
                    result=result,
                    fallback_code=fallback_code,
                    notification_run=notification_run,
                )
                if sent:
                    logger.info(f"[{stock_code}] single-stock push succeeded")
                else:
                    logger.warning(f"[{stock_code}] single-stock push failed")
            except Exception as e:
                notification_run = self._build_notification_run_snapshot(
                    channel="report",
                    status="failed",
                    success=False,
                    error_message=e,
                )
                record_notification_run(
                    channel="report",
                    status="failed",
                    success=False,
                    error_message=e,
                )
                self._refresh_saved_diagnostic_snapshot(
                    result=result,
                    fallback_code=fallback_code,
                    notification_run=notification_run,
                )
                logger.error(f"[{stock_code}] single-stock push error: {e}")

    def _save_local_report(
        self,
        results: List[AnalysisResult],
        report_type: ReportType = ReportType.SIMPLE,
    ) -> Optional[str]:
        """Save the analysis report to a local file (decoupled from notification pushing)"""
        self._last_local_report_path = None
        self._last_local_report_error = None
        report: Optional[str] = None
        try:
            report = self._generate_aggregate_report(results, report_type)
        except Exception as e:
            self._last_local_report_error = str(e)
            logger.error("Failed to generate local report content: %s", e)
            return None

        try:
            filepath = self.notifier.save_report_to_file(report)
            if filepath:
                filepath = str(filepath)
                self._last_local_report_path = filepath
                logger.info(f"Decision dashboard daily report saved: {filepath}")
                return filepath
            self._last_local_report_error = "notifier returned empty report path"
            logger.error("Failed to save local report: the notification service returned no report path")
        except Exception as e:
            self._last_local_report_error = str(e)
            logger.error(f"Failed to save local report: {e}")

        logger.warning("Falling back to a local filesystem path to save the aggregate report")
        fallback_path = self._fallback_save_report_to_file(report)
        if fallback_path:
            self._last_local_report_path = fallback_path
            self._last_local_report_error = None
            logger.warning("Fallback local report save succeeded: %s", fallback_path)
            return fallback_path
        if self._last_local_report_error is None:
            self._last_local_report_error = "fallback local report save failed"
            return None
        return None

    @staticmethod
    def _default_report_filename() -> str:
        """Build default local report filename (aligned with notifier defaults)."""
        date_str = datetime.now().strftime('%Y%m%d')
        return f"report_{date_str}.md"

    @staticmethod
    def _report_output_dir() -> Path:
        """Default report output directory (kept same as NotificationService behavior)."""
        return Path(__file__).resolve().parents[2] / 'reports'

    @classmethod
    def _fallback_save_report_to_file(
        cls,
        content: str,
        filename: Optional[str] = None,
    ) -> Optional[str]:
        """Persist report content via local filesystem as resilient fallback."""
        try:
            reports_dir = cls._report_output_dir()
            reports_dir.mkdir(parents=True, exist_ok=True)
            filename = filename or cls._default_report_filename()
            filepath = reports_dir / filename
            filepath.write_text(content, encoding='utf-8')
            logger.info("Decision dashboard daily report written via fallback: %s", filepath)
            return str(filepath)
        except Exception as exc:  # pragma: no cover - defensive fallback
            logger.error("Fallback report write failed: %s", exc)
            return None

    def _send_notifications(
        self,
        results: List[AnalysisResult],
        report_type: ReportType = ReportType.SIMPLE,
        skip_push: bool = False,
    ) -> None:
        """
        Send the analysis result notification
        
        Generates the report in decision-dashboard format
        
        Args:
            results: the list of analysis results
            skip_push: whether to skip pushing (save locally only, used by single-stock push mode)
        """
        noise_decision = None
        noise_finalized = False
        try:
            logger.info("Generating the decision dashboard daily report...")
            report = self._generate_aggregate_report(results, report_type)
            
            # Skip the push (single-stock push mode / merge mode: the report was already saved by _save_local_report)
            if skip_push:
                notification_run = self._build_notification_run_snapshot(
                    channel="report",
                    status="skipped",
                    success=False,
                    attempts=0,
                )
                record_notification_run(
                    channel="report",
                    status="skipped",
                    success=False,
                    attempts=0,
                )
                self._refresh_saved_diagnostic_snapshot(
                    results=results,
                    notification_run=notification_run,
                )
                return
            
            # Push the notification
            if self.notifier.is_available():
                channels = self.notifier.get_available_channels()
                channels = self.notifier.get_channels_for_route("report", channels=channels)

                def _send_channel_safely(
                    channel_label: str,
                    send_func: Callable[[], bool],
                ) -> tuple[bool, Optional[Exception]]:
                    try:
                        return bool(send_func()), None
                    except Exception as e:
                        logger.exception(
                            "Notification channel %s failed, continuing with other channels: %s",
                            channel_label,
                            e,
                        )
                        return False, e

                def _record_channel_result(
                    channel_label: str,
                    success: bool,
                    error_message: Optional[Exception] = None,
                    target_results: Optional[List[AnalysisResult]] = None,
                ) -> None:
                    notification_run = self._build_notification_run_snapshot(
                        channel=channel_label,
                        status="success" if success else "failed",
                        success=success,
                        error_message=error_message,
                    )
                    record_notification_run(
                        channel=channel_label,
                        status="success" if success else "failed",
                        success=success,
                        error_message=error_message,
                    )
                    self._refresh_saved_diagnostic_snapshot(
                        results=results if target_results is None else target_results,
                        notification_run=notification_run,
                    )

                send_context = self.notifier.send_to_context(report)
                if send_context:
                    _record_channel_result("__context__", True)

                should_broadcast_static = True
                should_broadcast_static_func = getattr(
                    self.notifier,
                    "should_broadcast_static_channels",
                    None,
                )
                if callable(should_broadcast_static_func):
                    should_broadcast_static = bool(should_broadcast_static_func())
                if not should_broadcast_static:
                    if not send_context:
                        _record_channel_result("__context__", False)
                    if send_context:
                        logger.info("Decision dashboard push succeeded")
                    else:
                        logger.warning("Decision dashboard push failed")
                    logger.info("Interactive reply mode: static notification channels skipped")
                    return

                if channels and hasattr(self.notifier, "evaluate_noise_control"):
                    report_type_key = report_type.value if isinstance(report_type, ReportType) else str(report_type)
                    codes_key = ",".join(
                        sorted(str(getattr(result, "code", "") or "") for result in results)
                    )
                    noise_key = f"report:aggregate:{report_type_key}:{codes_key}"
                    noise_decision = self.notifier.evaluate_noise_control(
                        report,
                        route_type="report",
                        severity="info",
                        dedup_key=noise_key,
                        cooldown_key=noise_key,
                    )
                    if not noise_decision.should_send:
                        notification_run = self._build_notification_run_snapshot(
                            channel="report",
                            status="skipped",
                            success=False,
                            attempts=0,
                        )
                        record_notification_run(
                            channel="report",
                            status="skipped",
                            success=False,
                            attempts=0,
                        )
                        self._refresh_saved_diagnostic_snapshot(
                            results=results,
                            notification_run=notification_run,
                        )
                        logger.info(noise_decision.message)
                        return

                # Issue #455: render Markdown to an image (matching the notification.send logic)
                from src.md2img import markdown_to_image

                channels_needing_image = {
                    ch for ch in channels
                    if ch.value in self.notifier._markdown_to_image_channels
                    and ch not in {NotificationChannel.NTFY, NotificationChannel.GOTIFY}
                }
                single_share_payload = (
                    _share_image_payload(results[0]) if len(results) == 1 else None
                )

                def _get_md2img_hint() -> str:
                    try:
                        engine = getattr(get_config(), "md2img_engine", "wkhtmltoimage")
                    except Exception:
                        engine = "wkhtmltoimage"
                    return (
                        "npm i -g markdown-to-file" if engine == "markdown-to-file"
                        else "wkhtmltopdf (apt install wkhtmltopdf / brew install wkhtmltopdf)"
                    )

                image_bytes = None
                if channels_needing_image:
                    image_kwargs: Dict[str, Any] = {
                        "max_chars": self.notifier._markdown_to_image_max_chars,
                    }
                    if single_share_payload is not None:
                        image_kwargs["structured_payload"] = single_share_payload
                    image_bytes = markdown_to_image(report, **image_kwargs)
                    if image_bytes:
                        logger.info(
                            "Markdown converted to an image; sending the image to %s",
                            [ch.value for ch in channels_needing_image],
                        )
                    else:
                        logger.warning(
                            "Markdown-to-image conversion failed, falling back to text. Check MARKDOWN_TO_IMAGE_CHANNELS and install %s",
                            _get_md2img_hint(),
                        )

                # Send the full report to every channel
                any_channel_success = False
                stock_email_groups = getattr(self.config, 'stock_email_groups', []) or []
                for channel in channels:
                    if channel == NotificationChannel.TELEGRAM:
                        def _send_telegram_report() -> bool:
                            use_image = self.notifier._should_use_image_for_channel(
                                channel, image_bytes
                            )
                            if use_image:
                                return self.notifier._send_telegram_photo(image_bytes)
                            return self.notifier.send_to_telegram(report)

                        channel_success, channel_error = _send_channel_safely(
                            channel.value,
                            _send_telegram_report,
                        )
                        any_channel_success = channel_success or any_channel_success
                        _record_channel_result(
                            channel.value,
                            channel_success,
                            channel_error,
                        )
                    elif channel == NotificationChannel.EMAIL:
                        if stock_email_groups:
                            code_to_emails: Dict[str, Optional[List[str]]] = {}
                            for r in results:
                                if r.code not in code_to_emails:
                                    canonical = normalize_stock_code(r.code)
                                    emails = []
                                    for stocks, emails_list in stock_email_groups:
                                        if canonical in stocks:
                                            emails.extend(emails_list)
                                    code_to_emails[r.code] = list(dict.fromkeys(emails)) if emails else None
                            emails_to_results: Dict[Optional[Tuple], List] = defaultdict(list)
                            for r in results:
                                recs = code_to_emails.get(r.code)
                                key = tuple(recs) if recs else None
                                emails_to_results[key].append(r)
                            for key, group_results in emails_to_results.items():
                                receivers = list(key) if key is not None else None

                                def _send_email_group(
                                    group_results=group_results,
                                    receivers=receivers,
                                ) -> bool:
                                    grp_report = self._generate_aggregate_report(group_results, report_type)
                                    grp_image_bytes = None
                                    if channel.value in self.notifier._markdown_to_image_channels:
                                        group_payload = (
                                            _share_image_payload(group_results[0])
                                            if len(group_results) == 1
                                            else None
                                        )
                                        group_image_kwargs: Dict[str, Any] = {
                                            "max_chars": self.notifier._markdown_to_image_max_chars,
                                        }
                                        if group_payload is not None:
                                            group_image_kwargs["structured_payload"] = group_payload
                                        grp_image_bytes = markdown_to_image(
                                            grp_report,
                                            **group_image_kwargs,
                                        )
                                    use_image = self.notifier._should_use_image_for_channel(
                                        channel, grp_image_bytes
                                    )
                                    if use_image:
                                        return self.notifier._send_email_with_inline_image(
                                            grp_image_bytes, receivers=receivers
                                        )
                                    return self.notifier.send_to_email(
                                        strip_hidden_markdown_metadata(grp_report).strip(),
                                        receivers=receivers,
                                    )

                                email_label = (
                                    f"{channel.value}:{','.join(receivers)}"
                                    if receivers else f"{channel.value}:default"
                                )
                                channel_success, channel_error = _send_channel_safely(
                                    email_label,
                                    _send_email_group,
                                )
                                any_channel_success = channel_success or any_channel_success
                                _record_channel_result(
                                    email_label,
                                    channel_success,
                                    channel_error,
                                    target_results=group_results,
                                )
                        else:
                            def _send_email_report() -> bool:
                                use_image = self.notifier._should_use_image_for_channel(
                                    channel, image_bytes
                                )
                                if use_image:
                                    return self.notifier._send_email_with_inline_image(image_bytes)
                                return self.notifier.send_to_email(
                                    strip_hidden_markdown_metadata(report).strip()
                                )

                            channel_success, channel_error = _send_channel_safely(
                                channel.value,
                                _send_email_report,
                            )
                            any_channel_success = channel_success or any_channel_success
                            _record_channel_result(
                                channel.value,
                                channel_success,
                                channel_error,
                            )
                    elif channel == NotificationChannel.CUSTOM:
                        def _send_custom_report() -> bool:
                            use_image = self.notifier._should_use_image_for_channel(
                                channel, image_bytes
                            )
                            if use_image:
                                return self.notifier._send_custom_webhook_image(
                                    image_bytes, fallback_content=report
                                )
                            return self.notifier.send_to_custom(report)

                        channel_success, channel_error = _send_channel_safely(
                            channel.value,
                            _send_custom_report,
                        )
                        any_channel_success = channel_success or any_channel_success
                        _record_channel_result(
                            channel.value,
                            channel_success,
                            channel_error,
                        )
                    elif channel == NotificationChannel.DISCORD:
                        channel_success, channel_error = _send_channel_safely(
                            channel.value,
                            lambda: self.notifier.send_to_discord(report),
                        )
                        any_channel_success = channel_success or any_channel_success
                        _record_channel_result(
                            channel.value,
                            channel_success,
                            channel_error,
                        )
                    elif channel == NotificationChannel.PUSHOVER:
                        channel_success, channel_error = _send_channel_safely(
                            channel.value,
                            lambda: self.notifier.send_to_pushover(report),
                        )
                        any_channel_success = channel_success or any_channel_success
                        _record_channel_result(
                            channel.value,
                            channel_success,
                            channel_error,
                        )
                    elif channel == NotificationChannel.NTFY:
                        channel_success, channel_error = _send_channel_safely(
                            channel.value,
                            lambda: self.notifier.send_to_ntfy(report),
                        )
                        any_channel_success = channel_success or any_channel_success
                        _record_channel_result(
                            channel.value,
                            channel_success,
                            channel_error,
                        )
                    elif channel == NotificationChannel.GOTIFY:
                        channel_success, channel_error = _send_channel_safely(
                            channel.value,
                            lambda: self.notifier.send_to_gotify(report),
                        )
                        any_channel_success = channel_success or any_channel_success
                        _record_channel_result(
                            channel.value,
                            channel_success,
                            channel_error,
                        )
                    elif channel == NotificationChannel.ASTRBOT:
                        channel_success, channel_error = _send_channel_safely(
                            channel.value,
                            lambda: self.notifier.send_to_astrbot(report),
                        )
                        any_channel_success = channel_success or any_channel_success
                        _record_channel_result(
                            channel.value,
                            channel_success,
                            channel_error,
                        )
                    elif channel == NotificationChannel.SLACK:
                        def _send_slack_report() -> bool:
                            use_image = self.notifier._should_use_image_for_channel(
                                channel, image_bytes
                            )
                            if use_image and self.notifier._slack_bot_token and self.notifier._slack_channel_id:
                                return self.notifier._send_slack_image(
                                    image_bytes, fallback_content=report
                                )
                            return self.notifier.send_to_slack(report)

                        channel_success, channel_error = _send_channel_safely(
                            channel.value,
                            _send_slack_report,
                        )
                        any_channel_success = channel_success or any_channel_success
                        _record_channel_result(
                            channel.value,
                            channel_success,
                            channel_error,
                        )
                    else:
                        logger.warning(f"Unknown notification channel: {channel}")

                has_targeted_channels = bool(channels)
                success = any_channel_success or send_context
                if (
                    any_channel_success
                    and noise_decision is not None
                    and hasattr(self.notifier, "record_noise_control")
                ):
                    self.notifier.record_noise_control(noise_decision)
                    noise_finalized = True
                elif (
                    noise_decision is not None
                    and hasattr(self.notifier, "release_noise_control")
                ):
                    self.notifier.release_noise_control(noise_decision)
                    noise_finalized = True
                if success:
                    logger.info("Decision dashboard push succeeded")
                else:
                    logger.warning("Decision dashboard push failed")
                if not has_targeted_channels and not send_context:
                    channel_label = ",".join(channel.value for channel in channels) or "report"
                    notification_run = self._build_notification_run_snapshot(
                        channel=channel_label,
                        status="success" if success else "failed",
                        success=success,
                    )
                    record_notification_run(
                        channel=channel_label,
                        status="success" if success else "failed",
                        success=success,
                    )
                    self._refresh_saved_diagnostic_snapshot(
                        results=results,
                        notification_run=notification_run,
                    )
            else:
                notification_run = self._build_notification_run_snapshot(
                    channel="report",
                    status="not_configured",
                    success=False,
                    attempts=0,
                )
                record_notification_run(
                    channel="report",
                    status="not_configured",
                    success=False,
                    attempts=0,
                )
                self._refresh_saved_diagnostic_snapshot(
                    results=results,
                    notification_run=notification_run,
                )
                logger.info("No notification channel configured, skipping push")
                
        except Exception as e:
            notification_run = self._build_notification_run_snapshot(
                channel="report",
                status="failed",
                success=False,
                error_message=e,
            )
            record_notification_run(
                channel="report",
                status="failed",
                success=False,
                error_message=e,
            )
            self._refresh_saved_diagnostic_snapshot(
                results=results,
                notification_run=notification_run,
            )
            if (
                noise_decision is not None
                and not noise_finalized
                and hasattr(self.notifier, "release_noise_control")
            ):
                self.notifier.release_noise_control(noise_decision)
            import traceback
            logger.error(f"Failed to send notification: {e}\n{traceback.format_exc()}")

    def _generate_aggregate_report(
        self,
        results: List[AnalysisResult],
        report_type: ReportType,
    ) -> str:
        """Generate aggregate report with backward-compatible notifier fallback."""
        generator = getattr(self.notifier, "generate_aggregate_report", None)
        if callable(generator):
            return generator(results, report_type)
        if report_type == ReportType.BRIEF and hasattr(self.notifier, "generate_brief_report"):
            return self.notifier.generate_brief_report(results)
        return self.notifier.generate_dashboard_report(results)

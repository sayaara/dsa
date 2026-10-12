# -*- coding: utf-8 -*-
"""
===================================
Broad-market review module
===================================

Responsibilities:
1. Fetch broad-market index data (SSE Composite, SZSE Component, ChiNext)
2. Search market news to build the review intelligence
3. Use the LLM to generate the daily broad-market review report
"""

import logging
import re
import time
from dataclasses import dataclass, field
from datetime import datetime
from inspect import getattr_static
from typing import Optional, Dict, Any, List


from src.agent.provider_trace import resolved_model_provider_identity
from src.config import get_config
from src.search_service import SearchService
from src.core.market_registry import MARKET_CODE_SET, get_market
from src.core.market_profile import get_profile, MarketProfile
from src.core.market_strategy import get_market_strategy_blueprint
from src.llm.backend_registry import (
    LOCAL_CLI_GENERATION_BACKEND_IDS,
    LITELLM_BACKEND_ID,
    resolve_generation_backend_id,
    resolve_generation_fallback_backend_id,
)
from src.llm.generation_backend import GenerationError, GenerationResult
from src.schemas.market_light import MARKET_LIGHT_REGIONS, MarketLightSnapshot
from src.services.run_diagnostics import record_llm_run, record_llm_run_started
from src.services.intelligence_service import IntelligenceService
from data_provider.base import DataFetcherManager

logger = logging.getLogger(__name__)

_LEGACY_ANALYZER_BACKEND_ID = "legacy_analyzer"

_TRUNCATED_REVIEW_NOTE = (
    "\n\n> Note: this review was cut off by the model's output-token limit "
    "and may be incomplete."
)

_ENGLISH_SECTION_PATTERNS = {
    "market_summary": r"###\s*(?:1\.\s*)?Market Summary",
    "index_commentary": r"###\s*(?:2\.\s*)?(?:Index Commentary|Major Indices)",
    "sector_highlights": r"###\s*(?:4\.\s*)?(?:Sector Highlights|Sector/Theme Highlights)",
}


@dataclass
class MarketIndex:
    """Broad-market index data"""
    code: str                    # index code
    name: str                    # index name
    current: float = 0.0         # current level
    change: float = 0.0          # point change
    change_pct: float = 0.0      # percentage change (%)
    open: float = 0.0            # opening level
    high: float = 0.0            # high
    low: float = 0.0             # low
    prev_close: float = 0.0      # previous close
    volume: float = 0.0          # trading volume (lots)
    amount: float = 0.0          # turnover (yuan)
    amplitude: float = 0.0       # amplitude (%)

    def to_dict(self) -> Dict[str, Any]:
        return {
            'code': self.code,
            'name': self.name,
            'current': self.current,
            'change': self.change,
            'change_pct': self.change_pct,
            'open': self.open,
            'high': self.high,
            'low': self.low,
            'volume': self.volume,
            'amount': self.amount,
            'amplitude': self.amplitude,
        }


@dataclass
class MarketOverview:
    """Market overview data"""
    date: str                           # date
    indices: List[MarketIndex] = field(default_factory=list)  # main indices


@dataclass
class MarketLightReviewResult:
    """Internal market-review parts built from one overview fetch."""

    overview: MarketOverview
    report: str
    market_light_snapshot: Optional[Dict[str, Any]]
    structured_payload: Dict[str, Any] = field(default_factory=dict)


class MarketAnalyzer:
    """
    Broad-market review analyser

    Capabilities:
    1. Fetch broad-market index real-time quotes
    2. Fetch market advance/decline statistics
    3. Fetch the sector advance/decline ranking
    4. Search market news
    5. Generate the broad-market review report
    """

    def __init__(
        self,
        search_service: Optional[SearchService] = None,
        analyzer=None,
        region: str = "us",
        config: Optional[Any] = None,
    ):
        """
        Initialise the broad-market analyser

        Args:
            search_service: the search service instance
            analyzer: the AI analyser instance (used to call the LLM)
            region: market region, ca = Canada, us = US
            config: the configuration for this review; the global configuration is read when omitted
        """
        self.config = config or get_config()
        self.search_service = search_service
        self.analyzer = analyzer
        self.data_manager = DataFetcherManager()
        self.region = region if region in MARKET_CODE_SET else "us"
        self.profile: MarketProfile = get_profile(self.region)
        self.strategy = get_market_strategy_blueprint(self.region)

    def _log_context(self) -> str:
        return f"component=market_review region={self.region}"

    @staticmethod
    def _resolve_configured_response_provider(
        configured_model: str,
        response_model: str,
        model_list: Optional[List[Dict[str, Any]]] = None,
    ) -> str:
        """Match the actual response model against all deployments of one alias."""
        normalized_configured_model = str(configured_model or "").strip()
        normalized_response_model = str(response_model or "").strip().lower()
        if not normalized_configured_model or not normalized_response_model or not model_list:
            return ""

        for entry in model_list:
            params = entry.get("litellm_params", {}) or {}
            model_name = str(entry.get("model_name") or "").strip()
            if not model_name:
                model_name = str(params.get("model") or "").strip()
            if model_name != normalized_configured_model:
                continue

            deployment_model = str(params.get("model") or "").strip()
            if deployment_model.lower() != normalized_response_model:
                continue

            normalized_deployment_model = deployment_model.lower()
            if normalized_deployment_model.startswith("openai/~") or "openrouter" in normalized_deployment_model:
                return "openrouter"

            _resolved_model, resolved_provider = resolved_model_provider_identity(
                deployment_model,
            )
            if resolved_provider:
                return resolved_provider
        return ""

    def _resolve_recorded_provider(
        self,
        *,
        provider: str,
        model: str,
        backend: str,
        usage_provider: str = "",
        response_model: str = "",
    ) -> str:
        """Resolve LiteLLM router aliases before persisting diagnostics."""
        normalized_backend = str(backend or "").strip().lower()
        normalized_model = str(model or "").strip()
        normalized_usage_provider = str(usage_provider or "").strip()
        normalized_response_model = str(response_model or "").strip()
        normalized_provider = str(provider or "").strip()
        resolved_route_provider = ""
        if normalized_backend == "litellm" and normalized_model:
            resolved_route_model, resolved_route_provider = resolved_model_provider_identity(
                normalized_model,
                getattr(self.config, "llm_model_list", None) or [],
            )
            normalized_route = str(resolved_route_model or normalized_model).strip().lower()
            if normalized_route.startswith("openai/~") or "openrouter" in normalized_route:
                resolved_route_provider = "openrouter"
        resolved_response_provider = ""
        if normalized_response_model:
            resolved_response_provider = self._resolve_configured_response_provider(
                normalized_model,
                normalized_response_model,
                getattr(self.config, "llm_model_list", None) or [],
            )
            if resolved_response_provider == "openrouter":
                return resolved_response_provider
        if normalized_usage_provider:
            return normalized_usage_provider
        if normalized_response_model:
            if resolved_response_provider:
                return resolved_response_provider
            if resolved_route_provider == "openrouter":
                return resolved_route_provider
            _wire_model, resolved_provider = resolved_model_provider_identity(
                normalized_response_model,
            )
            if resolved_provider:
                return resolved_provider
        if normalized_backend != "litellm" or not normalized_model:
            return normalized_provider
        return resolved_route_provider or normalized_provider or "openai"

    def _resolve_recorded_error_model(
        self,
        *,
        error: Any,
        fallback_model: str = "",
    ) -> str:
        """Preserve route/model diagnostics for LiteLLM configuration failures."""
        details = getattr(error, "details", None)
        if isinstance(details, dict):
            visited: set[int] = set()

            def _find_error_model(payload: Dict[str, Any]) -> str:
                payload_id = id(payload)
                if payload_id in visited:
                    return ""
                visited.add(payload_id)
                for key in ("last_model", "route_name"):
                    candidate = str(payload.get(key) or "").strip()
                    if candidate:
                        return candidate
                fallback_error = payload.get("fallback_error")
                if isinstance(fallback_error, dict):
                    nested_details = fallback_error.get("details")
                    if isinstance(nested_details, dict):
                        candidate = _find_error_model(nested_details)
                        if candidate:
                            return candidate
                    return _find_error_model(fallback_error)
                return ""

            candidate = _find_error_model(details)
            if candidate:
                return candidate
        backend = str(getattr(error, "backend", "") or "").strip()
        configured_model = str(getattr(self.config, "litellm_model", "") or "").strip()
        normalized_fallback_model = str(fallback_model or "").strip()
        if backend == "litellm":
            return normalized_fallback_model or configured_model or backend
        return normalized_fallback_model or backend

    def _get_output_language(self) -> str:
        """Return the report language for payload and directives (reports are English-only)."""
        return "en"

    def _get_review_language(self) -> str:
        """Return the structural/template language (reports are English-only)."""
        return "en"

    def _get_template_review_language(self) -> str:
        return self._get_review_language()

    def _get_market_scope_name(self, review_language: str | None = None) -> str:
        review_language = review_language or self._get_review_language()
        if self.region == "us":
            return "US market"
        return "Canadian market"

    def _get_turnover_unit_label(self) -> str:
        """Return the turnover unit label for the current market/language."""
        spec = get_market(self.region)
        if spec is not None:
            return f"{spec.currency} bn"
        return "CNY 100m"

    def _format_turnover_value(self, amount_raw: float) -> str:
        """Format raw turnover according to market-specific units."""
        if amount_raw == 0.0:
            return "N/A"
        if self.region in MARKET_CODE_SET:
            return f"{amount_raw / 1e9:.2f}"
        if amount_raw > 1e6:
            return f"{amount_raw / 1e8:.0f}"
        return f"{amount_raw:.0f}"

    def _get_index_change_arrow(self, change_pct: float) -> str:
        if change_pct == 0:
            return "⚪"
        color_scheme = getattr(getattr(self, "config", None), "market_review_color_scheme", "green_up")
        if color_scheme == "red_up":
            return "🔴" if change_pct > 0 else "🟢"
        return "🟢" if change_pct > 0 else "🔴"

    def _get_review_title(self, date: str) -> str:
        market_names = {
            "us": "US Market Recap",
            "ca": "Canada Market Recap",
        }
        market_name = market_names.get(self.region, "US Market Recap")
        return f"## {date} {market_name}"

    def _get_index_hint(self) -> str:
        if self.region == "us":
            return "Analyze the key moves in the S&P 500, Nasdaq, Dow, and other major indices."
        if self.region == "ca":
            return "Analyze the key moves in the S&P/TSX Composite, the TSX Venture Composite, and other major indices."
        return "Analyze the price action in the SSE, SZSE, ChiNext, and other major indices."

    def _get_strategy_prompt_block(self) -> str:
        return self.strategy.to_prompt_block()

    def _get_strategy_markdown_block(self, review_language: str | None = None) -> str:
        return self.strategy.to_markdown_block()

    def _get_market_mood_text(self, mood_key: str, review_language: str | None = None) -> str:
        mapping = {
            "strong_up": "strong gains",
            "mild_up": "moderate gains",
            "mild_down": "mild losses",
            "strong_down": "clear weakness",
            "range": "range-bound trading",
        }
        return mapping[mood_key]

    def get_market_overview(self) -> MarketOverview:
        """
        Fetch the market overview data

        Returns:
            MarketOverview: the market overview data object
        """
        today = datetime.now().strftime('%Y-%m-%d')
        overview = MarketOverview(date=today)

        # Fetch the main index quotes (switched by region between Canada and the US)
        overview.indices = self._get_main_indices()

        return overview

    def _get_main_indices(self) -> List[MarketIndex]:
        """Fetch the main index real-time quotes"""
        indices = []

        try:
            logger.info("[Market] %s action=get_main_indices status=start", self._log_context())

            # Use DataFetcherManager for the index quotes (switched by region)
            data_list = self.data_manager.get_main_indices(region=self.region)

            if data_list:
                for item in data_list:
                    index = MarketIndex(
                        code=item['code'],
                        name=item['name'],
                        current=item['current'],
                        change=item['change'],
                        change_pct=item['change_pct'],
                        open=item['open'],
                        high=item['high'],
                        low=item['low'],
                        prev_close=item['prev_close'],
                        volume=item['volume'],
                        amount=item['amount'],
                        amplitude=item['amplitude']
                    )
                    indices.append(index)

            if not indices:
                logger.warning("[Market] %s action=get_main_indices status=empty", self._log_context())
            else:
                logger.info(
                    "[Market] %s action=get_main_indices status=success count=%d",
                    self._log_context(),
                    len(indices),
                )

        except Exception as e:
            logger.error("[Market] %s action=get_main_indices status=failed error=%s", self._log_context(), e)

        return indices

    def search_market_news(self) -> List[Dict]:
        """
        Search market news

        Returns:
            The news list
        """
        if not self.search_service:
            logger.warning(
                "[Market] %s action=search_market_news status=skipped reason=no_search_service",
                self._log_context(),
            )
            return []

        all_news = []

        # Use different news search terms per region
        search_queries = self.profile.news_queries
        market_names = {
            "us": "US market",
            "ca": "Canadian market",
        }

        try:
            logger.info("[Market] %s action=search_market_news status=start", self._log_context())

            # Set the search context name from the region so a US search is not read as a different market
            market_name = market_names.get(self.region, "market")
            for query in search_queries:
                response = self.search_service.search_stock_news(
                    stock_code="market",
                    stock_name=market_name,
                    max_results=3,
                    focus_keywords=query.split()
                )
                if response and response.results:
                    all_news.extend(response.results)
                    logger.info(
                        "[Market] %s action=search_market_news status=query_success count=%d",
                        self._log_context(),
                        len(response.results),
                    )

            logger.info(
                "[Market] %s action=search_market_news status=success count=%d",
                self._log_context(),
                len(all_news),
            )

        except Exception as e:
            logger.error("[Market] %s action=search_market_news status=failed error=%s", self._log_context(), e)

        return all_news

    def generate_market_review(self, overview: MarketOverview, news: List) -> str:
        """
        Generate the broad-market review report with the LLM

        Args:
            overview: the market overview data
            news: the market news list (a list of SearchResult objects)

        Returns:
            The broad-market review report text
        """
        backend_error = self._get_analyzer_generation_backend_config_error()
        if backend_error is not None:
            logger.error(
                "[Market] %s action=generate_review status=failed error_type=%s error=%s",
                self._log_context(),
                type(backend_error).__name__,
                backend_error,
            )
            record_llm_run(
                success=False,
                provider=backend_error.provider or backend_error.backend,
                model=self._resolve_recorded_error_model(error=backend_error),
                call_type="market_review",
                error_type=type(backend_error).__name__,
                error_message=backend_error,
            )
            raise backend_error

        if not self.analyzer or not self.analyzer.is_available():
            logger.warning(
                "[Market] %s action=generate_review status=fallback_template reason=no_analyzer",
                self._log_context(),
            )
            return self._generate_template_review(overview, news)

        # Build the prompt
        prompt = self._build_review_prompt(overview, news)

        logger.info("[Market] %s action=generate_review status=start", self._log_context())
        # Use public analyzer APIs so diagnostics reflect the actual execution backend.
        llm_started_at = time.perf_counter()
        provider, model = self._get_analyzer_generation_backend_identity()
        try:
            record_llm_run_started(
                provider=provider,
                model=model,
                call_type="market_review",
            )
            generation_result = self._generate_market_review_with_metadata(
                prompt,
                provider=provider,
                model=model,
            )
            review = generation_result.text if generation_result else None
            generation_diagnostics = (
                getattr(generation_result, "diagnostics", None) if generation_result is not None else None
            )
            if generation_result is not None:
                model = generation_result.model or model
                usage_payload = getattr(generation_result, "usage", None)
                provider = self._resolve_recorded_provider(
                    provider=generation_result.provider or generation_result.backend or provider,
                    model=model,
                    backend=generation_result.backend or "",
                    usage_provider=(
                        usage_payload.get("provider") if isinstance(usage_payload, dict) else ""
                    ),
                    response_model=(
                        usage_payload.get("response_model") if isinstance(usage_payload, dict) else ""
                    ),
                )
        except Exception as exc:
            error_provider = getattr(exc, "provider", None) or getattr(exc, "backend", None) or provider
            error_model = self._resolve_recorded_error_model(
                error=exc,
                fallback_model=model,
            )
            record_llm_run(
                success=False,
                provider=error_provider,
                model=error_model,
                call_type="market_review",
                duration_ms=int((time.perf_counter() - llm_started_at) * 1000),
                error_type=type(exc).__name__,
                error_message=exc,
            )
            raise

        failed_all_models = (
            isinstance(generation_diagnostics, dict)
            and generation_diagnostics.get("reason") == "all_models_failed"
        )
        record_llm_run(
            success=bool(review),
            provider=provider,
            model=model,
            call_type="market_review",
            duration_ms=int((time.perf_counter() - llm_started_at) * 1000),
            error_type=None if review else ("AllModelsFailed" if failed_all_models else "EmptyResponse"),
            error_message=(
                None
                if review
                else (
                    generation_diagnostics
                    if failed_all_models
                    else "empty market review response"
                )
            ),
        )

        if review:
            logger.info(
                "[Market] %s action=generate_review status=success length=%d",
                self._log_context(),
                len(review),
            )
            if isinstance(generation_diagnostics, dict) and generation_diagnostics.get("finish_reason") == "length":
                logger.warning(
                    "[MarketReview] %s action=generate_review status=truncated reason=output_token_limit",
                    self._log_context(),
                )
                review = review.rstrip() + _TRUNCATED_REVIEW_NOTE
            # Inject structured data tables into LLM prose sections
            return self._inject_data_into_review(review, overview, news)

        logger.warning(
            "[Market] %s action=generate_review status=fallback_template reason=empty_llm_response",
            self._log_context(),
        )
        return self._generate_template_review(overview, news)

    def _get_analyzer_generation_backend_config_error(self) -> Optional[GenerationError]:
        """Return analyzer backend config errors without relying on dynamic mock attributes."""
        if self.analyzer is None:
            try:
                resolve_generation_backend_id(self.config)
                resolve_generation_fallback_backend_id(self.config)
            except GenerationError as exc:
                return exc
            return None
        missing = object()
        if getattr_static(self.analyzer, "get_generation_backend_config_error", missing) is missing:
            return None
        method = getattr(self.analyzer, "get_generation_backend_config_error", None)
        if not callable(method):
            return None
        error = method()
        return error if isinstance(error, GenerationError) else None

    def _get_configured_generation_backend_identity(self) -> tuple[str, str]:
        """Best-effort backend identity for legacy analyzers without metadata APIs."""
        backend_id = str(getattr(self.config, "generation_backend", "") or "").strip().lower()
        if not backend_id:
            backend_id = LITELLM_BACKEND_ID
        if backend_id in LOCAL_CLI_GENERATION_BACKEND_IDS:
            return backend_id, backend_id
        return backend_id, str(getattr(self.config, "litellm_model", "") or "")

    def _get_legacy_analyzer_generation_backend_identity(self) -> tuple[str, str]:
        """Return a neutral identity for injected analyzers that expose no metadata APIs."""
        return _LEGACY_ANALYZER_BACKEND_ID, _LEGACY_ANALYZER_BACKEND_ID

    def _get_analyzer_generation_backend_identity(self) -> tuple[str, str]:
        """Use analyzer metadata API when available, otherwise fall back to configured identity."""
        if self.analyzer is None:
            return self._get_configured_generation_backend_identity()
        missing = object()
        if getattr_static(self.analyzer, "get_generation_backend_identity", missing) is not missing:
            method = getattr(self.analyzer, "get_generation_backend_identity", None)
            if callable(method):
                return method()
        return self._get_legacy_analyzer_generation_backend_identity()

    def _generate_market_review_with_metadata(
        self,
        prompt: str,
        *,
        provider: str,
        model: str,
    ) -> Optional[GenerationResult]:
        """Support legacy analyzers that only implement the public generate_text() contract."""
        if self.analyzer is None:
            return None
        missing = object()
        if getattr_static(self.analyzer, "generate_text_with_metadata", missing) is not missing:
            method = getattr(self.analyzer, "generate_text_with_metadata", None)
            if callable(method):
                return method(
                    prompt,
                    max_tokens=8192,
                    temperature=0.7,
                )

        if getattr_static(self.analyzer, "generate_text", missing) is missing:
            raise AttributeError(
                "analyzer must implement generate_text_with_metadata() or generate_text()"
            )
        legacy_method = getattr(self.analyzer, "generate_text", None)
        if not callable(legacy_method):
            raise AttributeError(
                "analyzer must implement generate_text_with_metadata() or generate_text()"
            )
        review = legacy_method(
            prompt,
            max_tokens=8192,
            temperature=0.7,
        )
        if review is None:
            return None
        return GenerationResult(
            text=review,
            provider=provider,
            model=model,
            backend=provider,
            usage={},
        )

    def build_market_review_payload(
        self,
        overview: MarketOverview,
        news: List,
        report: str,
        market_light_snapshot: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Build the structured market-review contract consumed by API, Web, and notifications."""
        language = self._get_output_language()
        sections = self._split_report_sections(report)
        title = self._extract_report_title(report) or self._get_review_title(overview.date).lstrip("# ").strip()
        light = (
            market_light_snapshot or self.build_market_light_snapshot(overview)
            if self._supports_market_light()
            else None
        )
        payload = {
            "version": 1,
            "kind": "market_review",
            "region": self.region,
            "language": language,
            "color_scheme": getattr(
                getattr(self, "config", None),
                "market_review_color_scheme",
                "green_up",
            ),
            "title": title,
            "generated_at": datetime.now().isoformat(),
            "date": overview.date,
            "market_scope": self._get_market_scope_name(language),
            "indices": [idx.to_dict() for idx in overview.indices],
            "news": [self._normalize_news_item(item) for item in (news or [])[:8]],
            "sections": sections,
            "markdown_report": report,
        }

        if light is not None:
            payload["market_light"] = light

        return payload

    def _supports_market_light(self) -> bool:
        return self.region in MARKET_LIGHT_REGIONS

    @staticmethod
    def _extract_report_title(report: str) -> str:
        for line in (report or "").splitlines():
            stripped = line.strip()
            if stripped.startswith("#"):
                return stripped.lstrip("#").strip()
        return ""

    @classmethod
    def _split_report_sections(cls, report: str) -> List[Dict[str, str]]:
        text = (report or "").strip()
        if not text:
            return []
        matches = list(re.finditer(r"^(#{2,3})\s+(.+?)\s*$", text, flags=re.MULTILINE))
        if not matches:
            return [{"key": "full_review", "title": "Review", "markdown": text}]

        sections: List[Dict[str, str]] = []
        first_match = matches[0]
        starts_with_report_title = first_match.start() == 0 and first_match.group(1) == "##"
        content_start_index = 1 if starts_with_report_title else 0
        intro_start = first_match.end() if starts_with_report_title else 0
        intro_end = (
            matches[1].start()
            if starts_with_report_title and len(matches) > 1
            else (len(text) if starts_with_report_title else matches[0].start())
        )
        intro = text[intro_start:intro_end].strip()
        if intro:
            sections.append({"key": "overview", "title": "Overview", "markdown": intro})

        for index, match in enumerate(matches[content_start_index:], start=content_start_index):
            start = match.end()
            end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
            title = match.group(2).strip()
            markdown = text[start:end].strip()
            if not markdown:
                continue
            key = re.sub(r"[^0-9a-zA-Z\u4e00-\u9fff]+", "_", title).strip("_").lower()
            sections.append({
                "key": key or f"section_{index + 1}",
                "title": title,
                "markdown": markdown,
            })
        return sections

    @classmethod
    def _normalize_news_item(cls, item: Any) -> Dict[str, str]:
        return {
            "title": cls._compact_news_text(cls._get_news_field(item, "title"), limit=120),
            "snippet": cls._compact_news_text(cls._get_news_field(item, "snippet"), limit=260),
            "source": cls._compact_news_text(cls._get_news_field(item, "source"), limit=80),
            "published_date": cls._compact_news_text(cls._get_news_field(item, "published_date"), limit=40),
            "url": cls._compact_news_text(cls._get_news_field(item, "url"), limit=240),
        }

    def _inject_data_into_review(
        self,
        review: str,
        overview: MarketOverview,
        news: Optional[List] = None,
    ) -> str:
        """Inject structured data tables into the corresponding LLM prose sections."""
        # Build data blocks
        stats_block = self._build_stats_block(overview)
        indices_block = self._build_indices_block(overview)
        patterns = _ENGLISH_SECTION_PATTERNS

        if stats_block:
            review = self._insert_after_section(
                review,
                patterns["market_summary"],
                stats_block,
            )

        if indices_block:
            review = self._insert_after_section(
                review,
                patterns["index_commentary"],
                indices_block,
            )

        return review

    @staticmethod
    def _insert_after_section(text: str, heading_pattern: str, block: str) -> str:
        """Insert a data block at the end of a markdown section (before the next ### heading)."""
        import re
        # Find the heading
        match = re.search(heading_pattern, text)
        if not match:
            return text
        start = match.end()
        # Find the next ### heading after this one
        next_heading = re.search(r'\n###\s', text[start:])
        if next_heading:
            insert_pos = start + next_heading.start()
        else:
            # No next heading — append at end
            insert_pos = len(text)
        # Insert the block before the next heading, with spacing
        return text[:insert_pos].rstrip() + '\n\n' + block + '\n\n' + text[insert_pos:].lstrip('\n')

    def _build_stats_block(self, overview: MarketOverview) -> str:
        """Build the market-signal block (CA/US have no breadth statistics)."""
        if not (self._supports_market_light() and overview.indices):
            return ""
        light = self.build_market_light_snapshot(overview)
        return "\n".join(
            [
                f"- **Market Signal**: {light['score']}/100 "
                f"({light['temperature_label']}, {light['label']})",
                f"- **Drivers**: {'; '.join(light['reasons'])}",
                f"- **Guidance**: {light['guidance']}",
            ]
        )

    def build_market_light_snapshot(self, overview: MarketOverview) -> Dict[str, Any]:
        """Build a deterministic market-light snapshot from structured breadth data."""
        scores = self._build_market_light_scores(overview)
        score = int(scores["score"])
        temperature_label = str(scores["temperature_label"])
        if score >= 60:
            status = "green"
        elif score >= 40:
            status = "yellow"
        else:
            status = "red"

        label_map = {
            "green": "risk-on",
            "yellow": "balanced",
            "red": "risk-off",
        }
        guidance_map = {
            "green": "Risk appetite is acceptable; focus on leading themes and position discipline.",
            "yellow": "Signals are mixed; keep position sizing moderate and wait for confirmation.",
            "red": "Risk is elevated; prioritize drawdown control and avoid chasing weak rebounds.",
        }
        reasons = self._build_market_light_reasons_en(overview, score)

        snapshot = MarketLightSnapshot(
            region=self.region,
            trade_date=overview.date,
            status=status,
            label=label_map[status],
            score=score,
            temperature_label=temperature_label,
            reasons=reasons,
            guidance=guidance_map[status],
            dimensions=scores["dimensions"],
            data_quality=str(scores["data_quality"]),
        )
        return snapshot.model_dump()

    def _build_market_light_reasons_en(self, overview: MarketOverview, score: int) -> List[str]:
        reasons: List[str] = []
        index_changes = [idx.change_pct for idx in overview.indices if idx.change_pct is not None]
        if index_changes:
            avg_change = sum(index_changes) / len(index_changes)
            reasons.append(f"average major-index change {avg_change:+.2f}%")
        if not reasons:
            reasons.append("limited structured breadth data; using available market inputs")
        return reasons

    def _build_indices_block(self, overview: MarketOverview) -> str:
        """Build the index quote table"""
        if not overview.indices:
            return ""
        lines = [
            f"| Index | Last | Change % | Open | High | Low | Amplitude | Turnover ({self._get_turnover_unit_label()}) |",
            "|-------|------|----------|------|------|-----|-----------|-----------------|",
        ]
        for idx in overview.indices:
            arrow = self._get_index_change_arrow(idx.change_pct)
            amount_raw = idx.amount or 0.0
            amount_str = self._format_turnover_value(amount_raw)
            lines.append(
                f"| {idx.name} | {idx.current:.2f} | {arrow} {idx.change_pct:+.2f}% | "
                f"{self._format_optional_number(idx.open)} | {self._format_optional_number(idx.high)} | "
                f"{self._format_optional_number(idx.low)} | {self._format_optional_pct(idx.amplitude)} | {amount_str} |"
            )
        return "\n".join(lines)

    def _build_news_block(self, news: List) -> str:
        """Build a compact source-aware news catalyst list for the rendered report."""
        if not news:
            return ""
        language = self._get_review_language()
        lines = [
            "#### News Catalysts",
        ]

        for idx, item in enumerate(news[:5], 1):
            lines.append(self._format_news_catalyst_line(idx, item, language=language))
        return "\n".join(lines)

    @staticmethod
    def _get_news_field(item: Any, field: str) -> str:
        if hasattr(item, field):
            value = getattr(item, field, "") or ""
        elif isinstance(item, dict):
            value = item.get(field, "") or ""
        else:
            value = ""
        return str(value).strip()

    @classmethod
    def _format_news_catalyst_line(cls, idx: int, item: Any, *, language: Optional[str] = None) -> str:
        fallback_title = "Untitled catalyst"
        title = cls._compact_news_text(cls._get_news_field(item, "title"), limit=90) or fallback_title
        source = cls._compact_news_text(cls._get_news_field(item, "source"), limit=40)
        date_text = cls._compact_news_text(cls._get_news_field(item, "published_date"), limit=24)
        url = cls._compact_news_text(cls._get_news_field(item, "url"), limit=0)
        title_text = cls._escape_markdown_link_label(title)
        if url:
            title_text = f"[{title_text}]({url})"
        meta_parts = [part for part in (source, date_text) if part]
        meta = f" ({' / '.join(meta_parts)})" if meta_parts else ""
        return f"- {idx}. {title_text}{meta}"

    @staticmethod
    def _compact_news_text(value: str, *, limit: int) -> str:
        text = " ".join(str(value or "").split())
        if limit <= 0 or len(text) <= limit:
            return text
        return text[: max(0, limit - 3)].rstrip() + "..."

    @staticmethod
    def _format_optional_number(value: float) -> str:
        return "N/A" if value in (None, 0, 0.0) else f"{value:.2f}"

    @staticmethod
    def _format_optional_pct(value: float) -> str:
        return "N/A" if value in (None, 0, 0.0) else f"{value:.2f}%"

    @staticmethod
    def _escape_markdown_link_label(value: str) -> str:
        return value.replace("\\", "\\\\").replace("[", "\\[").replace("]", "\\]")

    def _build_market_light_scores(self, overview: MarketOverview) -> Dict[str, Any]:
        """Build the canonical Market Light scores used by reports and alerts."""

        # Breadth and limit-up/down data are not available for CA/US, so those
        # dimensions stay neutral and unavailable (the stored contract keeps the keys).
        breadth_score = 50
        breadth_available = False

        index_changes = [idx.change_pct for idx in overview.indices if idx.change_pct is not None]
        index_available = bool(overview.indices and index_changes)
        index_score = 50
        if index_available:
            avg_change = sum(index_changes) / len(index_changes)
            index_score = int(max(0, min(100, 50 + avg_change * 12)))

        limit_score = 50
        limit_available = False

        dimensions = {
            "breadth": {"score": breadth_score, "available": breadth_available},
            "index": {"score": index_score, "available": index_available},
            "limit": {"score": limit_score, "available": limit_available},
        }

        if not index_available:
            data_quality = "unavailable"
        elif all(dimension["available"] for dimension in dimensions.values()):
            data_quality = "ok"
        else:
            data_quality = "partial"

        score = int(round(breadth_score * 0.45 + index_score * 0.35 + limit_score * 0.20))
        if score >= 70:
            label = "risk-on"
        elif score >= 55:
            label = "constructive"
        elif score >= 40:
            label = "mixed"
        else:
            label = "defensive"
        return {
            "score": score,
            "temperature_label": label,
            "dimensions": dimensions,
            "data_quality": data_quality,
        }

    def _build_market_temperature(self, overview: MarketOverview) -> tuple[int, str]:
        scores = self._build_market_light_scores(overview)
        score = int(scores["score"])
        label = str(scores["temperature_label"])
        return score, label

    def _build_output_template_sections(self, review_language: str) -> str:
        """Build LLM output sections according to market data capabilities."""
        section_number = 3
        sections: List[str] = []
        sections.extend([
            f"""### {section_number}. News Catalysts
(Connect recent news to index price action and macro/external-market clues. Do not infer unsupported breadth, fund-flow, or sector-ranking data.)""",
            f"""### {section_number + 1}. Outlook
(Provide the near-term outlook based on index price action and the available news.)""",
            f"""### {section_number + 2}. Risk Alerts
(List the main risks to monitor.)""",
            f"""### {section_number + 3}. Strategy Plan
(Provide an offensive/balanced/defensive stance, a position-sizing guideline, one invalidation trigger, and end with "For reference only, not investment advice.")""",
        ])
        return "\n\n".join(sections)

    def _build_review_prompt(self, overview: MarketOverview, news: List) -> str:
        """Build the review report prompt"""
        review_language = self._get_review_language()
        shell_language_label = "English"

        # Index quote details (concise format, no emoji)
        indices_text = ""
        for idx in overview.indices:
            direction = "↑" if idx.change_pct > 0 else "↓" if idx.change_pct < 0 else "-"
            indices_text += f"- {idx.name}: {idx.current:.2f} ({direction}{abs(idx.change_pct):.2f}%)\n"

        # News details - accepts SearchResult objects or dicts
        news_text = ""
        for i, n in enumerate(news[:6], 1):
        # Tolerate both SearchResult objects and dicts
            title = self._compact_news_text(self._get_news_field(n, "title"), limit=90)
            snippet = self._compact_news_text(self._get_news_field(n, "snippet"), limit=220)
            source = self._compact_news_text(self._get_news_field(n, "source"), limit=60)
            published_date = self._compact_news_text(self._get_news_field(n, "published_date"), limit=30)
            url = self._compact_news_text(self._get_news_field(n, "url"), limit=180)
            meta_parts = [part for part in (source, published_date) if part]
            meta = f" ({' / '.join(meta_parts)})" if meta_parts else ""
            url_line = f"\n   URL: {url}" if url else ""
            news_text += f"{i}. {title}{meta}\n   {snippet or '-'}{url_line}\n"

        # None of the supported markets (CA/US) has advance-decline counts or sector data
        data_limits_block = (
            "## Data Limits\n"
            "- Market breadth, aggregate turnover, participation, and fund-flow signals are not available for this market.\n"
            "- Sector/theme ranking data is not available for this market."
        )

        data_no_indices_hint = (
            "Note: Market data fetch failed. Rely mainly on [Market News] for qualitative analysis. Do not invent index levels."
            if not indices_text
            else ""
        )
        indices_placeholder = indices_text if indices_text else "No index data (API error)"
        news_placeholder = news_text if news_text else "No relevant news"
        data_boundary_requirement = (
            "- Respect Data Limits: do not invent or over-interpret unsupported breadth, fund-flow, turnover, participation, or sector-ranking data.\n"
        )
        market_summary_hint = "2-3 sentences summarizing overall market tone, index moves, and available news context."

        output_template_sections = self._build_output_template_sections(review_language)

        report_title = self._get_review_title(overview.date).removeprefix("## ").strip()
        return f"""You are a professional {self._get_market_scope_name('en')} analyst. Please produce a concise market recap report based on the data below.

[Requirements]
- Output pure Markdown only
- No JSON
- No code blocks
- Use emoji sparingly in headings (at most one per heading)
- The entire fixed shell, headings, guidance, and conclusion must be in {shell_language_label}
{data_boundary_requirement}

---

# Today's Market Data

## Date
{overview.date}

## Major Indices
{indices_placeholder}

{data_limits_block}

## Market News
{news_placeholder}

{data_no_indices_hint}

{self._get_strategy_prompt_block()}

---

# Output Template (follow this structure)

## {report_title}

### 1. Market Summary
({market_summary_hint})

### 2. Index Commentary
({self._get_index_hint()})

{output_template_sections}

---

Output the report content directly, no extra commentary.
"""

    def _generate_template_review(self, overview: MarketOverview, news: List) -> str:
        """Generate the review report from a template (the fallback when no LLM is available)"""
        template_language = self._get_template_review_language()
        mood_code = self.profile.mood_index_code
        # Find the matching index from mood_index_code
        # cn: mood_code="000001", idx.code may be "sh000001" (it ends with mood_code)
        # us: mood_code="SPX", idx.code is exactly "SPX"
        mood_index = next(
            (
                idx
                for idx in overview.indices
                if idx.code == mood_code or idx.code.endswith(mood_code)
            ),
            None,
        )
        if mood_index:
            if mood_index.change_pct > 1:
                market_mood = self._get_market_mood_text("strong_up", template_language)
            elif mood_index.change_pct > 0:
                market_mood = self._get_market_mood_text("mild_up", template_language)
            elif mood_index.change_pct > -1:
                market_mood = self._get_market_mood_text("mild_down", template_language)
            else:
                market_mood = self._get_market_mood_text("strong_down", template_language)
        else:
            market_mood = self._get_market_mood_text("range", template_language)

        # Index quotes (concise format)
        indices_text = ""
        for idx in overview.indices[:4]:
            marker = self._get_index_change_arrow(idx.change_pct)
            indices_text += f"- **{idx.name}**: {idx.current:.2f} ({marker} {idx.change_pct:+.2f}%)\n"

        stats_section = ""
        if self._supports_market_light():
            stats_block = self._build_stats_block(overview)
            if stats_block:
                stats_section = f"""
### 3. Breadth & Liquidity
{stats_block}
"""
        market_names = {
            "us": "US Market Recap",
            "ca": "Canada Market Recap",
        }
        market_name = market_names.get(self.region, "US Market Recap")
        report = f"""## {overview.date} {market_name}

### 1. Market Summary
Today's {self._get_market_scope_name(template_language)} showed **{market_mood}**.

### 2. Major Indices
{indices_text or "- No index data available"}
{stats_section}
### 5. Risk Alerts
Market conditions can change quickly. The data above is for reference only and does not constitute investment advice.

{self._get_strategy_markdown_block(template_language)}

---
*Review Time: {datetime.now().strftime('%H:%M')}*
"""
        return report

    def _run_daily_review_parts(self) -> MarketLightReviewResult:
        """Run market review once and keep report/snapshot on the same overview."""
        logger.info("========== Starting the market review ==========")

        # 1. Fetch the market overview
        overview = self.get_market_overview()

        # 2. Search market news
        news = self.search_market_news()
        news = self._merge_persisted_market_intelligence(news)

        # 3. Generate the review report
        report = self.generate_market_review(overview, news)
        snapshot = self.build_market_light_snapshot(overview) if self._supports_market_light() else None
        structured_payload = self.build_market_review_payload(
            overview,
            news,
            report,
            snapshot,
        )

        logger.info("========== Market review finished ==========")

        return MarketLightReviewResult(
            overview=overview,
            report=report,
            market_light_snapshot=snapshot,
            structured_payload=structured_payload,
        )

    def _merge_persisted_market_intelligence(self, news: List) -> List:
        """Merge local persisted market intelligence and search news with bounded prompt/payload slot preservation."""
        search_news = list(news or [])
        merged_local = []
        seen_urls = {
            self._get_news_field(item, "url")
            for item in search_news
            if self._get_news_field(item, "url")
        }
        try:
            service = IntelligenceService(config=self.config)
            service.refresh_auto_sources()
            payload = service.list_items(
                scope_type="market",
                market=self.region,
                published_days=max(1, int(self.config.get_effective_news_window_days() or 1)),
                page=1,
                page_size=6,
            )
            for item in payload.get("items", []):
                if not isinstance(item, dict):
                    continue
                url = str(item.get("url") or "")
                if url and url in seen_urls:
                    continue
                seen_urls.add(url)
                merged_local.append({
                    "title": item.get("title") or "Untitled news",
                    "snippet": item.get("summary") or "",
                    "source": item.get("source") or item.get("source_name") or "local-intel",
                    "published_date": item.get("published_at") or "",
                    "url": "" if url.startswith("no-url:intel:") else url,
                })
        except Exception as exc:
            logger.debug("[Market] %s action=load_local_intelligence status=failed error=%s", self._log_context(), exc)
        merged_news = []
        merged_local_index = 0
        merged_search_index = 0
        while merged_local_index < len(merged_local) or merged_search_index < len(search_news):
            if merged_local_index < len(merged_local):
                merged_news.append(merged_local[merged_local_index])
                merged_local_index += 1
            if merged_search_index < len(search_news):
                merged_news.append(search_news[merged_search_index])
                merged_search_index += 1
        return merged_news

    def run_daily_review(self) -> str:
        """
        Run the daily broad-market review flow

        Returns:
            The review report text
        """
        return self.run_daily_review_with_snapshot().report

    def run_daily_review_with_snapshot(self) -> MarketLightReviewResult:
        """Run daily review and return the report plus its structured Market Light snapshot."""
        return self._run_daily_review_parts()


# Manual test entry point
if __name__ == "__main__":
    import sys
    sys.path.insert(0, '.')

    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s | %(levelname)-8s | %(name)-20s | %(message)s',
    )

    analyzer = MarketAnalyzer()

    # Test the market overview fetch
    overview = analyzer.get_market_overview()
    print("\n=== Market overview ===")
    print(f"Date: {overview.date}")
    print(f"Index count: {len(overview.indices)}")
    for idx in overview.indices:
        print(f"  {idx.name}: {idx.current:.2f} ({idx.change_pct:+.2f}%)")

    # Test the template report generation
    report = analyzer._generate_template_review(overview, [])
    print("\n=== Review report ===")
    print(report)

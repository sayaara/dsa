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
from src.report_language import resolve_report_language
from src.search_service import SearchService
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

_CHINESE_SECTION_PATTERNS = {
    "market_summary": r"###\s*一、(?:盘面总览|市场总结)",
    "index_commentary": r"###\s*二、(?:指数结构|指数点评|主要指数)",
    "sector_highlights": r"###\s*三、(?:板块主线|热点解读|板块表现)",
    "funds_sentiment": r"###\s*四、(?:资金与情绪|资金动向)",
    "news_catalysts": r"###\s*五、(?:消息催化|后市展望)",
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
            region: market region, ca = Canada, hk = HK, us = US
            config: the configuration for this review; the global configuration is read when omitted
        """
        self.config = config or get_config()
        self.search_service = search_service
        self.analyzer = analyzer
        self.data_manager = DataFetcherManager()
        self.region = region if region in ("us", "hk", "ca") else "us"
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
        """Return the truthful report language (zh/en/ko) for payload and directives."""
        return resolve_report_language(getattr(getattr(self, "config", None), "report_language", None))

    def _get_review_language(self) -> str:
        # Structural/template language. Korean reuses the English scaffolding;
        # the Korean output directive is applied in the prompt builder.
        language = self._get_output_language()
        return "en" if language == "ko" else language

    def _get_template_review_language(self) -> str:
        return self._get_review_language()

    def _get_market_scope_name(self, review_language: str | None = None) -> str:
        review_language = review_language or self._get_review_language()
        if self.region == "us":
            return "US market" if review_language == "en" else "美股市场"
        if self.region == "ca":
            return "Canadian market" if review_language == "en" else "加拿大市场"
        return "Hong Kong market" if review_language == "en" else "港股市场"

    def _get_turnover_unit_label(self) -> str:
        """Return the turnover unit label for the current market/language."""
        if self.region == "us":
            return "USD bn" if self._get_review_language() == "en" else "十亿美元"
        if self.region == "hk":
            return "HKD bn" if self._get_review_language() == "en" else "十亿港元"
        if self.region == "ca":
            return "CAD bn" if self._get_review_language() == "en" else "十亿加元"
        return "CNY 100m" if self._get_review_language() == "en" else "亿"

    def _format_turnover_value(self, amount_raw: float) -> str:
        """Format raw turnover according to market-specific units."""
        if amount_raw == 0.0:
            return "N/A"
        if self.region in ("us", "hk", "ca"):
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
        if self._get_review_language() == "en":
            market_names = {
                "us": "US Market Recap",
                "hk": "HK Market Recap",
                "ca": "Canada Market Recap",
            }
            market_name = market_names.get(self.region, "US Market Recap")
            return f"## {date} {market_name}"
        return f"## {date} 大盘复盘"

    def _get_index_hint(self) -> str:
        if self._get_review_language() == "en":
            if self.region == "us":
                return "Analyze the key moves in the S&P 500, Nasdaq, Dow, and other major indices."
            if self.region == "hk":
                return "Analyze the key moves in the HSI, Hang Seng Tech, HSCEI, and other major indices."
            if self.region == "ca":
                return "Analyze the key moves in the S&P/TSX Composite, the TSX Venture Composite, and other major indices."
            return "Analyze the price action in the SSE, SZSE, ChiNext, and other major indices."
        return self.profile.prompt_index_hint

    def _get_strategy_prompt_block(self) -> str:
        if self.region == "hk" and self._get_review_language() == "en":
            return """## Strategy Blueprint: Hong Kong Market Regime Strategy
Focus on HSI trend, southbound flow dynamics, and sector rotation to define next-session risk posture.

### Strategy Principles
- Read market regime from HSI, HSTECH, and HSCEI alignment first.
- Track southbound capital flow as a key sentiment driver.
- Translate recap into actionable risk-on/risk-off stance with clear invalidation points.

### Analysis Dimensions
- Trend Regime: Classify the market as momentum, range, or risk-off.
  - Are HSI/HSTECH/HSCEI directionally aligned
  - Did volume confirm the move
  - Are key index levels reclaimed or lost
- Capital Flows: Map southbound flow and macro narrative into equity risk appetite.
  - Southbound net flow direction and magnitude
  - USD/HKD and China policy implications
  - Breadth and leadership concentration
- Sector Themes: Identify persistent leaders and vulnerable laggards.
  - Tech/internet platform trend persistence
  - Financials/property sensitivity to policy shifts
  - Defensive vs growth factor rotation

### Action Framework
- Risk-on: broad index breakout with expanding southbound participation.
- Neutral: mixed index signals; focus on selective relative strength.
- Risk-off: failed breakouts and rising volatility; prioritize capital preservation."""
        if self.region == "ca" and self._get_review_language() == "zh":
            return """## 加拿大市场三段式复盘策略
聚焦标普/多伦多证交所综合指数趋势、大宗商品与利率叙事、板块轮动，给出次日风控与仓位框架。

### 策略原则
- 先看 S&P/TSX 综合指数方向，再看创业板综合指数反映的小盘风险偏好。
- 区分能源、材料等大宗商品驱动的行情与金融、科技板块的轮动。
- 将复盘输出映射为“进攻/均衡/防守”动作建议，并给出明确触发失效条件。

### 分析维度
- 趋势结构：判断市场处于上冲、震荡还是防守转向，关注关键支撑位是否被跌破。
- 宏观与商品：结合加拿大央行政策、国债收益率、加元汇率以及原油、天然气、黄金价格评估风险偏好。
- 主题主线：识别银行保险、能源管道、金矿与基本金属矿业等权重板块的持续性。

### 行动框架
- 进攻：指数共振上行且商品价格配合、参与度扩大。
- 均衡：指数分化或缩量震荡，仓位保守执行。
- 防守：突破失守、商品下跌或波动率抬升时，优先减码并保留反弹可交易性。"""
        if self.region == "us" and self._get_review_language() == "zh":
            return """## 美股市场三段式复盘策略
聚焦指数趋势、宏观叙事与板块轮动，给出次日风控与仓位框架。

### 策略原则
- 先看标普500、纳斯达克、道琼斯是否同向，确认主线是否一致。
- 结合宏观与流动性指标，识别风险偏好是修复还是转弱。
- 将复盘输出映射为“进攻/均衡/防守”动作建议，并给出明确触发失效条件。

### 分析维度
- 趋势结构：明确市场处于上冲、震荡还是防守转向，判断是否存在关键支撑位背离。
- 资金与情绪：区分宏观政策、货币面与波动率对权益风险的影响。
- 主题线索：识别持续性最强的主题与板块轮动是否形成可交易主线。

### 行动框架
- 进攻：主板块联动上行且量能/风险位同步改善。
- 均衡：指数分化或量能未明显放大，仓位保守执行。
- 防守：突破失守且波动率抬升时，优先减码并保留反弹可交易性。"""
        return self.strategy.to_prompt_block()

    def _get_strategy_markdown_block(self, review_language: str | None = None) -> str:
        review_language = review_language or self._get_review_language()
        if self.region == "hk" and review_language == "en":
            return """### 6. Strategy Framework
- **Trend Regime**: Classify the market as momentum, range, or risk-off based on HSI/HSTECH/HSCEI alignment.
- **Capital Flows**: Track southbound flow direction and macro narrative for risk appetite signals.
- **Sector Themes**: Focus on tech/internet platform persistence and financials/property policy sensitivity.
"""
        if self.region == "ca" and review_language == "zh":
            return """### 六、策略框架
- **趋势结构**：判断 S&P/TSX 综合指数与创业板综合指数是否同向，市场处于进攻、震荡还是防守。
- **宏观与商品**：结合央行政策、加元汇率与原油、黄金等商品价格评估风险偏好。
- **主题主线**：识别银行、能源、矿业等权重板块中可延续的主线与防守线索。
"""
        if self.region == "us" and review_language == "zh":
            return """### 六、策略框架
- **趋势结构**：判断市场在进攻、震荡与防守中的状态是否一致。
- **资金与情绪**：结合波动率、宽度和主题轮动评估风险偏好。
- **主题主线**：识别可延续和可放大的行业主线与防守线索。
"""
        return self.strategy.to_markdown_block()

    def _get_market_mood_text(self, mood_key: str, review_language: str | None = None) -> str:
        review_language = review_language or self._get_review_language()
        if review_language == "en":
            mapping = {
                "strong_up": "strong gains",
                "mild_up": "moderate gains",
                "mild_down": "mild losses",
                "strong_down": "clear weakness",
                "range": "range-bound trading",
            }
        else:
            mapping = {
                "strong_up": "强势上涨",
                "mild_up": "小幅上涨",
                "mild_down": "小幅下跌",
                "strong_down": "明显下跌",
                "range": "震荡整理",
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
        
        # Fetch the main index quotes (switched by region between Canada, US and HK)
        overview.indices = self._get_main_indices()

        return overview

    
    def _get_main_indices(self) -> List[MarketIndex]:
        """Fetch the main index real-time quotes"""
        indices = []

        try:
            logger.info("[大盘] %s action=get_main_indices status=start", self._log_context())

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
                logger.warning("[大盘] %s action=get_main_indices status=empty", self._log_context())
            else:
                logger.info(
                    "[大盘] %s action=get_main_indices status=success count=%d",
                    self._log_context(),
                    len(indices),
                )

        except Exception as e:
            logger.error("[大盘] %s action=get_main_indices status=failed error=%s", self._log_context(), e)

        return indices

    def search_market_news(self) -> List[Dict]:
        """
        Search market news
        
        Returns:
            The news list
        """
        if not self.search_service:
            logger.warning(
                "[大盘] %s action=search_market_news status=skipped reason=no_search_service",
                self._log_context(),
            )
            return []
        
        all_news = []

        # Use different news search terms per region
        search_queries = self.profile.news_queries
        review_language = self._get_review_language()
        market_names = {
            "us": "美股市场" if review_language == "zh" else "US market",
            "hk": "港股市场" if review_language == "zh" else "HK market",
            "ca": "加拿大市场" if review_language == "zh" else "Canadian market",
        }
        
        try:
            logger.info("[大盘] %s action=search_market_news status=start", self._log_context())
            
            # Set the search context name from the region so a US search is not read as a different market
            market_name = market_names.get(self.region, "大盘")
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
                        "[大盘] %s action=search_market_news status=query_success count=%d",
                        self._log_context(),
                        len(response.results),
                    )
            
            logger.info(
                "[大盘] %s action=search_market_news status=success count=%d",
                self._log_context(),
                len(all_news),
            )
            
        except Exception as e:
            logger.error("[大盘] %s action=search_market_news status=failed error=%s", self._log_context(), e)
        
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
                "[大盘] %s action=generate_review status=failed error_type=%s error=%s",
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
                "[大盘] %s action=generate_review status=fallback_template reason=no_analyzer",
                self._log_context(),
            )
            return self._generate_template_review(overview, news)

        # Build the prompt
        prompt = self._build_review_prompt(overview, news)

        logger.info("[大盘] %s action=generate_review status=start", self._log_context())
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
                "[大盘] %s action=generate_review status=success length=%d",
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
            "[大盘] %s action=generate_review status=fallback_template reason=empty_llm_response",
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
        patterns = (
            _ENGLISH_SECTION_PATTERNS
            if self._get_review_language() == "en"
            else _CHINESE_SECTION_PATTERNS
        )

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
        """Build the market-signal block (CA/HK/US have no breadth statistics)."""
        if not (self._supports_market_light() and overview.indices):
            return ""
        light = self.build_market_light_snapshot(overview)
        if self._get_review_language() == "en":
            return "\n".join(
                [
                    f"- **Market Signal**: {light['score']}/100 "
                    f"({light['temperature_label']}, {light['label']})",
                    f"- **Drivers**: {'; '.join(light['reasons'])}",
                    f"- **Guidance**: {light['guidance']}",
                ]
            )
        return "\n".join(
            [
                f"- **盘面信号**：{light['score']}/100（{light['temperature_label']}，{light['label']}）",
                f"- **信号依据**：{'；'.join(light['reasons'])}",
                f"- **操作建议**：{light['guidance']}",
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

        if self._get_review_language() == "en":
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
        else:
            label_map = {
                "green": "可进攻",
                "yellow": "需观察",
                "red": "偏防守",
            }
            guidance_map = {
                "green": "风险偏好尚可，关注主线延续与仓位纪律。",
                "yellow": "信号分化，控制仓位并等待量价确认。",
                "red": "风险偏高，优先控制回撤，避免追高弱反弹。",
            }
            reasons = self._build_market_light_reasons_zh(overview, score)

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

    def _build_market_light_reasons_zh(self, overview: MarketOverview, score: int) -> List[str]:
        reasons: List[str] = []
        index_changes = [idx.change_pct for idx in overview.indices if idx.change_pct is not None]
        if index_changes:
            avg_change = sum(index_changes) / len(index_changes)
            reasons.append(f"主要指数平均涨跌幅 {avg_change:+.2f}%")
        if not reasons:
            reasons.append("结构化涨跌数据有限，按可用行情综合判断")
        return reasons

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
        if self._get_review_language() == "en":
            lines = [
                f"| Index | Last | Change % | Open | High | Low | Amplitude | Turnover ({self._get_turnover_unit_label()}) |",
                "|-------|------|----------|------|------|-----|-----------|-----------------|",
            ]
        else:
            lines = [
                "| 指数 | 最新 | 涨跌幅 | 开盘 | 最高 | 最低 | 振幅 | 成交额(亿) |",
                "|------|------|--------|------|------|------|------|-----------|",
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
        if language == "en":
            lines = [
                "#### News Catalysts",
            ]
        else:
            lines = [
                "#### 近三日市场线索",
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
        language = resolve_report_language(language)
        fallback_title = "Untitled catalyst" if language == "en" else "未命名线索"
        title = cls._compact_news_text(cls._get_news_field(item, "title"), limit=90) or fallback_title
        source = cls._compact_news_text(cls._get_news_field(item, "source"), limit=40)
        date_text = cls._compact_news_text(cls._get_news_field(item, "published_date"), limit=24)
        url = cls._compact_news_text(cls._get_news_field(item, "url"), limit=0)
        title_text = cls._escape_markdown_link_label(title)
        if url:
            title_text = f"[{title_text}]({url})"
        meta_parts = [part for part in (source, date_text) if part]
        if language == "en":
            meta = f" ({' / '.join(meta_parts)})" if meta_parts else ""
        else:
            meta = f"（{' / '.join(meta_parts)}）" if meta_parts else ""
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

        # Breadth and limit-up/down data are not available for CA/HK/US, so those
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
        if self._get_review_language() == "en":
            if score >= 70:
                label = "risk-on"
            elif score >= 55:
                label = "constructive"
            elif score >= 40:
                label = "mixed"
            else:
                label = "defensive"
        else:
            if score >= 70:
                label = "强势"
            elif score >= 55:
                label = "偏暖"
            elif score >= 40:
                label = "震荡"
            else:
                label = "偏弱"
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
        if review_language == "en":
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

        numerals = ["一", "二", "三", "四", "五", "六", "七", "八"]
        section_number = 3
        sections: List[str] = []

        def add_section(title: str, hint: str) -> None:
            nonlocal section_number
            sections.append(f"### {numerals[section_number - 1]}、{title}\n{hint}")
            section_number += 1

        add_section(
            "消息催化",
            "（结合近三日新闻和指数表现，提炼真正影响明日交易的催化或扰动；不要推断未提供的资金流、市场宽度或板块榜）",
        )
        add_section("明日交易计划", "（给出进攻/均衡/防守结论、仓位区间、关注方向、回避方向和一个触发失效条件）")
        add_section("风险提示", "（列出需要关注的风险点；最后补充“建议仅供参考，不构成投资建议”。）")
        return "\n\n".join(sections)

    def _build_review_prompt(self, overview: MarketOverview, news: List) -> str:
        """Build the review report prompt"""
        review_language = self._get_review_language()
        # Korean reuses the English structural template but the model is told to
        # write the entire shell, headings, guidance and conclusion in Korean.
        shell_language_label = "Korean (한국어)" if self._get_output_language() == "ko" else "English"

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
        
        # None of the supported markets (CA/HK/US) has advance-decline counts or sector data
        data_limits_block = (
            "## Data Limits\n"
            "- Market breadth, aggregate turnover, participation, and fund-flow signals are not available for this market.\n"
            "- Sector/theme ranking data is not available for this market."
            if review_language == "en"
            else "## 数据边界\n"
            "- 该市场暂无涨跌家数、涨跌停、成交额汇总、参与度或资金流信号。\n"
            "- 该市场暂无行业板块/概念题材涨跌榜。"
        )

        data_no_indices_hint = (
            "注意：由于行情数据获取失败，请主要根据【市场新闻】进行定性分析和总结，不要编造具体的指数点位。"
            if not indices_text
            else ""
        )
        if review_language == "en":
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
        else:
            indices_placeholder = indices_text if indices_text else "暂无指数数据（接口异常）"
            news_placeholder = news_text if news_text else "暂无相关新闻"
            data_boundary_requirement = (
                "- 严格遵守数据边界：未提供涨跌家数、资金流、成交额汇总或板块榜时，不要编造或过度解读。\n"
            )
            market_summary_hint = "2-3句话概括指数表现、新闻线索和整体风险状态，不要补写未提供的市场宽度或资金流数据"

        output_template_sections = self._build_output_template_sections(review_language)
        zh_report_title = f"{overview.date} 大盘复盘"
        workflow_hint = "报告要像交易员盘后工作台：先给结论，再按指数、新闻催化和计划展开"

        if review_language == "en":
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

        # The default path uses Chinese prompt wording
        return f"""你是一位专业的{self._get_market_scope_name('zh')}分析师，请根据以下数据生成一份结构化的{self._get_market_scope_name('zh')}大盘复盘报告。

【重要】输出要求：
- 必须输出纯 Markdown 文本格式
- 禁止输出 JSON 格式
- 禁止输出代码块
- emoji 仅在标题处少量使用（每个标题最多1个）
- {workflow_hint}
- 不要重复列出已由系统注入的表格数据；正文负责解释表格背后的含义
{data_boundary_requirement}

---

# 今日市场数据

## 日期
{overview.date}

## 主要指数
{indices_placeholder}

{data_limits_block}

## 市场新闻
{news_placeholder}

{data_no_indices_hint}

{self._get_strategy_prompt_block()}

---

# 输出格式模板（请严格按此格式输出）

## {zh_report_title}

> 一句话给出今日市场状态、核心矛盾和明日优先观察方向。

### 一、盘面总览
（{market_summary_hint}）

### 二、指数结构
（{self._get_index_hint()}，说明谁在护盘、谁在拖累，以及关键支撑/压力）

{output_template_sections}

---

请直接输出复盘报告内容，不要输出其他说明文字。
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
        
        if template_language == "en":
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
                "hk": "HK Market Recap",
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

        market_labels = {"us": "美股", "hk": "港股", "ca": "加拿大"}
        market_label = market_labels.get(self.region, "美股")
        dashboard_block = self._build_stats_block(overview) if self._supports_market_light() else ""
        indices_block = self._build_indices_block(overview)
        market_summary_block = dashboard_block or "- 当前以主要指数与可用新闻线索评估整体风险状态。"
        return f"""## {overview.date} 大盘复盘

> 今日{market_label}市场整体呈现**{market_mood}**态势，优先观察指数承接、消息催化和整体风险状态。

### 一、盘面总览
{market_summary_block}

### 二、指数结构
{indices_block or indices_text or "暂无指数数据。"}

### 五、消息催化
- 暂无可用新闻时，应降低对题材持续性的确定性判断。

{self._get_strategy_markdown_block(template_language)}

### 七、风险提示
- 市场有风险，投资需谨慎。以上数据仅供参考，不构成投资建议。

---
*复盘时间: {datetime.now().strftime('%H:%M')}*
"""
    
    def _run_daily_review_parts(self) -> MarketLightReviewResult:
        """Run market review once and keep report/snapshot on the same overview."""
        logger.info("========== 开始大盘复盘分析 ==========")

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

        logger.info("========== 大盘复盘分析完成 ==========")

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
                    "title": item.get("title") or "未命名资讯",
                    "snippet": item.get("summary") or "",
                    "source": item.get("source") or item.get("source_name") or "local-intel",
                    "published_date": item.get("published_at") or "",
                    "url": "" if url.startswith("no-url:intel:") else url,
                })
        except Exception as exc:
            logger.debug("[大盘] %s action=load_local_intelligence status=failed error=%s", self._log_context(), exc)
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
    print(f"\n=== 市场概览 ===")
    print(f"日期: {overview.date}")
    print(f"指数数量: {len(overview.indices)}")
    for idx in overview.indices:
        print(f"  {idx.name}: {idx.current:.2f} ({idx.change_pct:+.2f}%)")
    
    # Test the template report generation
    report = analyzer._generate_template_review(overview, [])
    print(f"\n=== 复盘报告 ===")
    print(report)

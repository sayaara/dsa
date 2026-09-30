# -*- coding: utf-8 -*-
"""DSA-native stock screening service.

The bundled screening implementation incorporates code derived from AlphaSift;
see ``THIRD_PARTY_NOTICES.md`` and per-file headers for attribution.
"""

from __future__ import annotations

import importlib
import json
import logging
import math
import os
import re
import threading
import uuid
from contextvars import ContextVar
from contextlib import contextmanager
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Iterator, List, Optional, Tuple

from fastapi import HTTPException
from pydantic import BaseModel, Field

from src.config import Config, get_configured_llm_models, normalize_llm_channel_api_surface
from src.services.screening import REFERENCE_PROJECT, REFERENCE_REVISION, __version__ as SCREENING_VERSION
from src.services.screening.config import Config as ScreeningPipelineConfig
from src.services.screening.pipeline import screen as run_screening_pipeline
from src.services.screening.strategy import list_strategies as load_screening_strategies
from src.storage import DatabaseManager

logger = logging.getLogger(__name__)

SCREENING_MANAGED_LITELLM_PROVIDERS = frozenset({"gemini", "vertex_ai", "anthropic", "openai", "deepseek"})
SCREENING_CONTRACT_VERSION = "1"
_SCREENING_RUNTIME_ENV_LOCK = threading.RLock()
DSA_ENRICHMENT_MAX_CANDIDATES = 3
DSA_PRE_RANK_CONTEXT_MAX_CANDIDATES = 3
DSA_SCREENING_LLM_CANDIDATE_MULTIPLIER = 2
DSA_SCREENING_LLM_MAX_CANDIDATES = 12
DSA_SCREENING_DAILY_FETCH_RETRIES = 3
DSA_SCREENING_SNAPSHOT_SOURCE_PRIORITY = "yfinance"
DSA_SCREENING_CANDIDATE_CONTEXT_PROVIDERS = "news"
DSA_SCREENING_DATA_DIR = Path("data") / "screening"
_DSA_FETCHER_MANAGER_LOCK = threading.RLock()
_DSA_FETCHER_MANAGER: Any = None
_FUNDAMENTAL_BLOCKS = ("valuation", "growth", "earnings", "institution", "capital_flow", "boards")
_SCREENING_LITELLM_COMPLETION_ROUTES: ContextVar[Optional[Tuple[Dict[str, Any], ...]]] = ContextVar(
    "screening_litellm_completion_routes",
    default=None,
)
_SCREENING_LITELLM_COMPLETION_ATTR = "_screening_litellm_completion_bridge"
_SCREENING_LITELLM_COMPLETION_LOCK = threading.Lock()


def _safe_float(value: Any) -> Optional[float]:
    try:
        if value is None or value == "":
            return None
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    return number


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _resolve_screening_data_dir() -> Path:
    configured = _env_text(os.getenv("SCREENING_DATA_DIR"))
    if configured:
        return Path(configured)
    return DSA_SCREENING_DATA_DIR


class ScreeningStrategyResponse(BaseModel):
    id: str
    name: str = ""
    title: str = ""
    description: str = ""
    category: str = ""
    tag: str = ""
    tags: List[str] = Field(default_factory=list)
    market_scope: List[str] = Field(default_factory=list)
    market: str = ""
    analysis_skills: List[str] = Field(default_factory=list)


class ScreeningService:
    """Coordinate stock screening with DSA-owned capabilities."""

    def __init__(self, config: Config, db_manager: Optional[DatabaseManager] = None):
        self.config = config
        self.db_manager = db_manager

    def status(self) -> Dict[str, Any]:
        engine_status, available, diagnostics = _get_screening_status_snapshot()
        payload = {
            "enabled": bool(self.config.screening_enabled),
            "available": available,
            "engine": engine_status.get("engine") or "builtin",
            "contract_version": engine_status.get("contract_version"),
            "version": engine_status.get("version"),
            "strategy_count": engine_status.get("strategy_count"),
            "reference_project": engine_status.get("reference_project"),
            "reference_revision": engine_status.get("reference_revision"),
        }
        source_health = _get_screening_source_health_snapshot()
        if source_health:
            payload["source_health"] = source_health
        if diagnostics:
            payload["diagnostics"] = diagnostics
        return payload

    def strategies(self) -> Dict[str, Any]:
        _ensure_screening_enabled(self.config)
        _ensure_screening_available_for_use()
        strategies = _list_strategies()
        return {
            "enabled": True,
            "strategies": strategies,
            "strategy_count": len(strategies),
        }

    def history(
        self,
        *,
        limit: int = 20,
        strategy: str = "",
        market: str = "",
    ) -> Dict[str, Any]:
        _ensure_screening_enabled(self.config)
        db_manager = self._require_history_database()
        runs = db_manager.list_screening_runs(
            limit=limit,
            strategy=_env_text(strategy) or None,
            market=_env_text(market) or None,
        )
        return {
            "enabled": True,
            "runs": runs,
            "run_count": len(runs),
        }

    def history_detail(self, run_id: str) -> Dict[str, Any]:
        _ensure_screening_enabled(self.config)
        db_manager = self._require_history_database()
        run = db_manager.get_screening_run(run_id)
        if run is None:
            raise HTTPException(
                status_code=404,
                detail={
                    "error": "screening_run_not_found",
                    "message": f"选股运行 {run_id} 不存在。",
                },
            )
        return {"enabled": True, **run}

    def source_history(self, *, limit: int = 100) -> Dict[str, Any]:
        _ensure_screening_enabled(self.config)
        db_manager = self._require_history_database()
        runs = db_manager.list_screening_runs(limit=limit)
        return _summarize_screening_source_history(runs)

    def _require_history_database(self) -> DatabaseManager:
        if self.db_manager is None:
            raise HTTPException(
                status_code=503,
                detail={
                    "error": "screening_history_unavailable",
                    "message": "DSA 数据库未注入，无法读取选股运行历史。",
                },
            )
        return self.db_manager

    def screen(
        self,
        *,
        strategy: str,
        market: str,
        max_results: int,
        selection_seed: str = "",
        progress_callback: Callable[[int, str], None] | None = None,
    ) -> Dict[str, Any]:
        _ensure_screening_enabled(self.config)
        _ensure_screening_available_for_use()
        _ensure_supported_market(market)
        _ensure_supported_strategy(strategy)

        try:
            raw = _call_screening_screen(
                strategy,
                market,
                max_results,
                self.config,
                selection_seed=selection_seed,
                progress_callback=progress_callback,
            )
        except ValueError as exc:
            raise HTTPException(
                status_code=400,
                detail={"error": "screening_screen_rejected", "message": str(exc)},
            ) from exc
        except (TypeError, KeyError) as exc:
            raise HTTPException(
                status_code=422,
                detail={"error": "screening_invalid_input", "message": f"Screening 参数非法：{exc}"},
            ) from exc
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(
                status_code=424,
                detail={"error": "screening_screen_failed", "message": f"Screening 选股运行失败：{exc}"},
            ) from exc

        raw_data = _to_plain(raw)
        if not isinstance(raw_data, dict):
            raw_data = {"candidates": raw_data}
        raw_data = _remove_non_finite_json_values(raw_data)

        candidates = _normalize_candidates(raw_data)
        selected = candidates[:max_results]
        _emit_screening_progress(
            progress_callback,
            92,
            "正在补充入选股票的新闻与事件",
        )
        selected, dsa_enrichment = _enrich_candidates_with_dsa(selected)
        warnings = _collect_screening_warning_messages(raw_data)
        response = {
            "enabled": True,
            "candidates": selected,
            "candidate_count": len(selected),
            "run_id": raw_data.get("run_id") or uuid.uuid4().hex,
            "strategy": raw_data.get("strategy") or strategy,
            "market": raw_data.get("market") or market,
            "snapshot_count": raw_data.get("snapshot_count"),
            "snapshot_source": raw_data.get("snapshot_source") or "",
            "after_filter_count": raw_data.get("after_filter_count"),
            "llm_ranked": raw_data.get("llm_ranked"),
            "llm_market_view": raw_data.get("llm_market_view") or "",
            "llm_selection_logic": raw_data.get("llm_selection_logic") or "",
            "llm_portfolio_risk": raw_data.get("llm_portfolio_risk") or "",
            "llm_coverage": raw_data.get("llm_coverage"),
            "llm_parse_errors": _list_text_values(raw_data.get("llm_parse_errors")),
            "llm_model_used": raw_data.get("llm_model_used") or "",
            "llm_attempted_models": _list_text_values(raw_data.get("llm_attempted_models")),
            "llm_failure_reason": raw_data.get("llm_failure_reason") or "",
            "ranking_mode": raw_data.get("ranking_mode") or (
                "llm" if raw_data.get("llm_ranked") else "factor"
            ),
            "degradation": _list_text_values(raw_data.get("degradation")),
            "warnings": warnings,
            "source_errors": _list_text_values(raw_data.get("source_errors")),
            "dsa_enrichment": dsa_enrichment,
            "deep_analysis_requested": raw_data.get("deep_analysis_requested"),
            "post_analyzers": raw_data.get("post_analyzers") or [],
            "daily_enriched": raw_data.get("daily_enriched"),
            "daily_enrich_count": raw_data.get("daily_enrich_count"),
            "risk_enabled": raw_data.get("risk_enabled"),
            "portfolio_diversity_enabled": raw_data.get("portfolio_diversity_enabled"),
            "portfolio_concentration_notes": raw_data.get("portfolio_concentration_notes") or [],
            "result_variant_applied": bool(raw_data.get("result_variant_applied")),
            "result_variant_pool_size": raw_data.get("result_variant_pool_size") or 0,
            "result_variant_rotated_slots": raw_data.get("result_variant_rotated_slots") or 0,
        }
        if self.db_manager is not None:
            self.db_manager.save_screening_run(response)
        return response


def _emit_screening_progress(
    callback: Callable[[int, str], None] | None,
    progress: int,
    message: str,
) -> None:
    if callback is None:
        return
    try:
        callback(progress, message)
    except Exception as exc:  # noqa: BLE001 - progress reporting must not fail screening.
        logger.debug("Screening service progress callback failed: %s", exc)


def _list_text_values(value: Any) -> List[str]:
    if value is None:
        return []
    if isinstance(value, str):
        text = _env_text(value)
        return [text] if text else []
    if not isinstance(value, list):
        text = _env_text(value)
        return [text] if text else []
    return [text for item in value if (text := _env_text(item))]


def _list_dict_values(value: Any) -> List[Dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _ensure_screening_enabled(config: Config) -> None:
    if not config.screening_enabled:
        raise HTTPException(
            status_code=403,
            detail={"error": "screening_disabled", "message": "SCREENING_ENABLED is false."},
        )


def _ensure_screening_available_for_use() -> None:
    _, available, diagnostics = _get_screening_status_snapshot()
    if available:
        return
    normalized_diagnostics = _include_screening_diagnostic_suffix(diagnostics)
    raise _screening_unavailable_exception(
        "选股功能初始化失败，请检查策略文件、依赖和服务端日志。",
        diagnostics=normalized_diagnostics,
    )


def _include_screening_diagnostic_suffix(
    diagnostics: Optional[Dict[str, str]],
) -> Optional[Dict[str, str]]:
    if diagnostics is None:
        return None
    normalized = dict(diagnostics)
    normalized.setdefault("resolution", "builtin_engine")
    normalized.setdefault(
        "message",
        "请检查后端日志、策略资源和基础数据依赖。",
    )
    return normalized


def _get_screening_status_snapshot() -> Tuple[Dict[str, Any], bool, Optional[Dict[str, str]]]:
    try:
        engine_status = _call_screening_status()
    except HTTPException as exc:
        return {}, False, _extract_screening_diagnostics(exc)
    except Exception as exc:
        diagnostics = _log_unexpected_screening_exception("status_probe", exc)
        return {}, False, diagnostics

    return engine_status, _is_engine_available(engine_status), None


def _get_screening_source_health_snapshot() -> Dict[str, Any]:
    health: Dict[str, Any] = {}
    for module_name, key, function_name in (
        ("src.services.screening.snapshot", "snapshot", "snapshot_source_health_snapshot"),
        ("src.services.screening.daily", "daily", "daily_source_health_snapshot"),
    ):
        try:
            module = importlib.import_module(module_name)
            snapshot_func = getattr(module, function_name, None)
            if callable(snapshot_func):
                snapshot = _remove_non_finite_json_values(_to_plain(snapshot_func()))
                if snapshot:
                    health[key] = snapshot
        except Exception as exc:
            logger.debug("Screening %s source health snapshot unavailable: %s", key, exc)
    return health


def _is_engine_available(engine_status: Any) -> bool:
    if isinstance(engine_status, dict):
        return bool(engine_status.get("available", True))
    return True


def _call_screening_status() -> Dict[str, Any]:
    try:
        strategy_count = len(load_screening_strategies())
    except Exception as exc:
        diagnostics = _log_unexpected_screening_exception("strategy_load", exc)
        raise _screening_unavailable_exception(
            f"选股功能状态检查失败：{exc}",
            diagnostics=diagnostics,
        ) from exc
    return {
        "available": True,
        "engine": "builtin",
        "version": SCREENING_VERSION,
        "contract_version": SCREENING_CONTRACT_VERSION,
        "strategy_count": strategy_count,
        "reference_project": REFERENCE_PROJECT,
        "reference_revision": REFERENCE_REVISION,
    }


def _screening_unavailable_exception(
    message: str,
    *,
    diagnostics: Optional[Dict[str, str]] = None,
) -> HTTPException:
    detail: Dict[str, Any] = {"error": "screening_unavailable", "message": message}
    if diagnostics:
        detail["diagnostics"] = diagnostics
    return HTTPException(status_code=424, detail=detail)


def _log_unexpected_screening_exception(stage: str, exc: BaseException) -> Dict[str, str]:
    logger.warning("Unexpected Screening %s failure: %s", stage, exc, exc_info=exc.__traceback__ is not None)
    return {
        "reason": "unexpected_exception",
        "stage": stage,
        "error_type": exc.__class__.__name__,
    }


def _extract_screening_diagnostics(exc: HTTPException) -> Optional[Dict[str, str]]:
    detail = exc.detail if isinstance(exc.detail, dict) else {}
    diagnostics = detail.get("diagnostics")
    if not isinstance(diagnostics, dict):
        return None
    return {str(key): str(value) for key, value in diagnostics.items()}


def _list_strategies() -> List[Dict[str, Any]]:
    raw = _to_plain(load_screening_strategies())
    if not isinstance(raw, list):
        raise HTTPException(
            status_code=424,
            detail={"error": "screening_invalid_result", "message": "选股策略列表结构非法。"},
        )

    normalized: List[Dict[str, Any]] = []
    for item in raw:
        strategy = _normalize_strategy(item)
        if not strategy.get("id"):
            continue
        normalized.append(strategy)
    return normalized


def _normalize_strategy(raw: Any) -> Dict[str, Any]:
    item = _to_plain(raw)
    if isinstance(item, str):
        return _strategy_model(id=item, name=item, title=item)
    if not isinstance(item, dict):
        value = str(item)
        return _strategy_model(id=value, name=value, title=value)

    tags = item.get("tags") if isinstance(item.get("tags"), list) else []
    market_scope = item.get("market_scope") or item.get("marketScope") or []
    if not isinstance(market_scope, list):
        market_scope = [str(market_scope)] if market_scope else []

    strategy_id = str(
        item.get("id")
        or item.get("strategy")
        or item.get("strategy_id")
        or item.get("name")
        or "",
    )
    name = str(item.get("display_name") or item.get("name") or item.get("title") or strategy_id)
    category = str(item.get("category") or item.get("tag") or "")
    return _strategy_model(
        id=strategy_id,
        name=name,
        title=str(item.get("title") or name),
        description=str(item.get("description") or ""),
        category=category,
        tag=str(item.get("tag") or category),
        tags=[str(tag) for tag in tags],
        market_scope=[str(market) for market in market_scope],
        market=str(item.get("market") or item.get("market_id") or ""),
        analysis_skills=_list_text_values(
            item.get("analysis_skills") or item.get("analysisSkills")
        ),
    )


def _strategy_model(**kwargs: Any) -> Dict[str, Any]:
    normalized = ScreeningStrategyResponse(**kwargs)
    try:
        return normalized.model_dump()
    except AttributeError:
        return normalized.dict()


def _summarize_screening_source_history(runs: List[Dict[str, Any]]) -> Dict[str, Any]:
    source_stats: Dict[str, Dict[str, Any]] = {}
    fallback_runs = 0

    def source_entry(source: str) -> Dict[str, Any]:
        return source_stats.setdefault(
            source,
            {
                "selected_runs": 0,
                "error_count": 0,
                "last_seen_at": None,
                "error_samples": [],
            },
        )

    for run in runs:
        created_at = run.get("created_at")
        selected_source = _env_text(run.get("snapshot_source")) or "unknown"
        selected = source_entry(selected_source)
        selected["selected_runs"] += 1
        if not selected["last_seen_at"]:
            selected["last_seen_at"] = created_at

        errors = _list_text_values(run.get("source_errors"))
        warnings = _collect_screening_warning_messages(run)
        if errors or any("fallback" in warning.lower() or "降级" in warning for warning in warnings):
            fallback_runs += 1
        for error in errors:
            source = _screening_source_from_error(error)
            entry = source_entry(source)
            entry["error_count"] += 1
            if not entry["last_seen_at"]:
                entry["last_seen_at"] = created_at
            samples = entry["error_samples"]
            if error not in samples and len(samples) < 5:
                samples.append(error)

    return {
        "enabled": True,
        "runs_analyzed": len(runs),
        "fallback_runs": fallback_runs,
        "sources": dict(sorted(source_stats.items())),
    }


def _screening_source_from_error(error: str) -> str:
    text = _env_text(error)
    match = re.search(
        r"(?:snapshot source fallback:\s*)?([a-zA-Z][a-zA-Z0-9_-]{1,31})\s*(?:after\s+\d+\s+attempts)?\s*:",
        text,
        flags=re.IGNORECASE,
    )
    return match.group(1).lower() if match else "unknown"


def _ensure_supported_strategy(strategy: str) -> None:
    strategies = _list_strategies()
    if not strategies:
        return

    ids = {item.get("id") for item in strategies if item.get("id")}
    if strategy in ids:
        return

    # The screening engine performs final validation of strategy parameters; pass them through here to support custom strategies.


def _call_screening_screen(
    strategy: str,
    market: str,
    max_results: int,
    config: Config,
    *,
    selection_seed: str = "",
    progress_callback: Callable[[int, str], None] | None = None,
) -> Any:
    # Environment bridging is process-global, so keep it brief: materialize an
    # immutable pipeline config while holding the lock, then release it before
    # any network or LLM work.
    with _screening_runtime_env(config, max_results=max_results):
        pipeline_config = ScreeningPipelineConfig.from_env()
        pipeline_context = _build_screening_context(config, max_results=max_results)

    daily_history_fetcher = _build_screening_dsa_daily_history_fetcher()
    with _screening_litellm_headers(config):
        return run_screening_pipeline(
            strategy,
            market=market,
            max_output=max_results,
            use_llm=True,
            selection_seed=selection_seed,
            context=pipeline_context,
            config=pipeline_config,
            progress_callback=progress_callback,
            daily_history_fetcher=daily_history_fetcher,
        )


@contextmanager
def _screening_runtime_env(config: Config, *, max_results: Optional[int] = None) -> Iterator[None]:
    updates = _build_screening_runtime_env(config, max_results=max_results)
    if not updates:
        yield
        return

    sentinel = object()
    with _SCREENING_RUNTIME_ENV_LOCK:
        previous = {key: os.environ.get(key, sentinel) for key in updates}
        os.environ.update(updates)
        try:
            yield
        finally:
            for key, value in previous.items():
                if value is sentinel:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value  # type: ignore[assignment]


def _build_screening_dsa_daily_history_fetcher() -> Optional[Callable[..., Any]]:
    """Build one request-local DSA-first daily-history fetcher.

    The returned closure captures the bundled Screening fetcher as its
    fallback. It never replaces ``daily.fetch_daily_history``, so overlapping
    screening requests cannot restore stale wrappers or build wrapper chains.
    """
    try:
        daily_module = importlib.import_module("src.services.screening.daily")
    except Exception:
        return None

    original_fetch = getattr(daily_module, "fetch_daily_history", None)
    if not callable(original_fetch):
        return None

    def fetch_daily_history_with_dsa(
        code: str,
        *,
        lookback_days: int = 120,
        source: str = "yfinance",
        retries: int = 2,
        cache_dir: str | Path | None = None,
        cache_ttl_seconds: float | None = None,
    ) -> Any:
        try:
            dsa_df, dsa_source = get_dsa_daily_history(code, lookback_days=lookback_days)
            normalized = _normalize_dsa_daily_history(dsa_df)
            if normalized is not None and not normalized.empty:
                resolved_source = f"dsa:{dsa_source}"
                normalized_code = code
                normalize_code = getattr(daily_module, "_normalize_daily_code", None)
                if callable(normalize_code):
                    normalized_code = normalize_code(code)
                normalized.attrs["source"] = resolved_source
                normalized.attrs["daily_source"] = resolved_source
                normalized.attrs["daily_requested_source"] = source
                normalized.attrs["daily_source_order"] = [resolved_source]
                normalized.attrs["daily_source_order_notes"] = []
                normalized.attrs["source_errors"] = []
                normalized.attrs["daily_source_health"] = {}
                if cache_dir is not None:
                    cache_path_builder = getattr(daily_module, "_daily_history_cache_path", None)
                    cache_writer = getattr(daily_module, "_write_daily_history_cache", None)
                    if callable(cache_path_builder) and callable(cache_writer):
                        cache_path = cache_path_builder(
                            cache_dir,
                            code=normalized_code,
                            source=source,
                            lookback_days=int(lookback_days),
                        )
                        cache_writer(
                            cache_path,
                            normalized,
                            code=normalized_code,
                            source=source,
                            lookback_days=int(lookback_days),
                        )
                return normalized
        except Exception as exc:
            logger.warning(
                "Screening DSA daily history fetch failed for %s; falling back to Screening source %s: %s",
                code,
                source,
                exc,
            )
        return original_fetch(
            code,
            lookback_days=lookback_days,
            source=source,
            retries=retries,
            cache_dir=cache_dir,
            cache_ttl_seconds=cache_ttl_seconds,
        )

    return fetch_daily_history_with_dsa


def _build_screening_runtime_env(config: Config, *, max_results: Optional[int] = None) -> Dict[str, str]:
    # Bridge runtime only: only inject resolved DSA values for this request/process scope.
    # User .env/config is never rewritten here; unset channels/models are not silently migrated.
    # Consistent with the LiteLLM provider/model, openai-compatible `api_base` and header injection semantics;
    # see https://docs.litellm.ai/docs/providers and
    # https://docs.litellm.ai/docs/proxy/configs#the-model_list-key
    env: Dict[str, str] = {}

    def put(key: str, value: Any) -> None:
        text = _env_text(value)
        if text:
            env[key] = text

    def put_default(key: str, value: Any) -> None:
        if os.getenv(key) not in (None, ""):
            return
        put(key, value)

    litellm_model, fallback_models = _resolve_screening_llm_models(config)
    put("LITELLM_MODEL", litellm_model)
    if fallback_models:
        put("LITELLM_FALLBACK_MODELS", ",".join(fallback_models))
    put("LITELLM_CONFIG", config.litellm_config_path)
    if os.getenv("LLM_TEMPERATURE") not in (None, ""):
        put("LLM_TEMPERATURE", config.llm_temperature)

    channels = _normalize_dsa_llm_channels(config)
    if channels:
        put("LLM_CHANNELS", ",".join(channel["name"] for channel in channels))
        for channel in channels:
            prefix = channel["name"].upper()
            put(f"LLM_{prefix}_ENABLED", "true")
            put(f"LLM_{prefix}_PROTOCOL", channel.get("protocol"))
            put(f"LLM_{prefix}_API_SURFACE", channel.get("api_surface"))
            put(f"LLM_{prefix}_BASE_URL", channel.get("base_url"))
            put(f"LLM_{prefix}_API_KEYS", ",".join(channel.get("api_keys") or []))
            put(f"LLM_{prefix}_MODELS", ",".join(channel.get("models") or []))
            if channel.get("extra_headers"):
                put(
                    f"LLM_{prefix}_EXTRA_HEADERS",
                    json.dumps(channel.get("extra_headers"), ensure_ascii=False),
                )

    gemini_keys = _dedupe_strings([
        *(config.gemini_api_keys or []),
        *_channel_keys_for_provider(channels, {"gemini", "vertex_ai"}),
    ])
    anthropic_keys = _dedupe_strings([
        *(config.anthropic_api_keys or []),
        *_channel_keys_for_provider(channels, {"anthropic"}),
    ])
    openai_keys = _dedupe_strings([
        *(config.openai_api_keys or []),
        *_channel_keys_for_provider(channels, {"openai"}),
    ])
    deepseek_keys = _dedupe_strings([
        *(config.deepseek_api_keys or []),
        *_channel_keys_for_provider(channels, {"deepseek"}),
    ])

    _put_provider_keys(env, "GEMINI", gemini_keys)
    _put_provider_keys(env, "ANTHROPIC", anthropic_keys)
    _put_provider_keys(env, "OPENAI", openai_keys)
    _put_provider_keys(env, "DEEPSEEK", deepseek_keys)

    put("OPENAI_BASE_URL", config.openai_base_url or _first_channel_base_url(channels, {"openai"}))
    put_default("DAILY_SOURCE", "yfinance")
    put_default("DAILY_FETCH_RETRIES", str(DSA_SCREENING_DAILY_FETCH_RETRIES))
    put_default("DAILY_FETCH_MAX_WORKERS", "1")
    put("LLM_CANDIDATE_CONTEXT_ENABLED", "false")
    put_default("LLM_CANDIDATE_CONTEXT_PROVIDERS", DSA_SCREENING_CANDIDATE_CONTEXT_PROVIDERS)
    put_default("LLM_CANDIDATE_MULTIPLIER", str(DSA_SCREENING_LLM_CANDIDATE_MULTIPLIER))
    put_default("LLM_MAX_CANDIDATES", str(_resolve_dsa_llm_max_candidates(max_results)))
    put_default("SNAPSHOT_SOURCE_PRIORITY", DSA_SCREENING_SNAPSHOT_SOURCE_PRIORITY)
    screening_data_dir = _resolve_screening_data_dir()
    put_default("SCREENING_DATA_DIR", str(screening_data_dir))
    put_default("SCREENING_FALLBACK_SNAPSHOT_PATH", str(screening_data_dir / "snapshot.last_good.json"))
    put_default("SCREENING_DAILY_HISTORY_CACHE_DIR", str(screening_data_dir / "daily_history"))
    put_default("SCREENING_INDUSTRY_PROVIDER_CACHE_DIR", str(screening_data_dir / "industry_provider_cache"))
    return env


def _build_screening_context(config: Config, *, max_results: Optional[int] = None) -> Dict[str, Any]:
    # context.llm.model/fallback/model_list are consistent with the LiteLLM routing semantics;
    # see https://docs.litellm.ai/docs/proxy/configs#the-model_list-key
    channels = _normalize_dsa_llm_channels(config)
    litellm_model, fallback_models = _resolve_screening_llm_models(config)
    return {
        "llm": {
            "model": litellm_model,
            "fallback_models": fallback_models,
            "temperature": config.llm_temperature,
            "channels": channels,
            "model_list": _build_screening_litellm_model_list(config, channels),
            "litellm_config_path": config.litellm_config_path or "",
            "candidate_context_enabled": False,
            "candidate_multiplier": DSA_SCREENING_LLM_CANDIDATE_MULTIPLIER,
            "max_candidates": _resolve_dsa_llm_max_candidates(max_results),
        },
        "dsa": {
            "contract_version": "1",
            "mode": "pre_rank_light",
            "max_candidates": DSA_PRE_RANK_CONTEXT_MAX_CANDIDATES,
            "include_news": False,
            "news_max_results": 0,
            "capabilities": [
                "candidate_context",
                "daily_history",
                "realtime_quote",
                "fundamental_context",
                "stock_events",
            ],
            "get_candidate_context": get_dsa_candidate_context,
            "get_daily_history": get_dsa_daily_history,
            "get_realtime_quote": get_dsa_realtime_quote,
            "get_fundamental_context": get_dsa_fundamental_context,
        },
    }


@contextmanager
def _screening_litellm_headers(config: Config) -> Iterator[None]:
    header_routes = _build_screening_litellm_header_routes(config)
    if not header_routes:
        yield
        return

    try:
        litellm_module = importlib.import_module("litellm")
    except Exception:
        yield
        return

    completion = getattr(litellm_module, "completion", None)
    if not callable(completion):
        yield
        return

    bridge_completion = getattr(completion, _SCREENING_LITELLM_COMPLETION_ATTR, None)
    if bridge_completion:
        token = _SCREENING_LITELLM_COMPLETION_ROUTES.set(
            tuple(route.copy() for route in header_routes),
        )
        try:
            yield
        finally:
            _SCREENING_LITELLM_COMPLETION_ROUTES.reset(token)
        return

    original_completion = completion

    def completion_with_dsa_headers(*args: Any, **kwargs: Any) -> Any:
        routes = _SCREENING_LITELLM_COMPLETION_ROUTES.get()
        if routes:
            headers = _match_screening_litellm_headers(args, kwargs, routes)
            if headers:
                existing_headers = kwargs.get("extra_headers")
                if isinstance(existing_headers, dict):
                    merged_headers = dict(headers)
                    merged_headers.update(existing_headers)
                    kwargs = dict(kwargs)
                    kwargs["extra_headers"] = merged_headers
                elif existing_headers in (None, ""):
                    kwargs = dict(kwargs)
                    kwargs["extra_headers"] = dict(headers)
        return original_completion(*args, **kwargs)

    setattr(completion_with_dsa_headers, _SCREENING_LITELLM_COMPLETION_ATTR, True)
    setattr(completion_with_dsa_headers, "_screening_litellm_completion_original", original_completion)
    completion_with_dsa_headers.__name__ = "completion_with_dsa_headers"

    if completion is not completion_with_dsa_headers:
        with _SCREENING_LITELLM_COMPLETION_LOCK:
            if not getattr(getattr(litellm_module, "completion", None), _SCREENING_LITELLM_COMPLETION_ATTR, False):
                setattr(litellm_module, "completion", completion_with_dsa_headers)

    token = _SCREENING_LITELLM_COMPLETION_ROUTES.set(
        tuple(route.copy() for route in header_routes),
    )
    try:
        yield
    finally:
        _SCREENING_LITELLM_COMPLETION_ROUTES.reset(token)


def _build_screening_litellm_model_list(config: Config, channels: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    explicit_model_list = _to_plain(config.llm_model_list or [])
    if isinstance(explicit_model_list, list) and explicit_model_list:
        return explicit_model_list
    return _channel_litellm_model_list(channels)


def _channel_litellm_model_list(channels: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    model_list_builder = getattr(Config, "_channels_to_model_list", None)
    if callable(model_list_builder):
        return _to_plain(model_list_builder(channels))

    model_list: List[Dict[str, Any]] = []
    for channel in channels:
        headers = dict(channel.get("extra_headers") or {})
        base_url = _env_text(channel.get("base_url"))
        for model_name in channel.get("models") or []:
            for api_key in channel.get("api_keys") or []:
                litellm_params: Dict[str, Any] = {"model": model_name}
                if api_key:
                    litellm_params["api_key"] = api_key
                if base_url:
                    litellm_params["api_base"] = base_url
                if headers:
                    litellm_params["extra_headers"] = dict(headers)
                model_list.append({"model_name": model_name, "litellm_params": litellm_params})
    return model_list


def _build_screening_litellm_header_routes(config: Config) -> List[Dict[str, Any]]:
    channels = _normalize_dsa_llm_channels(config)
    model_list = _build_screening_litellm_model_list(config, channels)
    routes: List[Dict[str, Any]] = []
    for entry in model_list:
        if not isinstance(entry, dict):
            continue
        params = entry.get("litellm_params") or {}
        if not isinstance(params, dict):
            continue
        headers = params.get("extra_headers")
        if not isinstance(headers, dict) or not headers:
            continue
        model_names = _dedupe_strings([
            entry.get("model_name"),
            params.get("model"),
        ])
        if not model_names:
            continue
        routes.append(
            {
                "models": model_names,
                "api_key": _env_text(params.get("api_key")),
                "api_base": _env_text(params.get("api_base") or params.get("base_url")),
                "extra_headers": dict(headers),
            }
        )
    return routes


def _match_screening_litellm_headers(
    args: Tuple[Any, ...],
    kwargs: Dict[str, Any],
    routes: List[Dict[str, Any]],
) -> Dict[str, Any]:
    model = _env_text(kwargs.get("model"))
    if not model and args:
        model = _env_text(args[0])
    if not model:
        return {}

    api_key = _env_text(kwargs.get("api_key"))
    api_base = _env_text(kwargs.get("api_base") or kwargs.get("base_url"))
    for route in routes:
        if model not in set(route.get("models") or []):
            continue
        route_api_key = _env_text(route.get("api_key"))
        if route_api_key and api_key and route_api_key != api_key:
            continue
        route_api_base = _env_text(route.get("api_base"))
        if route_api_base and api_base and route_api_base != api_base:
            continue
        headers = route.get("extra_headers")
        return dict(headers) if isinstance(headers, dict) else {}
    return {}


def _resolve_dsa_llm_max_candidates(max_results: Optional[int]) -> int:
    requested = max_results if isinstance(max_results, int) and max_results > 0 else DSA_ENRICHMENT_MAX_CANDIDATES
    return min(
        DSA_SCREENING_LLM_MAX_CANDIDATES,
        max(requested, requested * DSA_SCREENING_LLM_CANDIDATE_MULTIPLIER),
    )


def _resolve_screening_llm_models(config: Config) -> Tuple[str, List[str]]:
    primary = _env_text(config.litellm_model)
    configured_models = get_configured_llm_models(config.llm_model_list or [])
    configured_model_set = set(configured_models)

    if configured_models and (
        not primary or (primary not in configured_model_set and _is_managed_litellm_model(primary))
    ):
        primary = configured_models[0]

    raw_fallbacks = _dedupe_strings(config.litellm_fallback_models or [])
    if not configured_models:
        return primary, [model for model in raw_fallbacks if model != primary]

    fallback_models: List[str] = []
    seen = {primary} if primary else set()

    for model in raw_fallbacks:
        if model in seen:
            continue
        if model in configured_model_set or not _is_managed_litellm_model(model):
            fallback_models.append(model)
            seen.add(model)

    for model in configured_models:
        if model and model not in seen:
            fallback_models.append(model)
            seen.add(model)

    return primary, fallback_models


def _is_managed_litellm_model(model: str) -> bool:
    text = _env_text(model)
    if not text:
        return False
    provider = text.split("/", 1)[0].lower() if "/" in text else "openai"
    return provider in SCREENING_MANAGED_LITELLM_PROVIDERS


def _normalize_dsa_llm_channels(config: Config) -> List[Dict[str, Any]]:
    channels: List[Dict[str, Any]] = []
    for index, raw in enumerate(config.llm_channels or []):
        if not isinstance(raw, dict):
            continue
        name = _env_text(raw.get("name")) or f"channel{index + 1}"
        api_keys = _dedupe_strings(raw.get("api_keys") if isinstance(raw.get("api_keys"), list) else [])
        models = _dedupe_strings(raw.get("models") if isinstance(raw.get("models"), list) else [])
        channel = {
            "name": name,
            "protocol": _env_text(raw.get("protocol")),
            "api_surface": normalize_llm_channel_api_surface(raw.get("api_surface")),
            "base_url": _env_text(raw.get("base_url")),
            "api_keys": api_keys,
            "models": models,
            "extra_headers": raw.get("extra_headers") if isinstance(raw.get("extra_headers"), dict) else {},
            "enabled": bool(raw.get("enabled", True)),
        }
        if channel["enabled"] and (api_keys or models or channel["base_url"] or channel["extra_headers"]):
            channels.append(channel)
    return channels


def _channel_keys_for_provider(channels: List[Dict[str, Any]], providers: set[str]) -> List[str]:
    keys: List[str] = []
    for channel in channels:
        protocol = _env_text(channel.get("protocol")).lower()
        models = channel.get("models") or []
        model_providers = {
            str(model).split("/", 1)[0].lower()
            for model in models
            if isinstance(model, str) and "/" in model
        }
        if protocol in providers or model_providers.intersection(providers):
            keys.extend(channel.get("api_keys") or [])
    return keys


def _first_channel_base_url(channels: List[Dict[str, Any]], providers: set[str]) -> str:
    for channel in channels:
        protocol = _env_text(channel.get("protocol")).lower()
        base_url = _env_text(channel.get("base_url"))
        if base_url and protocol in providers:
            return base_url
    return ""


def _put_provider_keys(env: Dict[str, str], provider: str, keys: List[str]) -> None:
    if not keys:
        return
    env[f"{provider}_API_KEYS"] = ",".join(keys)
    env[f"{provider}_API_KEY"] = keys[0]


def _dedupe_strings(values: Any) -> List[str]:
    result: List[str] = []
    seen: set[str] = set()
    if not isinstance(values, list):
        return result
    for value in values:
        text = _env_text(value)
        if not text or text in seen:
            continue
        result.append(text)
        seen.add(text)
    return result


def _collect_screening_warning_messages(payload: Dict[str, Any]) -> List[str]:
    warnings: List[str] = []
    seen: set[str] = set()
    for key in ("warnings", "degradation"):
        for value in _list_text_values(payload.get(key)):
            if value in seen:
                continue
            seen.add(value)
            warnings.append(value)
    return warnings


def _env_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and not math.isfinite(value):
        return ""
    text = str(value).strip()
    if text.lower() in {"nan", "none", "null"}:
        return ""
    return text


def _get_dsa_fetcher_manager() -> Any:
    global _DSA_FETCHER_MANAGER
    if _DSA_FETCHER_MANAGER is None:
        with _DSA_FETCHER_MANAGER_LOCK:
            if _DSA_FETCHER_MANAGER is None:
                from data_provider import DataFetcherManager

                _DSA_FETCHER_MANAGER = DataFetcherManager()
    return _DSA_FETCHER_MANAGER


def _get_dsa_search_service() -> Any:
    from src.search_service import get_search_service

    return get_search_service()


def get_dsa_daily_history(stock_code: str, *, lookback_days: int = 120) -> Tuple[Any, str]:
    from src.services.history_loader import load_history_df

    normalized_code = _env_text(stock_code).zfill(6)
    days = max(int(lookback_days or 0), 30)
    return load_history_df(normalized_code, days=days)


def _normalize_dsa_daily_history(raw_df: Any) -> Any:
    if raw_df is None:
        return None

    import pandas as pd

    df = pd.DataFrame(raw_df).copy()
    if df.empty:
        return df

    aliases = {
        "date": ("date", "trade_date", "datetime", "日期"),
        "open": ("open", "开盘"),
        "high": ("high", "最高"),
        "low": ("low", "最低"),
        "close": ("close", "收盘", "price"),
        "volume": ("volume", "vol", "成交量"),
        "amount": ("amount", "成交额"),
    }
    normalized = pd.DataFrame(index=df.index)
    for target, candidates in aliases.items():
        source_column = next((column for column in candidates if column in df.columns), None)
        if source_column is not None:
            normalized[target] = df[source_column]

    if "close" not in normalized.columns:
        return pd.DataFrame()
    for column in ("open", "high", "low"):
        if column not in normalized.columns:
            normalized[column] = normalized["close"]
    if "volume" not in normalized.columns:
        normalized["volume"] = 0

    if "date" in normalized.columns:
        normalized["date"] = normalized["date"].map(_normalize_daily_date_value)

    for column in ("open", "high", "low", "close", "volume", "amount"):
        if column in normalized.columns:
            normalized[column] = pd.to_numeric(normalized[column], errors="coerce")
    normalized = normalized.dropna(subset=["close"])
    return normalized.reset_index(drop=True)


def _normalize_daily_date_value(value: Any) -> str:
    text = _env_text(value)
    if len(text) == 8 and text.isdigit():
        return f"{text[:4]}-{text[4:6]}-{text[6:]}"
    return text


def get_dsa_realtime_quote(stock_code: str) -> Dict[str, Any]:
    manager = _get_dsa_fetcher_manager()
    quote = manager.get_realtime_quote(stock_code, log_final_failure=False)
    if quote is None:
        return {}
    if hasattr(quote, "to_dict") and callable(quote.to_dict):
        return _remove_non_finite_json_values(quote.to_dict())
    payload = _to_plain(quote)
    return _remove_non_finite_json_values(payload if isinstance(payload, dict) else {})


def get_dsa_fundamental_context(stock_code: str) -> Dict[str, Any]:
    manager = _get_dsa_fetcher_manager()
    context = manager.get_fundamental_context(stock_code, budget_seconds=4.0)
    return _compact_fundamental_context(_remove_non_finite_json_values(_to_plain(context)))


def search_dsa_stock_news(stock_code: str, stock_name: str = "", max_results: int = 3) -> Dict[str, Any]:
    service = _get_dsa_search_service()
    if not getattr(service, "is_available", False):
        return {
            "success": False,
            "error": "DSA search service unavailable",
            "results": [],
        }

    response = service.search_stock_news(stock_code, stock_name or stock_code, max_results=max_results)
    return _normalize_dsa_search_response(response, max_results=max_results)


def search_dsa_stock_events(stock_code: str, stock_name: str = "", max_results: int = 3) -> Dict[str, Any]:
    """Reuse DSA event search for earnings, reduction and announcement context."""
    service = _get_dsa_search_service()
    if not getattr(service, "is_available", False):
        return {
            "success": False,
            "error": "DSA search service unavailable",
            "results": [],
        }

    response = service.search_stock_events(stock_code, stock_name or stock_code)
    return _normalize_dsa_search_response(response, max_results=max_results)


def _normalize_dsa_search_response(response: Any, *, max_results: int) -> Dict[str, Any]:
    results = []
    for item in (getattr(response, "results", []) or [])[:max(0, int(max_results))]:
        results.append(
            {
                "title": getattr(item, "title", ""),
                "snippet": getattr(item, "snippet", ""),
                "url": getattr(item, "url", ""),
                "source": getattr(item, "source", ""),
                "published_date": getattr(item, "published_date", None),
            }
        )
    return _remove_non_finite_json_values(
        {
            "query": getattr(response, "query", ""),
            "provider": getattr(response, "provider", ""),
            "success": bool(getattr(response, "success", False)),
            "error": getattr(response, "error_message", None),
            "results": results,
        }
    )


def get_dsa_candidate_context(
    stock_code: str,
    stock_name: str = "",
    *,
    include_news: bool = False,
    include_fundamentals: bool = True,
    mode: str = "pre_rank_light",
) -> Dict[str, Any]:
    candidate = {"code": stock_code, "name": stock_name, "raw": {}}
    context = _build_dsa_candidate_context(
        candidate,
        include_news=include_news,
        include_events=include_news,
        include_fundamentals=include_fundamentals,
        profile=mode or "pre_rank_light",
    )
    return context.get("dsa_context", {})


def _enrich_candidates_with_dsa(candidates: List[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    enriched_count = 0
    warnings: List[str] = []
    limit = min(len(candidates), DSA_ENRICHMENT_MAX_CANDIDATES)

    for index, candidate in enumerate(candidates):
        if index >= limit:
            continue
        existing_context = candidate.get("dsa_context")
        if (
            isinstance(existing_context, dict)
            and existing_context.get("enriched")
            and _candidate_has_dsa_news(candidate)
        ):
            enriched_count += 1
            existing_warnings = existing_context.get("warnings") or []
            if isinstance(existing_warnings, list):
                warnings.extend(str(item) for item in existing_warnings if item)
            elif existing_warnings:
                warnings.append(str(existing_warnings))
            continue
        try:
            enriched = _build_dsa_candidate_context(
                candidate,
                include_news=True,
                include_fundamentals=True,
                profile="post_rank_full",
            )
            candidate.update(enriched)
            if enriched.get("dsa_context", {}).get("enriched"):
                enriched_count += 1
            warnings.extend(enriched.get("dsa_context", {}).get("warnings") or [])
        except Exception as exc:  # noqa: BLE001 - DSA enrichment must not block screening.
            code = candidate.get("code") or f"rank-{candidate.get('rank', index + 1)}"
            message = f"{code}: {exc}"
            warnings.append(message)
            logger.warning("DSA enrichment failed for Screening candidate %s: %s", code, exc)
            candidate["dsa_context"] = {
                "enriched": False,
                "warnings": [message],
            }

    return candidates, {
        "enabled": True,
        "max_candidates": DSA_ENRICHMENT_MAX_CANDIDATES,
        "requested_count": limit,
        "enriched_count": enriched_count,
        "warnings": _dedupe_strings(warnings),
    }


def _candidate_has_dsa_news(candidate: Dict[str, Any]) -> bool:
    news_items = candidate.get("dsa_news")
    if isinstance(news_items, list) and any(isinstance(item, dict) for item in news_items):
        return True
    context = candidate.get("dsa_context")
    if not isinstance(context, dict):
        return False
    return _news_has_results(context.get("news"))


def _news_has_results(news: Any) -> bool:
    if isinstance(news, dict):
        results = news.get("results")
        return isinstance(results, list) and any(isinstance(item, dict) for item in results)
    if isinstance(news, list):
        return any(isinstance(item, dict) for item in news)
    return False


def _build_dsa_candidate_context(
    candidate: Dict[str, Any],
    *,
    include_news: bool = True,
    include_events: bool = True,
    include_fundamentals: bool = True,
    profile: str = "post_rank_full",
) -> Dict[str, Any]:
    code = _env_text(candidate.get("code"))
    name = _env_text(candidate.get("name"))
    warnings: List[str] = []
    if not code:
        return {
            "dsa_context": {
                "enriched": False,
                "warnings": ["missing candidate code"],
            }
        }

    existing_context = candidate.get("dsa_context")
    if not isinstance(existing_context, dict):
        existing_context = {}

    quote = existing_context.get("quote") if isinstance(existing_context.get("quote"), dict) else {}
    fundamentals = (
        existing_context.get("fundamentals")
        if isinstance(existing_context.get("fundamentals"), dict)
        else {}
    )
    existing_news = existing_context.get("news") if isinstance(existing_context.get("news"), dict) else {}
    news: Dict[str, Any] = dict(existing_news) if existing_news else {"success": False, "results": []}
    existing_events = existing_context.get("events") if isinstance(existing_context.get("events"), dict) else {}
    events: Dict[str, Any] = dict(existing_events) if existing_events else {"success": False, "results": []}
    existing_warnings = existing_context.get("warnings") or []
    if isinstance(existing_warnings, list):
        warnings.extend(str(item) for item in existing_warnings if item)
    elif existing_warnings:
        warnings.append(str(existing_warnings))

    try:
        manager = _get_dsa_fetcher_manager()
        resolved_name = manager.get_stock_name(code, allow_realtime=False)
        if resolved_name and (not name or name == code):
            name = resolved_name
            candidate["name"] = resolved_name
    except Exception as exc:  # noqa: BLE001
        warnings.append(f"stock_name_failed: {exc}")

    if not quote:
        try:
            quote = get_dsa_realtime_quote(code)
            if not quote:
                warnings.append("realtime_quote_missing")
        except Exception as exc:  # noqa: BLE001
            warnings.append(f"realtime_quote_failed: {exc}")
            quote = {}

    if quote:
        candidate["price"] = _first_non_empty(candidate.get("price"), quote.get("price"))
        candidate["change_pct"] = _first_non_empty(candidate.get("change_pct"), quote.get("change_pct"))
        candidate["amount"] = _first_non_empty(candidate.get("amount"), quote.get("amount"))
        if not candidate.get("name") and quote.get("name"):
            candidate["name"] = quote.get("name")

    if include_fundamentals and not fundamentals:
        try:
            fundamentals = get_dsa_fundamental_context(code)
        except Exception as exc:  # noqa: BLE001
            warnings.append(f"fundamental_context_failed: {exc}")
            fundamentals = {}

    if include_news:
        if not _news_has_results(news):
            try:
                news = search_dsa_stock_news(code, _env_text(candidate.get("name")) or name or code, max_results=3)
                if not news.get("success"):
                    warnings.append(news.get("error") or "stock_news_unavailable")
            except Exception as exc:  # noqa: BLE001
                warnings.append(f"stock_news_failed: {exc}")
                news = {"success": False, "error": str(exc), "results": []}
    elif not _news_has_results(news):
        news = {
            "success": False,
            "skipped": True,
            "reason": "pre_rank_light_context",
            "results": [],
        }

    if include_events:
        if not _news_has_results(events):
            try:
                events = search_dsa_stock_events(
                    code,
                    _env_text(candidate.get("name")) or name or code,
                    max_results=3,
                )
                if not events.get("success"):
                    warnings.append(events.get("error") or "stock_events_unavailable")
            except Exception as exc:  # noqa: BLE001
                warnings.append(f"stock_events_failed: {exc}")
                events = {"success": False, "error": str(exc), "results": []}
    elif not _news_has_results(events):
        events = {
            "success": False,
            "skipped": True,
            "reason": "pre_rank_light_context",
            "results": [],
        }

    summary = _build_dsa_analysis_summary(candidate, quote, fundamentals, news, events)
    context = {
        "enriched": bool(quote or fundamentals or news.get("results") or events.get("results")),
        "profile": profile,
        "news_included": bool(include_news),
        "events_included": bool(include_events),
        "quote": quote,
        "fundamentals": fundamentals,
        "news": news,
        "events": events,
        "warnings": _dedupe_strings(warnings),
    }
    return {
        "dsa_context": context,
        "dsa_news": news.get("results") or [],
        "dsa_events": events.get("results") or [],
        "dsa_analysis_summary": summary,
    }


def _first_non_empty(*values: Any) -> Any:
    for value in values:
        if value not in (None, ""):
            return value
    return None


def _compact_fundamental_context(context: Any) -> Dict[str, Any]:
    if not isinstance(context, dict):
        return {}
    compact: Dict[str, Any] = {
        "market": context.get("market"),
        "status": context.get("status"),
        "coverage": context.get("coverage") if isinstance(context.get("coverage"), dict) else {},
    }
    for block in _FUNDAMENTAL_BLOCKS:
        payload = context.get(block)
        if isinstance(payload, dict):
            compact[block] = {
                "status": payload.get("status"),
                "data": payload.get("data") if isinstance(payload.get("data"), dict) else {},
            }
    errors = context.get("errors")
    if isinstance(errors, list) and errors:
        compact["errors"] = [str(item) for item in errors[:3]]
    return compact


def _build_dsa_analysis_summary(
    candidate: Dict[str, Any],
    quote: Dict[str, Any],
    fundamentals: Dict[str, Any],
    news: Dict[str, Any],
    events: Optional[Dict[str, Any]] = None,
) -> str:
    parts: List[str] = []
    price = _first_non_empty(quote.get("price"), candidate.get("price"))
    change_pct = _first_non_empty(quote.get("change_pct"), candidate.get("change_pct"))
    if price is not None:
        text = f"DSA行情：现价 {price}"
        if change_pct is not None:
            text += f"，涨跌幅 {change_pct}%"
        parts.append(text)

    coverage = fundamentals.get("coverage") if isinstance(fundamentals, dict) else {}
    if isinstance(coverage, dict) and coverage:
        available_blocks = [key for key, value in coverage.items() if str(value).lower() in {"available", "partial"}]
        if available_blocks:
            parts.append(f"DSA基本面覆盖：{', '.join(available_blocks[:4])}")

    news_results = news.get("results") if isinstance(news, dict) else []
    if isinstance(news_results, list) and news_results:
        titles = [str(item.get("title") or "").strip() for item in news_results if isinstance(item, dict)]
        titles = [title for title in titles if title]
        if titles:
            parts.append(f"DSA新闻：{'；'.join(titles[:2])}")

    event_results = events.get("results") if isinstance(events, dict) else []
    if isinstance(event_results, list) and event_results:
        titles = [str(item.get("title") or "").strip() for item in event_results if isinstance(item, dict)]
        titles = [title for title in titles if title]
        if titles:
            parts.append(f"DSA事件：{'；'.join(titles[:2])}")

    if not parts:
        return ""
    return "；".join(parts)


def _ensure_supported_market(market: str) -> None:
    status = _call_screening_status()
    supported_markets = status.get("supported_markets") or status.get("markets") or status.get("market")
    if not supported_markets:
        return

    normalized: List[Any]
    if isinstance(supported_markets, str):
        normalized = [supported_markets]
    elif isinstance(supported_markets, (list, tuple, set)):
        normalized = list(supported_markets)
    else:
        normalized = []

    if market not in normalized:
        raise HTTPException(
            status_code=422,
            detail={
                "error": "screening_invalid_market",
                "message": (
                    f"市场 {market} 不在选股功能支持范围内"
                    f"（支持市场：{', '.join(map(str, normalized)) or '未知'}）。"
                ),
            },
        )


def _normalize_candidates(raw: Any) -> List[Dict[str, Any]]:
    data = _to_plain(raw)
    items = data
    if isinstance(data, dict):
        for key in ("candidates", "picks", "items", "results", "stocks"):
            if isinstance(data.get(key), list):
                items = data[key]
                break
    if not isinstance(items, list):
        return []
    return [_normalize_candidate(item, index + 1) for index, item in enumerate(items)]


def _normalize_candidate(raw: Any, rank: int) -> Dict[str, Any]:
    item = _remove_non_finite_json_values(_to_plain(raw))
    if not isinstance(item, dict):
        item = {"code": str(item)}
    source = item.get("raw") if isinstance(item.get("raw"), dict) else item
    dsa_context = item.get("dsa_context") or source.get("dsa_context") or {}
    dsa_news = item.get("dsa_news") or source.get("dsa_news") or _extract_dsa_news_from_context(dsa_context)
    dsa_events = item.get("dsa_events") or source.get("dsa_events") or _extract_dsa_events_from_context(dsa_context)
    dsa_analysis_summary = (
        item.get("dsa_analysis_summary")
        or source.get("dsa_analysis_summary")
        or _extract_dsa_analysis_summary_from_context(dsa_context)
    )
    return {
        "rank": item.get("rank") or source.get("rank") or rank,
        "code": item.get("code") or source.get("code") or item.get("symbol") or source.get("symbol") or item.get("stock_code") or source.get("stock_code") or "",
        "name": item.get("name") or source.get("name") or item.get("stock_name") or source.get("stock_name") or "",
        "score": _first_present(item, source, "score", "final_score"),
        "screen_score": _first_present(item, source, "screen_score"),
        "reason": item.get("reason") or source.get("reason") or source.get("ranking_reason") or source.get("risk_summary") or item.get("summary") or _build_candidate_reason(source),
        "risk_level": item.get("risk_level") or source.get("risk_level") or "",
        "risk_flags": item.get("risk_flags") or source.get("risk_flags") or [],
        "llm_score": _first_present(item, source, "llm_score"),
        "llm_confidence": _first_present(item, source, "llm_confidence"),
        "llm_sector": item.get("llm_sector") or source.get("llm_sector") or "",
        "llm_theme": item.get("llm_theme") or source.get("llm_theme") or "",
        "llm_tags": item.get("llm_tags") or source.get("llm_tags") or [],
        "llm_thesis": item.get("llm_thesis") or source.get("llm_thesis") or "",
        "llm_catalysts": item.get("llm_catalysts") or source.get("llm_catalysts") or [],
        "llm_risks": item.get("llm_risks") or source.get("llm_risks") or [],
        "llm_watch_items": item.get("llm_watch_items") or source.get("llm_watch_items") or [],
        "llm_invalidators": item.get("llm_invalidators") or source.get("llm_invalidators") or [],
        "llm_style_fit": item.get("llm_style_fit") or source.get("llm_style_fit") or "",
        "price": _first_present(item, source, "price"),
        "change_pct": _first_present(item, source, "change_pct"),
        "amount": _first_present(item, source, "amount"),
        "industry": item.get("industry") or source.get("industry") or "",
        "factor_scores": item.get("factor_scores") or source.get("factor_scores") or {},
        "dsa_context": dsa_context,
        "dsa_news": dsa_news,
        "dsa_events": dsa_events,
        "dsa_analysis_summary": dsa_analysis_summary,
        "post_analysis_summaries": item.get("post_analysis_summaries") or source.get("post_analysis_summaries") or {},
        "post_analysis_tags": item.get("post_analysis_tags") or source.get("post_analysis_tags") or [],
        "raw": source,
    }


def _extract_dsa_news_from_context(context: Any) -> List[Dict[str, Any]]:
    if not isinstance(context, dict):
        return []
    news = context.get("news")
    if isinstance(news, dict):
        results = news.get("results")
    elif isinstance(news, list):
        results = news
    else:
        results = None
    if not isinstance(results, list):
        return []
    return [item for item in results if isinstance(item, dict)]


def _extract_dsa_events_from_context(context: Any) -> List[Dict[str, Any]]:
    if not isinstance(context, dict):
        return []
    events = context.get("events")
    if isinstance(events, dict):
        results = events.get("results")
    elif isinstance(events, list):
        results = events
    else:
        results = None
    if not isinstance(results, list):
        return []
    return [item for item in results if isinstance(item, dict)]


def _extract_dsa_analysis_summary_from_context(context: Any) -> str:
    if not isinstance(context, dict):
        return ""
    for key in ("dsa_analysis_summary", "analysis_summary", "summary"):
        value = context.get(key)
        if isinstance(value, str) and value.strip():
            return value
    news = context.get("news")
    if isinstance(news, dict):
        for key in ("analysis_summary", "summary"):
            value = news.get(key)
            if isinstance(value, str) and value.strip():
                return value
    news_items = _extract_dsa_news_from_context(context)
    if not news_items:
        return ""
    quote = context.get("quote") if isinstance(context.get("quote"), dict) else {}
    fundamentals = context.get("fundamentals") if isinstance(context.get("fundamentals"), dict) else {}
    return _build_dsa_analysis_summary({}, quote, fundamentals, {"results": news_items})


def _first_present(primary: Dict[str, Any], source: Dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if primary.get(key) is not None:
            return primary.get(key)
        if source.get(key) is not None:
            return source.get(key)
    return None


def _build_candidate_reason(item: Dict[str, Any]) -> str:
    summaries = item.get("post_analysis_summaries")
    if isinstance(summaries, dict):
        summary = next((str(value) for value in summaries.values() if value), "")
        if summary:
            return summary

    factors = item.get("factor_scores")
    parts: List[str] = []
    if isinstance(factors, dict) and factors:
        top_factors = sorted(
            ((key, value) for key, value in factors.items() if isinstance(value, (int, float))),
            key=lambda pair: pair[1],
            reverse=True,
        )[:3]
        if top_factors:
            factor_text = "、".join(f"{key} {value:.1f}" for key, value in top_factors)
            parts.append(f"主要因子：{factor_text}")
    if item.get("industry"):
        parts.append(f"行业：{item['industry']}")
    if item.get("risk_level"):
        parts.append(f"风险等级：{item['risk_level']}")
    return "；".join(parts)


def _to_plain(value: Any) -> Any:
    if is_dataclass(value):
        return asdict(value)
    if hasattr(value, "model_dump"):
        return value.model_dump()
    if hasattr(value, "dict") and callable(value.dict):
        return value.dict()
    if isinstance(value, list):
        return [_to_plain(item) for item in value]
    return value


def _remove_non_finite_json_values(value: Any) -> Any:
    if isinstance(value, list):
        return [_remove_non_finite_json_values(item) for item in value]
    if isinstance(value, tuple):
        return [_remove_non_finite_json_values(item) for item in value]
    if isinstance(value, dict):
        return {key: _remove_non_finite_json_values(item) for key, item in value.items()}
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    return value

# -*- coding: utf-8 -*-
"""Timeout partial delivery helpers for RuntimeSchedulerService.

When the Web/API runtime scheduler hard-timeout kills a worker, successful
per-stock analyses may already be persisted. This module collects those rows
and optionally sends a partial notification with richer diagnostics.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional, Sequence

from sqlalchemy import and_, desc, select

logger = logging.getLogger(__name__)

TIMEOUT_PARTIAL_NOTIFY_ENV = "DSA_TIMEOUT_PARTIAL_NOTIFY"
_FALSEY = {"0", "false", "no", "off"}
_TRUTHY = {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class CompletedAnalysisSummary:
    """One stock analysis already saved before the timeout kill."""

    code: str
    name: Optional[str] = None
    operation_advice: Optional[str] = None
    sentiment_score: Optional[int] = None
    created_at: Optional[datetime] = None
    history_id: Optional[int] = None


@dataclass(frozen=True)
class TimeoutPartialOutcome:
    """Result of timeout partial collection + optional notify."""

    completed: List[CompletedAnalysisSummary]
    pending_codes: List[str]
    notified: bool
    notify_skipped_reason: Optional[str]
    error_message: str


def is_timeout_partial_notify_enabled() -> bool:
    """Return whether ``DSA_TIMEOUT_PARTIAL_NOTIFY`` allows timeout notify.

    Default: enabled (true) when unset. Accepts common truthy/falsey strings.
    """
    raw = os.getenv(TIMEOUT_PARTIAL_NOTIFY_ENV)
    if raw is None or not str(raw).strip():
        return True
    normalized = str(raw).strip().lower()
    if normalized in _FALSEY:
        return False
    if normalized in _TRUTHY:
        return True
    logger.warning(
        "Invalid %s=%r; treating as enabled",
        TIMEOUT_PARTIAL_NOTIFY_ENV,
        raw,
    )
    return True


def resolve_expected_stock_codes(
    stock_codes: Optional[Sequence[str]],
    *,
    config: Optional[Any] = None,
) -> List[str]:
    """Resolve the stock universe for this run.

    When ``stock_codes`` is provided, normalize and return it. Otherwise fall
    back to ``config.stock_list`` (caller may pass a loaded Config).
    """
    if stock_codes is not None:
        return _normalize_codes(stock_codes)

    if config is not None:
        stock_list = getattr(config, "stock_list", None) or []
        return _normalize_codes(stock_list)

    return []


def collect_completed_analyses_since(
    *,
    run_started_at: datetime,
    expected_codes: Sequence[str],
    db: Optional[Any] = None,
) -> List[CompletedAnalysisSummary]:
    """Load successful analysis_history rows created at/after run start.

    Only codes in ``expected_codes`` are considered when that list is non-empty.
    When the same code has multiple rows in the window, keep the latest.
    Fail-open: DB/import errors return an empty list after logging a warning.
    Callers cannot tell "no rows yet" from "collect failed"; operators must
    grep ``Failed to collect completed analyses after timeout``. ``status()``
    may then show ``completed=0`` or keep the baseline timeout ``last_error``.
    """
    try:
        rows = _query_history_rows_since(
            run_started_at=run_started_at,
            expected_codes=expected_codes,
            db=db,
        )
        return _summaries_from_history_rows(rows, expected_codes)
    except Exception as exc:  # noqa: BLE001 - timeout path must stay fail-open
        logger.warning("Failed to collect completed analyses after timeout: %s", exc)
        return []


def _query_history_rows_since(
    *,
    run_started_at: datetime,
    expected_codes: Sequence[str],
    db: Optional[Any] = None,
) -> List[Any]:
    """Fetch raw analysis_history ORM rows for the timeout window."""
    storage_mod = _resolve_storage_module()
    database = db if db is not None else storage_mod.get_db()
    AnalysisHistory = storage_mod.AnalysisHistory
    codes = _normalize_codes(expected_codes)
    conditions = [
        AnalysisHistory.created_at >= run_started_at,
        AnalysisHistory.report_type != "market_review",
    ]
    if codes:
        conditions.append(AnalysisHistory.code.in_(codes))

    with database.get_session() as session:
        return list(
            session.execute(
                select(AnalysisHistory)
                .where(and_(*conditions))
                .order_by(desc(AnalysisHistory.created_at), desc(AnalysisHistory.id))
                .limit(500)
            ).scalars().all()
        )


def _resolve_storage_module() -> Any:
    """Load ``src.storage``, cleaning up broken partial imports on failure.

    On import failure, drop ``src.storage`` / ``src.storage.*`` from
    ``sys.modules`` and raise. The timeout collect path fail-opens to an
    empty list; this is not surfaced on ``status().last_error`` beyond a
    possible ``completed=0`` enrich. Watch the warning log, not the API.
    """
    import importlib
    import sys

    existing = sys.modules.get("src.storage")
    if existing is not None:
        return existing
    try:
        return importlib.import_module("src.storage")
    except Exception as exc:
        for name in list(sys.modules):
            if name == "src.storage" or name.startswith("src.storage."):
                sys.modules.pop(name, None)
        raise RuntimeError("storage unavailable for timeout partial collect") from exc


def _summaries_from_history_rows(
    rows: Sequence[Any],
    expected_codes: Sequence[str],
) -> List[CompletedAnalysisSummary]:
    """Convert ORM/history-like rows into latest-per-code summaries."""
    codes = _normalize_codes(expected_codes)
    latest_by_code: Dict[str, CompletedAnalysisSummary] = {}
    for row in rows:
        code = str(getattr(row, "code", "") or "").strip()
        if not code or code in latest_by_code:
            continue
        if codes and code not in set(codes):
            continue
        latest_by_code[code] = CompletedAnalysisSummary(
            code=code,
            name=getattr(row, "name", None),
            operation_advice=getattr(row, "operation_advice", None),
            sentiment_score=getattr(row, "sentiment_score", None),
            created_at=getattr(row, "created_at", None),
            history_id=getattr(row, "id", None),
        )

    if codes:
        return [latest_by_code[code] for code in codes if code in latest_by_code]
    return list(latest_by_code.values())


def format_timeout_error_message(
    *,
    timeout_seconds: int,
    completed: Sequence[CompletedAnalysisSummary],
    pending_codes: Sequence[str],
) -> str:
    """Build structured ``last_error`` text for RuntimeSchedulerService.status()."""
    completed_codes = [item.code for item in completed]
    pending = [str(code).strip() for code in pending_codes if str(code).strip()]
    parts = [
        f"runtime scheduled analysis timed out after {timeout_seconds}s",
        f"completed={len(completed_codes)}",
        f"pending={len(pending)}",
    ]
    if completed_codes:
        parts.append(f"completed_codes={','.join(completed_codes)}")
    if pending:
        parts.append(f"pending_codes={','.join(pending)}")
    return "; ".join(parts)


_PARTIAL_TIMEOUT_TEXT: Dict[str, Dict[str, str]] = {
    "zh": {
        "title": "## 定时分析超时（部分完成）",
        "hard_timeout": "- 硬超时：`{seconds}` 秒",
        "completed_count": "- 已完成：`{count}` 只",
        "pending_count": "- 未完成：`{count}` 只",
        "completed_heading": "### 已落库结果",
        "completed_item": "- `{code}` {name}｜建议：{advice}｜评分：{score}",
        "pending_heading": "### 未完成",
        "footer": "_本轮因 runtime scheduler 硬超时被终止；已完成个股结果已写入分析历史，未完成部分可稍后手动重跑。_",
    },
    "en": {
        "title": "## Scheduled analysis timed out (partially completed)",
        "hard_timeout": "- Hard timeout: `{seconds}` s",
        "completed_count": "- Completed: `{count}` stocks",
        "pending_count": "- Not completed: `{count}` stocks",
        "completed_heading": "### Saved results",
        "completed_item": "- `{code}` {name} | Advice: {advice} | Score: {score}",
        "pending_heading": "### Not completed",
        "footer": (
            "_This run was stopped by the runtime scheduler's hard timeout; completed stock results were saved "
            "to the analysis history, and the rest can be rerun manually later._"
        ),
    },
    "ko": {
        "title": "## 예약 분석 시간 초과(일부 완료)",
        "hard_timeout": "- 하드 타임아웃: `{seconds}`초",
        "completed_count": "- 완료: `{count}`개 종목",
        "pending_count": "- 미완료: `{count}`개 종목",
        "completed_heading": "### 저장된 결과",
        "completed_item": "- `{code}` {name} | 의견: {advice} | 점수: {score}",
        "pending_heading": "### 미완료",
        "footer": (
            "_이번 실행은 runtime scheduler 하드 타임아웃으로 중단되었습니다. 완료된 종목 결과는 분석 이력에 저장되었으며, "
            "미완료 종목은 나중에 수동으로 다시 실행할 수 있습니다._"
        ),
    },
}


def build_partial_timeout_report(
    *,
    timeout_seconds: int,
    completed: Sequence[CompletedAnalysisSummary],
    pending_codes: Sequence[str],
    report_language: Optional[str] = None,
) -> str:
    """Build Markdown body for the partial-success timeout notification.

    ``report_language`` defaults to the configured report language.
    """
    from src.report_language import resolve_report_language

    text = _PARTIAL_TIMEOUT_TEXT[resolve_report_language(report_language)]
    lines = [
        text["title"],
        "",
        text["hard_timeout"].format(seconds=timeout_seconds),
        text["completed_count"].format(count=len(completed)),
        text["pending_count"].format(count=len(list(pending_codes))),
        "",
    ]
    if completed:
        lines.append(text["completed_heading"])
        for item in completed:
            name = item.name or "-"
            advice = item.operation_advice or "-"
            score = item.sentiment_score if item.sentiment_score is not None else "-"
            lines.append(text["completed_item"].format(code=item.code, name=name, advice=advice, score=score))
        lines.append("")
    if pending_codes:
        lines.append(text["pending_heading"])
        lines.append(", ".join(f"`{code}`" for code in pending_codes))
        lines.append("")
    lines.append(text["footer"])
    return "\n".join(lines)


def send_partial_timeout_notification(
    report: str,
    *,
    completed_codes: Sequence[str],
    no_notify: bool = False,
) -> bool:
    """Send ``report`` via NotificationService unless ``no_notify`` is set.

    Returns True when a send was attempted and succeeded.

    Channel/import exceptions are swallowed: this function logs a warning
    (``Partial timeout notification failed``) and returns False. It does not
    re-raise, so it cannot keep ``RuntimeSchedulerService`` ``_run_lock``
    held or flip ``status().running`` — notify runs on a daemon thread after
    that lock is already released. Structured ``last_error`` is still returned
    by ``handle_runtime_analysis_timeout`` with ``notify_skipped_reason=send_failed``.
    """
    if no_notify:
        return False
    if not is_timeout_partial_notify_enabled():
        return False
    if not report or not str(report).strip():
        return False

    try:
        from src.notification import NotificationService

        service = NotificationService()
        return bool(
            service.send(
                report,
                email_stock_codes=list(completed_codes) or None,
                route_type="system_error",
                severity="warning",
                dedup_key=f"runtime_timeout_partial:{','.join(completed_codes)}",
            )
        )
    except Exception as exc:  # noqa: BLE001 - never break scheduler on notify failure
        logger.warning("Partial timeout notification failed: %s", exc)
        return False


def handle_runtime_analysis_timeout(
    *,
    timeout_seconds: int,
    run_started_at: datetime,
    stock_codes: Optional[Sequence[str]] = None,
    no_notify: bool = False,
    config: Optional[Any] = None,
    db: Optional[Any] = None,
) -> TimeoutPartialOutcome:
    """Orchestrate collect → format error → optional partial notify.

    Intended call site: ``RuntimeSchedulerService._run_analysis_with_watchdog``
    timeout branch, after the worker process tree is terminated.
    """
    expected = resolve_expected_stock_codes(stock_codes, config=config)
    completed = collect_completed_analyses_since(
        run_started_at=run_started_at,
        expected_codes=expected,
        db=db,
    )
    completed_code_set = {item.code for item in completed}
    pending_codes = [code for code in expected if code not in completed_code_set]
    error_message = format_timeout_error_message(
        timeout_seconds=timeout_seconds,
        completed=completed,
        pending_codes=pending_codes,
    )

    notified = False
    notify_skipped_reason: Optional[str] = None
    if no_notify:
        notify_skipped_reason = "no_notify"
    elif not is_timeout_partial_notify_enabled():
        notify_skipped_reason = "env_disabled"
    elif not completed:
        notify_skipped_reason = "no_completed_results"
    else:
        report = build_partial_timeout_report(
            timeout_seconds=timeout_seconds,
            completed=completed,
            pending_codes=pending_codes,
        )
        notified = send_partial_timeout_notification(
            report,
            completed_codes=[item.code for item in completed],
            no_notify=False,
        )
        if not notified:
            notify_skipped_reason = "send_failed"

    return TimeoutPartialOutcome(
        completed=list(completed),
        pending_codes=pending_codes,
        notified=notified,
        notify_skipped_reason=notify_skipped_reason,
        error_message=error_message,
    )


def _normalize_codes(codes: Sequence[Any]) -> List[str]:
    seen = set()
    ordered: List[str] = []
    for raw in codes:
        code = str(raw or "").strip()
        if not code or code in seen:
            continue
        seen.add(code)
        ordered.append(code)
    return ordered

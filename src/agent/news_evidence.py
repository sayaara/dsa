# -*- coding: utf-8 -*-
"""Count of the news evidence the Agent actually consumed during a run.

The empty-news disclosure must reflect the news evidence this analysis genuinely used. In
Agent mode the Agent gathers intelligence by calling the search tools itself, so the count can
only come from what those tools actually returned. A single `search_stock_news()` call made
after the analysis is no substitute: it is unrelated to the evidence the Agent consumed and
distorts in both directions - the Agent may have used news yet be marked 「未纳入新闻面证据」 because the follow-up failed, or have found none yet skip the notice because the follow-up succeeded.

Usage: the pipeline opens and reads the scope around `executor.run()`, and the search tools
record how many items were genuinely handed to the Agent. The tools run in a
ThreadPoolExecutor and `src/agent/runner.py` submits them via `contextvars.copy_context()`, so
the **mutable** accumulator in the ContextVar is the same object in the worker and parent
threads, and increments made on a tool thread are visible to the pipeline. Do not replace it with a ContextVar holding an immutable value - the parent thread would then read nothing.
"""

from __future__ import annotations

import logging
import threading
from contextvars import ContextVar, Token
from typing import Optional

logger = logging.getLogger(__name__)


class NewsEvidenceAccumulator:
    """Thread-safely accumulate how many news items the Agent consumed in this analysis."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._total = 0

    def record(self, count: int) -> None:
        """Record how many items one search tool actually returned; zero hits must also be recorded (as 0)."""
        try:
            value = int(count)
        except (TypeError, ValueError):
            value = 0
        if value < 0:
            value = 0
        with self._lock:
            self._total += value

    @property
    def total(self) -> int:
        with self._lock:
            return self._total

    def resolve(self, *, search_available: bool) -> Optional[int]:
        """Collapse into the tri-state semantics of `news_result_count`.

        - No search channel available: `None`, meaning no search ran, disclosed as 「未配置搜索渠道」.
        - A channel is available: start at `0` and count whatever the Agent's tool calls returned.

The case where a channel is available but the Agent never searched is deliberately counted as
        `0` rather than `None`: the report genuinely has no news evidence, but 「未配置搜索渠道」 would
        be a false explanation, whereas 「未获取到可用的新闻面数据」 holds in both sub-cases.
        """
        if not search_available:
            return None
        return self.total


_CURRENT_ACCUMULATOR: ContextVar[Optional[NewsEvidenceAccumulator]] = ContextVar(
    "news_evidence_accumulator",
    default=None,
)


def activate_news_evidence_scope() -> Token:
    """Open the evidence scope for one Agent run and return the reset token."""
    return _CURRENT_ACCUMULATOR.set(NewsEvidenceAccumulator())


def get_current_news_evidence() -> Optional[NewsEvidenceAccumulator]:
    return _CURRENT_ACCUMULATOR.get()


def reset_news_evidence_scope(token: Optional[Token]) -> None:
    if token is None:
        return
    try:
        _CURRENT_ACCUMULATOR.reset(token)
    except Exception as exc:  # pragma: no cover - defensive fail-open
        logger.warning("news evidence scope reset failed: %s", exc)


def record_news_evidence(count: int) -> None:
    """Called by the Agent's search tools.

    Silently ignored when no scope is active: the non-Agent path maintains its own count, and the
    tools may also be called outside an Agent analysis (for example a follow-up news lookup on the
    report page). Neither should affect this analysis's disclosure decision.
    """
    accumulator = _CURRENT_ACCUMULATOR.get()
    if accumulator is None:
        return
    accumulator.record(count)

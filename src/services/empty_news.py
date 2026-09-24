# -*- coding: utf-8 -*-
"""Report disclosure text for when the news search did not run, or returned zero hits.

Single source of truth: both the string-concatenation renderer (src/notification.py)
and the template rendering path (src/services/report_renderer.py + templates/*.j2) share this
module, so one analysis result cannot disclose on some channels while staying silent on others.

The disclosure asserts whether this conclusion used news-based evidence at all, so the primary
criterion is whether the news evidence the analysis actually received (news_context) is non-empty,
not how many search hits there were. news_context may come from a live search, social sentiment, or the locally persisted intelligence pool; the latter two reach the model input without producing search hits, so counting alone would misreport
such an analysis as "未纳入新闻面证据" (review OR-COR-2e4b9d61).

news_result_count is therefore secondary, and only explains the reason when there genuinely is no evidence:
    None  no search performed (no search channel configured)
    0     a search ran but returned zero hits (rate limiting, every source failing, and so on)
    > 0   the live search returned hits (evidence necessarily exists)
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Optional, Tuple

from src.report_language import SUPPORTED_REPORT_LANGUAGES

_ZH_NOT_CONFIGURED = "⚠️ 未配置搜索渠道，本次分析未纳入新闻面证据。"
_EN_NOT_CONFIGURED = (
    "⚠️ No news search channel is configured; "
    "this analysis does not incorporate news-based evidence."
)
_ZH_ZERO_RESULTS = "⚠️ 本次未获取到可用的新闻面数据，以下结论未纳入新闻维度证据。"
_EN_ZERO_RESULTS = (
    "⚠️ No news data could be retrieved for this run; "
    "the conclusions below do not incorporate news-based evidence."
)
_KO_NOT_CONFIGURED = (
    "⚠️ 뉴스 검색 채널이 설정되지 않아 이번 분석에는 "
    "뉴스 근거를 반영하지 않았습니다."
)
_KO_ZERO_RESULTS = (
    "⚠️ 이번 분석에서 사용 가능한 뉴스 데이터를 가져오지 못해 "
    "아래 결론에는 뉴스 근거를 반영하지 않았습니다."
)

_DISCLOSURES = {
    "zh": (_ZH_NOT_CONFIGURED, _ZH_ZERO_RESULTS),
    "en": (_EN_NOT_CONFIGURED, _EN_ZERO_RESULTS),
    "ko": (_KO_NOT_CONFIGURED, _KO_ZERO_RESULTS),
}

if set(_DISCLOSURES) != set(SUPPORTED_REPORT_LANGUAGES):
    raise RuntimeError(
        "Empty-news disclosures must cover every SUPPORTED_REPORT_LANGUAGES value"
    )


def persisted_news_result_state(
    raw_result: Any,
    context_snapshot: Any = None,
) -> Tuple[Optional[int], bool]:
    """Recover the count and its trustworthiness from the persisted payload.

    Newer records store the tri-state value explicitly in raw_result; older records may leave a
    0 / >0 count in context_snapshot. When neither carries the field, the only valid verdict is
    legacy unknown - a missing field must not be treated as an explicit None.
    """
    if isinstance(raw_result, Mapping):
        if raw_result.get("news_result_count_known") is False:
            return None, False
        if "news_result_count" in raw_result:
            return raw_result.get("news_result_count"), True

    if isinstance(context_snapshot, Mapping) and "news_result_count" in context_snapshot:
        return context_snapshot.get("news_result_count"), True

    return None, False


def news_evidence_present(*sources: Any) -> bool:
    """Whether this analysis genuinely received news evidence. True if any single source is true.

    Each source is either a real item count (int) or a content string **with placeholder text already excluded**.
    The live search, social sentiment and local intelligence pool each count as one source. Both
    pipeline paths use this function; do not write a separate check anywhere else.

    **Do not pass in the news_context block that the pipeline has already assembled.**
    `format_intel_report()` in `src/search_service.py` still emits a `【XX 情报搜索结果】` heading
    and a `未找到相关信息` placeholder for every dimension on zero hits, so the block is never
    empty. Judging by it would turn "searched but retrieved nothing" into "has evidence", swallowing
    exactly the disclosure this module exists to add (review OR-COR-8f4c2d1b). The decision must register each source individually, never sniff a string.
    """
    for source in sources:
        if source is None or isinstance(source, bool):
            if source:
                return True
            continue
        if isinstance(source, (int, float)):
            if source > 0:
                return True
            continue
        if str(source).strip():
            return True
    return False


def _disclosure_for_state(
    news_result_count: Optional[int],
    *,
    known: bool,
    evidence_present: bool,
    language: str,
) -> Optional[str]:
    try:
        not_configured, zero_results = _DISCLOSURES[language]
    except KeyError as exc:
        raise ValueError(f"Unsupported report language for empty-news disclosure: {language}") from exc

    if not known:
        return None
    # If evidence exists, say nothing, whichever source it came from; the count only explains why there is none.
    if evidence_present:
        return None
    if news_result_count is None:
        return not_configured
    if news_result_count == 0:
        return zero_results
    return None


def empty_news_disclosure(result: Any, language: str = "zh") -> Optional[str]:
    """Return the matching notice when no search ran or it returned zero hits; return None on normal hits.

    The decision must be independent of whether the model produced any news text: the analyzer output
    schema requires market_sentiment / hot_topics to be filled even when there is no news, so deciding
    by whether those fields are empty would produce the worst combination of all: showing the model's
    generated sentiment while concealing that there was no news evidence behind it.
    """
    if isinstance(result, Mapping):
        news_result_count, known = persisted_news_result_state(result)
        evidence_present = persisted_news_evidence_present(result, news_result_count)
    else:
        news_result_count = getattr(result, "news_result_count", None)
        known = getattr(result, "news_result_count_known", True)
        evidence_present = bool(getattr(result, "news_evidence_present", False))
    return _disclosure_for_state(
        news_result_count,
        known=known,
        evidence_present=evidence_present,
        language=language,
    )


def empty_news_disclosure_from_stored(
    raw_result: Any,
    context_snapshot: Any,
    language: str = "zh",
) -> Optional[str]:
    """Build the disclosure from the persisted payload for the history and API entry points; stay silent when an older record lacks the field."""
    news_result_count, known = persisted_news_result_state(raw_result, context_snapshot)
    return _disclosure_for_state(
        news_result_count,
        known=known,
        evidence_present=persisted_news_evidence_present(raw_result, news_result_count),
        language=language,
    )


def persisted_news_evidence_present(raw_result: Any, news_result_count: Optional[int]) -> bool:
    """Recover, from the persisted payload, whether this analysis used news evidence.

    Records written before this PR lack the field, so fall back to inferring from the count: >0 means
    evidence existed, anything else is treated as no evidence. That matches how the record's report behaved at the time and does not retroactively change old reports.
    """
    if isinstance(raw_result, Mapping) and "news_evidence_present" in raw_result:
        return bool(raw_result.get("news_evidence_present"))
    return bool(news_result_count)

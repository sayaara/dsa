# -*- coding: utf-8 -*-
"""Data values inside the English analysis request are English and keep their meaning."""

import re

import pytest

from tests.litellm_stub import ensure_litellm_stub

ensure_litellm_stub()

from src.analyzer import (  # noqa: E402
    _BEARISH_TREND_HINTS,
    _BULLISH_TREND_HINTS,
    _WEAK_BEARISH_TREND_HINTS,
    _WEAK_BULLISH_TREND_HINTS,
    _contains_trend_hint,
    _infer_trend_direction,
    _sanitize_trend_analysis_for_prompt,
)
from src.core.pipeline import StockAnalysisPipeline  # noqa: E402
from src.report_language import localize_operation_advice  # noqa: E402
from src.search_service import SearchResponse, SearchResult, SearchService  # noqa: E402
from src.stock_analyzer import BuySignal, MACDStatus, RSIStatus, TrendStatus, VolumeStatus  # noqa: E402

_CJK = re.compile(r"[　-〿一-鿿＀-￯]")
_BULL = _BULLISH_TREND_HINTS + _WEAK_BULLISH_TREND_HINTS
_BEAR = _BEARISH_TREND_HINTS + _WEAK_BEARISH_TREND_HINTS


@pytest.mark.parametrize("enum_cls", [TrendStatus, VolumeStatus, BuySignal, MACDStatus, RSIStatus])
def test_trend_enums_are_english_and_distinct(enum_cls) -> None:
    values = [member.value for member in enum_cls]
    assert len(values) == len(set(values)) == len(enum_cls.__members__)
    assert [v for v in values if _CJK.search(v)] == []


def test_buy_signal_values_survive_the_english_localizer_unchanged() -> None:
    for member in BuySignal:
        assert localize_operation_advice(member.value, "en") == member.value


@pytest.mark.parametrize(
    ("status", "alignment", "direction"),
    [
        ("Strong Bullish", "Strong bullish alignment, MAs fanning upward", "bullish"),
        ("Bullish", "Bullish alignment MA5>MA10>MA20", "bullish"),
        ("Weak Bullish", "Weak bullish, MA5>MA10 but MA10≤MA20", "bullish"),
        ("Sideways", "MAs tangled, direction unclear", "neutral"),
        ("Weak Bearish", "Weak bearish, MA5<MA10 but MA10≥MA20", "bearish"),
        ("Bearish", "Bearish alignment MA5<MA10<MA20", "bearish"),
        ("Strong Bearish", "Strong bearish alignment, MAs fanning downward", "bearish"),
        # stored Chinese values from older runs still classify
        ("空头排列", "空头排列 MA5<MA10<MA20", "bearish"),
    ],
)
def test_english_trend_states_infer_the_same_direction(status, alignment, direction) -> None:
    assert _infer_trend_direction({"trend_status": status, "ma_alignment": alignment}) == direction


@pytest.mark.parametrize(
    ("text", "bullish", "bearish"),
    [
        ("✓ Bullish MACD, still rising", True, False),
        ("⚠ Bearish MACD, still falling", False, True),
        ("✅ Golden cross, uptrend", True, False),
        ("❌ Death cross, downtrend", False, True),
        # these had no trend hint in Chinese, so they must not gain one in English
        ("✅ RSI strong (65.0), buying pressure solid", False, False),
        ("Rising on heavy volume, strong buying", False, False),
        ("✅ Price slightly below MA5 (-0.5%), pullback entry", False, False),
        ("⚡ DIF crossed above zero, trend strengthening", False, False),
    ],
)
def test_english_reasons_keep_their_trend_hint_status(text, bullish, bearish) -> None:
    assert _contains_trend_hint(text, _BULL) is bullish
    assert _contains_trend_hint(text, _BEAR) is bearish


def test_consistency_notes_follow_the_language() -> None:
    trend = {
        "trend_status": "Bearish",
        "ma_alignment": "Bearish alignment MA5<MA10<MA20",
        "signal_reasons": ["✓ Bullish MACD, still rising", "✅ MA5 support holding"],
        "risk_factors": [],
    }

    english = _sanitize_trend_analysis_for_prompt(trend, volume_change_ratio=12.0, language="en")
    chinese = _sanitize_trend_analysis_for_prompt(trend, volume_change_ratio=12.0)

    assert english["signal_reasons"] == ["✅ MA5 support holding"]
    assert [n for n in english["prompt_consistency_notes"] if _CJK.search(n)] == []
    assert any("12.00x" in n for n in english["prompt_consistency_notes"])
    assert all(_CJK.search(n) for n in chinese["prompt_consistency_notes"])


def test_ma_status_is_english() -> None:
    compute = StockAnalysisPipeline._compute_ma_status
    assert compute(110, 105, 100, 95) == "Bullish alignment 📈"
    assert compute(90, 95, 100, 105) == "Bearish alignment 📉"
    assert compute(100, 100, 100, 100) == "Range-bound ↔️"


@pytest.mark.parametrize("code", ["RY.TO", "TECK-B.TO", "ABX.V", "AAPL", "HK00700"])
def test_canadian_and_other_supported_tickers_are_foreign_for_search(code) -> None:
    assert SearchService._is_foreign_stock(code) is True


def test_news_context_is_english() -> None:
    result = SearchResult(
        title="Royal Bank beats estimates", snippet="Quarterly profit rose.", url="https://example.com/a",
        source="Reuters", published_date="2026-10-01", relevance_score=90,
        relevance_category="direct_company_news", relevance_reasons=["company name in title: Royal Bank"],
    )
    context = SearchResponse(query="RY.TO", results=[result], provider="Unit").to_context()
    empty = SearchResponse(query="RY.TO", results=[], provider="Unit").to_context()
    report = SearchService.__new__(SearchService).format_intel_report(
        {"latest_news": SearchResponse(query="q", results=[result], provider="Unit"),
         "risk_check": SearchResponse(query="q", results=[], provider="Unit")},
        "Royal Bank of Canada",
    )

    for text in (context, empty, report):
        assert _CJK.findall(text) == [], text
    assert "Relevance: direct_company_news; score=90; basis: company name in title: Royal Bank" in context
    assert "📰 Latest news (source: Unit):" in report
    assert "No relevant information found" in report

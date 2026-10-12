# -*- coding: utf-8 -*-
"""Tests for Issue #1381 daily market context decision guardrail."""

from __future__ import annotations

from src.analyzer import AnalysisResult
from src.daily_market_context_guardrail import apply_daily_market_context_guardrail


def _result() -> AnalysisResult:
    return AnalysisResult(
        code="600519",
        name="贵州茅台",
        sentiment_score=82,
        trend_prediction="看多",
        operation_advice="立即买入并积极加仓",
        decision_type="buy",
        confidence_level="高",
        analysis_summary="个股信号强势",
        dashboard={
            "operation_advice": "立即买入并积极加仓",
            "decision_type": "buy",
            "core_conclusion": {
                "one_sentence": "立即买入并积极加仓",
                "position_advice": {
                    "no_position": "立即买入并积极加仓",
                    "has_position": "继续加仓",
                },
            },
            "battle_plan": {
                "position_strategy": {
                    "suggested_position": "满仓买入",
                    "entry_plan": "突破后立即买入",
                    "risk_control": "回踩继续加仓",
                },
            },
            "phase_decision": {
                "data_limitations": [],
                "confidence_reason": "趋势强",
            },
        },
    )


def test_conservative_market_context_softens_aggressive_buy() -> None:
    result = _result()

    adjustments = apply_daily_market_context_guardrail(
        result,
        daily_market_context={
            "region": "cn",
            "trade_date": "2026-06-06",
            "summary": "大盘退潮，高风险，建议观望，仓位上限30%。",
            "risk_tags": ["high_risk", "low_position_cap"],
        },
        report_language="zh",
    )

    assert "daily_market_context_buy_softened" in adjustments
    assert result.decision_type == "hold"
    assert result.operation_advice == "Watch"
    assert len(result.operation_advice) <= 20
    assert result.confidence_level == "Medium"
    assert result.sentiment_score == 52
    assert result.dashboard["operation_advice"] == result.operation_advice
    assert result.dashboard["decision_type"] == "hold"
    assert result.dashboard["sentiment_score"] == 52
    core = result.dashboard["core_conclusion"]
    assert core["one_sentence"] == result.operation_advice
    no_position = "Do not open a new position until market risk eases or confirmation appears."
    assert core["position_advice"] == {
        "no_position": no_position,
        "has_position": "Hold only a small position; do not increase exposure, and reduce if risk controls break.",
    }
    position_strategy = result.dashboard["battle_plan"]["position_strategy"]
    assert position_strategy == {
        "suggested_position": "Small/defensive position",
        "entry_plan": no_position,
        "risk_control": "Do not increase exposure before market risk eases; control drawdown strictly.",
    }
    phase_decision = result.dashboard["phase_decision"]
    assert "Daily market context is conservative/high risk; aggressive buy advice was softened." in phase_decision["data_limitations"]
    assert phase_decision["confidence_reason"] == "趋势强; Market context requires conservative sizing."


def test_position_cap_only_market_context_softens_aggressive_buy() -> None:
    cases = [
        ("zh", "市场震荡，仓位不超过30%。", "Buy now and add aggressively.", "High", "Watch"),
        ("en", "Major indices are mixed. Position limit 30%.", "Buy now and add aggressively.", "High", "Watch"),
    ]
    for language, summary, advice, confidence, expected_advice in cases:
        result = _result()
        result.operation_advice = advice
        result.confidence_level = confidence

        adjustments = apply_daily_market_context_guardrail(
            result,
            daily_market_context={
                "region": "us" if language == "en" else "cn",
                "trade_date": "2026-06-06",
                "summary": summary,
                "risk_tags": [],
                "position_cap": "30%",
            },
            report_language=language,
        )

        assert "daily_market_context_buy_softened" in adjustments
        assert result.decision_type == "hold"
        assert result.operation_advice == expected_advice


def test_neutral_market_context_leaves_hold_unchanged() -> None:
    result = _result()
    result.decision_type = "hold"
    result.operation_advice = "持有观察"
    result.confidence_level = "中"

    adjustments = apply_daily_market_context_guardrail(
        result,
        daily_market_context={
            "region": "cn",
            "trade_date": "2026-06-06",
            "summary": "市场震荡，结构分化。",
            "risk_tags": [],
        },
        report_language="zh",
    )

    assert adjustments == []
    assert result.decision_type == "hold"
    assert result.operation_advice == "持有观察"


def test_conservative_market_context_does_not_soften_no_action_in_english() -> None:
    result = _result()
    result.decision_type = "hold"
    result.operation_advice = "No add now; keep watching for confirmation."

    adjustments = apply_daily_market_context_guardrail(
        result,
        daily_market_context={
            "region": "us",
            "trade_date": "2026-06-06",
            "summary": "Market cooling and elevated risk. Cautious on new positions."
        },
        report_language="en",
    )

    assert adjustments == []
    assert result.decision_type == "hold"
    assert result.operation_advice == "No add now; keep watching for confirmation."


def test_conservative_market_context_softens_generic_buy_advice_phrase() -> None:
    result = _result()
    result.operation_advice = "回踩买入，强支撑上攻。"
    result.confidence_level = "高"

    adjustments = apply_daily_market_context_guardrail(
        result,
        daily_market_context={
            "region": "cn",
            "trade_date": "2026-06-06",
            "summary": "大盘退潮，高风险，建议观望，仓位上限30%。",
            "risk_tags": ["high_risk", "low_position_cap"],
        },
        report_language="zh",
    )

    assert "daily_market_context_buy_softened" in adjustments
    assert result.decision_type == "hold"
    assert result.operation_advice == "Watch"


def test_conservative_market_context_softens_when_risk_warning_then_recommend_buy() -> None:
    result = _result()
    result.decision_type = "buy"
    result.operation_advice = "风险不能忽视，但建议买入等待确认信号。"
    result.confidence_level = "高"

    adjustments = apply_daily_market_context_guardrail(
        result,
        daily_market_context={
            "region": "cn",
            "trade_date": "2026-06-06",
            "summary": "大盘退潮，高风险，建议观望，仓位上限30%。",
            "risk_tags": ["high_risk", "low_position_cap"],
        },
        report_language="zh",
    )

    assert "daily_market_context_buy_softened" in adjustments
    assert result.decision_type == "hold"
    assert result.operation_advice == "Watch"


def test_conservative_market_context_softens_when_negated_chase_then_recommend_buy() -> None:
    result = _result()
    result.decision_type = "buy"
    result.operation_advice = "不建议追高，但建议分批买入。"
    result.confidence_level = "高"

    adjustments = apply_daily_market_context_guardrail(
        result,
        daily_market_context={
            "region": "cn",
            "trade_date": "2026-06-06",
            "summary": "大盘退潮，高风险，建议观望，仓位上限30%。",
            "risk_tags": ["high_risk", "low_position_cap"],
        },
        report_language="zh",
    )

    assert "daily_market_context_buy_softened" in adjustments
    assert result.decision_type == "hold"
    assert result.operation_advice == "Watch"


def test_conservative_market_context_does_not_soften_buy_when_negated_explicitly_in_english() -> None:
    result = _result()
    result.decision_type = "buy"
    result.operation_advice = "No buy now; avoid adding."

    adjustments = apply_daily_market_context_guardrail(
        result,
        daily_market_context={
            "region": "cn",
            "trade_date": "2026-06-06",
            "summary": "大盘退潮，高风险，建议观望，仓位上限30%。",
            "risk_tags": ["high_risk", "low_position_cap"],
        },
        report_language="en",
    )

    assert adjustments == []
    assert result.decision_type == "buy"
    assert result.operation_advice == "No buy now; avoid adding."


def test_conservative_market_context_does_not_soften_do_not_buy_in_english() -> None:
    result = _result()
    result.decision_type = "buy"
    result.operation_advice = "Do not buy now; sell into strength."

    adjustments = apply_daily_market_context_guardrail(
        result,
        daily_market_context={
            "region": "us",
            "trade_date": "2026-06-06",
            "summary": "Market cooling and elevated risk. Cautious on new positions.",
        },
        report_language="en",
    )

    assert adjustments == []
    assert result.decision_type == "buy"
    assert result.operation_advice == "Do not buy now; sell into strength."

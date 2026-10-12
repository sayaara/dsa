# -*- coding: utf-8 -*-
"""The English analysis request (``GeminiAnalyzer._format_prompt_en``)."""

import re
from unittest.mock import patch

import pytest

from tests.litellm_stub import ensure_litellm_stub

ensure_litellm_stub()

from src.analyzer import GeminiAnalyzer, _format_amount_en, _format_volume_en  # noqa: E402

_CJK = re.compile(r"[　-〿一-鿿＀-￯]")


def _analyzer(**kwargs) -> GeminiAnalyzer:
    with patch.object(GeminiAnalyzer, "_init_litellm", return_value=None):
        return GeminiAnalyzer(**kwargs)


def _context(code: str, name: str) -> dict:
    return {
        "code": code,
        "stock_name": name,
        "date": "2026-10-02",
        "today": {
            "close": 412.5, "open": 410.0, "high": 415.0, "low": 408.0,
            "pct_chg": 0.6, "volume": 2_300_000, "amount": 948_000_000,
            "ma5": 409.1, "ma10": 405.2, "ma20": 398.7,
        },
        "ma_status": "Bullish alignment",
        "realtime": {"price": 412.5, "volume_ratio": 1.1, "turnover_rate": 0.4, "total_mv": 3.1e12},
        "chip": {"profit_ratio": 0.8, "avg_cost": 380.0, "concentration_90": 0.12, "concentration_70": 0.08,
                 "chip_status": "Concentrated"},
        "trend_analysis": {
            "trend_status": "Bullish", "ma_alignment": "MA5>MA10>MA20", "trend_strength": 72,
            "bias_ma5": 0.8, "bias_ma10": 1.8, "volume_status": "Normal", "volume_trend": "Steady",
            "buy_signal": "Hold", "signal_score": 66, "signal_reasons": ["Trend intact"],
            "risk_factors": ["Near resistance"],
        },
        "yesterday": {"close": 410.0},
        "volume_change_ratio": 1.2,
        "price_change_ratio": 0.6,
        "fundamental_context": {
            "earnings": {"data": {"financial_report": {"report_date": "2026-06-30"}, "dividend": {}}},
            "capital_flow": {"data": {"stock_flow": {"main_net_inflow": 1.0}, "sector_rankings": {}}},
        },
        "news_window_days": 3,
    }


@pytest.mark.parametrize(
    ("code", "name", "currency"),
    [("AAPL", "Apple Inc.", "USD"), ("RY.TO", "Royal Bank of Canada", "CAD")],
)
def test_english_request_uses_the_stock_currency_and_no_chinese(code, name, currency) -> None:
    prompt = _analyzer()._format_prompt(_context(code, name), name, news_context="2026-10-01 Earnings beat.",
                                        report_language="en")

    assert prompt.startswith("# Decision Dashboard Analysis Request")
    assert f"| Close | 412.5 {currency} |" in prompt
    assert f"| Average cost | 380.0 {currency} |" in prompt
    assert f"| Turnover | 948.00M {currency} |" in prompt
    assert "| Volume | 2.30M shares |" in prompt
    assert "元" not in prompt
    assert _CJK.findall(prompt) == []


def test_english_request_asks_for_the_english_company_name() -> None:
    prompt = _analyzer()._format_prompt(_context("AAPL", "Apple Inc."), "Apple Inc.", report_language="en")

    assert 'for example "Apple Inc. (AAPL)"' in prompt
    assert "correct English company name" in prompt
    assert "600519" not in prompt


def test_missing_name_falls_back_to_the_code_not_the_chinese_placeholder() -> None:
    context = _context("ZZZZ", "")
    context["stock_name"] = "股票ZZZZ"

    prompt = _analyzer()._format_prompt(context, "股票ZZZZ", report_language="en")

    assert "| Stock name | **ZZZZ** |" in prompt
    assert "股票" not in prompt


def test_skill_mode_uses_the_skill_questions() -> None:
    analyzer = _analyzer(skill_instructions="### Skill 1\n- Watch the pivot", default_skill_policy="",
                         use_legacy_default_prompt=False)

    prompt = analyzer._format_prompt(_context("AAPL", "Apple Inc."), "Apple Inc.", report_language="en")

    assert "Technical and Structure Analysis (reference for the active skills)" in prompt
    assert "Does the current structure meet the key trigger conditions of the active skills?" in prompt
    assert "Is MA5>MA10>MA20 (bullish alignment) satisfied?" not in prompt


def test_every_report_language_gets_the_english_request() -> None:
    analyzer = _analyzer()
    context = _context("AAPL", "Apple Inc.")

    english = analyzer._format_prompt(context, "Apple Inc.", report_language="en")
    for language in ("zh", "ko", None):
        assert analyzer._format_prompt(context, "Apple Inc.", report_language=language) == english
    assert english.startswith("# Decision Dashboard Analysis Request")


def test_text_system_prompt_is_english() -> None:
    assert GeminiAnalyzer.TEXT_SYSTEM_PROMPT.startswith("You are a professional stock analysis assistant.")
    assert "Do not invent prices, financial results or news facts." in GeminiAnalyzer.TEXT_SYSTEM_PROMPT
    assert _CJK.findall(GeminiAnalyzer.TEXT_SYSTEM_PROMPT) == []


def test_english_formatters() -> None:
    assert _format_volume_en(None) == "N/A"
    assert _format_volume_en(1_500_000_000) == "1.50B shares"
    assert _format_volume_en(12_345) == "12,345 shares"
    assert _format_amount_en(2_500_000_000, "HKD") == "2.50B HKD"
    assert _format_amount_en(7_500_000, "") == "7.50M"
    assert _format_amount_en(None, "USD") == "N/A"

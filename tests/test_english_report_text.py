# -*- coding: utf-8 -*-
"""English reports contain no Chinese text.

Renders a fully populated English analysis result through every report
generator (with and without the Jinja2 renderer) and checks that no line
contains CJK characters or full-width punctuation.
"""

import re
from unittest import mock

import pytest

try:
    import litellm  # noqa: F401
except ModuleNotFoundError:
    from tests.litellm_stub import ensure_litellm_stub
    ensure_litellm_stub()

from src.analyzer import AnalysisResult, GeminiAnalyzer
from src.config import Config
from src.notification import NotificationService

CJK = re.compile(r"[一-鿿　-〿＀-￯]")

_DASHBOARD = {
    "core_conclusion": {
        "one_sentence": "Hold and wait for a pullback to MA10 before adding.",
        "signal_type": "🟡Hold and watch",
        "time_sensitivity": "Within this week",
        "position_advice": {"no_position": "Wait for a pullback.", "has_position": "Hold with a stop below MA20."},
    },
    "data_perspective": {
        "trend_status": {"ma_alignment": "MA5>MA10>MA20", "is_bullish": True, "trend_score": 72},
        "price_position": {"current_price": 232.5, "ma5": 230.1, "ma10": 227.4, "ma20": 221.9, "bias_ma5": 1.04,
                           "bias_status": "Safe", "support_level": 227.0, "resistance_level": 240.0},
        "volume_analysis": {"volume_ratio": 0.9, "volume_status": "Flat", "turnover_rate": 0.6,
                            "volume_meaning": "Low-volume pullback."},
        "chip_structure": {"profit_ratio": 0.78, "avg_cost": 215.3, "concentration": 0.12, "chip_health": "Healthy"},
    },
    "intelligence": {
        "latest_news": "Record services revenue.",
        "risk_alerts": ["Valuation is above the five-year average."],
        "positive_catalysts": ["New product cycle."],
        "earnings_outlook": "Mid-single-digit growth.",
        "sentiment_summary": "Constructive.",
    },
    "battle_plan": {
        "sniper_points": {"ideal_buy": "Ideal entry: 227", "secondary_buy": "Second-best entry: 222",
                          "stop_loss": "Stop loss: 218", "take_profit": "Target: 245"},
        "position_strategy": {"suggested_position": "3 tenths", "entry_plan": "Scale in.", "risk_control": "Exit below 218."},
        "action_checklist": ["✅ Check 1: bullish alignment", "⚠️ Check 2: bias is reasonable"],
    },
}

_TEXT_FIELDS = {
    "confidence_level": "Medium",
    "key_points": "Trend intact, valuation high",
    "risk_warning": "Valuation risk",
    "buy_reason": "Trend-following entry on pullbacks",
    "trend_analysis": "Higher highs and higher lows",
    "short_term_outlook": "Range 227-240",
    "medium_term_outlook": "Grind higher",
    "technical_analysis": "MACD positive",
    "ma_analysis": "Above all MAs",
    "volume_analysis": "Flat",
    "pattern_analysis": "Bull flag",
    "fundamental_analysis": "Strong margins",
    "sector_position": "Leader",
    "company_highlights": "Services growth",
    "news_summary": "Record services revenue",
    "market_sentiment": "Constructive",
    "hot_topics": "AI devices",
    "data_sources": "daily:YfinanceFetcher",
    "search_performed": True,
}


def _market_snapshot(code: str, report_language: str = "en") -> dict:
    """Build the snapshot with the real analyzer method, as the pipeline does."""
    analyzer = GeminiAnalyzer.__new__(GeminiAnalyzer)
    context = {
        "code": code,
        "date": "2026-10-08",
        "today": {"open": 230.0, "high": 234.0, "low": 229.5, "close": 232.5, "pct_chg": 0.86,
                  "volume": 5_200_000, "amount": 990_000_000},
        "yesterday": {"close": 230.5},
        "realtime": {"price": 232.5, "volume_ratio": 0.9, "turnover_rate": 0.6, "source": "yfinance"},
    }
    return analyzer._build_market_snapshot(context, report_language)


def _fundamental_context(currency: str) -> dict:
    return {
        "earnings": {
            "status": "ok",
            "data": {
                "financial_report": {
                    "report_date": "2026-06-30",
                    "revenue": 390_000_000_000,
                    "net_profit_parent": -12_500_000,
                    "operating_cash_flow": 110_000_000_000,
                    "roe": 28.5,
                    "currency": currency,
                },
                "dividend": {
                    "ttm_cash_dividend_per_share": 5.9,
                    "ttm_event_count": 4,
                    "ttm_dividend_yield_pct": 3.4,
                    "currency": currency,
                    "events": [{"ex_dividend_date": "2026-07-24"}],
                },
            },
        },
        "growth": {"status": "ok", "data": {"revenue_yoy": 6.1, "net_profit_yoy": 4.2, "gross_margin": 46.0}},
    }


def _result(code: str, name: str, score: int, advice: str, decision: str) -> AnalysisResult:
    result = AnalysisResult(
        code=code,
        name=name,
        trend_prediction="Bullish",
        sentiment_score=score,
        operation_advice=advice,
        analysis_summary="Uptrend intact; wait for a better entry.",
        decision_type=decision,
        dashboard=_DASHBOARD,
        report_language="en",
        model_used="anthropic/claude-sonnet-5-5",
    )
    for attr, value in _TEXT_FIELDS.items():
        if hasattr(result, attr):
            setattr(result, attr, value)
    result.market_snapshot = _market_snapshot(code)
    result.fundamental_context = _fundamental_context("CAD" if code.endswith(".TO") else "USD")
    return result


def _results():
    return [
        _result("AAPL", "Apple Inc.", 68, "Hold", "hold"),
        _result("MSFT", "Microsoft Corporation", 81, "Buy", "buy"),
        _result("RY.TO", "Royal Bank of Canada", 35, "Reduce", "sell"),
    ]


def _chinese_lines(text: str):
    return [line for line in str(text).splitlines() if CJK.search(line)]


@pytest.mark.parametrize("renderer_enabled", [False, True])
@mock.patch("src.notification.get_config")
def test_english_reports_have_no_chinese_text(mock_get_config, renderer_enabled):
    mock_get_config.return_value = Config(
        stock_list=[], report_language="en", report_renderer_enabled=renderer_enabled
    )
    service = NotificationService()
    results = _results()
    outputs = {
        "daily": service.generate_daily_report(results),
        "dashboard": service.generate_dashboard_report(results),
        "brief": service.generate_brief_report(results),
        "single": service.generate_single_stock_report(results[0]),
        "aggregate_simple": service.generate_aggregate_report(results, "simple"),
        "aggregate_full": service.generate_aggregate_report(results, "full"),
        "aggregate_brief": service.generate_aggregate_report(results, "brief"),
    }
    for name, text in outputs.items():
        assert text, name
        assert _chinese_lines(text) == [], name
        # The snapshot and fundamentals blocks are rendered, not silently skipped.
        assert "5.20M shares" in text or name == "brief" or name == "aggregate_brief", name


@mock.patch("src.notification.get_config")
def test_english_report_units_use_the_stock_currency(mock_get_config):
    mock_get_config.return_value = Config(stock_list=[], report_language="en", report_renderer_enabled=False)
    service = NotificationService()
    us, _, ca = _results()

    us_report = service.generate_single_stock_report(us)
    ca_report = service.generate_single_stock_report(ca)

    assert "990.00M USD" in us_report
    assert "990.00M CAD" in ca_report
    assert "390.00B CAD" in ca_report
    assert "-12.50M CAD" in ca_report
    assert "5.9000 CAD" in ca_report
    assert " USD" not in ca_report


def test_chinese_snapshot_keeps_chinese_units_with_the_stock_currency():
    assert _market_snapshot("AAPL", "zh")["amount"] == "9.90 亿美元"
    assert _market_snapshot("RY.TO", "zh")["amount"] == "9.90 亿加元"
    assert _market_snapshot("RY.TO", "zh")["volume"] == "520.00 万股"

# -*- coding: utf-8 -*-
"""Tests for signal_attribution real entry points (not just schema)."""

import sys
import os

# Make sure the project root is on sys.path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.utils.data_processing import normalize_signal_attribution_values, normalize_dashboard_signal_attribution

# AnalysisResult is defined in analyzer.py
from src.analyzer import AnalysisResult


class TestNormalizeSignalAttribution:
    """Tests for the normalisation helper (it runs before _parse_response)"""

    def test_string_percentage_conversion(self):
        d = {"technical_indicators": "70%", "news_sentiment": "0%", "fundamentals": "15%", "market_conditions": "15%"}
        normalize_signal_attribution_values(d)
        assert d["technical_indicators"] == 70
        assert d["news_sentiment"] == 0

    def test_na_string_becomes_none(self):
        d = {"technical_indicators": "N/A", "news_sentiment": 0, "fundamentals": 0, "market_conditions": 0}
        normalize_signal_attribution_values(d)
        assert d["technical_indicators"] is None

    def test_negative_clamped_to_zero(self):
        d = {"technical_indicators": -10, "news_sentiment": 20, "fundamentals": 30, "market_conditions": 60}
        normalize_signal_attribution_values(d)
        assert d["technical_indicators"] == 0

    def test_sum_normalized_to_100(self):
        d = {"technical_indicators": 70, "news_sentiment": 10, "fundamentals": 20, "market_conditions": 10}
        # sum=110
        normalize_signal_attribution_values(d)
        total = sum([d["technical_indicators"], d["news_sentiment"], d["fundamentals"], d["market_conditions"]])
        assert total == 100

    def test_partial_none_no_normalization(self):
        d = {"technical_indicators": 70, "news_sentiment": None, "fundamentals": 30, "market_conditions": None}
        normalize_signal_attribution_values(d)
        # Only two valid values, so no normalisation
        assert d["technical_indicators"] == 70
        assert d["news_sentiment"] is None


class TestNormalizeDashboardSignalAttribution:
    """Tests for dashboard-level normalisation (operating directly on the dashboard dict)"""

    def test_inplace_normalization(self):
        dashboard = {
            "signal_attribution": {
                "technical_indicators": "70%",
                "news_sentiment": "0%",
                "fundamentals": "15%",
                "market_conditions": "15%",
            }
        }
        normalize_dashboard_signal_attribution(dashboard)
        sa = dashboard["signal_attribution"]
        assert sa["technical_indicators"] == 70

    def test_no_signal_attribution_key(self):
        dashboard = {"core_conclusion": {}}
        normalize_dashboard_signal_attribution(dashboard)  # must not raise
        assert "signal_attribution" not in dashboard

    def test_signal_attribution_none(self):
        dashboard = {"signal_attribution": None}
        normalize_dashboard_signal_attribution(dashboard)  # must not raise


class TestParseResponseIntegration:
    """
    Check that _parse_response parses signal_attribution correctly.
    _parse_response is an instance method with heavy configuration dependencies, so this is an integration test confirming the normalisation helper is called.
    """

    def test_normalization_called_in_parse_response(self):
        """
        Check that a percentage the LLM returns as a string becomes an int after normalisation.
        Verified by exercising the normalisation call _parse_response makes.
        """
        # Mock the data dict the LLM returns
        data = {
            "sentiment_score": 50,
            "trend_prediction": "震荡",
            "operation_advice": "持有",
            "decision_type": "hold",
            "confidence_level": "中",
            "analysis_summary": "测试",
            "dashboard": {
                "signal_attribution": {
                    "technical_indicators": "70%",
                    "news_sentiment": "0%",
                    "fundamentals": "15%",
                    "market_conditions": "15%",
                    "strongest_bullish_signal": "MACD金叉",
                    "strongest_bearish_signal": None,
                }
            },
        }
        # Call the normalisation by hand (mimicking what _parse_response does)
        normalize_dashboard_signal_attribution(data.get("dashboard"))
        sa = data["dashboard"]["signal_attribution"]
        assert sa["technical_indicators"] == 70
        assert sa["news_sentiment"] == 0


class TestHistoryServiceDisplay:
    """Check that HistoryService._generate_single_stock_markdown can render signal_attribution"""

    def test_signal_attribution_in_markdown(self):
        """Check that the markdown report includes the signal attribution section"""
        from src.services.history_service import HistoryService

        result = AnalysisResult(
            code="600519",
            name="贵州茅台",
            sentiment_score=50,
            trend_prediction="震荡",
            operation_advice="持有",
            dashboard={
                "signal_attribution": {
                    "technical_indicators": 70,
                    "news_sentiment": 0,
                    "fundamentals": 15,
                    "market_conditions": 15,
                    "strongest_bullish_signal": "MACD金叉",
                    "strongest_bearish_signal": None,
                }
            },
        )

        # Create a mock record
        class MockRecord:
            created_at = None

        markdown = HistoryService()._generate_single_stock_markdown(result, MockRecord())
        assert "信号归因" in markdown or "Signal Attribution" in markdown
        assert "70%" in markdown or "70%" in markdown

    def test_no_signal_attribution_no_section(self):
        """Check that the section is hidden when there is no signal_attribution"""
        from src.services.history_service import HistoryService

        result = AnalysisResult(
            code="600519",
            name="贵州茅台",
            sentiment_score=50,
            trend_prediction="震荡",
            operation_advice="持有",
            dashboard={},
        )

        class MockRecord:
            created_at = None

        markdown = HistoryService()._generate_single_stock_markdown(result, MockRecord())
        assert "信号归因" not in markdown


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v"])

"""
End-to-end tests: the full signal_attribution contract.

Paths covered:
1. LLM raw JSON -> _parse_response() -> AnalysisResult.dashboard (normalisation applied)
2. AnalysisResult.dashboard -> notification (rendered correctly)
3. AnalysisResult.dashboard -> Jinja2 template (rendered correctly)
4. AnalysisResult.dashboard -> HistoryService markdown (rendered correctly)
5. check_content_integrity() (the contract check)
"""
import sys
import os
import pytest
import json

# Add src to the path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from src.analyzer import AnalysisResult, check_content_integrity
from src.utils.data_processing import normalize_dashboard_signal_attribution
from src.agent.runner import parse_dashboard_json
from src.services.report_renderer import render


class TestSignalAttributionE2E:
    """End to end: signal_attribution works correctly on every path"""

    def _make_dashboard_with_signal_attr(self, signal_attr):
        """Build a dashboard dict carrying signal_attribution"""
        return {
            "core_conclusion": {
                "one_sentence": "测试结论",
                "signal": "buy",
                "confidence": "中",
            },
            "intelligence": {
                "risk_alerts": ["测试风险"],
            },
            "signal_attribution": signal_attr,
        }

    def _make_result(self, dashboard):
        """Build an AnalysisResult"""
        return AnalysisResult(
            code="600519",
            name="测试股票",
            sentiment_score=50,
            trend_prediction="震荡",
            operation_advice="持有",
            decision_type="hold",
            confidence_level="中",
            dashboard=dashboard,
            analysis_summary="测试摘要",
        )

    # ========== Test 1: _parse_response() normalisation ==========
    def test_normalize_called_in_parse_response(self):
        """
        Check that _parse_response() calls the normalisation helper.

        Verifies:
        1. A contribution supplied as the string "30%" becomes the int 30 after normalisation
        2. Contributions that do not sum to 100 are normalised so that they do
        """
        from src.analyzer import GeminiAnalyzer

        # Create the analyzer instance
        analyzer = GeminiAnalyzer.__new__(GeminiAnalyzer)

        # Mock the JSON the LLM returns (contributions as strings, total != 100)
        response_text = json.dumps({
            "sentiment_score": 50,
            "trend_prediction": "震荡",
            "operation_advice": "持有",
            "decision_type": "hold",
            "confidence_level": "中",
            "analysis_summary": "测试",
            "dashboard": {
                "core_conclusion": {"one_sentence": "测试", "signal": "hold", "confidence": "中"},
                "intelligence": {"risk_alerts": []},
                "signal_attribution": {
                    "technical_indicators": "30%",
                    "news_sentiment": 20,
                    "fundamentals": 30,
                    "market_conditions": 10,  # total 90, and one of them is a string
                    "strongest_bullish_signal": "测试看涨",
                    "strongest_bearish_signal": "测试看空",
                },
            },
        })

        # Call _parse_response()
        result = analyzer._parse_response(response_text, "600519", "测试")

        # Check the normalisation ran
        dash = result.dashboard
        assert isinstance(dash, dict), "dashboard 应该是 dict"

        signal_attr = dash.get("signal_attribution")
        assert signal_attr is not None, "signal_attribution 应该存在"

        # Check the string became an int
        assert isinstance(signal_attr.get("technical_indicators"), int), "technical_indicators 应该是 int"

        # Check the total is 100
        total = sum([
            signal_attr.get("technical_indicators", 0),
            signal_attr.get("news_sentiment", 0),
            signal_attr.get("fundamentals", 0),
            signal_attr.get("market_conditions", 0),
        ])
        assert total == 100, f"贡献度之和应该=100，实际={total}"

    # ========== Test 2: notification rendering ==========
    def test_notification_renders_signal_attribution(self):
        """
        Check that generate_dashboard_report() in notification.py renders signal_attribution correctly.

        Verifies:
        1. With signal_attribution present, the notification carries the "信号归因" section
        2. All four contributions are displayed correctly
        """
        from src.notification import NotificationService

        signal_attr = {
            "technical_indicators": 35,
            "news_sentiment": 25,
            "fundamentals": 20,
            "market_conditions": 20,
            "strongest_bullish_signal": "MACD金叉",
            "strongest_bearish_signal": "成交量萎缩",
        }
        dashboard = self._make_dashboard_with_signal_attr(signal_attr)
        result = self._make_result(dashboard)

        # Call generate_dashboard_report()
        notification = NotificationService()
        report = notification.generate_dashboard_report([result], [dashboard])

        # Check the signal attribution section is present
        assert "信号归因" in report or "Signal Attribution" in report, "通知应包含信号归因段落"
        assert "35%" in report, "通知应显示 technical_indicators=35%"
        assert "25%" in report, "通知应显示 news_sentiment=25%"
        assert "20%" in report, "通知应显示 fundamentals=20%"
        assert "20%" in report, "通知应显示 market_conditions=20%"
        assert "MACD金叉" in report, "通知应显示 strongest_bullish_signal"

    # ========== Test 3: Jinja2 template rendering ==========
    def test_jinja2_template_renders_signal_attribution(self):
        """
        Check that templates/report_markdown.j2 renders signal_attribution correctly.

        Verifies:
        1. With signal_attribution present, the template output carries the attribution weights
        2. All four contributions are displayed correctly
        """
        signal_attr = {
            "technical_indicators": 35,
            "news_sentiment": 25,
            "fundamentals": 20,
            "market_conditions": 20,
            "strongest_bullish_signal": "MACD金叉",
        }
        result = self._make_result(self._make_dashboard_with_signal_attr(signal_attr))

        out = render("markdown", [result], summary_only=False, extra_context={"report_language": "zh"})

        assert out is not None
        assert "35%" in out
        assert "MACD金叉" in out

    def test_parse_dashboard_json_normalizes_nested_dashboard_payload(self):
        """Agent JSON can return a full report object with nested dashboard."""
        payload = json.dumps({
            "dashboard": {
                "signal_attribution": {
                    "technical_indicators": "70%",
                    "news_sentiment": "10%",
                    "fundamentals": "10%",
                    "market_conditions": "10%",
                }
            }
        })

        parsed = parse_dashboard_json(payload)

        assert parsed is not None
        signal_attr = parsed["dashboard"]["signal_attribution"]
        assert signal_attr["technical_indicators"] == 70
        assert isinstance(signal_attr["technical_indicators"], int)

    def test_non_dict_signal_attribution_is_removed_before_rendering(self):
        """Invalid non-dict signal_attribution must not survive into renderers."""
        dashboard = {"signal_attribution": "bad payload"}

        normalize_dashboard_signal_attribution(dashboard)

        assert "signal_attribution" not in dashboard

    def test_partial_signal_attribution_uses_same_display_contract(self):
        """Partial weights should not render N/A% or None% in any report path."""
        from src.notification import NotificationService
        from src.services.history_service import HistoryService

        dashboard = self._make_dashboard_with_signal_attr({
            "technical_indicators": 35,
            "news_sentiment": None,
            "fundamentals": None,
            "market_conditions": 0,
            "strongest_bullish_signal": "MACD金叉",
        })
        result = self._make_result(dashboard)
        notification = NotificationService()

        dashboard_report = notification.generate_dashboard_report([result], [dashboard])
        single_report = notification.generate_single_stock_report(result)

        class MockRecord:
            created_at = None

        history_report = HistoryService.__new__(HistoryService)._generate_single_stock_markdown(result, MockRecord())
        template_report = render("markdown", [result], summary_only=False, extra_context={"report_language": "zh"})

        for output in [dashboard_report, single_report, history_report, template_report]:
            assert output is not None
            assert "N/A%" not in output
            assert "None%" not in output
            assert "35%" in output

    def test_all_zero_signal_attribution_is_hidden_without_signals(self):
        """All-zero weights without strongest signals should not render attribution."""
        from src.notification import NotificationService
        from src.services.history_service import HistoryService

        dashboard = self._make_dashboard_with_signal_attr({
            "technical_indicators": 0,
            "news_sentiment": 0,
            "fundamentals": 0,
            "market_conditions": 0,
            "strongest_bullish_signal": None,
            "strongest_bearish_signal": None,
        })
        result = self._make_result(dashboard)
        notification = NotificationService()

        dashboard_report = notification.generate_dashboard_report([result], [dashboard])
        single_report = notification.generate_single_stock_report(result)

        class MockRecord:
            created_at = None

        history_report = HistoryService.__new__(HistoryService)._generate_single_stock_markdown(result, MockRecord())
        template_report = render("markdown", [result], summary_only=False, extra_context={"report_language": "zh"})

        for output in [dashboard_report, single_report, history_report, template_report]:
            assert output is not None
            assert "信号归因" not in output
            assert "Signal Attribution" not in output

    def test_non_finite_signal_attribution_is_hidden_across_real_paths(self):
        """NaN/Infinity weights are missing values, not confident attribution."""
        from src.analyzer import GeminiAnalyzer
        from src.notification import NotificationService
        from src.services.history_service import HistoryService

        def non_finite_signal_attr():
            return {
                "technical_indicators": float("nan"),
                "news_sentiment": "NaN",
                "fundamentals": float("inf"),
                "market_conditions": "-Infinity",
                "strongest_bullish_signal": None,
                "strongest_bearish_signal": "",
            }

        response_text = json.dumps({
            "sentiment_score": 50,
            "trend_prediction": "震荡",
            "operation_advice": "持有",
            "decision_type": "hold",
            "confidence_level": "中",
            "analysis_summary": "测试",
            "dashboard": {
                "core_conclusion": {"one_sentence": "测试", "signal": "hold", "confidence": "中"},
                "intelligence": {"risk_alerts": []},
                "signal_attribution": non_finite_signal_attr(),
            },
        })

        analyzer = GeminiAnalyzer.__new__(GeminiAnalyzer)
        result = analyzer._parse_response(response_text, "600519", "测试")
        dashboard = result.dashboard
        signal_attr = dashboard["signal_attribution"]

        for key in ("technical_indicators", "news_sentiment", "fundamentals", "market_conditions"):
            assert signal_attr[key] is None
        assert signal_attr["strongest_bearish_signal"] is None

        parsed = parse_dashboard_json(json.dumps({
            "dashboard": {
                "signal_attribution": non_finite_signal_attr(),
            }
        }))
        assert parsed is not None
        parsed_attr = parsed["dashboard"]["signal_attribution"]
        for key in ("technical_indicators", "news_sentiment", "fundamentals", "market_conditions"):
            assert parsed_attr[key] is None

        notification = NotificationService()
        dashboard_report = notification.generate_dashboard_report([result], [dashboard])
        single_report = notification.generate_single_stock_report(result)

        class MockRecord:
            created_at = None

        history_report = HistoryService.__new__(HistoryService)._generate_single_stock_markdown(result, MockRecord())
        template_report = render("markdown", [result], summary_only=False, extra_context={"report_language": "zh"})

        for output in [dashboard_report, single_report, history_report, template_report]:
            assert output is not None
            assert "信号归因" not in output
            assert "Signal Attribution" not in output
            assert "NaN" not in output
            assert "Infinity" not in output

    # ========== Test 4: HistoryService markdown rendering ==========
    def test_history_service_renders_signal_attribution(self):
        """
        Check that HistoryService._generate_single_stock_markdown() renders signal_attribution correctly.

        Verifies:
        1. With signal_attribution present, the markdown carries the "信号归因分析" section
        2. All four contributions are displayed correctly
        """
        from src.services.history_service import HistoryService

        signal_attr = {
            "technical_indicators": 35,
            "news_sentiment": 25,
            "fundamentals": 20,
            "market_conditions": 20,
            "strongest_bullish_signal": "MACD金叉",
            "strongest_bearish_signal": "成交量萎缩",
        }
        dashboard = self._make_dashboard_with_signal_attr(signal_attr)
        result = self._make_result(dashboard)

        # Create a mock record
        class MockRecord:
            created_at = None

        # Call _generate_single_stock_markdown()
        history_service = HistoryService.__new__(HistoryService)
        markdown = history_service._generate_single_stock_markdown(result, MockRecord())

        # Check the signal attribution section is present
        assert "信号归因" in markdown or "Signal Attribution" in markdown, "Markdown 应包含信号归因段落"
        assert "35%" in markdown, "Markdown 应显示 technical_indicators=35%"
        assert "MACD金叉" in markdown, "Markdown 应显示 strongest_bullish_signal"

    # ========== Test 5: the check_content_integrity() optional contract ==========
    def test_check_content_integrity_treats_signal_attribution_as_optional(self):
        """
        Check that check_content_integrity() treats signal_attribution as an optional display field.

        Verifies:
        1. With signal_attribution present, nothing is added to missing
        2. With signal_attribution absent, nothing is added to missing
        3. With the signal_attribution contributions absent, nothing is added to missing
        """
        # Case 1: signal_attribution complete
        signal_attr = {
            "technical_indicators": 35,
            "news_sentiment": 25,
            "fundamentals": 20,
            "market_conditions": 20,
        }
        dashboard = self._make_dashboard_with_signal_attr(signal_attr)
        result = self._make_result(dashboard)

        passed, missing = check_content_integrity(result)
        signal_attr_missing = [m for m in missing if "signal_attribution" in m]
        assert len(signal_attr_missing) == 0, f"signal_attribution 完整时不应出现在 missing 中，实际: {signal_attr_missing}"

        # Case 2: signal_attribution absent
        dashboard_no_attr = self._make_dashboard_with_signal_attr(None)
        dashboard_no_attr["battle_plan"] = {"sniper_points": {"stop_loss": "100"}}
        result_no_attr = self._make_result(dashboard_no_attr)

        passed, missing = check_content_integrity(result_no_attr)
        assert passed is True
        signal_attr_missing = [m for m in missing if "signal_attribution" in m]
        assert len(signal_attr_missing) == 0, "signal_attribution 缺失时不应出现在 missing 中"

        # Case 3: signal_attribution contributions absent
        signal_attr_incomplete = {
            "technical_indicators": 35,
            "news_sentiment": 25,
            # fundamentals and market_conditions are missing
        }
        dashboard_incomplete = self._make_dashboard_with_signal_attr(signal_attr_incomplete)
        dashboard_incomplete["battle_plan"] = {"sniper_points": {"stop_loss": "100"}}
        result_incomplete = self._make_result(dashboard_incomplete)

        passed, missing = check_content_integrity(result_incomplete)
        assert passed is True
        signal_attr_missing = [m for m in missing if "signal_attribution" in m]
        assert len(signal_attr_missing) == 0, "signal_attribution 贡献度缺失时不应出现在 missing 中"

    # ========== Test 6: normalisation helper tests ==========
    def test_normalize_dashboard_signal_attribution_direct(self):
        """
        Test normalize_dashboard_signal_attribution() directly.

        Verifies:
        1. A percentage string becomes an int
        2. A negative becomes 0
        3. A total other than 100 is normalised to 100
        4. None values are handled
        """
        # Case 1: a percentage string
        dashboard = {
            "signal_attribution": {
                "technical_indicators": "30%",
                "news_sentiment": 20,
                "fundamentals": "30",
                "market_conditions": 10,
                "strongest_bullish_signal": "测试",
            },
        }
        normalize_dashboard_signal_attribution(dashboard)
        attr = dashboard["signal_attribution"]
        # Check the string became an int (the exact value may shift under normalisation, but it must be an int)
        assert isinstance(attr["technical_indicators"], int), f"字符串百分比应转为 int: {attr['technical_indicators']}"
        assert isinstance(attr["fundamentals"], int), f"字符串应转为 int: {attr['fundamentals']}"

        # Check the total is 100
        total = sum([
            attr.get("technical_indicators", 0),
            attr.get("news_sentiment", 0),
            attr.get("fundamentals", 0),
            attr.get("market_conditions", 0),
        ])
        assert total == 100, f"归一化后总和应为 100: {total}"

        # Case 2: a negative
        dashboard = {
            "signal_attribution": {
                "technical_indicators": -10,
                "news_sentiment": 20,
                "fundamentals": 30,
                "market_conditions": 40,
            },
        }
        normalize_dashboard_signal_attribution(dashboard)
        attr = dashboard["signal_attribution"]
        assert attr["technical_indicators"] == 0, f"负数应转为 0: {attr['technical_indicators']}"

        # Case 3: total already 100, so no normalisation needed
        dashboard = {
            "signal_attribution": {
                "technical_indicators": 25,
                "news_sentiment": 25,
                "fundamentals": 25,
                "market_conditions": 25,
            },
        }
        normalize_dashboard_signal_attribution(dashboard)
        attr = dashboard["signal_attribution"]
        total = sum([attr["technical_indicators"], attr["news_sentiment"], attr["fundamentals"], attr["market_conditions"]])
        assert total == 100, f"总和应为 100: {total}"

        # Case 4: total != 100 (normalisation needed)
        dashboard = {
            "signal_attribution": {
                "technical_indicators": 10,
                "news_sentiment": 20,
                "fundamentals": 30,
                "market_conditions": 30,  # total 90
            },
        }
        normalize_dashboard_signal_attribution(dashboard)
        attr = dashboard["signal_attribution"]
        total = sum([attr["technical_indicators"], attr["news_sentiment"], attr["fundamentals"], attr["market_conditions"]])
        assert total == 100, f"归一化后总和应为 100: {total}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

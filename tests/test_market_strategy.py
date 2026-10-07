# -*- coding: utf-8 -*-
"""Tests for market strategy blueprints."""

import re
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from src.core.market_strategy import get_market_strategy_blueprint
from src.market_analyzer import MarketAnalyzer, MarketOverview


class TestMarketStrategyBlueprint(unittest.TestCase):
    """Validate CN/US strategy blueprint basics."""

    def test_us_blueprint_contains_regime_strategy(self):
        blueprint = get_market_strategy_blueprint("us")
        block = blueprint.to_prompt_block()

        self.assertIn("US Market Regime Strategy", block)
        self.assertIn("Risk-on", block)
        self.assertIn("Macro & Flows", block)

    def test_every_blueprint_is_english(self):
        cjk = re.compile(r"[　-〿一-鿿＀-￯]")
        for region in ("us", "ca"):
            blueprint = get_market_strategy_blueprint(region)
            with self.subTest(region=region):
                self.assertEqual(cjk.findall(blueprint.to_prompt_block()), [])
                self.assertEqual(cjk.findall(blueprint.to_markdown_block()), [])
                self.assertTrue(blueprint.to_markdown_block().startswith("### VI. Strategy Framework"))

        self.assertIn("Canadian Market Regime Strategy", get_market_strategy_blueprint("ca").to_prompt_block())


class TestMarketAnalyzerStrategyPrompt(unittest.TestCase):
    """Validate strategy section is injected into prompt/report."""

    def test_us_prompt_contains_strategy_plan_section(self):
        with patch("src.market_analyzer.get_config", return_value=SimpleNamespace(report_language="en")):
            analyzer = MarketAnalyzer(region="us")

        prompt = analyzer._build_review_prompt(MarketOverview(date="2026-02-24"), [])

        self.assertIn("Strategy Plan", prompt)
        self.assertIn("US Market Regime Strategy", prompt)

    def test_us_prompt_localizes_strategy_markdown_when_report_language_is_zh(self):
        with patch("src.market_analyzer.get_config", return_value=SimpleNamespace(report_language="zh")):
            analyzer = MarketAnalyzer(region="us")

        prompt = analyzer._build_review_prompt(MarketOverview(date="2026-02-24"), [])

        self.assertIn("美股市场", prompt)
        self.assertNotIn("US Market Regime Strategy", prompt)
        self.assertNotIn("Strategy Blueprint", prompt)
        self.assertIn("风险偏好", prompt)

    def test_ca_strategy_blocks_follow_the_review_language(self):
        for language, expected, unexpected in (
            ("en", "Canadian Market Regime Strategy", "加拿大市场三段式复盘策略"),
            ("ko", "Canadian Market Regime Strategy", "加拿大市场三段式复盘策略"),
            ("zh", "加拿大市场三段式复盘策略", "Canadian Market Regime Strategy"),
        ):
            with patch("src.market_analyzer.get_config", return_value=SimpleNamespace(report_language=language)):
                analyzer = MarketAnalyzer(region="ca")
            with self.subTest(language=language):
                self.assertIn(expected, analyzer._get_strategy_prompt_block())
                self.assertNotIn(unexpected, analyzer._get_strategy_prompt_block())

        with patch("src.market_analyzer.get_config", return_value=SimpleNamespace(report_language="zh")):
            zh_analyzer = MarketAnalyzer(region="ca")
        self.assertTrue(zh_analyzer._get_strategy_markdown_block().startswith("### 六、策略框架"))


if __name__ == "__main__":
    unittest.main()

# -*- coding: utf-8 -*-
"""Output-language directives in analysis prompts are English for every report language."""

import unittest

from src.agent.agents.decision_agent import DecisionAgent
from src.agent.protocols import AgentContext
from src.analysis_context_pack_prompt import normalize_analysis_context_pack_language
from src.market_phase_prompt import format_market_phase_prompt_section


def _phase_ctx():
    return {
        "market": "us",
        "phase": "premarket",
        "market_local_time": "2026-06-29T08:00:00-04:00",
        "effective_daily_bar_date": "2026-06-27",
        "minutes_to_open": 90,
        "warnings": [],
    }


class DecisionAgentLanguageDirectiveTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.agent = DecisionAgent(tool_registry=None, llm_adapter=None)

    def _system_prompt(self, language: str, *, chat: bool = False) -> str:
        meta = {"report_language": language}
        if chat:
            meta["response_mode"] = "chat"
        ctx = AgentContext(stock_code="005930.KS", stock_name="삼성전자", meta=meta)
        return self.agent.system_prompt(ctx)

    def test_every_language_gets_the_english_dashboard_directive(self) -> None:
        for language in ("en", "zh", "ko"):
            prompt = self._system_prompt(language)
            self.assertIn("Write all human-readable JSON values in English.", prompt)
            self.assertIn("`decision_type` must remain `buy|hold|sell`.", prompt)

    def test_every_language_gets_the_english_chat_directive(self) -> None:
        for language in ("en", "zh", "ko"):
            self.assertIn("Always answer in English.", self._system_prompt(language, chat=True))


class StructuralLanguageRoutingTestCase(unittest.TestCase):
    def test_context_pack_language_is_english_for_every_language(self) -> None:
        for language in ("ko", "en", "zh", None):
            self.assertEqual(normalize_analysis_context_pack_language(language), "en")

    def test_market_phase_korean_matches_english_structure(self) -> None:
        ko_section = format_market_phase_prompt_section(_phase_ctx(), report_language="ko")
        en_section = format_market_phase_prompt_section(_phase_ctx(), report_language="en")
        self.assertEqual(ko_section, en_section)
        self.assertIn("## Market Phase Context", ko_section)


if __name__ == "__main__":
    unittest.main()

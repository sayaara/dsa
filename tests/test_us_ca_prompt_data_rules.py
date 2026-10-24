# -*- coding: utf-8 -*-
"""The model is not asked to reason from A-share data that US/CA runs never have.

Chip distribution (profit ratio, average cost, concentration) and main-fund flows have no
US/CA data source, so the analyzer and agent prompts, the default trading baseline and the
strategy files must not tell the model to weigh them or ask for a ``chip_structure`` block.
The data-gated prompt sections (a ``chip`` or ``capital_flow`` context) are not covered:
they appear only when such data exists.
"""

import json
import re
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

from tests.litellm_stub import ensure_litellm_stub

ensure_litellm_stub()

from src.agent import executor  # noqa: E402
from src.agent.skills.defaults import CORE_TRADING_SKILL_POLICY_EN  # noqa: E402
from src.analyzer import GeminiAnalyzer  # noqa: E402
from src.analyzer_prompt_en import (  # noqa: E402
    ENGLISH_DEFAULT_SYSTEM_PROMPT,
    ENGLISH_SKILL_SYSTEM_PROMPT,
)

A_SHARE_DATA = re.compile(r"chip|profit ratio|main.fund|main funds|fund flow|money flow", re.IGNORECASE)
STRATEGIES_DIR = Path(__file__).resolve().parents[1] / "strategies"


@pytest.mark.parametrize(
    "name, text",
    [
        ("ENGLISH_DEFAULT_SYSTEM_PROMPT", ENGLISH_DEFAULT_SYSTEM_PROMPT),
        ("ENGLISH_SKILL_SYSTEM_PROMPT", ENGLISH_SKILL_SYSTEM_PROMPT),
        ("CORE_TRADING_SKILL_POLICY_EN", CORE_TRADING_SKILL_POLICY_EN),
        ("AGENT_SYSTEM_PROMPT", executor.AGENT_SYSTEM_PROMPT),
        ("LEGACY_DEFAULT_AGENT_SYSTEM_PROMPT", executor.LEGACY_DEFAULT_AGENT_SYSTEM_PROMPT),
        ("CHAT_SYSTEM_PROMPT", executor.CHAT_SYSTEM_PROMPT),
        ("LEGACY_DEFAULT_CHAT_SYSTEM_PROMPT", executor.LEGACY_DEFAULT_CHAT_SYSTEM_PROMPT),
    ],
)
def test_system_prompt_has_no_a_share_data_rules(name, text):
    match = A_SHARE_DATA.search(text)
    assert match is None, f"{name} mentions {match.group(0)!r}"


def test_baseline_keeps_section_3_for_volume_confirmation():
    # Strategy files cite "core idea 3: efficiency first" for volume confirmation, and
    # ``core_rules`` lists refer to the section numbers, so the numbering must not shift.
    headings = re.findall(r"^### (\d+)\. (.+)$", CORE_TRADING_SKILL_POLICY_EN, re.MULTILINE)
    assert [number for number, _ in headings] == [str(n) for n in range(1, 8)]
    assert dict(headings)["3"] == "Efficiency first (volume confirmation)"


def test_strategy_values_have_no_a_share_data_rules():
    for path in sorted(STRATEGIES_DIR.glob("*.yaml")):
        text = json.dumps(yaml.safe_load(path.read_text(encoding="utf-8")), ensure_ascii=False)
        match = A_SHARE_DATA.search(text)
        assert match is None, f"{path.name} mentions {match.group(0)!r}"


def _context() -> dict:
    # What the pipeline passes for a US/CA stock: no ``chip`` and no capital flow.
    return {
        "code": "RY.TO",
        "stock_name": "Royal Bank of Canada",
        "date": "2026-10-02",
        "today": {
            "close": 140.5, "open": 139.0, "high": 141.0, "low": 138.8,
            "pct_chg": 0.6, "volume": 2_300_000, "amount": 320_000_000,
            "ma5": 139.1, "ma10": 138.2, "ma20": 136.7,
        },
        "ma_status": "Bullish alignment",
        "realtime": {"price": 140.5, "volume_ratio": 1.1, "turnover_rate": 0.4},
        "trend_analysis": {
            "trend_status": "Bullish", "ma_alignment": "MA5>MA10>MA20", "trend_strength": 72,
            "bias_ma5": 0.8, "bias_ma10": 1.8, "volume_status": "Normal", "volume_trend": "Steady",
            "buy_signal": "Hold", "signal_score": 66, "signal_reasons": ["Trend intact"],
            "risk_factors": ["Near resistance"],
        },
        "yesterday": {"close": 139.6},
        "news_window_days": 3,
    }


@pytest.mark.parametrize("use_legacy_default_prompt", [True, False])
def test_us_ca_request_has_no_a_share_data_rules(use_legacy_default_prompt):
    kwargs = {} if use_legacy_default_prompt else {
        "skill_instructions": "### Skill 1\n- Watch the pivot",
        "default_skill_policy": "",
        "use_legacy_default_prompt": False,
    }
    with patch.object(GeminiAnalyzer, "_init_litellm", return_value=None):
        analyzer = GeminiAnalyzer(**kwargs)

    prompt = analyzer._format_prompt(_context(), "Royal Bank of Canada", report_language="en")

    assert "Key questions" in prompt
    match = A_SHARE_DATA.search(prompt)
    assert match is None, f"request mentions {match.group(0)!r}"

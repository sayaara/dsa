# -*- coding: utf-8 -*-
"""Every built-in strategy may only require tools the agent actually registers.

A strategy that names a removed tool (``get_sector_rankings`` went with the mainland China data
sources) tells the model to call something it does not have.
"""

from __future__ import annotations

from pathlib import Path

from src.agent.factory import get_tool_registry
from src.agent.skills.base import load_skills_from_directory

STRATEGIES_DIR = Path(__file__).resolve().parents[1] / "strategies"

# US/Canada strategies that replaced the China-specific ones (A8).
_US_CA_REPLACEMENTS = {"rising_three_methods", "sector_leadership", "sentiment_extremes", "structure_divergence"}
_REMOVED_CHINA_SPECIFIC = {"dragon_head", "hot_theme", "emotion_cycle", "chan_theory", "one_yang_three_yin"}


def _registered_tool_names() -> set[str]:
    return set(get_tool_registry().list_names())


def test_strategies_require_only_registered_tools():
    registered = _registered_tool_names()
    missing = {
        skill.name: sorted(set(skill.required_tools) - registered)
        for skill in load_skills_from_directory(STRATEGIES_DIR)
        if set(skill.required_tools) - registered
    }
    assert missing == {}


def test_us_ca_replacements_are_loaded_and_china_specific_strategies_are_gone():
    names = {skill.name for skill in load_skills_from_directory(STRATEGIES_DIR)}
    assert _US_CA_REPLACEMENTS <= names
    assert not _REMOVED_CHINA_SPECIFIC & names

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

# China-specific strategies that still name ``get_sector_rankings``; they are removed in the next change (A8).
_PENDING_REMOVAL = {"dragon_head", "hot_theme"}

# US/Canada strategies that replace the China-specific ones.
_US_CA_REPLACEMENTS = {"rising_three_methods", "sector_leadership", "sentiment_extremes", "structure_divergence"}


def _registered_tool_names() -> set[str]:
    return set(get_tool_registry().list_names())


def test_strategies_require_only_registered_tools():
    registered = _registered_tool_names()
    missing = {
        skill.name: sorted(set(skill.required_tools) - registered)
        for skill in load_skills_from_directory(STRATEGIES_DIR)
        if skill.name not in _PENDING_REMOVAL and set(skill.required_tools) - registered
    }
    assert missing == {}


def test_us_ca_replacement_strategies_are_loaded():
    names = {skill.name for skill in load_skills_from_directory(STRATEGIES_DIR)}
    assert _US_CA_REPLACEMENTS <= names

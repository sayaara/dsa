# -*- coding: utf-8 -*-
"""Removed China-specific strategy ids map to their US/Canada replacements (audit A8)."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from src.agent.factory import _normalize_skill_ids, _resolve_selected_skill_ids
from src.agent.skills.defaults import LEGACY_SKILL_ID_REPLACEMENTS, replace_legacy_skill_ids

LOADED = {"bull_trend", "rising_three_methods", "sector_leadership", "sentiment_extremes", "structure_divergence"}


def test_every_removed_id_maps_to_a_shipped_strategy():
    from pathlib import Path

    from src.agent.skills.base import load_skills_from_directory

    shipped = {s.name for s in load_skills_from_directory(Path(__file__).resolve().parents[1] / "strategies")}
    assert set(LEGACY_SKILL_ID_REPLACEMENTS.values()) <= shipped
    assert not set(LEGACY_SKILL_ID_REPLACEMENTS) & shipped


def test_replacement_keeps_order_and_drops_duplicates():
    assert replace_legacy_skill_ids(["dragon_head", "bull_trend", "hot_theme"]) == ["sector_leadership", "bull_trend"]
    assert replace_legacy_skill_ids(["chan_theory"], available_skill_ids=LOADED) == ["structure_divergence"]


def test_a_custom_strategy_that_reuses_an_old_id_is_kept():
    assert replace_legacy_skill_ids(["chan_theory"], available_skill_ids=LOADED | {"chan_theory"}) == ["chan_theory"]


def test_factory_normalizes_saved_and_requested_old_ids():
    assert _normalize_skill_ids(["emotion_cycle", "bull_trend"], available_skill_ids=LOADED) == (
        ["sentiment_extremes", "bull_trend"],
        [],
    )
    selected, explicit = _resolve_selected_skill_ids(
        requested_skills=None,
        configured_skills=["one_yang_three_yin"],
        default_skills=["bull_trend"],
        available_skill_ids=LOADED,
    )
    assert (selected, explicit) == (["rising_three_methods"], True)


def test_orchestrator_context_maps_old_ids():
    from src.agent.orchestrator import AgentOrchestrator

    orchestrator = AgentOrchestrator.__new__(AgentOrchestrator)
    with patch("src.agent.skills.router.SkillRouter._get_available_ids", return_value=LOADED):
        ctx = orchestrator._build_context("analyze", {"stock_code": "AAPL", "skills": ["chan_theory", "bull_trend"]})
    assert ctx.meta["skills_requested"] == ["structure_divergence", "bull_trend"]


def test_router_maps_configured_old_ids():
    from src.agent.skills.router import SkillRouter

    skills = [SimpleNamespace(name=name) for name in sorted(LOADED)]
    with patch("src.config.get_config", return_value=SimpleNamespace(agent_skills=["dragon_head"])), patch.object(
        SkillRouter, "_get_available_skills", return_value=skills
    ):
        assert SkillRouter._get_manual_skills(max_count=3) == ["sector_leadership"]

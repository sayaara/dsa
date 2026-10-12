# -*- coding: utf-8 -*-
"""The skill and chat prompts the model reads are English (audit A6/A7).

Still Chinese, on purpose until their own eval: the agent analysis prompts
(``AGENT_SYSTEM_PROMPT``, ``LEGACY_DEFAULT_AGENT_SYSTEM_PROMPT``) and the multi-agent prompts.
"""

import json
import re
from pathlib import Path

import pytest
import yaml

try:
    import litellm  # noqa: F401
except ModuleNotFoundError:
    from tests.litellm_stub import ensure_litellm_stub
    ensure_litellm_stub()

from src.agent import chat_context, executor
from src.agent.skills.base import SkillManager, load_skills_from_directory
from src.agent.skills.defaults import (
    ACTIVE_SKILLS_HEADING,
    CORE_TRADING_SKILL_POLICY_EN,
    get_default_trading_skill_policy,
)
from src.analyzer import GeminiAnalyzer
from src.analyzer_prompt_en import ENGLISH_DEFAULT_SYSTEM_PROMPT

CJK = re.compile(r"[㐀-鿿　-〿＀-￯]")
STRATEGIES_DIR = Path(__file__).resolve().parents[1] / "strategies"


@pytest.mark.parametrize(
    "name, text",
    [
        ("GeminiAnalyzer.SYSTEM_PROMPT", GeminiAnalyzer.SYSTEM_PROMPT),
        ("CHAT_SYSTEM_PROMPT", executor.CHAT_SYSTEM_PROMPT),
        ("LEGACY_DEFAULT_CHAT_SYSTEM_PROMPT", executor.LEGACY_DEFAULT_CHAT_SYSTEM_PROMPT),
        ("CODEX_CHAT_SYSTEM_PROMPT", executor.CODEX_CHAT_SYSTEM_PROMPT),
        ("SUMMARY_SYSTEM_PROMPT", chat_context.SUMMARY_SYSTEM_PROMPT),
        ("SUMMARY_USER_PREFIX", chat_context.SUMMARY_USER_PREFIX),
        ("CORE_TRADING_SKILL_POLICY_EN", CORE_TRADING_SKILL_POLICY_EN),
        ("ACTIVE_SKILLS_HEADING", ACTIVE_SKILLS_HEADING),
    ],
)
def test_prompt_is_english(name, text):
    assert not CJK.search(text), f"{name} contains CJK text: {CJK.search(text).group(0)!r}"


def test_strategy_values_are_english():
    # Parsed values only: comments may quote the A-share strategy a file replaced (AGENTS.md).
    for path in sorted(STRATEGIES_DIR.glob("*.yaml")):
        text = json.dumps(yaml.safe_load(path.read_text(encoding="utf-8")), ensure_ascii=False)
        match = CJK.search(text)
        assert match is None, f"{path.name} contains CJK text: {match.group(0)!r}"


def test_rendered_skill_sections_of_every_builtin_strategy_are_english():
    manager = SkillManager()
    for skill in load_skills_from_directory(STRATEGIES_DIR):
        manager.register(skill)
    manager.activate([skill.name for skill in manager.list_skills()])
    rendered = manager.get_skill_instructions()
    assert "### Skill 1:" in rendered and "**When to use**:" in rendered
    assert not CJK.search(rendered)


def test_default_policy_matches_the_english_default_prompt():
    # The implicit-default chat and agent prompts and the default analyzer prompt state one baseline.
    assert CORE_TRADING_SKILL_POLICY_EN in ENGLISH_DEFAULT_SYSTEM_PROMPT
    assert get_default_trading_skill_policy(explicit_skill_selection=False) == CORE_TRADING_SKILL_POLICY_EN
    assert get_default_trading_skill_policy(explicit_skill_selection=True) == ""

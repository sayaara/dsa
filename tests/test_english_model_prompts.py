# -*- coding: utf-8 -*-
"""The prompts, requests and tool outputs the model reads are English (audit A6/A7).

Covers the analyzer skill prompt, the chat and agent prompts, the agent request, the
strategy files, every string literal in the agent and multi-agent modules whose text
reaches the model, and the bot's ``/ask`` request and natural-language router prompt (the
user-input parsers in ``src/agent/orchestrator.py``, the ``web_intent_*`` modules and the
bot's pre-filter and command aliases are not prompts and keep their Chinese keywords).
"""

import io
import json
import re
import tokenize
from pathlib import Path

import pytest
import yaml

try:
    import litellm  # noqa: F401
except ModuleNotFoundError:
    from tests.litellm_stub import ensure_litellm_stub
    ensure_litellm_stub()

from bot.commands.ask import AskCommand
from bot.dispatcher import CommandDispatcher
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
REPO_ROOT = Path(__file__).resolve().parents[1]
STRATEGIES_DIR = REPO_ROOT / "strategies"
# Modules whose string literals become prompt, request or tool-output text.
MODEL_FACING_MODULES = (
    "src/agent/executor.py",
    "src/agent/chat_context.py",
    "src/agent/tools/analysis_tools.py",
    "src/agent/tools/search_tools.py",
    "src/agent/agents/decision_agent.py",
    "src/agent/agents/intel_agent.py",
    "src/agent/agents/risk_agent.py",
)


@pytest.mark.parametrize(
    "name, text",
    [
        ("GeminiAnalyzer.SYSTEM_PROMPT", GeminiAnalyzer.SYSTEM_PROMPT),
        ("CHAT_SYSTEM_PROMPT", executor.CHAT_SYSTEM_PROMPT),
        ("LEGACY_DEFAULT_CHAT_SYSTEM_PROMPT", executor.LEGACY_DEFAULT_CHAT_SYSTEM_PROMPT),
        ("CODEX_CHAT_SYSTEM_PROMPT", executor.CODEX_CHAT_SYSTEM_PROMPT),
        ("AGENT_SYSTEM_PROMPT", executor.AGENT_SYSTEM_PROMPT),
        ("LEGACY_DEFAULT_AGENT_SYSTEM_PROMPT", executor.LEGACY_DEFAULT_AGENT_SYSTEM_PROMPT),
        ("SUMMARY_SYSTEM_PROMPT", chat_context.SUMMARY_SYSTEM_PROMPT),
        ("SUMMARY_USER_PREFIX", chat_context.SUMMARY_USER_PREFIX),
        ("CORE_TRADING_SKILL_POLICY_EN", CORE_TRADING_SKILL_POLICY_EN),
        ("ACTIVE_SKILLS_HEADING", ACTIVE_SKILLS_HEADING),
        ("CommandDispatcher._NL_PARSE_PROMPT", CommandDispatcher._NL_PARSE_PROMPT),
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


@pytest.mark.parametrize("relative_path", MODEL_FACING_MODULES)
def test_model_facing_module_string_literals_are_english(relative_path):
    # String tokens only: comments may quote localized literals (AGENTS.md).
    source = (REPO_ROOT / relative_path).read_text(encoding="utf-8")
    offending = [
        f"line {token.start[0]}: {token.string[:60]}"
        for token in tokenize.generate_tokens(io.StringIO(source).readline)
        if token.type == tokenize.STRING and CJK.search(token.string)
    ]
    assert not offending, f"{relative_path} has CJK string literals: {offending}"


def test_agent_request_is_english():
    agent = executor.AgentExecutor(tool_registry=None, llm_adapter=None)
    message = agent._build_user_message(
        "Analyze stock AAPL (Apple) and return the full decision dashboard JSON.",
        {
            "stock_code": "AAPL",
            "report_type": "simple",
            "report_language": "en",
            "realtime_quote": {"price": 1.0},
            "chip_distribution": {"avg_cost": 1.0},
            "news_context": "Apple ships a new product.",
        },
    )
    assert "Stock code: AAPL" in message and "[Real-time quote already fetched by the system]" in message
    assert not CJK.search(message), CJK.search(message).group(0)


@pytest.mark.parametrize(
    "skill_id, skill_text, expected",
    [
        ("", "", "Analyze stock RY.TO"),
        ("bull_trend", "", "Analyze stock RY.TO using the bull_trend skill"),
        ("wave_theory", "elliott wave", "Analyze stock RY.TO, elliott wave"),
    ],
)
def test_bot_ask_request_is_english(skill_id, skill_text, expected):
    message = AskCommand._build_user_message("RY.TO", skill_id, skill_text)
    assert message == expected
    assert not CJK.search(message)


def test_bot_router_strategy_examples_resolve_to_a_skill(monkeypatch):
    # The router's "strategy" goes to /ask as a skill argument, so every strategy the prompt
    # shows must resolve to a built-in skill rather than fall back to the default.
    skills = load_skills_from_directory(STRATEGIES_DIR)
    monkeypatch.setattr(AskCommand, "_load_skills", staticmethod(lambda: skills))
    monkeypatch.setattr(AskCommand, "_get_default_skill_id", classmethod(lambda cls: ""))
    prompt = CommandDispatcher._NL_PARSE_PROMPT
    examples = set(re.findall(r'"strategy":"([^"]+)"', prompt))
    examples |= set(re.findall(r'"([^"]+)"', prompt.split("e.g.", 1)[1].split("\n", 1)[0]))
    assert {"elliott wave", "trend", "structure_divergence"} <= examples
    command = AskCommand()
    unresolved = [text for text in sorted(examples) if not command._parse_skill(["AAPL", text])]
    assert not unresolved, f"router prompt strategies that /ask cannot resolve: {unresolved}"

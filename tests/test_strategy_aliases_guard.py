# -*- coding: utf-8 -*-
"""Guard the deliberately Chinese parts of ``strategies/*.yaml``.

``aliases`` are live matching vocabulary (``/ask`` and natural-language routing
match them inside the user's message) and ``display_name`` is the user-facing
name. Only the ``instructions`` block is meant to be translated. A well-meaning
"make the strategies English" cleanup would silently break bot matching, so
these tests fail loudly instead.
"""

import re
from pathlib import Path
from unittest.mock import patch

try:
    import litellm  # noqa: F401
except ModuleNotFoundError:
    from tests.litellm_stub import ensure_litellm_stub
    ensure_litellm_stub()

from bot.commands.ask import AskCommand
from src.agent.skills.base import load_skills_from_directory
from src.report_language import localize_strategy_skill

STRATEGIES_DIR = Path(__file__).resolve().parents[1] / "strategies"
YAML_FILES = sorted(STRATEGIES_DIR.glob("*.yaml"))
CJK = re.compile(r"[㐀-鿿]")

# ``display_name`` values that the report language map does not know, so a
# report that looks a strategy up by its display name cannot localize it. Every
# strategy still localizes by id. Remove an entry here once the map learns it.
DISPLAY_NAMES_NOT_IN_REPORT_MAP = {"chan_theory", "dragon_head", "one_yang_three_yin"}


def _skills():
    return load_skills_from_directory(STRATEGIES_DIR)


def test_every_strategy_file_loads():
    assert YAML_FILES, "no strategy files found"
    assert sorted(skill.name for skill in _skills()) == sorted(path.stem for path in YAML_FILES)


def test_ids_are_ascii_identifiers_and_names_and_aliases_stay_chinese():
    for skill in _skills():
        assert re.fullmatch(r"[a-z][a-z0-9_]*", skill.name), skill.name
        assert CJK.search(skill.display_name), f"{skill.name}: display_name was translated: {skill.display_name!r}"
        assert skill.aliases, f"{skill.name}: aliases were removed"
        assert any(CJK.search(alias) for alias in skill.aliases), (
            f"{skill.name}: no Chinese alias left, /ask can no longer match Chinese input: {skill.aliases!r}"
        )


def test_ask_command_resolves_every_name_and_alias_to_its_own_strategy():
    skills = _skills()
    command = AskCommand()
    # A neutral default, so an alias that stops matching cannot pass by falling back to it.
    with patch.object(AskCommand, "_load_skills", return_value=skills), patch.object(
        AskCommand, "_get_default_skill_id", return_value="no-default"
    ):
        wrong = []
        for skill in skills:
            for text in [skill.name, skill.display_name, *skill.aliases]:
                resolved = command._parse_skill(["600519", "please", f"use {text} analysis"])
                if resolved != skill.name:
                    wrong.append((skill.name, text, resolved))
    assert wrong == []


# Phrases users actually type after a stock code; each must keep selecting its strategy.
CHINESE_PHRASES = {
    "请用缠论分析": "chan_theory",
    "用波浪理论看看": "wave_theory",
    "均线金叉": "ma_golden_cross",
    "放量突破怎么样": "volume_breakout",
    "缩量回踩": "shrink_pullback",
    "箱体震荡": "box_oscillation",
    "一阳穿三阴": "one_yang_three_yin",
    "情绪周期": "emotion_cycle",
    "龙头战法": "dragon_head",
    "事件驱动": "event_driven",
    "成长股": "growth_quality",
    "热点题材": "hot_theme",
    "预期差": "expectation_repricing",
    "地量见底": "bottom_volume",
    "多头趋势": "bull_trend",
}


def test_ask_command_still_matches_chinese_phrases_users_type():
    skills = _skills()
    command = AskCommand()
    with patch.object(AskCommand, "_load_skills", return_value=skills), patch.object(
        AskCommand, "_get_default_skill_id", return_value="no-default"
    ):
        resolved = {phrase: command._parse_skill(["600519", phrase]) for phrase in CHINESE_PHRASES}
    assert resolved == CHINESE_PHRASES


def test_every_strategy_localizes_by_id_and_display_name_gaps_are_the_known_ones():
    without_display_key = set()
    for skill in _skills():
        english = localize_strategy_skill(skill.name, "en")
        assert english and not CJK.search(english), (skill.name, english)
        if localize_strategy_skill(skill.display_name, "en") != english:
            without_display_key.add(skill.name)
    assert without_display_key == DISPLAY_NAMES_NOT_IN_REPORT_MAP


def test_every_strategy_file_carries_the_do_not_translate_note():
    for path in YAML_FILES:
        text = path.read_text(encoding="utf-8")
        assert "`aliases` and `display_name` are intentionally Chinese" in text, path.name

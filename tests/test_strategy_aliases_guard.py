# -*- coding: utf-8 -*-
"""Guard the user-facing fields of ``strategies/*.yaml``.

``display_name`` and ``description`` are shown in the Web strategy menu and the
agent prompt, and ``aliases`` are the ``/ask`` matching vocabulary (matched
case-insensitively inside the user's message). They are English, and so are the
``instructions`` blocks (audit A7, ``tests/test_english_model_prompts.py``).
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


def _skills():
    return load_skills_from_directory(STRATEGIES_DIR)


def test_every_strategy_file_loads():
    assert YAML_FILES, "no strategy files found"
    assert sorted(skill.name for skill in _skills()) == sorted(path.stem for path in YAML_FILES)


def test_ids_are_ascii_identifiers_and_user_facing_fields_are_english():
    for skill in _skills():
        assert re.fullmatch(r"[a-z][a-z0-9_]*", skill.name), skill.name
        assert skill.display_name and not CJK.search(skill.display_name), (skill.name, skill.display_name)
        assert skill.description and not CJK.search(skill.description), (skill.name, skill.description)
        assert skill.aliases, f"{skill.name}: aliases were removed"
        assert not any(CJK.search(alias) for alias in skill.aliases), (skill.name, skill.aliases)


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
                for variant in {text, text.lower(), text.upper(), text.title()}:
                    resolved = command._parse_skill(["AAPL", "please", f"use {variant} analysis"])
                    if resolved != skill.name:
                        wrong.append((skill.name, variant, resolved))
    assert wrong == []


# Phrases users actually type after a stock code; each must keep selecting its strategy.
ENGLISH_PHRASES = {
    "check the divergence": "structure_divergence",
    "Elliott wave count": "wave_theory",
    "golden cross?": "ma_golden_cross",
    "is this a volume breakout": "volume_breakout",
    "low-volume pullback": "shrink_pullback",
    "trading range": "box_oscillation",
    "Rising Three Methods": "rising_three_methods",
    "capitulation or euphoria": "sentiment_extremes",
    "sector leader": "sector_leadership",
    "relative strength vs the sector": "sector_leadership",
    "earnings catalyst": "event_driven",
    "growth stock": "growth_quality",
    "expectation gap": "expectation_repricing",
    "bottom volume surge": "bottom_volume",
    "bull trend": "bull_trend",
}


def test_ask_command_matches_english_phrases_users_type():
    skills = _skills()
    command = AskCommand()
    with patch.object(AskCommand, "_load_skills", return_value=skills), patch.object(
        AskCommand, "_get_default_skill_id", return_value="no-default"
    ):
        resolved = {phrase: command._parse_skill(["AAPL", phrase]) for phrase in ENGLISH_PHRASES}
    assert resolved == ENGLISH_PHRASES


def test_retired_chinese_aliases_fall_back_to_the_default_strategy():
    """The Chinese aliases were replaced by English ones (audit A9, option B)."""
    skills = _skills()
    command = AskCommand()
    with patch.object(AskCommand, "_load_skills", return_value=skills), patch.object(
        AskCommand, "_get_default_skill_id", return_value="no-default"
    ):
        for phrase in ("请用缠论分析", "放量突破", "龙头战法"):
            assert command._parse_skill(["AAPL", phrase]) == "no-default", phrase


def test_every_strategy_localizes_by_id_and_by_display_name():
    """A model may echo the display name it saw in the prompt instead of the id."""
    for skill in _skills():
        english = localize_strategy_skill(skill.name, "en")
        assert english and not CJK.search(english), (skill.name, english)
        assert localize_strategy_skill(skill.display_name, "en") == english, (
            f"{skill.name}: display_name {skill.display_name!r} is not a key of the report language map"
        )
        assert skill.display_name == english, (skill.name, skill.display_name, english)


def test_every_strategy_file_carries_the_english_fields_note():
    for path in YAML_FILES:
        text = path.read_text(encoding="utf-8")
        assert "`display_name`, `description` and `aliases` are English" in text, path.name

# -*- coding: utf-8 -*-
"""Prompt variants compared by the prompt-language eval.

A variant is a context manager that puts the analyzer into one prompt
configuration for the duration of a run (for example by patching
``GeminiAnalyzer._get_analysis_system_prompt`` or ``_format_prompt``).
Everything else - fixtures, model, report language - stays identical, so
differences in the report come from the prompt alone.

``current`` is the production prompt as shipped (the English default prompt in
``src/analyzer_prompt_en.py`` plus the "Output Language" block) and is the baseline.
Register a new variant here before translating the base prompts, then
compare it against ``current`` with ``run_eval.py``.

``skills`` runs the skill-driven prompt instead (``GeminiAnalyzer.SYSTEM_PROMPT`` with
an explicit skill selection, ``EVAL_SKILLS``), the path a request takes when the user picks
strategies. To measure a change to that path, run ``--variant skills`` on a checkout without
the change and on one with it (same fixtures), and compare the two reports.
"""

from __future__ import annotations

from contextlib import contextmanager, nullcontext
from typing import Callable, ContextManager, Dict, Iterator

VariantFactory = Callable[[], ContextManager[None]]


def _current() -> ContextManager[None]:
    return nullcontext()


def _patched_english_default_prompt(prompt) -> ContextManager[None]:
    from unittest.mock import patch

    from src.analyzer import GeminiAnalyzer

    return patch.object(GeminiAnalyzer, "ENGLISH_DEFAULT_SYSTEM_PROMPT", prompt)


def _english_plain() -> ContextManager[None]:
    """The English translation without the "exactly one JSON object" rule."""
    from evals.prompt_language.english_base import ENGLISH_PLAIN_SYSTEM_PROMPT

    return _patched_english_default_prompt(ENGLISH_PLAIN_SYSTEM_PROMPT)


# One trend skill and two framework skills, so the prompt holds several skill sections.
EVAL_SKILLS = ("shrink_pullback", "volume_breakout", "growth_quality")


def _skills() -> ContextManager[None]:
    """The skill-driven prompt with an explicit selection of ``EVAL_SKILLS``."""
    from unittest.mock import patch

    import src.agent.factory as factory

    resolve = factory.resolve_skill_prompt_state

    def _resolve_with_eval_skills(config=None, skills=None):
        return resolve(config, skills=list(EVAL_SKILLS))

    # GeminiAnalyzer imports resolve_skill_prompt_state from the module at call time.
    return patch.object(factory, "resolve_skill_prompt_state", _resolve_with_eval_skills)


VARIANTS: Dict[str, VariantFactory] = {
    "current": _current,
    "english_plain": _english_plain,
    "skills": _skills,
}

BASELINE_VARIANT = "current"


def register_variant(name: str, factory: VariantFactory) -> None:
    """Register an extra variant (used by tests and by experiments kept outside this module)."""
    if name in VARIANTS:
        raise ValueError(f"variant already registered: {name}")
    VARIANTS[name] = factory


@contextmanager
def activate(name: str) -> Iterator[None]:
    try:
        factory = VARIANTS[name]
    except KeyError as exc:
        known = ", ".join(sorted(VARIANTS))
        raise KeyError(f"unknown variant {name!r}; known variants: {known}") from exc
    with factory():
        yield

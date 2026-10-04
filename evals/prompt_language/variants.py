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


def _chinese_base() -> ContextManager[None]:
    """The Chinese default prompt that English reports used before the English prompt shipped."""
    return _patched_english_default_prompt(None)


def _english_plain() -> ContextManager[None]:
    """The English translation without the "exactly one JSON object" rule."""
    from evals.prompt_language.english_base import ENGLISH_PLAIN_SYSTEM_PROMPT

    return _patched_english_default_prompt(ENGLISH_PLAIN_SYSTEM_PROMPT)


def _chinese_user_prompt() -> ContextManager[None]:
    """The English system prompt with the Chinese analysis request (``_format_prompt``) used before
    the English request (``_format_prompt_en``) shipped."""
    from unittest.mock import patch

    from src.analyzer import GeminiAnalyzer

    return patch.object(GeminiAnalyzer, "ENGLISH_USER_PROMPT_ENABLED", False)


VARIANTS: Dict[str, VariantFactory] = {
    "current": _current,
    "chinese_base": _chinese_base,
    "english_plain": _english_plain,
    "chinese_user_prompt": _chinese_user_prompt,
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

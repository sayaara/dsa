# -*- coding: utf-8 -*-
"""Prompt variants compared by the prompt-language eval.

A variant is a context manager that puts the analyzer into one prompt
configuration for the duration of a run (for example by patching
``GeminiAnalyzer._get_analysis_system_prompt`` or ``_format_prompt``).
Everything else - fixtures, model, report language - stays identical, so
differences in the report come from the prompt alone.

``current`` is the production prompt as shipped (Chinese base system prompt
plus the English "Output Language" override block) and is the baseline.
Register a new variant here before translating the base prompts, then
compare it against ``current`` with ``run_eval.py``.
"""

from __future__ import annotations

from contextlib import contextmanager, nullcontext
from typing import Callable, ContextManager, Dict, Iterator

VariantFactory = Callable[[], ContextManager[None]]


def _current() -> ContextManager[None]:
    return nullcontext()


def _patched_default_prompt(prompt: str) -> ContextManager[None]:
    from unittest.mock import patch

    from src.analyzer import GeminiAnalyzer

    return patch.object(GeminiAnalyzer, "LEGACY_DEFAULT_SYSTEM_PROMPT", prompt)


def _english_base() -> ContextManager[None]:
    """Replace the Chinese default system prompt with its English translation."""
    from evals.prompt_language.english_base import ENGLISH_DEFAULT_SYSTEM_PROMPT

    return _patched_default_prompt(ENGLISH_DEFAULT_SYSTEM_PROMPT)


def _english_base_strict() -> ContextManager[None]:
    """English translation plus an explicit "exactly one JSON object" rule."""
    from evals.prompt_language.english_base import ENGLISH_STRICT_SYSTEM_PROMPT

    return _patched_default_prompt(ENGLISH_STRICT_SYSTEM_PROMPT)


VARIANTS: Dict[str, VariantFactory] = {
    "current": _current,
    "english_base": _english_base,
    "english_base_strict": _english_base_strict,
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

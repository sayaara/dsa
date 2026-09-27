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


VARIANTS: Dict[str, VariantFactory] = {
    "current": _current,
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

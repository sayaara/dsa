# -*- coding: utf-8 -*-
"""Chat-prompt variants compared by the chat-prompt language eval.

A variant is a context manager that puts Agent Chat into one prompt
configuration for the duration of a run, usually by patching the chat prompt
templates in ``src.agent.executor`` (``prepare_agent_chat`` reads them at call
time). Everything else - tool outputs, model, skills, report language - stays
identical, so differences in the report come from the prompt alone.

``current`` is the production prompt as shipped and is the baseline. Which
template it uses (``CHAT_SYSTEM_PROMPT`` or ``LEGACY_DEFAULT_CHAT_SYSTEM_PROMPT``)
follows the configured skills, exactly as in production. Register a
translated prompt here with ``patched_chat_prompts`` before shipping it, then
compare it against ``current`` with ``run_eval.py``.
"""

from __future__ import annotations

from contextlib import ExitStack, contextmanager, nullcontext
from typing import Callable, ContextManager, Dict, Iterator, Optional

VariantFactory = Callable[[], ContextManager[None]]

# Placeholders every chat template must keep, because prepare_agent_chat fills them.
CHAT_TEMPLATE_FIELDS = (
    "market_role",
    "market_guidelines",
    "default_skill_policy_section",
    "skills_section",
    "language_section",
)


def _current() -> ContextManager[None]:
    return nullcontext()


@contextmanager
def patched_chat_prompts(chat_prompt: Optional[str] = None, legacy_prompt: Optional[str] = None) -> Iterator[None]:
    """Replace the skill-driven and/or the legacy default chat template for the duration of a run."""
    from unittest.mock import patch

    import src.agent.executor as executor

    with ExitStack() as stack:
        if chat_prompt is not None:
            stack.enter_context(patch.object(executor, "CHAT_SYSTEM_PROMPT", chat_prompt))
        if legacy_prompt is not None:
            stack.enter_context(patch.object(executor, "LEGACY_DEFAULT_CHAT_SYSTEM_PROMPT", legacy_prompt))
        yield


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

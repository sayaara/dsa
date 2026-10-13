# -*- coding: utf-8 -*-
"""Agent analysis variants compared by the agent analysis eval.

A variant fixes the skill selection the executor is built with and, optionally,
a context manager that patches the agent prompt templates in
``src.agent.executor`` (``AgentExecutor.run`` reads them at call time).

``current`` builds the executor exactly as the pipeline does with no strategy
picked, so it runs ``LEGACY_DEFAULT_AGENT_SYSTEM_PROMPT`` (the implicit
``bull_trend`` default) unless ``AGENT_SKILLS`` is configured, and is the
baseline. ``skills`` selects ``EVAL_SKILLS`` explicitly (the prompt-language
eval's selection), the path a request takes when the user picks strategies,
so it runs ``AGENT_SYSTEM_PROMPT``. To measure a change to the agent prompts,
run the same variants on a checkout without the change and on one with it,
with the same fixtures, and compare the two reports; or register a patched
variant here with ``patched_agent_prompts``.
"""

from __future__ import annotations

from contextlib import ExitStack, contextmanager, nullcontext
from dataclasses import dataclass, field
from typing import Callable, ContextManager, Dict, Iterator, Optional, Tuple

from evals.prompt_language.variants import EVAL_SKILLS

# Placeholders every agent template must keep, because AgentExecutor.run fills them.
AGENT_TEMPLATE_FIELDS = (
    "market_role",
    "market_guidelines",
    "default_skill_policy_section",
    "skills_section",
    "language_section",
)


@dataclass(frozen=True)
class AgentVariant:
    """Skills to build the executor with (None = the configured default) and a prompt patch."""

    skills: Optional[Tuple[str, ...]] = None
    patch: Callable[[], ContextManager[None]] = field(default=nullcontext)


@contextmanager
def patched_agent_prompts(agent_prompt: Optional[str] = None, legacy_prompt: Optional[str] = None) -> Iterator[None]:
    """Replace the skill-driven and/or the legacy default agent template for the duration of a run."""
    from unittest.mock import patch

    import src.agent.executor as executor

    with ExitStack() as stack:
        if agent_prompt is not None:
            stack.enter_context(patch.object(executor, "AGENT_SYSTEM_PROMPT", agent_prompt))
        if legacy_prompt is not None:
            stack.enter_context(patch.object(executor, "LEGACY_DEFAULT_AGENT_SYSTEM_PROMPT", legacy_prompt))
        yield


VARIANTS: Dict[str, AgentVariant] = {
    "current": AgentVariant(),
    "skills": AgentVariant(skills=tuple(EVAL_SKILLS)),
}

BASELINE_VARIANT = "current"


def register_variant(name: str, variant: AgentVariant) -> None:
    """Register an extra variant (used by tests and by experiments kept outside this module)."""
    if name in VARIANTS:
        raise ValueError(f"variant already registered: {name}")
    VARIANTS[name] = variant


def get_variant(name: str) -> AgentVariant:
    try:
        return VARIANTS[name]
    except KeyError as exc:
        known = ", ".join(sorted(VARIANTS))
        raise KeyError(f"unknown variant {name!r}; known variants: {known}") from exc

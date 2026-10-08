# -*- coding: utf-8 -*-
"""Serve captured tool outputs to the production Agent Chat loop.

``build_replay_registry`` copies the production ``ToolRegistry`` (same names,
descriptions, parameters, policies and category timeouts, so the model sees
the identical tool surface) and swaps every handler for one that returns the
output captured by ``capture_fixtures.py``. The runner then serializes it
exactly as it serialized the live result, so the model reads the same text
in every variant. A captured failure is raised again, so the model sees the
same ``{"error": ...}`` result the live run produced.

A captured entry is matched by tool name and its key argument: ``stock_code``
for stock tools, ``region`` for ``get_market_indices``, nothing for tools
without either. Other arguments (``days``, ``periods``, ``stock_name``) are
ignored, because the captured call used the tool's defaults. A call the
fixture cannot answer raises, so the runner hands the model an ``{"error":
...}`` result, and it is recorded so the report can show it.
"""

from __future__ import annotations

import copy
import functools
import json
from dataclasses import replace
from typing import Any, Callable, Dict, List, Mapping, Optional

KEY_ARGUMENTS = ("stock_code", "region")


class NotCapturedError(RuntimeError):
    """A tool call the fixture has no captured output for."""


class ReplayedToolError(RuntimeError):
    """A tool failure captured from the live run, raised again on replay."""


def normalize_key_value(value: Any) -> str:
    return str(value or "").strip().upper()


def replay_key(tool_name: str, arguments: Mapping[str, Any]) -> str:
    """Fixture key for one call: ``tool`` or ``tool:KEYVALUE``."""
    for argument in KEY_ARGUMENTS:
        if argument in arguments:
            return f"{tool_name}:{normalize_key_value(arguments[argument])}"
    return tool_name


def captured_entry(result: Any = None, *, error: Optional[str] = None,
                   arguments: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
    """Fixture entry for one live call: the result frozen to JSON values, or the error message.

    The frozen result is kept (not only its text) because the runner inspects
    returned dicts, for example ``retriable: false`` errors are cached. When
    freezing changes the text the model would read (a value ``json`` cannot
    round-trip), the serialized text is stored instead and ``text_only`` is set.
    """
    from src.agent.tools.execution import serialize_tool_result

    entry: Dict[str, Any] = {"arguments": json.loads(json.dumps(dict(arguments or {}), default=str))}
    if error is not None:
        entry.update(ok=False, error=error)
        return entry
    live_text = serialize_tool_result(result)
    try:
        frozen = json.loads(json.dumps(result, ensure_ascii=False, default=str))
    except (TypeError, ValueError):
        frozen = None
    if frozen is not None and serialize_tool_result(frozen) == live_text:
        entry.update(ok=True, result=frozen)
    else:
        entry.update(ok=True, result=live_text, text_only=True)
    return entry


def build_replay_registry(source: Any, captured: Mapping[str, Mapping[str, Any]],
                          off_fixture_calls: List[Dict[str, Any]]) -> Any:
    """Return a registry with ``source``'s tool surface whose handlers replay ``captured``.

    ``off_fixture_calls`` collects every call the fixture could not answer; the
    caller clears it between turns.
    """
    from src.agent.tools.registry import ToolRegistry

    registry = ToolRegistry(source.category_timeout_map)
    for tool_def in source.list_tools():
        registry.register(replace(tool_def, handler=_replay_handler(tool_def, captured, off_fixture_calls)))
    return registry


def _replay_handler(tool_def: Any, captured: Mapping[str, Mapping[str, Any]],
                    off_fixture_calls: List[Dict[str, Any]]) -> Callable[..., Any]:
    name = tool_def.name

    # ``wraps`` keeps the original signature visible to ``inspect``, so the
    # registry's descriptor schemas do not change.
    @functools.wraps(tool_def.handler)
    def handler(**kwargs: Any) -> Any:
        key = replay_key(name, kwargs)
        entry = captured.get(key)
        if entry is None:
            off_fixture_calls.append({"tool": name, "arguments": dict(kwargs), "key": key})
            raise NotCapturedError(f"No data available for {key} in this evaluation run")
        if not entry.get("ok", False):
            raise ReplayedToolError(str(entry.get("error") or "tool failed"))
        # A copy, so nothing downstream can change the fixture between turns;
        # a ``text_only`` string passes through ``serialize_tool_result`` unchanged.
        return copy.deepcopy(entry["result"])

    return handler

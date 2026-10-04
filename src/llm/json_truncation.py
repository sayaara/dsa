# -*- coding: utf-8 -*-
"""Detect JSON replies that an output-token limit cut off.

Shared by the stock analysis (``src.analyzer``) and the agent dashboard parser
(``src.agent.runner``); kept dependency-free so either can import it cheaply.
"""

from __future__ import annotations

from typing import Optional


def is_truncated_json_text(text: Optional[str]) -> bool:
    """Return True when *text* is a JSON object that was cut off before it ended.

    This is what an output-token limit produces: the reply (optionally inside a
    ``json`` code fence that is never closed) stops inside a string or with
    unclosed braces. Replies with prose before the object, or whose object is
    complete, are not truncated in this sense.
    """
    body = (text or "").strip()
    if body.startswith("```"):
        newline = body.find("\n")
        body = body[newline + 1:].rstrip() if newline != -1 else ""
        if body.endswith("```"):
            return False
    start = body.find("{")
    if start == -1 or body[:start].strip():
        return False
    depth = 0
    in_string = False
    escaped = False
    for char in body[start:]:
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return False
    return True

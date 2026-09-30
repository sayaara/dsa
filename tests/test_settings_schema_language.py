# -*- coding: utf-8 -*-
"""Settings schema text and Settings service messages are English.

Two things are allowed to stay Chinese on purpose: the literal
``FEISHU_WEBHOOK_KEYWORD=股票日报`` config examples, and the matching text in
``system_config_service.py`` that recognises error output (a full-width colon
in a regex, and the ``请求被拦截`` token).
"""

import ast
import re
from pathlib import Path

from src.core.config_registry import build_schema_response

CJK = re.compile(r"[㐀-鿿＀-￯]")
SERVICE = Path(__file__).resolve().parents[1] / "src" / "services" / "system_config_service.py"


def _cjk_strings(value, path=()):
    if isinstance(value, str):
        if CJK.search(value):
            yield ".".join(path), value
    elif isinstance(value, dict):
        for key, item in value.items():
            yield from _cjk_strings(item, path + (str(key),))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            yield from _cjk_strings(item, path + (str(index),))


def test_schema_titles_descriptions_options_and_doc_labels_are_english():
    schema = build_schema_response()
    leaks = []
    for category in schema["categories"]:
        for path, text in _cjk_strings({k: v for k, v in category.items() if k != "fields"}):
            leaks.append((category["category"], path, text))
        for field in category["fields"]:
            # ``examples`` hold literal config values, which stay as they are.
            checked = {k: v for k, v in field.items() if k != "examples"}
            for path, text in _cjk_strings(checked):
                leaks.append((field["key"], path, text))
    assert leaks == []


def test_settings_service_messages_are_english():
    tree = ast.parse(SERVICE.read_text(encoding="utf-8"))
    docstrings = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            body = getattr(node, "body", [])
            if body and isinstance(body[0], ast.Expr) and isinstance(getattr(body[0], "value", None), ast.Constant):
                docstrings.add(id(body[0].value))

    def allowed(text: str) -> bool:
        return text == "请求被拦截" or "[:：]" in text

    leaks = [
        (node.lineno, node.value)
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and id(node) not in docstrings
        and CJK.search(node.value)
        and not allowed(node.value)
    ]
    assert leaks == []

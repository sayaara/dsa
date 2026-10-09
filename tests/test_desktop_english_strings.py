# -*- coding: utf-8 -*-
"""The desktop app ships English-only text.

The Web app has its own no-Chinese source guard; this covers the Electron shell
(`apps/dsa-desktop`): its update dialogs, status messages and errors are shown to users.
Desktop tests are excluded: they use non-ASCII fixture paths on purpose.
"""

import re
from pathlib import Path

DESKTOP_DIR = Path(__file__).resolve().parents[1] / "apps" / "dsa-desktop"
CJK_OR_FULL_WIDTH = re.compile(r"[　-〿㐀-鿿＀-￯]")
SOURCE_SUFFIXES = {".js", ".cjs", ".mjs", ".html", ".nsh", ".css"}


def _desktop_sources():
    for path in sorted(DESKTOP_DIR.rglob("*")):
        relative = path.relative_to(DESKTOP_DIR)
        if relative.parts[0] in {"node_modules", "tests", "dist", "release"}:
            continue
        if path.is_file() and path.suffix in SOURCE_SUFFIXES:
            yield path


def test_desktop_sources_exist():
    names = {path.relative_to(DESKTOP_DIR).as_posix() for path in _desktop_sources()}
    assert {"main.js", "preload.js", "renderer/loading.html"} <= names


def test_desktop_sources_have_no_chinese_text():
    offending = [
        f"{path.relative_to(DESKTOP_DIR).as_posix()}:{number}: {line.strip()}"
        for path in _desktop_sources()
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1)
        if CJK_OR_FULL_WIDTH.search(line)
    ]
    assert offending == []

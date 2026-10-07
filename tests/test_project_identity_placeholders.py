# -*- coding: utf-8 -*-
"""Guard: the upstream author's identity appears only in the legal notices."""

import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
UPSTREAM_MARKERS = ("zhulinsen", "霸天土小豆")
# MIT requires keeping the original copyright line; the AlphaSift entries
# record the provenance of Apache-2.0 code under src/services/screening/.
ALLOWED = {
    "LICENSE": 1,
    "THIRD_PARTY_NOTICES.md": 1,
    "docs/screening-engine.md": 1,
    "src/services/screening/__init__.py": 1,
    "tests/test_project_identity_placeholders.py": 2,
}


def _tracked_files():
    try:
        out = subprocess.run(
            ["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, encoding="utf-8", check=True
        ).stdout
    except (OSError, subprocess.CalledProcessError):
        pytest.skip("git is not available")
    return [line for line in out.splitlines() if line]


def test_upstream_identity_only_in_legal_notices():
    offenders = {}
    for rel in _tracked_files():
        path = ROOT / rel
        try:
            text = path.read_text(encoding="utf-8").lower()
        except (OSError, UnicodeDecodeError):
            continue
        lines = sum(1 for line in text.splitlines() if any(marker in line for marker in UPSTREAM_MARKERS))
        if lines and lines > ALLOWED.get(rel, 0):
            offenders[rel] = lines
    assert offenders == {}

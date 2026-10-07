# -*- coding: utf-8 -*-
"""Messages returned by the API, the chat and the notification setup are English.

These functions build text that reaches users regardless of REPORT_LANGUAGE
(Web settings, the backtest and screening pages, chat replies, email headers,
channel names), so they must not contain Chinese literals.
"""

import ast
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
CJK = re.compile(r"[㐀-鿿＀-￯]")

GUARDED_FUNCTIONS = {
    "src/auth.py": ("_validate_password", "set_initial_password", "change_password", "overwrite_password"),
    "src/services/backtest_service.py": ("_build_run_diagnostics",),
    "src/services/task_service.py": ("submit_analysis",),
    "src/storage.py": ("get_chat_sessions",),
    "src/agent/chat_executor.py": ("execute_turn",),
    "src/agent/executor.py": ("chat",),
    "src/notification.py": ("get_channel_name",),
    "src/scheduler.py": ("_get_next_run_time",),
    "src/services/generation_backend_status_service.py": ("smoke_test",),
    "data_provider/base.py": ("_daily_source_unavailable_error",),
    "src/services/decision_profile_policy.py": ("_warnings_for_guardrail",),
    "src/config.py": ("_parse_market_review_color_scheme", "_load_from_env"),
    "src/notification_sender/email_sender.py": ("__init__",),
    # Screening page: progress messages, candidate reasons and enrichment summaries.
    "src/services/screening/pipeline.py": ("screen",),
    "src/services/screening_service.py": (
        "screen",
        "_include_screening_diagnostic_suffix",
        "_build_dsa_analysis_summary",
        "_build_candidate_reason",
    ),
    "src/services/screening/dsa_provider.py": ("_build_dsa_summary",),
    "src/services/screening/post_analysis.py": ("_scorecard_delta",),
}


def _chinese_literals(rel_path: str, names: tuple) -> list:
    tree = ast.parse((ROOT / rel_path).read_text(encoding="utf-8"))
    found = []
    seen = set()
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) or node.name not in names:
            continue
        seen.add(node.name)
        docstring = ast.get_docstring(node, clean=False)
        for child in ast.walk(node):
            if (
                isinstance(child, ast.Constant)
                and isinstance(child.value, str)
                and child.value != docstring
                and CJK.search(child.value)
            ):
                found.append(f"{rel_path}:{child.lineno} {node.name}: {child.value[:40]!r}")
    assert seen == set(names), f"{rel_path}: functions not found: {set(names) - seen}"
    return found


@pytest.mark.parametrize("rel_path", sorted(GUARDED_FUNCTIONS))
def test_guarded_functions_have_no_chinese_literals(rel_path):
    assert _chinese_literals(rel_path, GUARDED_FUNCTIONS[rel_path]) == []


def _is_main_guard(node) -> bool:
    test = node.test if isinstance(node, ast.If) else None
    return (
        isinstance(test, ast.Compare)
        and isinstance(test.left, ast.Name)
        and test.left.id == "__name__"
        and any(isinstance(c, ast.Constant) and c.value == "__main__" for c in test.comparators)
    )


def test_manual_main_blocks_have_no_chinese():
    found = []
    for directory in ("src", "data_provider", "api", "bot"):
        for path in sorted((ROOT / directory).rglob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in tree.body:
                if not _is_main_guard(node):
                    continue
                for child in ast.walk(node):
                    if isinstance(child, ast.Constant) and isinstance(child.value, str) and CJK.search(child.value):
                        found.append(f"{path.relative_to(ROOT)}:{child.lineno} {child.value[:30]!r}")
    assert found == []


def test_password_validation_messages_are_english():
    from src.auth import MIN_PASSWORD_LEN, _validate_password

    assert _validate_password("") == "Password cannot be empty"
    assert _validate_password("x") == f"Password must be at least {MIN_PASSWORD_LEN} characters"


def test_channel_names_are_english():
    from src.notification import ChannelDetector, NotificationChannel

    for channel in NotificationChannel:
        assert not CJK.search(ChannelDetector.get_channel_name(channel)), channel
    assert ChannelDetector.get_channel_name(NotificationChannel.EMAIL) == "Email"


def test_email_sender_name_default_is_english():
    from src.config import Config

    assert Config.__dataclass_fields__["email_sender_name"].default == "Stock Analysis Assistant"

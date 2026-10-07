# -*- coding: utf-8 -*-
"""The multi-agent dashboard fallback text follows the report language.

The orchestrator fills empty dashboard fields and rewrites them after a risk
override. Those values reach the report, so they come from ``_FALLBACK_TEXT``
and the report-language localizers; the zh values keep the original wording.
"""

import ast
import re
from pathlib import Path

import pytest

try:
    import litellm  # noqa: F401
except ModuleNotFoundError:
    from tests.litellm_stub import ensure_litellm_stub
    ensure_litellm_stub()

from src.agent import orchestrator as orch

ROOT = Path(__file__).resolve().parents[1]
CJK = re.compile(r"[㐀-鿿＀-￯]")
SIGNALS = ("buy", "hold", "sell", "unknown")


def _helper_values(language):
    values = []
    for signal in SIGNALS:
        values.append(orch._signal_to_operation(signal, language))
        values.append(orch._signal_to_signal_type(signal, language))
        values.extend(orch._default_position_advice(signal, language).values())
        values.extend(orch._post_risk_position_advice(signal, language).values())
        values.append(orch._default_position_size(signal, language))
        values.append(orch._adjust_operation_advice("anything", signal, language))
    values.extend(orch._confidence_label(c, language) for c in (0.2, 0.5, 0.9))
    return values


@pytest.mark.parametrize("language", ["en", "ko"])
def test_non_chinese_reports_get_no_chinese_fallback_text(language):
    for value in _helper_values(language):
        assert not CJK.search(value), value
    for key, value in orch._FALLBACK_TEXT[language].items():
        assert not CJK.search(str(value)), key


def test_fallback_tables_have_the_same_keys():
    zh_keys = set(orch._FALLBACK_TEXT["zh"])
    for language in ("en", "ko"):
        assert set(orch._FALLBACK_TEXT[language]) == zh_keys


def test_chinese_reports_keep_the_original_wording():
    assert orch._signal_to_operation("buy", "zh") == "买入"
    assert orch._signal_to_operation("hold", "zh") == "观望"
    assert orch._signal_to_operation("sell", "zh") == "减仓/卖出"
    assert orch._signal_to_signal_type("hold", "zh") == "🟡持有观望"
    assert orch._adjust_operation_advice("买入", "hold", "zh") == "观望（原建议已被风控下调）"
    assert orch._default_position_size("sell", "zh") == "降仓防守"
    assert orch._confidence_label(0.9, "zh") == "高"


def test_english_labels_reuse_the_report_vocabulary():
    assert orch._signal_to_operation("hold", "en") == "Watch"
    assert orch._signal_to_operation("sell", "en") == "Reduce/Sell"
    assert orch._confidence_label(0.5, "en") == "Medium"
    assert orch._signal_to_signal_type("hold", "en") == "🟡 Hold / Watch"


def test_dashboard_builders_have_no_chinese_literals():
    guarded = {
        "_finalize_dashboard_payload", "_build_data_perspective", "_mark_partial_dashboard",
        "_merge_risk_warning", "_build_timeout_result", "_build_budget_skip_result",
        "_adjust_operation_advice", "_signal_to_operation", "_signal_to_signal_type",
        "_default_position_advice", "_post_risk_position_advice", "_default_position_size",
        "_normalize_operation_advice_value", "_confidence_label",
    }
    tree = ast.parse((ROOT / "src" / "agent" / "orchestrator.py").read_text(encoding="utf-8"))
    seen, found = set(), []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in guarded:
            seen.add(node.name)
            docstring = ast.get_docstring(node, clean=False)
            for child in ast.walk(node):
                if (
                    isinstance(child, ast.Constant)
                    and isinstance(child.value, str)
                    and child.value != docstring
                    and CJK.search(child.value)
                ):
                    found.append(f"{node.name}:{child.lineno} {child.value[:30]!r}")
    assert seen == guarded
    assert found == []

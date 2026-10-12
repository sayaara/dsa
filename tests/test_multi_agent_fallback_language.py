# -*- coding: utf-8 -*-
"""The multi-agent dashboard fallback text is English.

The orchestrator fills empty dashboard fields and rewrites them after a risk
override. Those values reach the report, so they come from ``_FALLBACK_TEXT``
(English only since reports became English-only) and the report-language localizers.
"""

import ast
import re
from pathlib import Path

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


def test_english_reports_get_no_chinese_fallback_text():
    for value in _helper_values("en"):
        assert not CJK.search(value), value
    for key, value in orch._FALLBACK_TEXT["en"].items():
        assert not CJK.search(str(value)), key


def test_fallback_table_is_english_only():
    assert set(orch._FALLBACK_TEXT) == {"en"}
    assert orch._fallback_text("zh") is orch._FALLBACK_TEXT["en"]
    assert orch._fallback_text("ko") is orch._FALLBACK_TEXT["en"]


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

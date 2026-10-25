# -*- coding: utf-8 -*-
"""Every surface shows, and every stored signal keeps, the same final action.

The rule lives in ``src/schemas/decision_action.py`` (``display_action_fields``) with the
reason lookup of ``extract_decision_guardrail_reason``: a neutral action with a score in a
directional band takes the score's action unless a guardrail reason is recorded. The
notifications, the report renderer, the history service and the bot call it directly; this
test pins the Web report payload (``api/v1/endpoints/analysis.py``) and the stored
DecisionSignal (``resolve_decision_signal_action_fields``) to the same answer.
"""

import pytest

from tests.litellm_stub import ensure_litellm_stub

ensure_litellm_stub()

from api.v1.endpoints.analysis import _ensure_report_action_fields  # noqa: E402
from src.analyzer import AnalysisResult  # noqa: E402
from src.schemas.decision_action import display_action_fields_for_result  # noqa: E402
from src.services.decision_signal_extractor import resolve_decision_signal_action_fields  # noqa: E402

_UNAVAILABLE_STABILITY = {
    "applied": False,
    "reason": "Capital flow unavailable; stability calibration not applied",
}

CASES = {
    # name: (score, advice, extra result attributes, dashboard, expected action)
    "hold in buy band, no reason": (62, "Hold", {}, {}, "buy"),
    "watch in sell band, no reason": (30, "Watch", {}, {}, "reduce"),
    "hold in buy band, reason in decision_stability": (
        62, "Hold", {}, {"decision_stability": {"reason": "Near resistance; wait for a breakout"}}, "hold",
    ),
    # Where the analyzer's parser puts the model's top-level ``guardrail_reason``.
    "hold in buy band, reason in score calibration": (
        62, "Hold", {}, {"decision_score_calibration": {"guardrail_reason": "Stale quote"}}, "hold",
    ),
    "hold in buy band, stability not applied": (62, "Hold", {}, {"decision_stability": _UNAVAILABLE_STABILITY}, "buy"),
    "hold in buy band, neutral wording only": (
        62, "Hold, wait for a pullback to support", {"analysis_summary": "Risk near resistance."}, {}, "buy",
    ),
    "hold in neutral band": (50, "Hold", {}, {}, "hold"),
    "buy in buy band": (75, "Buy", {}, {}, "buy"),
}


def _result(score, advice, extra, dashboard) -> AnalysisResult:
    result = AnalysisResult(
        code="RY.TO",
        name="Royal Bank of Canada",
        sentiment_score=score,
        trend_prediction="Sideways",
        operation_advice=advice,
        decision_type="hold",
        report_language="en",
        dashboard=dict(dashboard),
    )
    for key, value in extra.items():
        setattr(result, key, value)
    return result


def _web_report_action(result: AnalysisResult) -> str:
    report = {
        "meta": {"report_type": "simple"},
        "summary": {"operation_advice": result.operation_advice, "sentiment_score": result.sentiment_score},
        "details": {"raw_result": result.to_dict()},
    }
    return _ensure_report_action_fields(report)["summary"]["action"]


@pytest.mark.parametrize("name", sorted(CASES))
def test_stored_signal_and_every_surface_agree(name):
    score, advice, extra, dashboard, expected = CASES[name]
    result = _result(score, advice, extra, dashboard)

    shown = display_action_fields_for_result(result)["action"]
    stored = resolve_decision_signal_action_fields(result, report_type="simple")["action"]
    web = _web_report_action(result)

    assert (shown, stored, web) == (expected, expected, expected)

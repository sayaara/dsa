# -*- coding: utf-8 -*-
"""Warnings for agent dashboards repaired after an output-token cut-off."""

import logging
from unittest.mock import MagicMock

from tests.litellm_stub import ensure_litellm_stub

ensure_litellm_stub()

from src.agent.llm_adapter import LLMResponse  # noqa: E402
from src.agent.runner import parse_dashboard_json, run_agent_loop  # noqa: E402
from src.agent.tools.registry import ToolRegistry  # noqa: E402
from src.llm.json_truncation import is_truncated_json_text  # noqa: E402

_CUT_OFF_DASHBOARD = '```json\n{"stock_name": "Tesla", "decision_type": "hold", "analysis_summary": "Margins are under pres'
_COMPLETE_DASHBOARD = '{"stock_name": "Tesla", "decision_type": "hold", "analysis_summary": "Margins are under pressure."}'


def test_repaired_cut_off_dashboard_is_returned_with_a_warning(caplog) -> None:
    with caplog.at_level(logging.WARNING, logger="src.agent.runner"):
        dashboard = parse_dashboard_json(_CUT_OFF_DASHBOARD)

    assert dashboard is not None
    assert dashboard["stock_name"] == "Tesla"
    assert "cut off before it ended and was repaired" in caplog.text


def test_cut_off_dashboard_after_prose_is_detected(caplog) -> None:
    content = "Here is the dashboard:\n\n" + _CUT_OFF_DASHBOARD.removeprefix("```json\n")
    with caplog.at_level(logging.WARNING, logger="src.agent.runner"):
        dashboard = parse_dashboard_json(content)

    assert dashboard is not None
    assert "cut off before it ended and was repaired" in caplog.text


def test_complete_dashboards_do_not_warn(caplog) -> None:
    with caplog.at_level(logging.WARNING, logger="src.agent.runner"):
        plain = parse_dashboard_json(_COMPLETE_DASHBOARD)
        fenced = parse_dashboard_json("Summary first.\n```json\n" + _COMPLETE_DASHBOARD + "\n```\nDone.")

    assert plain is not None and fenced is not None
    assert "repaired" not in caplog.text


def test_unparseable_text_still_returns_none_without_the_repair_warning(caplog) -> None:
    with caplog.at_level(logging.WARNING, logger="src.agent.runner"):
        assert parse_dashboard_json("no json here") is None

    assert "repaired" not in caplog.text


def test_run_agent_loop_records_a_cut_off_final_answer(caplog) -> None:
    adapter = MagicMock()
    adapter.call_with_tools.return_value = LLMResponse(
        content=_CUT_OFF_DASHBOARD,
        tool_calls=[],
        usage={},
        provider="openai",
        model="openai/gpt-test",
        finish_reason="length",
    )

    with caplog.at_level(logging.WARNING, logger="src.agent.runner"):
        result = run_agent_loop(
            messages=[{"role": "user", "content": "Analyze TSLA"}],
            tool_registry=ToolRegistry(),
            llm_adapter=adapter,
            max_steps=1,
        )

    assert result.success is True
    assert result.finish_reason == "length"
    assert "final answer was cut off by the output-token limit" in caplog.text


def test_run_agent_loop_finish_reason_defaults_to_none_for_adapters_without_it() -> None:
    adapter = MagicMock()
    adapter.call_with_tools.return_value = LLMResponse(
        content="Done.", tool_calls=[], usage={}, provider="openai", model="openai/gpt-test"
    )

    result = run_agent_loop(
        messages=[{"role": "user", "content": "Analyze"}],
        tool_registry=ToolRegistry(),
        llm_adapter=adapter,
        max_steps=1,
    )

    assert result.finish_reason is None


def test_analyzer_re_exports_the_shared_detector() -> None:
    from src.analyzer import is_truncated_json_text as analyzer_detector

    assert analyzer_detector is is_truncated_json_text

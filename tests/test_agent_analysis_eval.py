# -*- coding: utf-8 -*-
"""Offline tests for the agent analysis eval (metrics, scoring, variants, runner guards).

The end-to-end tests drive the production ``AgentExecutor`` with a scripted
model, so the real ReAct loop executes the replayed tools and the real
dashboard parser, contract check and analyzer parser score the answer;
only usage persistence is patched out.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from evals.agent_analysis import capture_fixtures, run_eval, variants
from evals.agent_analysis.metrics import AgentRecord, build_report, format_text_report, summarize_trajectory
from evals.chat_language.replay import captured_entry, replay_key
from src.agent.executor import AgentExecutor
from src.agent.factory import get_tool_registry
from src.agent.llm_adapter import LLMResponse, ToolCall
from src.agent.tools.execution import serialize_tool_result

QUOTE = {"code": "AAPL", "name": "Apple", "price": 201.5, "change_pct": 1.2}
HISTORY = {"code": "AAPL", "bars": [{"date": "2026-10-06", "close": 199.1}]}
TREND = {"code": "AAPL", "trend": "bullish", "ma5": 198.0}
NEWS = {"code": "AAPL", "results": [{"title": "Apple ships a new product", "snippet": "..."}]}

DASHBOARD = {
    "stock_name": "Apple",
    "sentiment_score": 64,
    "trend_prediction": "Bullish",
    "operation_advice": "Buy",
    "decision_type": "buy",
    "confidence_level": "Medium",
    "analysis_summary": "Uptrend intact above MA20.",
    "risk_warning": "Valuation is high.",
    "dashboard": {
        "core_conclusion": {"one_sentence": "Uptrend intact.", "signal_type": "buy"},
        "intelligence": {"risk_alerts": ["Valuation"]},
        "battle_plan": {"sniper_points": {"stop_loss": "190"}},
    },
}


def _fixture() -> dict:
    code = {"stock_code": "AAPL"}
    tools = {
        replay_key("get_realtime_quote", code): captured_entry(QUOTE, arguments=code),
        replay_key("get_daily_history", code): captured_entry(HISTORY, arguments=code),
        replay_key("analyze_trend", code): captured_entry(TREND, arguments=code),
        replay_key("search_stock_news", code): captured_entry(NEWS, arguments=dict(code, stock_name="Apple")),
        replay_key("get_stock_info", code): captured_entry(error="provider down", arguments=code),
    }
    return {"stock_code": "AAPL", "market": "us", "stock_name": "Apple", "report_language": "en", "tools": tools}


def _call(call_id: str, name: str, **arguments) -> ToolCall:
    return ToolCall(id=call_id, name=name, arguments=arguments)


class _ScriptedAdapter:
    """Returns one scripted response per loop step and keeps the messages it was sent."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def call_with_tools(self, messages, tools, timeout=None):
        self.calls.append([dict(m) for m in messages])
        return self.responses.pop(0)

    @property
    def is_available(self) -> bool:  # a property, like LLMToolAdapter.is_available
        return True


def _script(final_text: str):
    return [
        LLMResponse(tool_calls=[_call("1", "get_realtime_quote", stock_code="AAPL"),
                                _call("2", "get_daily_history", stock_code="AAPL", days=60)],
                    provider="test", model="test/model", usage={"total_tokens": 10}),
        LLMResponse(tool_calls=[_call("3", "analyze_trend", stock_code="AAPL")], provider="test", model="test/model"),
        LLMResponse(tool_calls=[_call("4", "search_stock_news", stock_code="AAPL", stock_name="Apple"),
                                _call("5", "get_analysis_context", stock_code="AAPL")],
                    provider="test", model="test/model"),
        LLMResponse(content=final_text, provider="test", model="test/model", usage={"total_tokens": 5}),
    ]


def _executor(adapter, *, legacy: bool = True) -> AgentExecutor:
    return AgentExecutor(get_tool_registry(), adapter, use_legacy_default_prompt=legacy, max_steps=8)


@pytest.fixture
def analyzer():
    with patch("src.agent.runner._persist_usage"):
        yield run_eval._build_analyzer()


def _run(adapter, analyzer, variant="current", legacy=True):
    executor = _executor(adapter, legacy=legacy)
    source = executor.tool_registry
    record = run_eval.run_sample(executor, source, _fixture(), variant, 0, sample_id="us_AAPL", analyzer=analyzer,
                                 report_type="simple", report_language="en")
    assert executor.tool_registry is source  # restored after the run
    return record


# ----- end to end through the production agent executor -----

def test_run_sample_scores_a_scripted_dashboard(analyzer) -> None:
    adapter = _ScriptedAdapter(_script("```json\n" + json.dumps(DASHBOARD) + "\n```"))
    record = _run(adapter, analyzer)

    assert record.ok and record.json_ok and record.contract_ok, record.error
    assert record.integrity_ok, record.missing_fields
    assert record.decision_type == "buy" and record.sentiment_score == 64.0
    assert record.cjk_ratio == 0.0
    # Calls within one step run in parallel, so their log order varies.
    assert sorted(record.tools_called) == ["analyze_trend", "get_analysis_context", "get_daily_history",
                                           "get_realtime_quote", "search_stock_news"]
    assert record.workflow_hit_rate == 1.0 and record.phase_order_ok is True
    assert record.off_fixture_calls == 1  # get_analysis_context reads saved state, which is not captured
    assert record.total_steps == 4 and record.total_tokens == 15
    assert record.system_prompt_sha256

    # The model got the pipeline's request and context, and exactly the captured tool text.
    user = adapter.calls[0][1]["content"]
    assert user.startswith(run_eval.AGENT_TASK.format(code="AAPL", stock_name="Apple"))
    assert json.dumps(QUOTE, ensure_ascii=False) in user
    tool_texts = {m["name"]: m["content"] for m in adapter.calls[1] if m.get("role") == "tool"}
    assert tool_texts["get_realtime_quote"] == serialize_tool_result(QUOTE)


def test_missing_fields_fail_integrity_without_repair(analyzer) -> None:
    thin = {"sentiment_score": 50, "decision_type": "hold", "operation_advice": "Hold"}
    record = _run(_ScriptedAdapter(_script(json.dumps(thin))), analyzer)
    assert record.json_ok and record.contract_ok
    assert record.integrity_ok is False
    assert "dashboard.core_conclusion.one_sentence" in record.missing_fields


def test_prose_answer_is_not_a_dashboard(analyzer) -> None:
    record = _run(_ScriptedAdapter(_script("AAPL looks fine, I would hold.")), analyzer)
    assert record.ok is True and record.json_ok is False
    assert record.decision_type is None and record.error.startswith("json:")


def test_a_patched_variant_changes_only_the_system_prompt(analyzer) -> None:
    marked = (
        "You are a {market_role} investment analysis agent.\n{market_guidelines}\n"
        "{default_skill_policy_section}\n{skills_section}\n{language_section}\nENGLISH-AGENT-MARKER"
    )
    name = "test_only_english_agent"
    variants.register_variant(name, variants.AgentVariant(
        patch=lambda: variants.patched_agent_prompts(agent_prompt=marked, legacy_prompt=marked)))
    try:
        assert run_eval.template_problems(name) == []
        systems, records = {}, {}
        for variant in ("current", name):
            adapter = _ScriptedAdapter(_script(json.dumps(DASHBOARD)))
            with variants.get_variant(variant).patch():
                records[variant] = _run(adapter, analyzer, variant=variant)
            systems[variant] = adapter.calls[0][0]["content"]
        assert "ENGLISH-AGENT-MARKER" in systems[name]
        assert "ENGLISH-AGENT-MARKER" not in systems["current"]
        assert records[name].system_prompt_sha256 != records["current"].system_prompt_sha256
    finally:
        variants.VARIANTS.pop(name, None)


def test_template_problems_reports_a_missing_placeholder() -> None:
    name = "test_only_broken_agent"
    broken = "{market_role} {market_guidelines} {default_skill_policy_section} {skills_section}"
    variants.register_variant(name, variants.AgentVariant(patch=lambda: variants.patched_agent_prompts(broken)))
    try:
        assert run_eval.template_problems(name) == [f"{name}: AGENT_SYSTEM_PROMPT lacks language_section"]
    finally:
        variants.VARIANTS.pop(name, None)
    assert run_eval.template_problems("current") == []


def test_skills_variant_builds_the_skill_driven_executor() -> None:
    from src.agent.factory import build_agent_executor

    skills = variants.get_variant("skills").skills
    assert skills and variants.get_variant("current").skills is None
    executor = build_agent_executor(None, list(skills))
    assert executor.use_legacy_default_prompt is False


def test_task_matches_the_pipeline_request() -> None:
    source = (Path(__file__).resolve().parents[1] / "src" / "core" / "pipeline.py").read_text(encoding="utf-8")
    assert 'f"' + run_eval.AGENT_TASK + '"' in source


def test_build_context_carries_the_quote_only_when_captured() -> None:
    context = run_eval.build_context(_fixture(), "simple", "en")
    assert context == {"stock_code": "AAPL", "stock_name": "Apple", "report_type": "simple",
                       "report_language": "en", "realtime_quote": QUOTE}
    no_quote = dict(_fixture(), tools={})
    assert "realtime_quote" not in run_eval.build_context(no_quote, "simple", "en")


# ----- metrics -----

def _record(sample_id, variant, repeat, decision, score, **extra):
    base = dict(ok=True, json_ok=True, contract_ok=True, integrity_ok=True, cjk_ratio=0.0,
                decision_type=decision, sentiment_score=score, workflow_hit_rate=1.0,
                phase_order_ok=True, total_steps=4, total_tokens=100, system_prompt_sha256="a" * 64)
    base.update(extra)
    return AgentRecord(sample_id=sample_id, variant=variant, repeat=repeat, **base)


def test_report_combines_dashboard_and_trajectory_measurements() -> None:
    base = [_record("a", "current", 0, "buy", 62), _record("a", "current", 1, "buy", 63),
            _record("b", "current", 0, "hold", 50, missing_workflow_tools=["analyze_trend"],
                    workflow_hit_rate=0.75, phase_order_ok=False, off_fixture_calls=2)]
    cand = [_record("a", "english", 0, "hold", 58), _record("a", "english", 1, "hold", 57),
            _record("b", "english", 0, "hold", 50, system_prompt_sha256="b" * 64),
            AgentRecord(sample_id="c", variant="english", repeat=0, error="run: timeout")]

    trajectory = summarize_trajectory(base)
    assert trajectory["full_workflow_rate"] == round(2 / 3, 4)
    assert trajectory["phase_order_rate"] == round(2 / 3, 4)
    assert trajectory["off_fixture_calls"] == 2
    assert trajectory["top_missing_tools"] == [("analyze_trend", 1)]

    report = build_report(base + cand, baseline="current")
    assert report["variants"]["english"]["summary"]["call_errors"] == 1
    assert report["variants"]["english"]["trajectory"]["system_prompts"] == ["aaaaaaaaaaaa", "bbbbbbbbbbbb"]
    assert report["comparisons"]["english"]["decision_flips"] == [
        {"sample_id": "a", "baseline": "buy", "candidate": "hold"}]
    text = format_text_report(report)
    assert text.startswith("Agent analysis eval (baseline: current)")
    assert "flip a: buy -> hold" in text and "[english trajectory]" in text


# ----- runner guards -----

def _write_fixture(directory: Path) -> None:
    from evals.chat_language.capture_fixtures import fixture_filename

    (directory / fixture_filename("AAPL")).write_text(json.dumps(_fixture()), encoding="utf-8")


def test_runner_without_run_flag_never_calls_the_model(tmp_path: Path, monkeypatch) -> None:
    adapter = _ScriptedAdapter([])
    monkeypatch.setattr(run_eval, "_build_agent_executor", lambda skills: _executor(adapter, legacy=not skills))
    monkeypatch.setattr(run_eval, "validate", lambda *a, **k: [])
    _write_fixture(tmp_path)
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "unused.db"))

    args = ["--fixtures", str(tmp_path), "--sample", "us_AAPL", "--variant", "current", "--variant", "skills"]
    assert run_eval.main(args) == 0
    assert run_eval.main(args + ["--run", "--max-runs", "5"]) == 2  # 1 x 2 x 3 = 6 runs
    assert adapter.calls == []


def test_runner_usage_errors(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "unused.db"))  # main() points it at a throwaway file
    assert run_eval.main(["--fixtures", str(tmp_path), "--variant", "nope"]) == 2
    assert run_eval.main(["--fixtures", str(tmp_path), "--repeats", "0"]) == 2
    assert run_eval.main(["--fixtures", str(tmp_path)]) == 1  # no fixtures


def test_capture_defaults_to_the_prompt_eval_stocks(monkeypatch, tmp_path: Path) -> None:
    seen = {}
    monkeypatch.setattr(capture_fixtures.chat_capture, "main", lambda argv: seen.setdefault("argv", argv) and 0)
    capture_fixtures.main(["--sample", "us_AAPL"])
    argv = seen["argv"]
    assert argv[argv.index("--samples") + 1] == str(capture_fixtures.DEFAULT_SAMPLES)
    assert argv[argv.index("--out") + 1] == str(capture_fixtures.DEFAULT_OUT)
    assert argv[-2:] == ["--sample", "us_AAPL"]
    seen.clear()
    capture_fixtures.main(["--out", str(tmp_path)])
    assert seen["argv"].count("--out") == 1 and str(tmp_path) in seen["argv"]
    samples = json.loads(capture_fixtures.DEFAULT_SAMPLES.read_text(encoding="utf-8"))
    assert len(samples) == 30 and {s["market"] for s in samples} == {"ca", "us"}

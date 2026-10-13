# -*- coding: utf-8 -*-
"""Offline tests for the chat-prompt language eval (metrics, replay, variants, runner guards).

The end-to-end tests drive the production ``AgentChatExecutor`` and
``LiteLLMAgentBackend`` with a scripted model, so the real ReAct loop executes
the replayed tools; only conversation persistence is patched out.
"""

from __future__ import annotations

import json
from contextlib import ExitStack
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from evals.chat_language import capture_fixtures, run_eval, variants
from evals.chat_language.metrics import (
    ChatRecord,
    build_report,
    format_text_report,
    parse_decision_line,
    phase_order_ok,
    summarize_variant,
)
from evals.chat_language.replay import build_replay_registry, captured_entry, replay_key
from src.agent.agent_backend import LiteLLMAgentBackend
from src.agent.chat_executor import AgentChatExecutor
from src.agent.factory import get_tool_registry
from src.agent.llm_adapter import LLMResponse, ToolCall
from src.agent.tools.execution import serialize_tool_result

QUOTE = {"code": "AAPL", "name": "Apple", "price": 201.5, "change_pct": 1.2}
HISTORY = {"code": "AAPL", "bars": [{"date": "2026-10-06", "close": 199.1}]}
TREND = {"code": "AAPL", "trend": "bullish", "ma5": 198.0}
NEWS = {"code": "AAPL", "results": [{"title": "Apple ships a new product", "snippet": "..."}]}


def _fixture() -> dict:
    tools = {
        replay_key("get_realtime_quote", {"stock_code": "AAPL"}): captured_entry(QUOTE, arguments={"stock_code": "AAPL"}),
        replay_key("get_daily_history", {"stock_code": "AAPL"}): captured_entry(HISTORY, arguments={"stock_code": "AAPL"}),
        replay_key("analyze_trend", {"stock_code": "AAPL"}): captured_entry(TREND, arguments={"stock_code": "AAPL"}),
        replay_key("search_stock_news", {"stock_code": "AAPL"}): captured_entry(
            NEWS, arguments={"stock_code": "AAPL", "stock_name": "Apple"}
        ),
        replay_key("get_stock_info", {"stock_code": "AAPL"}): captured_entry(
            error="provider down", arguments={"stock_code": "AAPL"}
        ),
    }
    return {"stock_code": "AAPL", "market": "us", "stock_name": "Apple", "report_language": "en", "tools": tools}


SAMPLE = {"id": "us_AAPL_decision", "stock_code": "AAPL", "market": "us", "with_context": True,
          "ask_decision": True, "question": "Should I buy AAPL?"}


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


def _workflow_script(final_text: str = "AAPL is trending up.\nDecision: buy"):
    return [
        LLMResponse(tool_calls=[_call("1", "get_realtime_quote", stock_code="AAPL"),
                                _call("2", "get_daily_history", stock_code="AAPL", days=30)],
                    provider="test", model="test/model", usage={"total_tokens": 10}),
        LLMResponse(tool_calls=[_call("3", "analyze_trend", stock_code="AAPL")], provider="test", model="test/model"),
        LLMResponse(tool_calls=[_call("4", "search_stock_news", stock_code="AAPL", stock_name="Apple"),
                                _call("5", "get_analysis_context", stock_code="AAPL")],
                    provider="test", model="test/model"),
        LLMResponse(content=final_text, provider="test", model="test/model", usage={"total_tokens": 5}),
    ]


def _executor(adapter) -> AgentChatExecutor:
    backend = LiteLLMAgentBackend(get_tool_registry(), adapter)
    return AgentChatExecutor(backend=backend, config=SimpleNamespace(), context_llm_adapter=object(), max_steps=8)


@pytest.fixture
def no_persistence():
    """Patch out conversation and usage storage so a chat turn runs without a database."""
    with ExitStack() as stack:
        bundle = stack.enter_context(patch("src.agent.executor.build_agent_chat_context_bundle"))
        bundle.return_value.context_messages = []
        stack.enter_context(patch("src.agent.chat_executor.conversation_manager.get_or_create"))
        stack.enter_context(patch("src.agent.chat_executor.conversation_manager.add_user_message", return_value=1))
        stack.enter_context(patch("src.agent.chat_executor.conversation_manager.add_message", return_value=2))
        stack.enter_context(patch("src.agent.chat_executor.persist_provider_trace_turns"))
        stack.enter_context(patch("src.agent.runner._persist_usage"))
        yield


# ----- metrics -----

def test_parse_decision_line_takes_the_last_explicit_line() -> None:
    assert parse_decision_line("I would buy on a dip.\nDecision: hold") == "hold"
    assert parse_decision_line("Decision: **SELL**") == "sell"
    assert parse_decision_line("Decision: buy\n...\nDecision: sell") == "sell"
    assert parse_decision_line("You could buy or sell.") is None


def test_phase_order_flags_merged_and_backward_phases() -> None:
    ordered = [{"step": 1, "tool": "get_realtime_quote"}, {"step": 1, "tool": "get_daily_history"},
               {"step": 2, "tool": "analyze_trend"}, {"step": 3, "tool": "search_stock_news"},
               {"step": 3, "tool": "get_market_indices"}]
    merged = [{"step": 1, "tool": "get_realtime_quote"}, {"step": 1, "tool": "analyze_trend"}]
    backward = [{"step": 1, "tool": "analyze_trend"}, {"step": 2, "tool": "get_realtime_quote"}]
    assert phase_order_ok(ordered) is True
    assert phase_order_ok(merged) is False
    assert phase_order_ok(backward) is False
    assert phase_order_ok([{"step": 1, "tool": "get_market_indices"}]) is None


def _record(sample_id, variant, repeat, decision=None, **extra):
    base = dict(ok=True, cjk_ratio=0.0, workflow_hit_rate=1.0, phase_order_ok=True, total_steps=4,
                decision_asked=decision is not None, decision_type=decision)
    base.update(extra)
    return ChatRecord(sample_id=sample_id, variant=variant, repeat=repeat, **base)


def test_summary_and_comparison() -> None:
    base = [_record("a", "current", 0, "buy"), _record("a", "current", 1, "buy"),
            _record("b", "current", 0, cjk_ratio=0.3, phase_order_ok=False,
                    workflow_hit_rate=0.5, missing_workflow_tools=["search_stock_news", "analyze_trend"])]
    cand = [_record("a", "english", 0, "hold"), _record("a", "english", 1, "hold"), _record("b", "english", 0),
            ChatRecord(sample_id="c", variant="english", repeat=0, error="turn: timeout", latency_ms=5)]

    summary = summarize_variant(base)
    assert summary["english_rate"] == round(2 / 3, 4)
    assert summary["full_workflow_rate"] == round(2 / 3, 4)
    assert summary["phase_order_rate"] == round(2 / 3, 4)
    assert summary["decision_distribution"] == {"buy": 2}
    assert ("search_stock_news", 1) in summary["top_missing_tools"]

    report = build_report(base + cand, baseline="current")
    cmp = report["comparisons"]["english"]
    assert report["variants"]["english"]["summary"]["failed_turns"] == 1
    assert cmp["decision_agreement"] == 0.0
    assert cmp["decision_flips"] == [{"sample_id": "a", "baseline": "buy", "candidate": "hold"}]
    assert cmp["english_rate_delta"] == round(1.0 - 2 / 3, 4)
    assert "flip a: buy -> hold" in format_text_report(report)


# ----- replay -----

def test_replay_registry_keeps_the_tool_surface_and_replays_results_and_errors() -> None:
    from src.agent.tools.execution import execute_runner_tool_call

    source = get_tool_registry()
    off = []
    replay = build_replay_registry(source, _fixture()["tools"], off)
    assert replay.to_openai_tools() == source.to_openai_tools()
    assert replay.category_timeout_map == source.category_timeout_map

    _, text, ok, *_ = execute_runner_tool_call(
        tool_call=_call("1", "get_realtime_quote", stock_code="aapl"), tool_registry=replay)
    assert ok and text == serialize_tool_result(QUOTE)

    _, text, ok, *_ = execute_runner_tool_call(
        tool_call=_call("2", "get_stock_info", stock_code="AAPL"), tool_registry=replay)
    assert not ok and json.loads(text) == {"error": "provider down"}

    _, text, ok, *_ = execute_runner_tool_call(
        tool_call=_call("3", "get_realtime_quote", stock_code="MSFT"), tool_registry=replay)
    assert not ok and "MSFT" in json.loads(text)["error"]
    assert off == [{"tool": "get_realtime_quote", "arguments": {"stock_code": "MSFT"},
                    "key": "get_realtime_quote:MSFT"}]


def test_captured_entry_falls_back_to_text_when_freezing_changes_the_output() -> None:
    class QuoteObject:
        def __init__(self) -> None:
            self.price = 1.5

        def __str__(self) -> str:
            return "QuoteObject"

    entry = captured_entry({"value": 1.5}, arguments={"stock_code": "AAPL"})
    assert entry == {"arguments": {"stock_code": "AAPL"}, "ok": True, "result": {"value": 1.5}}
    # A tuple freezes to a list, which serializes to the same text.
    assert captured_entry({"values": (1, 2)})["result"] == {"values": [1, 2]}
    # The runner serializes an object through its __dict__, but json would freeze it to str(obj).
    text_entry = captured_entry(QuoteObject())
    assert text_entry["text_only"] is True
    assert text_entry["result"] == serialize_tool_result(QuoteObject()) == '{"price": 1.5}'


# ----- end to end through the production chat executor -----

def test_run_turn_scores_a_scripted_workflow(no_persistence) -> None:
    adapter = _ScriptedAdapter(_workflow_script())
    executor = _executor(adapter)
    source = executor.backend.tool_registry

    record = run_eval.run_turn(executor, source, SAMPLE, _fixture(), "current", 0)

    assert record.ok, record.error
    assert record.tools_called == ["get_realtime_quote", "get_daily_history", "analyze_trend",
                                   "search_stock_news", "get_analysis_context"]
    assert record.workflow_hit_rate == 1.0 and record.missing_workflow_tools == []
    assert record.phase_order_ok is True
    assert record.off_fixture_calls == 1
    assert record.decision_type == "buy"
    assert record.cjk_ratio == 0.0
    assert record.total_steps == 4 and record.total_tokens == 15
    assert record.system_prompt_sha256

    # The model received the decision instruction and exactly the captured tool text.
    first_call = adapter.calls[0]
    assert first_call[-1]["content"].endswith(run_eval.DECISION_SUFFIX)
    tool_texts = {m["name"]: m["content"] for m in adapter.calls[1] if m.get("role") == "tool"}
    assert tool_texts["get_realtime_quote"] == serialize_tool_result(QUOTE)


def test_a_registered_variant_changes_only_the_system_prompt(no_persistence) -> None:
    english = (
        "You are a {market_role} investment analysis agent.\n{market_guidelines}\n"
        "{default_skill_policy_section}\n{skills_section}\n{language_section}\nENGLISH-VARIANT-MARKER"
    )
    name = "test_only_english_chat"
    variants.register_variant(name, lambda: variants.patched_chat_prompts(chat_prompt=english, legacy_prompt=english))
    try:
        assert run_eval.template_problems(name) == []
        records = {}
        systems = {}
        for variant in ("current", name):
            adapter = _ScriptedAdapter(_workflow_script())
            executor = _executor(adapter)
            with variants.activate(variant):
                records[variant] = run_eval.run_turn(executor, executor.backend.tool_registry, SAMPLE, _fixture(),
                                                     variant, 0)
            systems[variant] = adapter.calls[0][0]["content"]
        assert "ENGLISH-VARIANT-MARKER" in systems[name]
        assert "ENGLISH-VARIANT-MARKER" not in systems["current"]
        assert records[name].system_prompt_sha256 != records["current"].system_prompt_sha256
        assert records[name].phase_order_ok is records["current"].phase_order_ok is True
    finally:
        variants.VARIANTS.pop(name, None)


def test_template_problems_reports_a_missing_placeholder() -> None:
    name = "test_only_broken_chat"
    broken = "{market_role} {market_guidelines} {default_skill_policy_section} {skills_section}"
    variants.register_variant(name, lambda: variants.patched_chat_prompts(chat_prompt=broken))
    try:
        problems = run_eval.template_problems(name)
        assert problems == [f"{name}: CHAT_SYSTEM_PROMPT lacks language_section"]
    finally:
        variants.VARIANTS.pop(name, None)
    assert run_eval.template_problems("current") == []


# ----- runner guards -----

def _write_fixture(directory: Path) -> None:
    (directory / capture_fixtures.fixture_filename("AAPL")).write_text(json.dumps(_fixture()), encoding="utf-8")


def test_validate_reports_missing_fixture_language_and_stale_tools() -> None:
    fixtures = {"AAPL": _fixture()}
    names = get_tool_registry().list_names()
    assert run_eval.validate([SAMPLE], fixtures, names, "en") == []
    assert run_eval.validate([dict(SAMPLE, stock_code="MSFT")], fixtures, names, "en")
    assert run_eval.validate([SAMPLE], fixtures, names, "zh")
    stale = {"AAPL": dict(_fixture(), tools={"retired_tool:AAPL": {"ok": True, "result": {}}})}
    assert any("retired_tool" in p for p in run_eval.validate([SAMPLE], stale, names, "en"))


def test_runner_without_run_flag_never_calls_the_model(tmp_path: Path, monkeypatch) -> None:
    adapter = _ScriptedAdapter([])
    monkeypatch.setattr(run_eval, "_build_chat_executor", lambda: _executor(adapter))
    monkeypatch.setattr(run_eval, "validate", lambda *a, **k: [])
    _write_fixture(tmp_path)
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "unused.db"))

    assert run_eval.main(["--fixtures", str(tmp_path), "--sample", "us_AAPL_analysis"]) == 0
    assert run_eval.main(["--fixtures", str(tmp_path), "--sample", "us_AAPL_analysis", "--run",
                          "--max-turns", "1"]) == 2
    assert adapter.calls == []


def test_runner_usage_errors(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "unused.db"))  # main() points it at a throwaway file
    assert run_eval.main(["--fixtures", str(tmp_path), "--variant", "nope"]) == 2
    assert run_eval.main(["--fixtures", str(tmp_path), "--repeats", "0"]) == 2
    assert run_eval.main(["--fixtures", str(tmp_path)]) == 1  # no fixtures


def test_samples_cover_both_markets_and_decision_questions() -> None:
    samples = capture_fixtures.load_samples(capture_fixtures.DEFAULT_SAMPLES)
    assert len({s["id"] for s in samples}) == len(samples) == 10
    assert {s["market"] for s in samples} == {"ca", "us"}
    assert any(s["ask_decision"] for s in samples) and any(not s["ask_decision"] for s in samples)
    assert any(s["with_context"] for s in samples) and any(not s["with_context"] for s in samples)
    for sample in samples:
        assert sample["stock_code"] in sample["question"]

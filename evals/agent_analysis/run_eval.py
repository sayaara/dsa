#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Compare Agent analysis variants on frozen tool outputs (agent analysis eval).

Builds the production single-agent executor (``build_agent_executor``, as the
pipeline does in agent mode), swaps only its tool registry for one that replays
the outputs captured by ``capture_fixtures.py``, and sends the pipeline's
analysis request for each stock under each requested variant, several times
each. Every run is the real ReAct loop ending in a decision dashboard, scored
without any repair: the dashboard with the prompt-language metrics (integrity
through the analyzer's parser, as in that eval; the pipeline's agent-result
conversion backfills missing fields, so it would hide them), the loop with the
tool trajectory metrics.

The context is what the pipeline always sends (code, name, report type, report
language and the real-time quote); the market phase, daily market context,
market structure, context-pack summary and news context blocks are left out,
so the run measures the agent prompts and the tool loop rather than those
already-English sections.

Without ``--run`` the script only validates the samples, fixtures and variant
templates and prints the plan. With ``--run`` it calls the configured LLM and
refuses to start when the plan exceeds ``--max-runs``. Each run makes several
model calls (one per loop step, up to ``AGENT_MAX_STEPS``). Database writes go
to a throwaway database, never to data/stock_analysis.db.

The eval is a reporter, not a gate. Exit codes: 0 = ran or validated,
1 = fixture or setup failure, 2 = usage error or plan above ``--max-runs``.

Usage:
    python evals/agent_analysis/run_eval.py
    python evals/agent_analysis/run_eval.py --run --repeats 3 --max-runs 90 --json-out agent_eval.json
    python evals/agent_analysis/run_eval.py --run --variant current --variant skills --max-runs 180
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from evals.agent_analysis.capture_fixtures import DEFAULT_OUT, DEFAULT_SAMPLES
from evals.agent_analysis.metrics import AgentRecord, build_report, format_text_report
from evals.agent_analysis.variants import AGENT_TEMPLATE_FIELDS, BASELINE_VARIANT, VARIANTS, get_variant
from evals.agent_trajectory.metrics import GoldenSample, compute_trajectory_metrics
from evals.chat_language.capture_fixtures import load_samples
from evals.chat_language.metrics import WORKFLOW_TOOLS, phase_order_ok
from evals.chat_language.replay import build_replay_registry, normalize_key_value, replay_key
from evals.chat_language.run_eval import load_fixtures, validate
from evals.prompt_language.metrics import cjk_ratio, normalize_decision

# The pipeline's agent analysis request (src/core/pipeline.py, _analyze_with_agent); a test keeps them equal.
AGENT_TASK = "Analyze stock {code} ({stock_name}) and return the full decision dashboard JSON."


def build_context(fixture: Mapping[str, Any], report_type: str, report_language: str) -> Dict[str, Any]:
    """The pipeline's initial agent context, reduced to the fields every run carries."""
    code = fixture["stock_code"]
    context: Dict[str, Any] = {
        "stock_code": code,
        "stock_name": fixture.get("stock_name") or code,
        "report_type": report_type,
        "report_language": report_language,
    }
    quote = fixture.get("tools", {}).get(replay_key("get_realtime_quote", {"stock_code": code}), {})
    if quote.get("ok") and isinstance(quote.get("result"), dict):
        context["realtime_quote"] = quote["result"]
    return context


def template_problems(variant: str) -> List[str]:
    """Check that a variant's agent templates keep every placeholder and still format."""
    import src.agent.executor as executor

    problems: List[str] = []
    dummy = {name: f"<{name}>" for name in AGENT_TEMPLATE_FIELDS}
    with get_variant(variant).patch():
        for attr in ("AGENT_SYSTEM_PROMPT", "LEGACY_DEFAULT_AGENT_SYSTEM_PROMPT"):
            template = getattr(executor, attr)
            missing = [name for name in AGENT_TEMPLATE_FIELDS if "{" + name + "}" not in template]
            if missing:
                problems.append(f"{variant}: {attr} lacks {', '.join(missing)}")
                continue
            try:
                template.format(**dummy)
            except (KeyError, IndexError, ValueError) as exc:
                problems.append(f"{variant}: {attr} does not format: {exc!r}")
    return problems


def _dashboard_value(dashboard: Mapping[str, Any], key: str) -> Any:
    """A top-level dashboard field, or the same field in a nested ``dashboard`` block."""
    value = dashboard.get(key)
    nested = dashboard.get("dashboard")
    if value in (None, "") and isinstance(nested, Mapping):
        value = nested.get(key)
    return value


def score_run(record: AgentRecord, result: Any, fixture: Mapping[str, Any], *, analyzer: Any,
              off_fixture_calls: Sequence[Mapping[str, Any]], max_steps: int) -> None:
    """Fill ``record`` from one ``AgentResult``-shaped object, without any repair."""
    from src.analyzer import check_content_integrity
    from src.report_language import infer_decision_type_from_advice

    log = list(getattr(result, "tool_calls_log", None) or [])
    record.tools_called = [str(entry.get("tool") or "") for entry in log]
    record.off_fixture_calls = len(off_fixture_calls)
    record.total_steps = int(getattr(result, "total_steps", 0) or 0)
    record.total_tokens = int(getattr(result, "total_tokens", 0) or 0)
    messages = getattr(result, "messages", None) or []
    if messages and messages[0].get("role") == "system":
        record.system_prompt_sha256 = hashlib.sha256(str(messages[0].get("content") or "").encode("utf-8")).hexdigest()
    trajectory = compute_trajectory_metrics(
        log,
        GoldenSample(
            id=record.sample_id,
            task_description=AGENT_TASK,
            expected_tools=list(WORKFLOW_TOOLS),
            stock_code=str(fixture["stock_code"]),
            allowed_max_steps=max_steps,
            allow_optional_tools=True,
        ),
        total_steps=record.total_steps or None,
    )
    record.workflow_hit_rate = trajectory.expected_hit_rate
    record.missing_workflow_tools = list(trajectory.missing_expected)
    record.failed_calls = trajectory.failed_calls
    record.redundant_calls = trajectory.redundant_calls
    record.phase_order_ok = phase_order_ok(log)

    content = str(getattr(result, "content", "") or "")
    dashboard = getattr(result, "dashboard", None)
    if not content:
        record.error = f"run: {getattr(result, 'error', None) or 'empty answer'}"[:200]
        return
    record.ok = True
    record.response_chars = len(content)
    if not isinstance(dashboard, dict):
        record.error = f"json: {getattr(result, 'error', None) or 'no dashboard'}"[:200]
        return
    record.json_ok = True
    try:
        analyzer._validate_analysis_minimal_contract(dashboard)
        record.contract_ok = True
    except Exception as exc:
        record.error = f"contract: {exc}"[:200]
    record.decision_type = normalize_decision(_dashboard_value(dashboard, "decision_type"))
    record.advice_decision = normalize_decision(
        infer_decision_type_from_advice(_dashboard_value(dashboard, "operation_advice"), default="")
    )
    score = _dashboard_value(dashboard, "sentiment_score")
    if isinstance(score, (int, float)) and not isinstance(score, bool):
        record.sentiment_score = float(score)
    record.cjk_ratio = cjk_ratio(dashboard)
    parsed = analyzer._parse_response(
        json.dumps(dashboard, ensure_ascii=False),
        str(fixture["stock_code"]), str(fixture.get("stock_name") or fixture["stock_code"]),
    )
    passed, missing = check_content_integrity(parsed, require_phase_decision=False)
    record.integrity_ok = bool(passed)
    record.missing_fields = list(missing)


def run_sample(executor: Any, source_registry: Any, fixture: Mapping[str, Any], variant: str, repeat: int, *,
               sample_id: str, analyzer: Any, report_type: str,
               report_language: str) -> AgentRecord:
    """Run the agent analysis for one stock once through ``executor`` with replayed tools."""
    record = AgentRecord(sample_id=sample_id, variant=variant, repeat=repeat)
    off_fixture_calls: List[Dict[str, Any]] = []
    executor.tool_registry = build_replay_registry(source_registry, fixture.get("tools", {}), off_fixture_calls)
    context = build_context(fixture, report_type, report_language)
    task = AGENT_TASK.format(code=context["stock_code"], stock_name=context["stock_name"])
    started = time.monotonic()
    try:
        result = executor.run(task, context=context)
    except Exception as exc:
        record.latency_ms = int((time.monotonic() - started) * 1000)
        record.error = f"run: {exc}"[:200]
        return record
    finally:
        executor.tool_registry = source_registry
    record.latency_ms = int((time.monotonic() - started) * 1000)
    score_run(record, result, fixture, analyzer=analyzer,
              off_fixture_calls=off_fixture_calls, max_steps=int(getattr(executor, "max_steps", 10) or 10))
    return record


def _build_agent_executor(skills: Optional[Sequence[str]]) -> Any:
    """Build the production single-agent executor (lazy import so tests can monkeypatch this)."""
    from src.agent.executor import AgentExecutor
    from src.agent.factory import build_agent_executor
    from src.config import get_config

    executor = build_agent_executor(get_config(), list(skills) if skills else None)
    if not isinstance(executor, AgentExecutor):
        raise RuntimeError("this eval needs the single-agent executor (AGENT_ARCH=single)")
    return executor


def _build_analyzer() -> Any:
    """The analyzer used for the contract check and the parser; it never calls a model here."""
    from src.analyzer import GeminiAnalyzer
    from src.config import get_config

    return GeminiAnalyzer(config=get_config())


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Agent analysis eval: compare agent prompt variants")
    parser.add_argument("--fixtures", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--samples", type=Path, default=DEFAULT_SAMPLES)
    parser.add_argument("--sample", action="append", help="Only this sample id (repeatable)")
    parser.add_argument("--variant", action="append", help=f"Variant to run (repeatable); default {BASELINE_VARIANT}")
    parser.add_argument("--repeats", type=int, default=3, help="Runs per sample and variant (default 3)")
    parser.add_argument("--run", action="store_true", help="Call the LLM; without it only validate and plan")
    parser.add_argument("--max-runs", type=int, default=0, help="Refuse to run when the plan needs more runs")
    parser.add_argument("--english-threshold", type=float, default=0.05,
                        help="Max CJK share of the dashboard text for it to count as English")
    parser.add_argument("--json-out", type=Path, help="Write records and report as JSON")
    args = parser.parse_args(argv)

    variants = args.variant or [BASELINE_VARIANT]
    unknown = [v for v in variants if v not in VARIANTS]
    if unknown or args.repeats < 1:
        parser.print_usage(sys.stderr)
        print(f"unknown variant(s): {unknown}; known: {sorted(VARIANTS)}" if unknown else "--repeats must be >= 1",
              file=sys.stderr)
        return 2

    # Keep the eval's usage and evidence rows out of the real database.
    scratch = Path(tempfile.mkdtemp(prefix="agent-analysis-eval-"))
    os.environ["DATABASE_PATH"] = str(scratch / "eval.db")
    os.environ.setdefault("LOG_DIR", str(scratch / "logs"))

    samples = load_samples(args.samples, args.sample)
    fixtures = load_fixtures(args.fixtures)
    if not fixtures:
        print(f"no fixtures in {args.fixtures}; run capture_fixtures.py first", file=sys.stderr)
        return 1
    try:
        executors = {name: _build_agent_executor(get_variant(name).skills) for name in variants}
        analyzer = _build_analyzer()
    except Exception as exc:
        print(f"error: failed to build the agent executor: {exc}", file=sys.stderr)
        return 1
    from src.config import get_config

    config = get_config()
    first = executors[variants[0]]
    problems = validate(samples, fixtures, first.tool_registry.list_names(), config.report_language)
    for variant in variants:
        problems.extend(template_problems(variant))
    if problems:
        print("validation failed:", file=sys.stderr)
        for problem in problems:
            print(f"  {problem}", file=sys.stderr)
        return 1

    planned = len(samples) * len(variants) * args.repeats
    max_steps = int(getattr(first, "max_steps", 10) or 10)
    for name, executor in executors.items():
        print(f"[{name}] legacy_default_prompt={executor.use_legacy_default_prompt}")
    print(f"{len(samples)} sample(s) valid; plan: {len(variants)} variant(s) x {args.repeats} repeat(s) = "
          f"{planned} agent run(s), at most {planned * max_steps} model call(s) "
          f"(AGENT_MAX_STEPS={max_steps}, before transport retries)")
    if not args.run:
        print("validation only; pass --run --max-runs N to call the model")
        return 0
    if planned > args.max_runs:
        print(f"plan needs {planned} runs but --max-runs is {args.max_runs}; not running", file=sys.stderr)
        return 2
    llm_adapter = getattr(first, "llm_adapter", None)
    if llm_adapter is None or not llm_adapter.is_available:
        print("no LLM is configured (see docs/LLM_CONFIG_GUIDE.md)", file=sys.stderr)
        return 1

    records: List[AgentRecord] = []
    for variant in variants:
        executor = executors[variant]
        source_registry = executor.tool_registry
        with get_variant(variant).patch():
            for sample in samples:
                fixture = fixtures[normalize_key_value(sample["stock_code"])]
                for repeat in range(args.repeats):
                    record = run_sample(executor, source_registry, fixture, variant, repeat,
                                        sample_id=str(sample["id"]), analyzer=analyzer,
                                        report_type=str(config.report_type), report_language=config.report_language)
                    records.append(record)
                    print(
                        f"[{variant}] {sample['id']} #{repeat}: json={record.json_ok} "
                        f"integrity={record.integrity_ok} decision={record.decision_type} "
                        f"score={record.sentiment_score} cjk={record.cjk_ratio} "
                        f"workflow={record.workflow_hit_rate} steps={record.total_steps} "
                        f"off_fixture={record.off_fixture_calls}"
                        + (f" error={record.error}" if record.error else ""),
                        flush=True,
                    )

    baseline = BASELINE_VARIANT if BASELINE_VARIANT in variants else variants[0]
    report = build_report(records, baseline=baseline, english_threshold=args.english_threshold)
    print()
    print(format_text_report(report))
    if args.json_out:
        args.json_out.write_text(
            json.dumps({"report": report, "records": [r.to_dict() for r in records]}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"\nJSON report written to {args.json_out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

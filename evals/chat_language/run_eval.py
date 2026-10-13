#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Compare Agent Chat prompt variants on frozen tool outputs (chat-prompt language eval).

Builds the production Agent Chat executor (``build_agent_chat_executor``, the
LiteLLM backend with the configured skills), swaps only its tool registry for
one that replays the outputs captured by ``capture_fixtures.py``, and asks
each sample question under each requested prompt variant, several times each.
Every turn runs the real ReAct loop, so the report covers what the chat
prompts control: the reply language, whether the four-phase tool workflow is
followed, and (on decision samples) the stance.

Without ``--run`` the script only validates the samples, fixtures and variant
templates and prints the plan. With ``--run`` it calls the configured LLM and
refuses to start when the plan exceeds ``--max-turns``. Each turn makes
several model calls (one per loop step, up to ``AGENT_MAX_STEPS``).

Conversation rows go to a throwaway database, never to data/stock_analysis.db.

The eval is a reporter, not a gate. Exit codes: 0 = ran or validated,
1 = fixture or setup failure, 2 = usage error or plan above ``--max-turns``.

Usage:
    python evals/chat_language/run_eval.py
    python evals/chat_language/run_eval.py --run --repeats 2 --max-turns 20 --json-out chat_eval.json
    python evals/chat_language/run_eval.py --run --variant current --variant <name> --max-turns 40
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from evals.agent_trajectory.metrics import GoldenSample, compute_trajectory_metrics
from evals.chat_language.capture_fixtures import DEFAULT_OUT, DEFAULT_SAMPLES, load_samples
from evals.chat_language.metrics import (
    WORKFLOW_TOOLS,
    ChatRecord,
    build_report,
    format_text_report,
    parse_decision_line,
    phase_order_ok,
    reply_cjk_ratio,
)
from evals.chat_language.replay import build_replay_registry, normalize_key_value
from evals.chat_language.variants import BASELINE_VARIANT, CHAT_TEMPLATE_FIELDS, VARIANTS, activate

# Appended to decision samples so the stance can be read without guessing from prose.
DECISION_SUFFIX = (
    "\n\nEnd your reply with one line in the form `Decision: buy`, `Decision: hold` or `Decision: sell`."
)


def load_fixtures(directory: Path) -> Dict[str, Dict[str, Any]]:
    """Captured fixtures keyed by normalized stock code."""
    fixtures: Dict[str, Dict[str, Any]] = {}
    for path in sorted(Path(directory).glob("*.json")):
        fixture = json.loads(path.read_text(encoding="utf-8"))
        fixtures[normalize_key_value(fixture.get("stock_code"))] = fixture
    return fixtures


def build_message(sample: Mapping[str, Any]) -> str:
    return str(sample["question"]) + (DECISION_SUFFIX if sample.get("ask_decision") else "")


def build_context(sample: Mapping[str, Any], fixture: Mapping[str, Any]) -> Optional[Dict[str, Any]]:
    """The context the Web chat sends when a question is asked from a stock's report, or None."""
    if not sample.get("with_context"):
        return None
    return {"stock_code": fixture["stock_code"], "stock_name": fixture.get("stock_name") or fixture["stock_code"]}


def validate(samples: Sequence[Mapping[str, Any]], fixtures: Mapping[str, Mapping[str, Any]],
             tool_names: Sequence[str], report_language: str) -> List[str]:
    """Return problems that would make a replay unlike the production chat turn."""
    problems: List[str] = []
    known = set(tool_names)
    missing_workflow = [t for t in WORKFLOW_TOOLS if t not in known]
    if missing_workflow:
        problems.append(f"workflow tools missing from the registry: {', '.join(missing_workflow)}")
    for sample in samples:
        fixture = fixtures.get(normalize_key_value(sample.get("stock_code")))
        if fixture is None:
            problems.append(f"{sample['id']}: no fixture for {sample.get('stock_code')}; run capture_fixtures.py")
            continue
        if fixture.get("report_language") != report_language:
            problems.append(
                f"{sample['id']}: fixture captured with REPORT_LANGUAGE={fixture.get('report_language')}, "
                f"current is {report_language}"
            )
    for fixture in fixtures.values():
        stale = sorted({key.split(":", 1)[0] for key in fixture.get("tools", {})} - known)
        if stale:
            problems.append(f"{fixture.get('stock_code')}: captured tools no longer registered: {', '.join(stale)}")
    return problems


def template_problems(variant: str) -> List[str]:
    """Check that a variant's chat templates keep every placeholder and still format."""
    import src.agent.executor as executor

    problems: List[str] = []
    dummy = {name: f"<{name}>" for name in CHAT_TEMPLATE_FIELDS}
    with activate(variant):
        for attr in ("CHAT_SYSTEM_PROMPT", "LEGACY_DEFAULT_CHAT_SYSTEM_PROMPT"):
            template = getattr(executor, attr)
            missing = [name for name in CHAT_TEMPLATE_FIELDS if "{" + name + "}" not in template]
            if missing:
                problems.append(f"{variant}: {attr} lacks {', '.join(missing)}")
                continue
            try:
                template.format(**dummy)
            except (KeyError, IndexError, ValueError) as exc:
                problems.append(f"{variant}: {attr} does not format: {exc!r}")
    return problems


def score_turn(record: ChatRecord, result: Any, sample: Mapping[str, Any],
               off_fixture_calls: Sequence[Mapping[str, Any]], max_steps: int) -> None:
    """Fill ``record`` from one chat result (an ``AgentResult``-shaped object)."""
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
            id=str(sample["id"]),
            task_description=str(sample["question"]),
            expected_tools=list(WORKFLOW_TOOLS),
            stock_code=str(sample.get("stock_code") or ""),
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

    reply = str(getattr(result, "content", "") or "")
    if not getattr(result, "success", False) or not reply:
        record.error = f"turn: {getattr(result, 'error', None) or 'empty reply'}"[:200]
        return
    record.ok = True
    record.reply_chars = len(reply)
    record.cjk_ratio = reply_cjk_ratio(reply)
    if record.decision_asked:
        record.decision_type = parse_decision_line(reply)


def run_turn(executor: Any, source_registry: Any, sample: Mapping[str, Any], fixture: Mapping[str, Any],
             variant: str, repeat: int) -> ChatRecord:
    """Ask one sample question once through ``executor`` with replayed tools."""
    record = ChatRecord(sample_id=str(sample["id"]), variant=variant, repeat=repeat,
                        decision_asked=bool(sample.get("ask_decision")))
    off_fixture_calls: List[Dict[str, Any]] = []
    executor.backend.tool_registry = build_replay_registry(source_registry, fixture.get("tools", {}), off_fixture_calls)
    started = time.monotonic()
    try:
        result = executor.chat(
            build_message(sample),
            f"chat-language-eval-{uuid.uuid4().hex}",
            context=build_context(sample, fixture),
        )
    except Exception as exc:
        record.latency_ms = int((time.monotonic() - started) * 1000)
        record.error = f"turn: {exc}"[:200]
        return record
    record.latency_ms = int((time.monotonic() - started) * 1000)
    score_turn(record, result, sample, off_fixture_calls, int(getattr(executor, "max_steps", 10) or 10))
    return record


def run_variant(executor: Any, source_registry: Any, samples: Sequence[Mapping[str, Any]],
                fixtures: Mapping[str, Mapping[str, Any]], variant: str, repeats: int) -> List[ChatRecord]:
    records: List[ChatRecord] = []
    with activate(variant):
        for sample in samples:
            fixture = fixtures[normalize_key_value(sample["stock_code"])]
            for repeat in range(repeats):
                record = run_turn(executor, source_registry, sample, fixture, variant, repeat)
                records.append(record)
                print(
                    f"[{variant}] {sample['id']} #{repeat}: ok={record.ok} cjk={record.cjk_ratio} "
                    f"workflow={record.workflow_hit_rate} phase_order={record.phase_order_ok} "
                    f"decision={record.decision_type} off_fixture={record.off_fixture_calls} "
                    f"steps={record.total_steps}" + (f" error={record.error}" if record.error else ""),
                    flush=True,
                )
    executor.backend.tool_registry = source_registry
    return records


def _build_chat_executor() -> Any:
    """Build the production Agent Chat executor (lazy import so tests can monkeypatch this)."""
    from src.agent.chat_executor import AgentChatExecutor
    from src.agent.factory import build_agent_chat_executor
    from src.config import get_config

    executor = build_agent_chat_executor(get_config())
    backend = getattr(executor, "backend", None)
    if not isinstance(executor, AgentChatExecutor) or getattr(backend, "backend_id", None) != "litellm":
        raise RuntimeError(
            "this eval needs the single-agent LiteLLM chat backend "
            "(AGENT_ARCH=single and AGENT_BACKEND=auto or litellm)"
        )
    return executor


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Chat-prompt language eval: compare chat prompt variants")
    parser.add_argument("--fixtures", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--samples", type=Path, default=DEFAULT_SAMPLES)
    parser.add_argument("--sample", action="append", help="Only this sample id (repeatable)")
    parser.add_argument("--variant", action="append", help=f"Variant to run (repeatable); default {BASELINE_VARIANT}")
    parser.add_argument("--repeats", type=int, default=2, help="Turns per sample and variant (default 2)")
    parser.add_argument("--run", action="store_true", help="Call the LLM; without it only validate and plan")
    parser.add_argument("--max-turns", type=int, default=0, help="Refuse to run when the plan needs more turns")
    parser.add_argument("--english-threshold", type=float, default=0.05,
                        help="Max CJK share of the reply for it to count as English")
    parser.add_argument("--json-out", type=Path, help="Write records and report as JSON")
    args = parser.parse_args(argv)

    variants = args.variant or [BASELINE_VARIANT]
    unknown = [v for v in variants if v not in VARIANTS]
    if unknown or args.repeats < 1:
        parser.print_usage(sys.stderr)
        print(f"unknown variant(s): {unknown}; known: {sorted(VARIANTS)}" if unknown else "--repeats must be >= 1",
              file=sys.stderr)
        return 2

    # Keep the eval's conversation rows out of the real database.
    scratch = Path(tempfile.mkdtemp(prefix="chat-language-eval-"))
    os.environ["DATABASE_PATH"] = str(scratch / "eval.db")
    os.environ.setdefault("LOG_DIR", str(scratch / "logs"))

    samples = load_samples(args.samples, args.sample)
    fixtures = load_fixtures(args.fixtures)
    if not fixtures:
        print(f"no fixtures in {args.fixtures}; run capture_fixtures.py first", file=sys.stderr)
        return 1
    try:
        executor = _build_chat_executor()
    except Exception as exc:
        print(f"error: failed to build the chat executor: {exc}", file=sys.stderr)
        return 1
    source_registry = executor.backend.tool_registry
    from src.config import get_config

    problems = validate(samples, fixtures, source_registry.list_names(), get_config().report_language)
    for variant in variants:
        problems.extend(template_problems(variant))
    if problems:
        print("validation failed:", file=sys.stderr)
        for problem in problems:
            print(f"  {problem}", file=sys.stderr)
        return 1

    planned = len(samples) * len(variants) * args.repeats
    max_steps = int(getattr(executor, "max_steps", 10) or 10)
    print(f"{len(samples)} sample(s) valid; skills: legacy_default_prompt={executor.use_legacy_default_prompt}")
    print(f"plan: {len(variants)} variant(s) x {args.repeats} repeat(s) = {planned} chat turn(s), "
          f"at most {planned * max_steps} model call(s) (AGENT_MAX_STEPS={max_steps}, before transport retries)")
    if not args.run:
        print("validation only; pass --run --max-turns N to call the model")
        return 0
    if planned > args.max_turns:
        print(f"plan needs {planned} turns but --max-turns is {args.max_turns}; not running", file=sys.stderr)
        return 2
    llm_adapter = getattr(executor.backend, "llm_adapter", None)
    if llm_adapter is None or not llm_adapter.is_available:
        print("no LLM is configured (see docs/LLM_CONFIG_GUIDE.md)", file=sys.stderr)
        return 1

    records: List[ChatRecord] = []
    for variant in variants:
        records.extend(run_variant(executor, source_registry, samples, fixtures, variant, args.repeats))

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

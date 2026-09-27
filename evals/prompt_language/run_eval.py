#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Compare prompt variants on frozen analyzer inputs (prompt-language eval).

Replays the fixtures written by ``capture_fixtures.py`` through
``GeminiAnalyzer.analyze`` under each requested prompt variant, several times
each, and scores the model's *first* answer: integrity retries are disabled,
so JSON validity and missing fields are measured before any repair. The
report shows per-variant rates, the run-to-run noise floor, and per-sample
decision agreement against the baseline variant.

Without ``--run`` the script only validates the fixtures (the prompt rebuilt
from each fixture must match the hash recorded at capture) and prints the
planned number of model calls. With ``--run`` it calls the configured LLM and
refuses to start when the plan exceeds ``--max-calls``.

The eval is a reporter, not a gate. Exit codes: 0 = ran, 1 = fixture or
setup failure, 2 = usage error.

Usage:
    python evals/prompt_language/run_eval.py
    python evals/prompt_language/run_eval.py --run --repeats 3 --max-calls 90 --json-out report.json
    python evals/prompt_language/run_eval.py --run --variant current --variant english_base --max-calls 180
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from evals.prompt_language.capture_fixtures import build_prompt, prompt_sha256, resolve_prompt_name
from evals.prompt_language.metrics import (
    ResponseRecord,
    build_report,
    cjk_ratio,
    format_text_report,
    normalize_decision,
)
from evals.prompt_language.variants import BASELINE_VARIANT, VARIANTS, activate

EVAL_DIR = Path(__file__).resolve().parent
DEFAULT_FIXTURES = EVAL_DIR / "fixtures"


def load_fixtures(directory: Path, only: Optional[List[str]] = None) -> List[Dict[str, Any]]:
    fixtures = [
        json.loads(path.read_text(encoding="utf-8"))
        for path in sorted(directory.glob("*.json"))
    ]
    if only:
        wanted = set(only)
        fixtures = [f for f in fixtures if f["sample_id"] in wanted]
    return fixtures


def validate_fixtures(analyzer: Any, fixtures: List[Dict[str, Any]], report_language: str) -> List[str]:
    """Return problems that would make a replay differ from the captured production prompt."""
    problems: List[str] = []
    for fixture in fixtures:
        sample_id = fixture.get("sample_id", "?")
        if fixture.get("report_language") != report_language:
            problems.append(
                f"{sample_id}: captured with REPORT_LANGUAGE={fixture.get('report_language')}, "
                f"current is {report_language}"
            )
            continue
        with activate(BASELINE_VARIANT):
            prompt = build_prompt(analyzer, fixture, report_language)
        if prompt_sha256(prompt) != fixture.get("prompt_sha256"):
            problems.append(f"{sample_id}: rebuilt prompt does not match the captured hash (code or data drift)")
    return problems


def score_response(analyzer: Any, fixture: Dict[str, Any], record: ResponseRecord, raw: Optional[str]) -> None:
    """Fill ``record`` from one raw model answer without any repair step."""
    from src.analyzer import check_content_integrity
    from src.report_language import infer_decision_type_from_advice

    if not raw:
        return
    record.ok = True
    record.response_chars = len(raw)
    try:
        _json_text, data = analyzer._extract_analysis_json_object(raw)
    except Exception as exc:
        record.error = f"json: {exc}"[:200]
        return
    record.json_ok = True
    try:
        analyzer._validate_analysis_minimal_contract(data)
        record.contract_ok = True
    except Exception as exc:
        record.error = f"contract: {exc}"[:200]
    record.decision_type = normalize_decision(data.get("decision_type"))
    record.advice_decision = normalize_decision(
        infer_decision_type_from_advice(data.get("operation_advice"), default="")
    )
    score = data.get("sentiment_score")
    if isinstance(score, (int, float)) and not isinstance(score, bool):
        record.sentiment_score = float(score)
    record.cjk_ratio = cjk_ratio(data)
    parsed = analyzer._parse_response(raw, fixture["stock_code"], resolve_prompt_name(fixture["context"]))
    require_phase = isinstance(fixture["context"].get("market_phase_context"), dict)
    passed, missing = check_content_integrity(parsed, require_phase_decision=require_phase)
    record.integrity_ok = bool(passed)
    record.missing_fields = list(missing)


def run_variant(analyzer: Any, fixtures: List[Dict[str, Any]], variant: str, repeats: int) -> List[ResponseRecord]:
    records: List[ResponseRecord] = []
    with activate(variant):
        for fixture in fixtures:
            for repeat in range(repeats):
                record = ResponseRecord(sample_id=fixture["sample_id"], variant=variant, repeat=repeat)
                started = time.monotonic()
                try:
                    result = analyzer.analyze(
                        fixture["context"],
                        news_context=fixture.get("news_context"),
                        analysis_context_pack_summary=fixture.get("analysis_context_pack_summary"),
                    )
                    record.latency_ms = int((time.monotonic() - started) * 1000)
                    raw = getattr(result, "raw_response", None)
                    if not raw:
                        record.error = f"call: {getattr(result, 'error_message', None) or 'no response'}"[:200]
                    score_response(analyzer, fixture, record, raw)
                except Exception as exc:
                    record.latency_ms = int((time.monotonic() - started) * 1000)
                    record.error = f"call: {exc}"[:200]
                records.append(record)
                print(
                    f"[{variant}] {fixture['sample_id']} #{repeat}: "
                    f"json={record.json_ok} integrity={record.integrity_ok} "
                    f"decision={record.decision_type} score={record.sentiment_score} cjk={record.cjk_ratio}",
                    flush=True,
                )
    return records


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Prompt-language eval: compare prompt variants on frozen inputs")
    parser.add_argument("--fixtures", type=Path, default=DEFAULT_FIXTURES)
    parser.add_argument("--sample", action="append", help="Only this sample id (repeatable)")
    parser.add_argument("--variant", action="append", help=f"Variant to run (repeatable); default {BASELINE_VARIANT}")
    parser.add_argument("--repeats", type=int, default=3, help="Model calls per sample and variant (default 3)")
    parser.add_argument("--run", action="store_true", help="Call the LLM; without it only validate and plan")
    parser.add_argument("--max-calls", type=int, default=0, help="Refuse to run when the plan needs more calls")
    parser.add_argument("--english-threshold", type=float, default=0.05,
                        help="Max CJK share of text values for a response to count as English")
    parser.add_argument("--json-out", type=Path, help="Write records and report as JSON")
    args = parser.parse_args(argv)

    variants = args.variant or [BASELINE_VARIANT]
    unknown = [v for v in variants if v not in VARIANTS]
    if unknown or args.repeats < 1:
        parser.print_usage(sys.stderr)
        print(f"unknown variant(s): {unknown}; known: {sorted(VARIANTS)}" if unknown else "--repeats must be >= 1",
              file=sys.stderr)
        return 2

    from src.analyzer import GeminiAnalyzer
    from src.config import get_config

    config = get_config()
    config.report_integrity_enabled = False  # score the first answer, before any repair
    analyzer = GeminiAnalyzer(config=config)

    fixtures = load_fixtures(args.fixtures, args.sample)
    if not fixtures:
        print(f"no fixtures in {args.fixtures}; run capture_fixtures.py first", file=sys.stderr)
        return 1
    problems = validate_fixtures(analyzer, fixtures, config.report_language)
    if problems:
        print("fixture validation failed:", file=sys.stderr)
        for problem in problems:
            print(f"  {problem}", file=sys.stderr)
        return 1

    planned = len(fixtures) * len(variants) * args.repeats
    print(f"{len(fixtures)} fixture(s) valid; plan: {len(variants)} variant(s) x {args.repeats} repeat(s) = "
          f"{planned} model call(s) (before transport-level retries)")
    if not args.run:
        print("validation only; pass --run --max-calls N to call the model")
        return 0
    if planned > args.max_calls:
        print(f"plan needs {planned} calls but --max-calls is {args.max_calls}; not running", file=sys.stderr)
        return 2
    if not analyzer.is_available():
        print("no LLM is configured (see docs/LLM_CONFIG_GUIDE.md)", file=sys.stderr)
        return 1

    records: List[ResponseRecord] = []
    for variant in variants:
        records.extend(run_variant(analyzer, fixtures, variant, args.repeats))

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

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Capture frozen analyzer inputs for the prompt-language eval.

Runs the real data pipeline for each sample (quotes, history, chips,
fundamentals, news, context pack) and records exactly what
``GeminiAnalyzer.analyze`` receives, instead of calling the model. Replaying
these fixtures lets every prompt variant be scored on identical inputs.

The capture is a real data run: it needs network access to the market data
providers and uses whatever search providers the environment configures, so
run it in the same environment as production. No LLM is called and nothing
is sent to notification channels. History rows are written to a throwaway
database under the output directory, never to data/stock_analysis.db.

Each fixture is kept only when the prompt rebuilt from its JSON form is
byte-identical to the prompt built from the live objects, so a replay
reproduces the production prompt exactly (the prompt hash is stored and
re-checked by run_eval.py).

Usage:
    python evals/prompt_language/capture_fixtures.py
    python evals/prompt_language/capture_fixtures.py --sample cn_600519 --sample us_AAPL
    python evals/prompt_language/capture_fixtures.py --out evals/prompt_language/fixtures
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

EVAL_DIR = Path(__file__).resolve().parent
DEFAULT_SAMPLES = EVAL_DIR / "samples.json"
DEFAULT_OUT = EVAL_DIR / "fixtures"


def load_samples(path: Path, only: Optional[List[str]] = None) -> List[Dict[str, Any]]:
    samples = json.loads(path.read_text(encoding="utf-8"))
    if only:
        wanted = set(only)
        unknown = wanted - {s["id"] for s in samples}
        if unknown:
            raise SystemExit(f"unknown sample id(s): {', '.join(sorted(unknown))}")
        samples = [s for s in samples if s["id"] in wanted]
    return samples


def prompt_sha256(prompt: str) -> str:
    return hashlib.sha256(prompt.encode("utf-8")).hexdigest()


def resolve_prompt_name(context: Dict[str, Any]) -> str:
    """Stock name used when formatting the prompt; the same value is used for both builds."""
    code = str(context.get("code") or "")
    name = context.get("stock_name")
    realtime = context.get("realtime")
    if (not name or str(name).startswith("股票")) and isinstance(realtime, dict) and realtime.get("name"):
        name = realtime["name"]
    return str(name or code)


def build_prompt(analyzer: Any, payload: Dict[str, Any], report_language: str) -> str:
    return analyzer._format_prompt(
        payload["context"],
        resolve_prompt_name(payload["context"]),
        payload.get("news_context"),
        report_language=report_language,
        analysis_context_pack_summary=payload.get("analysis_context_pack_summary"),
    )


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Capture analyzer inputs for the prompt-language eval")
    parser.add_argument("--samples", type=Path, default=DEFAULT_SAMPLES)
    parser.add_argument("--sample", action="append", help="Capture only this sample id (repeatable)")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args(argv)

    args.out.mkdir(parents=True, exist_ok=True)
    scratch = Path(tempfile.mkdtemp(prefix="capture-", dir=args.out))
    # Keep capture side effects (history rows, logs) out of the real data directory.
    os.environ["DATABASE_PATH"] = str(scratch / "capture.db")
    os.environ.setdefault("LOG_DIR", str(scratch / "logs"))

    from src.analyzer import AnalysisResult, GeminiAnalyzer
    from src.config import get_config
    from src.core.pipeline import StockAnalysisPipeline

    config = get_config()
    # Force the classic analyzer path: the agent path never calls GeminiAnalyzer.analyze.
    config.agent_mode = False
    config.agent_skills = []
    report_language = config.report_language

    captured: Dict[str, Dict[str, Any]] = {}
    original_analyze = GeminiAnalyzer.analyze

    def capturing_analyze(self, context, news_context=None, progress_callback=None,
                          stream_progress_callback=None, analysis_context_pack_summary=None):
        payload = {
            "context": context,
            "news_context": news_context,
            "analysis_context_pack_summary": analysis_context_pack_summary,
        }
        live_prompt = build_prompt(self, payload, report_language)
        frozen = json.loads(json.dumps(payload, ensure_ascii=False, default=str))
        frozen_prompt = build_prompt(self, frozen, report_language)
        captured[str(context.get("code"))] = {
            "payload": frozen,
            "prompt_sha256": prompt_sha256(live_prompt),
            "roundtrip_identical": frozen_prompt == live_prompt,
        }
        return AnalysisResult(
            code=str(context.get("code") or ""),
            name=resolve_prompt_name(context),
            sentiment_score=50,
            trend_prediction="",
            operation_advice="",
            success=False,
            error_message="captured for prompt-language eval; model not called",
            report_language=report_language,
        )

    GeminiAnalyzer.analyze = capturing_analyze
    failures = 0
    try:
        pipeline = StockAnalysisPipeline(
            config=config,
            max_workers=1,
            query_source="prompt_language_eval",
            daily_market_context_allow_generate=False,
        )
        for sample in load_samples(args.samples, args.sample):
            code = sample["stock_code"]
            captured.clear()
            print(f"[capture] {sample['id']} ({code}) ...", flush=True)
            try:
                pipeline.process_single_stock(code, single_stock_notify=False)
            except Exception as exc:  # the eval must keep going past one bad symbol
                print(f"[capture] {sample['id']}: pipeline error: {exc}", flush=True)
            entry = next(iter(captured.values()), None)
            if entry is None:
                print(f"[capture] {sample['id']}: analyzer was not reached (data fetch failed?)", flush=True)
                failures += 1
                continue
            if not entry["roundtrip_identical"]:
                print(f"[capture] {sample['id']}: JSON round-trip changes the prompt; not saved", flush=True)
                failures += 1
                continue
            fixture = {
                "sample_id": sample["id"],
                "stock_code": code,
                "market": sample.get("market"),
                "captured_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "report_language": report_language,
                "prompt_sha256": entry["prompt_sha256"],
                **entry["payload"],
            }
            path = args.out / f"{sample['id']}.json"
            path.write_text(json.dumps(fixture, ensure_ascii=False, indent=1), encoding="utf-8")
            print(f"[capture] {sample['id']}: saved {path.name}", flush=True)
    finally:
        GeminiAnalyzer.analyze = original_analyze

    print(f"[capture] done: {failures} failure(s); throwaway data in {scratch}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())

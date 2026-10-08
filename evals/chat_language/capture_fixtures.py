#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Capture frozen tool outputs for the chat-prompt language eval.

For each stock in ``samples.json`` this calls the real Agent tools once with
their default arguments (quote, daily history, stock info, the technical
tools, the two search tools) plus ``get_market_indices`` for every supported
region, and records each result. ``run_eval.py`` replays these outputs, so
every prompt variant sees identical data whatever tools the model picks.

The capture is a real data run: it needs network access to the market data
providers and uses whatever search providers the environment configures (each
stock costs two search-tool calls). No LLM is called. Database writes go to a
throwaway database under the output directory, never to data/stock_analysis.db.

Tools that read saved DSA state (analysis context, backtests, portfolio) are
not captured; a model call to one is answered with a "no data" error and
counted as an off-fixture call.

Usage:
    python evals/chat_language/capture_fixtures.py
    python evals/chat_language/capture_fixtures.py --sample us_AAPL_analysis
"""

from __future__ import annotations

import argparse
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

# Stock tools captured with their default arguments; the search tools also get the stock name.
STOCK_TOOLS = (
    "get_realtime_quote",
    "get_daily_history",
    "get_stock_info",
    "analyze_trend",
    "calculate_ma",
    "get_volume_analysis",
    "analyze_pattern",
)
SEARCH_TOOLS = ("search_stock_news", "search_comprehensive_intel")
MARKET_REGIONS = ("us", "ca")


def load_samples(path: Path, only: Optional[List[str]] = None) -> List[Dict[str, Any]]:
    samples = json.loads(path.read_text(encoding="utf-8"))
    if only:
        wanted = set(only)
        unknown = wanted - {s["id"] for s in samples}
        if unknown:
            raise SystemExit(f"unknown sample id(s): {', '.join(sorted(unknown))}")
        samples = [s for s in samples if s["id"] in wanted]
    return samples


def fixture_filename(stock_code: str) -> str:
    return stock_code.strip().upper().replace(".", "_") + ".json"


def capture_call(registry: Any, tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
    """Run one live tool call and freeze its outcome the way the runner would see it."""
    from evals.chat_language.replay import captured_entry

    try:
        result = registry.execute(tool_name, **arguments)
    except Exception as exc:  # the runner turns a raised error into {"error": str(exc)}
        return captured_entry(error=str(exc), arguments=arguments)
    return captured_entry(result, arguments=arguments)


def _stock_name(entry: Dict[str, Any], fallback: str) -> str:
    result = entry.get("result")
    if entry.get("ok") and isinstance(result, dict) and result.get("name"):
        return str(result["name"])
    return fallback


def capture_stock(registry: Any, stock_code: str, market_entries: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    """Capture every replayable tool output for one stock."""
    from evals.chat_language.replay import replay_key

    tools: Dict[str, Dict[str, Any]] = {}
    for tool_name in STOCK_TOOLS:
        arguments = {"stock_code": stock_code}
        tools[replay_key(tool_name, arguments)] = capture_call(registry, tool_name, arguments)
    stock_name = _stock_name(tools[replay_key("get_stock_info", {"stock_code": stock_code})], stock_code)
    for tool_name in SEARCH_TOOLS:
        arguments = {"stock_code": stock_code, "stock_name": stock_name}
        tools[replay_key(tool_name, arguments)] = capture_call(registry, tool_name, arguments)
    tools.update(market_entries)
    return {"stock_name": stock_name, "tools": tools}


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Capture tool outputs for the chat-prompt language eval")
    parser.add_argument("--samples", type=Path, default=DEFAULT_SAMPLES)
    parser.add_argument("--sample", action="append", help="Capture only this sample's stock (repeatable)")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args(argv)

    samples = load_samples(args.samples, args.sample)
    args.out.mkdir(parents=True, exist_ok=True)
    scratch = Path(tempfile.mkdtemp(prefix="capture-", dir=args.out))
    # Keep capture side effects (cache rows, logs) out of the real data directory.
    os.environ["DATABASE_PATH"] = str(scratch / "capture.db")
    os.environ.setdefault("LOG_DIR", str(scratch / "logs"))

    from evals.chat_language.replay import replay_key
    from src.agent.factory import get_tool_registry
    from src.config import get_config

    config = get_config()
    registry = get_tool_registry(config)

    market_entries: Dict[str, Dict[str, Any]] = {}
    for region in MARKET_REGIONS:
        arguments = {"region": region}
        market_entries[replay_key("get_market_indices", arguments)] = capture_call(
            registry, "get_market_indices", arguments
        )

    stocks: Dict[str, str] = {}
    for sample in samples:
        stocks.setdefault(sample["stock_code"], sample.get("market") or "")

    failures = 0
    for stock_code, market in stocks.items():
        print(f"[capture] {stock_code} ...", flush=True)
        captured = capture_stock(registry, stock_code, market_entries)
        failed = sorted(key for key, entry in captured["tools"].items() if not entry.get("ok"))
        quote_key = replay_key("get_realtime_quote", {"stock_code": stock_code})
        if quote_key in failed:
            print(f"[capture] {stock_code}: no quote ({captured['tools'][quote_key].get('error')}); not saved",
                  flush=True)
            failures += 1
            continue
        fixture = {
            "stock_code": stock_code,
            "market": market,
            "stock_name": captured["stock_name"],
            "captured_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "report_language": config.report_language,
            "tools": captured["tools"],
        }
        path = args.out / fixture_filename(stock_code)
        path.write_text(json.dumps(fixture, ensure_ascii=False, indent=1), encoding="utf-8")
        note = f"; failed tools replay their error: {', '.join(failed)}" if failed else ""
        print(f"[capture] {stock_code}: saved {path.name}{note}", flush=True)

    print(f"[capture] done: {failures} failure(s); throwaway data in {scratch}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())

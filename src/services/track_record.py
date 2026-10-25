# -*- coding: utf-8 -*-
"""Forward-only track record: what DSA and a plain prompt said each day, scored later.

Every daily run appends one ledger line per stock and arm to an append-only JSONL file:

- ``dsa``: the final action the reports showed (the stored analysis, resolved by
  ``display_action_fields``), with its score.
- ``plain``: one call to the same model with the same snapshot (the stored
  ``enhanced_context`` and news) and a short neutral prompt. DSA's own rule-based score
  is removed from that snapshot, because it is part of the analysis layer under test.

The ledger is written before the outcome exists and is never rewritten, so scoring it
later cannot be replayed with hindsight. ``score_ledger`` measures each call against
holding the stock's market benchmark (``MarketSpec.benchmark_symbol``) from the next
session's open, because the run happens after the close.

This module is pure: no network, model or database access. ``scripts/track_record.py``
does the I/O. See docs/track-record.md.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from src.core.market_registry import get_market
from src.core.trading_calendar import get_market_for_stock
from src.schemas.decision_action import decision_bucket_for_action, display_action_fields
from src.schemas.decision_scale import extract_decision_guardrail_reason

LEDGER_SCHEMA_VERSION = 1
ARMS: Tuple[str, ...] = ("dsa", "plain")
DECISIONS: Tuple[str, ...] = ("buy", "hold", "sell")
# Trading days after the entry session.
HORIZONS: Tuple[int, ...] = (5, 20, 60)

# Outputs of DSA's own scoring (``StockTrendAnalyzer``) that the plain arm must not see.
_DSA_ONLY_TREND_KEYS = ("signal_score", "buy_signal", "signal_reasons")

PLAIN_PROMPT_TEMPLATE = """Analyze {name} ({code}) for the next 1-4 weeks, using only the data below.

Respond with exactly one JSON object and nothing else:
{{"decision": "buy" | "hold" | "sell", "score": integer 0-100 (50 is neutral, higher is more bullish), "confidence": "High" | "Medium" | "Low", "rationale": "one sentence"}}

## Market data (JSON)
{context_json}

## News
{news}
"""


def _as_mapping(value: Any) -> Dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
        except ValueError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def _score(value: Any) -> Optional[int]:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(number) or not 0 <= number <= 100:
        return None
    return int(round(number))


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def snapshot_from_record(record: Any) -> Tuple[Dict[str, Any], Optional[str]]:
    """Return the stored prompt context and news text of an analysis history row."""

    snapshot = _as_mapping(getattr(record, "context_snapshot", None))
    context = _as_mapping(snapshot.get("enhanced_context"))
    news = snapshot.get("news_content")
    if news is None:
        news = getattr(record, "news_content", None)
    return context, (str(news) if news else None)


def _entry_base(record: Any, context: Mapping[str, Any]) -> Optional[Dict[str, Any]]:
    code = str(getattr(record, "code", "") or context.get("code") or "").strip()
    as_of = str(context.get("date") or "").strip()[:10]
    if not code or not as_of:
        return None
    market = get_market_for_stock(code)
    spec = get_market(market)
    if spec is None or not spec.benchmark_symbol:
        return None
    today = _as_mapping(context.get("today"))
    return {
        "schema_version": LEDGER_SCHEMA_VERSION,
        "as_of": as_of,
        "code": code,
        "market": spec.code,
        "benchmark": spec.benchmark_symbol,
        "reference_close": today.get("close"),
        "recorded_at": _now_iso(),
        "source_report_id": getattr(record, "id", None),
    }


def dsa_entry(record: Any, *, model: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Ledger line for the action the reports showed for a stored analysis."""

    if str(getattr(record, "report_type", "") or "") == "market_review":
        return None
    context, _ = snapshot_from_record(record)
    base = _entry_base(record, context)
    if base is None:
        return None
    raw = _as_mapping(getattr(record, "raw_result", None))
    if raw.get("success") is False:
        return None
    fields = display_action_fields(
        operation_advice=raw.get("operation_advice") or getattr(record, "operation_advice", None),
        explicit_action=raw.get("action"),
        action_label=raw.get("action_label"),
        report_type=getattr(record, "report_type", None),
        sentiment_score=getattr(record, "sentiment_score", None),
        guardrail_reason=extract_decision_guardrail_reason(raw),
    )
    decision = decision_bucket_for_action(fields["action"])
    if decision is None:
        return None
    return {
        **base,
        "arm": "dsa",
        "action": fields["action"],
        "decision": decision,
        "score": _score(getattr(record, "sentiment_score", None)),
        "confidence": raw.get("confidence_level"),
        "model": model or raw.get("model_used"),
    }


def build_plain_prompt(code: str, name: Optional[str], context: Mapping[str, Any], news: Optional[str]) -> str:
    """The plain arm's request: the stored snapshot without DSA's own scoring outputs."""

    data = dict(context)
    trend = data.get("trend_analysis")
    if isinstance(trend, Mapping):
        data["trend_analysis"] = {k: v for k, v in trend.items() if k not in _DSA_ONLY_TREND_KEYS}
    return PLAIN_PROMPT_TEMPLATE.format(
        name=name or code,
        code=code,
        context_json=json.dumps(data, ensure_ascii=False, default=str, indent=1),
        news=news.strip() if news and news.strip() else "No news was retrieved.",
    )


def parse_plain_reply(text: Optional[str]) -> Optional[Dict[str, Any]]:
    """Return ``decision``/``score``/``confidence``/``rationale`` from a reply, or None."""

    if not text:
        return None
    decoder = json.JSONDecoder()
    start = text.find("{")
    while start != -1:
        try:
            value, _ = decoder.raw_decode(text, start)
        except ValueError:
            start = text.find("{", start + 1)
            continue
        if isinstance(value, dict):
            decision = str(value.get("decision") or "").strip().lower()
            score = _score(value.get("score"))
            if decision in DECISIONS and score is not None:
                return {
                    "decision": decision,
                    "score": score,
                    "confidence": value.get("confidence"),
                    "rationale": str(value.get("rationale") or "")[:500] or None,
                }
        start = text.find("{", start + 1)
    return None


def plain_entry(record: Any, reply: Mapping[str, Any], *, model: Optional[str]) -> Optional[Dict[str, Any]]:
    """Ledger line for a parsed plain-arm reply about a stored analysis."""

    context, _ = snapshot_from_record(record)
    base = _entry_base(record, context)
    if base is None:
        return None
    return {
        **base,
        "arm": "plain",
        "action": reply["decision"],
        "decision": reply["decision"],
        "score": reply["score"],
        "confidence": reply.get("confidence"),
        "rationale": reply.get("rationale"),
        "model": model,
    }


def ledger_key(entry: Mapping[str, Any]) -> Tuple[str, str, str]:
    return (str(entry.get("as_of")), str(entry.get("code")), str(entry.get("arm")))


def load_ledger(ledger_dir: Path) -> List[Dict[str, Any]]:
    entries: List[Dict[str, Any]] = []
    for path in sorted(Path(ledger_dir).glob("*.jsonl")):
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                entries.append(json.loads(line))
    return entries


def append_entries(ledger_dir: Path, entries: Iterable[Mapping[str, Any]]) -> int:
    """Append new lines to ``<ledger_dir>/<YYYY-MM>.jsonl``; a day already recorded is kept."""

    ledger_dir = Path(ledger_dir)
    ledger_dir.mkdir(parents=True, exist_ok=True)
    seen = {ledger_key(entry) for entry in load_ledger(ledger_dir)}
    written = 0
    for entry in entries:
        key = ledger_key(entry)
        if key in seen:
            continue
        seen.add(key)
        path = ledger_dir / f"{str(entry['as_of'])[:7]}.jsonl"
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, ensure_ascii=False, sort_keys=True) + "\n")
        written += 1
    return written


# ---------- scoring ----------

@dataclass(frozen=True)
class Bar:
    date: str  # YYYY-MM-DD
    open: float
    close: float


def forward_return(bars: Sequence[Bar], as_of: str, horizon: int) -> Optional[Tuple[str, str, float]]:
    """Return (entry date, exit date, return) from the next session's open after ``as_of``.

    The exit is the close of the ``horizon``-th session counted from the entry session.
    None until that session exists (the call is not mature yet).
    """

    ordered = sorted(bars, key=lambda bar: bar.date)
    entry_index = next((i for i, bar in enumerate(ordered) if bar.date > as_of), None)
    if entry_index is None:
        return None
    exit_index = entry_index + horizon - 1
    if exit_index >= len(ordered):
        return None
    entry, exit_ = ordered[entry_index], ordered[exit_index]
    if not entry.open or entry.open <= 0:
        return None
    return entry.date, exit_.date, exit_.close / entry.open - 1.0


def _window_return(bars: Sequence[Bar], entry_date: str, exit_date: str) -> Optional[float]:
    by_date = {bar.date: bar for bar in bars}
    entry, exit_ = by_date.get(entry_date), by_date.get(exit_date)
    if entry is None or exit_ is None or not entry.open or entry.open <= 0:
        return None
    return exit_.close / entry.open - 1.0


def _ranks(values: Sequence[float]) -> List[float]:
    order = sorted(range(len(values)), key=lambda i: values[i])
    ranks = [0.0] * len(values)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
            j += 1
        for k in range(i, j + 1):
            ranks[order[k]] = (i + j) / 2.0 + 1.0
        i = j + 1
    return ranks


def spearman(xs: Sequence[float], ys: Sequence[float]) -> Optional[float]:
    """Spearman rank correlation with average ranks for ties; None below 3 pairs or no spread."""

    if len(xs) != len(ys) or len(xs) < 3:
        return None
    rx, ry = _ranks(xs), _ranks(ys)
    mx, my = sum(rx) / len(rx), sum(ry) / len(ry)
    cov = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    vx = sum((a - mx) ** 2 for a in rx)
    vy = sum((b - my) ** 2 for b in ry)
    if vx == 0 or vy == 0:
        return None
    return cov / math.sqrt(vx * vy)


def scored_calls(
    entries: Iterable[Mapping[str, Any]],
    bars_by_symbol: Mapping[str, Sequence[Bar]],
    horizon: int,
) -> List[Dict[str, Any]]:
    """Mature calls at ``horizon`` with the stock return, benchmark return and excess."""

    rows: List[Dict[str, Any]] = []
    for entry in entries:
        stock_bars = bars_by_symbol.get(str(entry.get("code")))
        bench_bars = bars_by_symbol.get(str(entry.get("benchmark")))
        if not stock_bars or not bench_bars:
            continue
        window = forward_return(stock_bars, str(entry.get("as_of")), horizon)
        if window is None:
            continue
        entry_date, exit_date, stock_return = window
        bench_return = _window_return(bench_bars, entry_date, exit_date)
        if bench_return is None:
            continue
        rows.append({
            "arm": entry.get("arm"),
            "code": entry.get("code"),
            "as_of": entry.get("as_of"),
            "decision": entry.get("decision"),
            "score": entry.get("score"),
            "stock_return": stock_return,
            "benchmark_return": bench_return,
            "excess": stock_return - bench_return,
        })
    return rows


def _mean(values: Sequence[float]) -> Optional[float]:
    return sum(values) / len(values) if values else None


def summarize(rows: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    """Per-arm metrics for one horizon."""

    summary: Dict[str, Any] = {}
    for arm in ARMS:
        arm_rows = [row for row in rows if row["arm"] == arm]
        by_decision = {}
        for decision in DECISIONS:
            excess = [row["excess"] for row in arm_rows if row["decision"] == decision]
            by_decision[decision] = {"n": len(excess), "mean_excess": _mean(excess)}
        buys = [row["excess"] for row in arm_rows if row["decision"] == "buy"]
        sells = [row["excess"] for row in arm_rows if row["decision"] == "sell"]
        scored = [row for row in arm_rows if row.get("score") is not None]
        summary[arm] = {
            "n": len(arm_rows),
            "by_decision": by_decision,
            "buy_hit_rate": _mean([1.0 if e > 0 else 0.0 for e in buys]),
            "sell_hit_rate": _mean([1.0 if e < 0 else 0.0 for e in sells]),
            "score_excess_spearman": spearman(
                [float(row["score"]) for row in scored], [row["excess"] for row in scored]
            ),
            "mean_stock_return": _mean([row["stock_return"] for row in arm_rows]),
            "mean_benchmark_return": _mean([row["benchmark_return"] for row in arm_rows]),
        }
    return summary


def score_ledger(
    entries: Sequence[Mapping[str, Any]],
    bars_by_symbol: Mapping[str, Sequence[Bar]],
    horizons: Sequence[int] = HORIZONS,
) -> Dict[int, Dict[str, Any]]:
    return {h: summarize(scored_calls(entries, bars_by_symbol, h)) for h in horizons}


def _pct(value: Optional[float]) -> str:
    return "n/a" if value is None else f"{value * 100:+.2f}%"


def _num(value: Optional[float]) -> str:
    return "n/a" if value is None else f"{value:+.2f}"


def render_report(report: Mapping[int, Mapping[str, Any]], *, entries: Sequence[Mapping[str, Any]]) -> str:
    days = sorted({str(e.get("as_of")) for e in entries})
    lines = [
        "# Track record",
        "",
        f"Ledger: {len(entries)} calls over {len(days)} sessions"
        + (f" ({days[0]} to {days[-1]})." if days else "."),
        "Entry at the next session's open; excess return is the stock minus its market benchmark"
        " over the same window. A call counts only once its horizon has passed.",
        "",
    ]
    for horizon, summary in report.items():
        lines += [
            f"## {horizon} trading days",
            "",
            "| Arm | Mature calls | Buy n / mean excess | Hold n / mean excess | Sell n / mean excess"
            " | Buy hit rate | Sell hit rate | Score vs excess (Spearman) |",
            "| --- | --- | --- | --- | --- | --- | --- | --- |",
        ]
        for arm in ARMS:
            s = summary[arm]
            cells = [f"{s['by_decision'][d]['n']} / {_pct(s['by_decision'][d]['mean_excess'])}" for d in DECISIONS]
            lines.append(
                f"| {arm} | {s['n']} | {' | '.join(cells)} | {_pct(s['buy_hit_rate']).lstrip('+')}"
                f" | {_pct(s['sell_hit_rate']).lstrip('+')} | {_num(s['score_excess_spearman'])} |"
            )
        lines.append("")
    lines.append(
        "Small samples are noise: treat any difference between the arms as evidence only after"
        " several months of mature calls."
    )
    return "\n".join(lines) + "\n"

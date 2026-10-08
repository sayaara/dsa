# -*- coding: utf-8 -*-
"""Pure metrics for the chat-prompt language eval.

Every function here works on already-collected chat turns; nothing calls a
model or reads configuration, so the layer is unit-testable offline.

A *chat record* is one Agent Chat turn for one (sample, variant, repeat): the
final reply plus the tool-call log of the loop that produced it. Language is
measured on the reply text, tool behaviour against the four-phase workflow the
chat prompts prescribe, and the stance only on samples that ask the model to
end with a ``Decision: buy|hold|sell`` line.
"""

from __future__ import annotations

import re
import statistics
from collections import Counter
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Sequence

from evals.prompt_language.metrics import (
    compare_variants,
    cjk_ratio,
    normalize_decision,
    within_variant_noise,
)

# The workflow the chat prompts prescribe: quote and history first, then the
# trend indicators, then the news search, each phase in its own step.
WORKFLOW_PHASES: Dict[str, int] = {
    "get_realtime_quote": 1,
    "get_daily_history": 1,
    "analyze_trend": 2,
    "search_stock_news": 3,
}
WORKFLOW_TOOLS = tuple(WORKFLOW_PHASES)

DECISION_LINE_RE = re.compile(r"decision\s*[:：]\s*\**\s*(buy|hold|sell)\b", re.IGNORECASE)


@dataclass
class ChatRecord:
    """Measurements for one chat turn."""

    sample_id: str
    variant: str
    repeat: int
    ok: bool = False  # the turn ended with a non-empty final reply
    reply_chars: int = 0
    cjk_ratio: Optional[float] = None
    decision_type: Optional[str] = None  # stance from the "Decision:" line; only asked on decision samples
    decision_asked: bool = False
    tools_called: List[str] = field(default_factory=list)  # in call order
    workflow_hit_rate: Optional[float] = None  # share of the four workflow tools called
    missing_workflow_tools: List[str] = field(default_factory=list)
    phase_order_ok: Optional[bool] = None  # None when no workflow tool was called
    off_fixture_calls: int = 0  # calls the fixture could not answer (the model saw a "not captured" error)
    failed_calls: int = 0
    redundant_calls: int = 0
    total_steps: int = 0
    total_tokens: int = 0
    latency_ms: Optional[int] = None
    system_prompt_sha256: Optional[str] = None
    error: Optional[str] = None
    # Always None for chat turns; present so the prompt eval's comparison helpers apply unchanged.
    sentiment_score: Optional[float] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def parse_decision_line(reply: str) -> Optional[str]:
    """Return the stance from the last ``Decision: buy|hold|sell`` line of a reply, if any."""
    matches = DECISION_LINE_RE.findall(reply or "")
    return normalize_decision(matches[-1]) if matches else None


def reply_cjk_ratio(reply: str) -> float:
    """Share of CJK characters among all letters of the reply text."""
    return cjk_ratio(reply or "")


def phase_order_ok(tool_calls_log: Sequence[Mapping[str, Any]]) -> Optional[bool]:
    """Whether the workflow tools were called one phase per step, in phase order.

    Tools outside the workflow are ignored. Skipped phases are not judged here
    (``missing_workflow_tools`` reports them); merging two phases into one step
    or going back to an earlier phase is a violation.
    """
    phases_by_step: Dict[int, set] = {}
    for entry in tool_calls_log:
        phase = WORKFLOW_PHASES.get(str(entry.get("tool") or ""))
        if phase is None:
            continue
        try:
            step = int(entry.get("step") or 0)
        except (TypeError, ValueError):
            step = 0
        phases_by_step.setdefault(step, set()).add(phase)
    if not phases_by_step:
        return None
    previous = 0
    for step in sorted(phases_by_step):
        phases = phases_by_step[step]
        if len(phases) > 1:
            return False
        phase = next(iter(phases))
        if phase < previous:
            return False
        previous = phase
    return True


def _rate(values: Sequence[Optional[bool]]) -> Optional[float]:
    judged = [v for v in values if v is not None]
    if not judged:
        return None
    return round(sum(1 for v in judged if v) / len(judged), 4)


def _mean(values: Sequence[float]) -> Optional[float]:
    return round(statistics.fmean(values), 3) if values else None


def summarize_variant(records: Sequence[ChatRecord], *, english_threshold: float = 0.05) -> Dict[str, Any]:
    """Aggregate one variant's chat records."""
    answered = [r for r in records if r.ok]
    ratios = [r.cjk_ratio for r in answered if r.cjk_ratio is not None]
    hit_rates = [r.workflow_hit_rate for r in answered if r.workflow_hit_rate is not None]
    decisions = Counter(r.decision_type or "missing" for r in answered if r.decision_asked)
    missing_tools = Counter(t for r in answered for t in r.missing_workflow_tools)
    latencies = [r.latency_ms for r in records if r.latency_ms is not None]
    return {
        "turns": len(records),
        "failed_turns": len(records) - len(answered),
        "english_rate": (
            round(sum(1 for x in ratios if x <= english_threshold) / len(ratios), 4) if ratios else None
        ),
        "mean_cjk_ratio": _mean(ratios),
        "mean_workflow_hit_rate": _mean(hit_rates),
        "full_workflow_rate": _rate([not r.missing_workflow_tools for r in answered]),
        "phase_order_rate": _rate([r.phase_order_ok for r in answered]),
        "top_missing_tools": missing_tools.most_common(4),
        "decision_distribution": dict(sorted(decisions.items())),
        "mean_steps": _mean([float(r.total_steps) for r in answered]),
        "mean_reply_chars": _mean([float(r.reply_chars) for r in answered]),
        "off_fixture_calls": sum(r.off_fixture_calls for r in records),
        "failed_tool_calls": sum(r.failed_calls for r in records),
        "redundant_tool_calls": sum(r.redundant_calls for r in records),
        "mean_tokens": _mean([float(r.total_tokens) for r in answered if r.total_tokens]),
        "median_latency_ms": int(statistics.median(latencies)) if latencies else None,
        "system_prompts": sorted({r.system_prompt_sha256[:12] for r in records if r.system_prompt_sha256}),
    }


def build_report(records: Sequence[ChatRecord], *, baseline: str, english_threshold: float = 0.05) -> Dict[str, Any]:
    """Per-variant summaries, the stance noise floor, and comparisons to the baseline."""
    variants: Dict[str, List[ChatRecord]] = {}
    for record in records:
        variants.setdefault(record.variant, []).append(record)
    report: Dict[str, Any] = {"baseline": baseline, "variants": {}, "comparisons": {}}
    for name, variant_records in variants.items():
        report["variants"][name] = {
            "summary": summarize_variant(variant_records, english_threshold=english_threshold),
            "noise": {
                "decision_consistency": within_variant_noise(variant_records)["decision_consistency"],
            },
        }
    if baseline in variants:
        base_summary = report["variants"][baseline]["summary"]
        for name, variant_records in variants.items():
            if name == baseline:
                continue
            stance = compare_variants(variants[baseline], variant_records)
            summary = report["variants"][name]["summary"]
            report["comparisons"][name] = {
                "shared_samples": stance["shared_samples"],
                "decision_agreement": stance["decision_agreement"],
                "decision_flips": stance["decision_flips"],
                "english_rate_delta": _delta(summary["english_rate"], base_summary["english_rate"]),
                "full_workflow_rate_delta": _delta(summary["full_workflow_rate"], base_summary["full_workflow_rate"]),
                "phase_order_rate_delta": _delta(summary["phase_order_rate"], base_summary["phase_order_rate"]),
            }
    return report


def _delta(candidate: Optional[float], baseline: Optional[float]) -> Optional[float]:
    if candidate is None or baseline is None:
        return None
    return round(candidate - baseline, 4)


def format_text_report(report: Mapping[str, Any]) -> str:
    """Human-readable summary of ``build_report`` output."""
    lines = [f"Chat-prompt language eval (baseline: {report['baseline']})", ""]
    for name, block in report["variants"].items():
        s = block["summary"]
        lines.append(f"[{name}] turns={s['turns']} failed_turns={s['failed_turns']} system_prompts={s['system_prompts']}")
        lines.append(f"  english={s['english_rate']} mean_cjk_ratio={s['mean_cjk_ratio']}")
        lines.append(
            f"  workflow: hit_rate={s['mean_workflow_hit_rate']} full={s['full_workflow_rate']} "
            f"phase_order={s['phase_order_rate']} mean_steps={s['mean_steps']}"
        )
        lines.append(
            f"  tools: off_fixture={s['off_fixture_calls']} failed={s['failed_tool_calls']} "
            f"redundant={s['redundant_tool_calls']}"
        )
        if s["top_missing_tools"]:
            lines.append(f"  top_missing_tools={s['top_missing_tools']}")
        lines.append(
            f"  decisions={s['decision_distribution']} "
            f"noise: decision_consistency={block['noise']['decision_consistency']}"
        )
        lines.append(
            f"  mean_reply_chars={s['mean_reply_chars']} mean_tokens={s['mean_tokens']} "
            f"median_latency_ms={s['median_latency_ms']}"
        )
    for name, cmp in report["comparisons"].items():
        lines.append("")
        lines.append(f"[{name} vs {report['baseline']}] shared_samples={cmp['shared_samples']}")
        lines.append(
            f"  decision_agreement={cmp['decision_agreement']} english_rate_delta={cmp['english_rate_delta']} "
            f"full_workflow_rate_delta={cmp['full_workflow_rate_delta']} "
            f"phase_order_rate_delta={cmp['phase_order_rate_delta']}"
        )
        for flip in cmp["decision_flips"]:
            lines.append(f"  flip {flip['sample_id']}: {flip['baseline']} -> {flip['candidate']}")
    return "\n".join(lines)

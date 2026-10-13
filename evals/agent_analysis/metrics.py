# -*- coding: utf-8 -*-
"""Pure scoring for the agent analysis eval.

An agent answer is scored twice. The dashboard gets the prompt-language eval's
measurements (``evals.prompt_language.metrics``: JSON and contract validity,
report integrity, decision, score, English share, the noise floor and the
comparison against the baseline), so the agent and analyzer paths report on
one scale. The tool loop gets the trajectory measurements also used by the
chat eval: workflow tools hit, phase order, failed, redundant and off-fixture
calls, steps and tokens. Nothing here imports ``src`` or calls a model.
"""

from __future__ import annotations

import statistics
from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Sequence

from evals.prompt_language import metrics as prompt_metrics
from evals.prompt_language.metrics import ResponseRecord


@dataclass
class AgentRecord(ResponseRecord):
    """One agent analysis run: the dashboard measurements plus the tool trajectory."""

    tools_called: List[str] = field(default_factory=list)
    workflow_hit_rate: Optional[float] = None
    missing_workflow_tools: List[str] = field(default_factory=list)
    phase_order_ok: Optional[bool] = None
    failed_calls: int = 0
    redundant_calls: int = 0
    off_fixture_calls: int = 0
    total_steps: int = 0
    total_tokens: int = 0
    system_prompt_sha256: Optional[str] = None


def _mean(values: Sequence[float]) -> Optional[float]:
    return round(statistics.fmean(values), 4) if values else None


def _rate(flags: Sequence[Optional[bool]]) -> Optional[float]:
    known = [f for f in flags if f is not None]
    return round(sum(1 for f in known if f) / len(known), 4) if known else None


def summarize_trajectory(records: Sequence[AgentRecord]) -> Dict[str, Any]:
    """Aggregate the tool-loop measurements of one variant (runs that returned an answer)."""
    answered = [r for r in records if r.ok]
    missing_tools = Counter(t for r in answered for t in r.missing_workflow_tools)
    return {
        "mean_workflow_hit_rate": _mean([r.workflow_hit_rate for r in answered if r.workflow_hit_rate is not None]),
        "full_workflow_rate": _rate([not r.missing_workflow_tools for r in answered]),
        "phase_order_rate": _rate([r.phase_order_ok for r in answered]),
        "top_missing_tools": missing_tools.most_common(4),
        "mean_steps": _mean([float(r.total_steps) for r in answered]),
        "mean_tokens": _mean([float(r.total_tokens) for r in answered if r.total_tokens]),
        "off_fixture_calls": sum(r.off_fixture_calls for r in records),
        "failed_tool_calls": sum(r.failed_calls for r in records),
        "redundant_tool_calls": sum(r.redundant_calls for r in records),
        "system_prompts": sorted({r.system_prompt_sha256[:12] for r in records if r.system_prompt_sha256}),
    }


def build_report(records: Sequence[AgentRecord], *, baseline: str, english_threshold: float = 0.05) -> Dict[str, Any]:
    """The prompt-language report, with a ``trajectory`` block per variant."""
    report = prompt_metrics.build_report(records, baseline=baseline, english_threshold=english_threshold)
    for name in report["variants"]:
        report["variants"][name]["trajectory"] = summarize_trajectory([r for r in records if r.variant == name])
    return report


def format_text_report(report: Mapping[str, Any]) -> str:
    """Human-readable summary of ``build_report`` output."""
    text = prompt_metrics.format_text_report(report).replace("Prompt-language eval", "Agent analysis eval", 1)
    lines = [text, ""]
    for name, block in report["variants"].items():
        t = block["trajectory"]
        lines.append(
            f"[{name} trajectory] workflow_hit={t['mean_workflow_hit_rate']} full={t['full_workflow_rate']} "
            f"phase_order={t['phase_order_rate']} mean_steps={t['mean_steps']} mean_tokens={t['mean_tokens']}"
        )
        lines.append(
            f"  tools: off_fixture={t['off_fixture_calls']} failed={t['failed_tool_calls']} "
            f"redundant={t['redundant_tool_calls']} system_prompts={t['system_prompts']}"
        )
        if t["top_missing_tools"]:
            lines.append(f"  top_missing_tools={t['top_missing_tools']}")
    return "\n".join(lines)

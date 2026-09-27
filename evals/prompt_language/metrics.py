# -*- coding: utf-8 -*-
"""Pure metrics for the prompt-language eval.

Every function here works on already-collected responses; nothing calls a
model or reads configuration, so the layer is unit-testable offline.

A *response record* is one model answer for one (sample, variant, repeat).
The runner fills it from the analyzer's first raw response (integrity
retries and placeholder fill disabled), so a weak answer is measured as the
model produced it rather than after the pipeline repaired it.
"""

from __future__ import annotations

import re
import statistics
from collections import Counter
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence

CJK_RE = re.compile(r"[㐀-䶿一-鿿豈-﫿]")
LETTER_RE = re.compile(r"[A-Za-z㐀-䶿一-鿿豈-﫿]")

# Keys whose values may legitimately stay in the original script: the model is
# told to keep the listed company name when it is not confident of an English one.
DEFAULT_CJK_EXEMPT_KEYS = frozenset({"stock_name"})

DECISIONS = ("buy", "hold", "sell")


@dataclass
class ResponseRecord:
    """Measurements for one model answer."""

    sample_id: str
    variant: str
    repeat: int
    ok: bool = False  # the model call returned text at all
    json_ok: bool = False  # a single valid analysis JSON object was extracted
    contract_ok: bool = False  # the minimal analysis contract validated
    integrity_ok: bool = False  # required report fields present without repair
    missing_fields: List[str] = field(default_factory=list)
    decision_type: Optional[str] = None
    advice_decision: Optional[str] = None  # decision inferred from operation_advice
    sentiment_score: Optional[float] = None
    cjk_ratio: Optional[float] = None
    response_chars: int = 0
    latency_ms: Optional[int] = None
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def iter_text_values(data: Any, exempt_keys: Iterable[str] = DEFAULT_CJK_EXEMPT_KEYS) -> Iterable[str]:
    """Yield every human-readable string value in a parsed JSON tree, skipping exempt keys."""
    exempt = set(exempt_keys)
    stack: List[Any] = [data]
    while stack:
        node = stack.pop()
        if isinstance(node, Mapping):
            for key, value in node.items():
                if key in exempt:
                    continue
                stack.append(value)
        elif isinstance(node, (list, tuple)):
            stack.extend(node)
        elif isinstance(node, str):
            yield node


def cjk_ratio(data: Any, exempt_keys: Iterable[str] = DEFAULT_CJK_EXEMPT_KEYS) -> float:
    """Share of CJK characters among all letters in the response's text values (0.0 when empty)."""
    cjk = 0
    letters = 0
    for text in iter_text_values(data, exempt_keys):
        cjk += len(CJK_RE.findall(text))
        letters += len(LETTER_RE.findall(text))
    return round(cjk / letters, 4) if letters else 0.0


def normalize_decision(value: Any) -> Optional[str]:
    text = str(value or "").strip().lower()
    return text if text in DECISIONS else None


def _rate(records: Sequence[ResponseRecord], attr: str) -> Optional[float]:
    if not records:
        return None
    return round(sum(1 for r in records if getattr(r, attr)) / len(records), 4)


def _mean(values: Sequence[float]) -> Optional[float]:
    return round(statistics.fmean(values), 3) if values else None


def summarize_variant(records: Sequence[ResponseRecord], *, english_threshold: float = 0.05) -> Dict[str, Any]:
    """Aggregate one variant's records into rates, distributions and score statistics."""
    scored = [r.sentiment_score for r in records if r.sentiment_score is not None]
    ratios = [r.cjk_ratio for r in records if r.cjk_ratio is not None]
    decisions = Counter(r.decision_type or "invalid" for r in records if r.ok)
    missing = Counter(f for r in records for f in r.missing_fields)
    latencies = [r.latency_ms for r in records if r.latency_ms is not None]
    return {
        "responses": len(records),
        "call_errors": sum(1 for r in records if not r.ok),
        "json_ok_rate": _rate(records, "json_ok"),
        "contract_ok_rate": _rate(records, "contract_ok"),
        "integrity_ok_rate": _rate(records, "integrity_ok"),
        "english_rate": (
            round(sum(1 for x in ratios if x <= english_threshold) / len(ratios), 4) if ratios else None
        ),
        "mean_cjk_ratio": _mean(ratios),
        "decision_distribution": dict(sorted(decisions.items())),
        "advice_decision_agreement": _advice_agreement(records),
        "mean_sentiment_score": _mean(scored),
        "top_missing_fields": missing.most_common(5),
        "median_latency_ms": int(statistics.median(latencies)) if latencies else None,
    }


def _advice_agreement(records: Sequence[ResponseRecord]) -> Optional[float]:
    """How often operation_advice implies the same decision as decision_type (internal consistency)."""
    pairs = [(r.decision_type, r.advice_decision) for r in records if r.decision_type and r.advice_decision]
    if not pairs:
        return None
    return round(sum(1 for a, b in pairs if a == b) / len(pairs), 4)


def _by_sample(records: Sequence[ResponseRecord]) -> Dict[str, List[ResponseRecord]]:
    grouped: Dict[str, List[ResponseRecord]] = {}
    for record in records:
        grouped.setdefault(record.sample_id, []).append(record)
    return grouped


def _modal_decision(records: Sequence[ResponseRecord]) -> Optional[str]:
    decisions = [r.decision_type for r in records if r.decision_type]
    if not decisions:
        return None
    counts = Counter(decisions).most_common()
    # A tie has no modal decision; treat it as undecided rather than picking arbitrarily.
    if len(counts) > 1 and counts[0][1] == counts[1][1]:
        return None
    return counts[0][0]


def within_variant_noise(records: Sequence[ResponseRecord]) -> Dict[str, Optional[float]]:
    """Run-to-run variation inside one variant: the floor any cross-variant difference must beat."""
    consistency: List[float] = []
    spreads: List[float] = []
    for sample_records in _by_sample(records).values():
        decisions = [r.decision_type for r in sample_records if r.decision_type]
        if len(decisions) >= 2:
            consistency.append(Counter(decisions).most_common(1)[0][1] / len(decisions))
        scores = [r.sentiment_score for r in sample_records if r.sentiment_score is not None]
        if len(scores) >= 2:
            spreads.append(statistics.pstdev(scores))
    return {
        "decision_consistency": _mean(consistency),
        "mean_score_stdev": _mean(spreads),
    }


def compare_variants(baseline: Sequence[ResponseRecord], candidate: Sequence[ResponseRecord]) -> Dict[str, Any]:
    """Per-sample agreement between two variants on the same fixtures."""
    base = _by_sample(baseline)
    cand = _by_sample(candidate)
    shared = sorted(set(base) & set(cand))
    agree = 0
    compared = 0
    score_deltas: List[float] = []
    flips: List[Dict[str, Any]] = []
    for sample_id in shared:
        b_decision = _modal_decision(base[sample_id])
        c_decision = _modal_decision(cand[sample_id])
        if b_decision and c_decision:
            compared += 1
            if b_decision == c_decision:
                agree += 1
            else:
                flips.append({"sample_id": sample_id, "baseline": b_decision, "candidate": c_decision})
        b_scores = [r.sentiment_score for r in base[sample_id] if r.sentiment_score is not None]
        c_scores = [r.sentiment_score for r in cand[sample_id] if r.sentiment_score is not None]
        if b_scores and c_scores:
            score_deltas.append(statistics.fmean(c_scores) - statistics.fmean(b_scores))
    return {
        "shared_samples": len(shared),
        "decision_agreement": round(agree / compared, 4) if compared else None,
        "decision_flips": flips,
        "mean_score_delta": _mean(score_deltas),
        "mean_abs_score_delta": _mean([abs(d) for d in score_deltas]),
    }


def build_report(records: Sequence[ResponseRecord], *, baseline: str, english_threshold: float = 0.05) -> Dict[str, Any]:
    """Assemble the structured report: per-variant summaries, noise floors and comparisons to the baseline."""
    variants: Dict[str, List[ResponseRecord]] = {}
    for record in records:
        variants.setdefault(record.variant, []).append(record)
    report: Dict[str, Any] = {"baseline": baseline, "variants": {}, "comparisons": {}}
    for name, variant_records in variants.items():
        report["variants"][name] = {
            "summary": summarize_variant(variant_records, english_threshold=english_threshold),
            "noise": within_variant_noise(variant_records),
        }
    if baseline in variants:
        for name, variant_records in variants.items():
            if name != baseline:
                report["comparisons"][name] = compare_variants(variants[baseline], variant_records)
    return report


def format_text_report(report: Mapping[str, Any]) -> str:
    """Human-readable summary of ``build_report`` output."""
    lines = [f"Prompt-language eval (baseline: {report['baseline']})", ""]
    for name, block in report["variants"].items():
        s = block["summary"]
        n = block["noise"]
        lines.append(f"[{name}] responses={s['responses']} call_errors={s['call_errors']}")
        lines.append(
            f"  json_ok={s['json_ok_rate']} contract_ok={s['contract_ok_rate']} "
            f"integrity_ok={s['integrity_ok_rate']} english={s['english_rate']} "
            f"mean_cjk_ratio={s['mean_cjk_ratio']}"
        )
        lines.append(
            f"  decisions={s['decision_distribution']} advice_agreement={s['advice_decision_agreement']} "
            f"mean_score={s['mean_sentiment_score']} median_latency_ms={s['median_latency_ms']}"
        )
        lines.append(
            f"  noise: decision_consistency={n['decision_consistency']} score_stdev={n['mean_score_stdev']}"
        )
        if s["top_missing_fields"]:
            lines.append(f"  top_missing_fields={s['top_missing_fields']}")
    for name, cmp in report["comparisons"].items():
        lines.append("")
        lines.append(f"[{name} vs {report['baseline']}] shared_samples={cmp['shared_samples']}")
        lines.append(
            f"  decision_agreement={cmp['decision_agreement']} mean_score_delta={cmp['mean_score_delta']} "
            f"mean_abs_score_delta={cmp['mean_abs_score_delta']}"
        )
        for flip in cmp["decision_flips"]:
            lines.append(f"  flip {flip['sample_id']}: {flip['baseline']} -> {flip['candidate']}")
    return "\n".join(lines)

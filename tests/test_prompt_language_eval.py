# -*- coding: utf-8 -*-
"""Offline tests for the prompt-language eval (metrics, scoring, fixture checks, runner guards)."""

from __future__ import annotations

import json
from contextlib import contextmanager
from pathlib import Path

import pytest

from evals.prompt_language import capture_fixtures, run_eval, variants
from evals.prompt_language.metrics import (
    ResponseRecord,
    build_report,
    cjk_ratio,
    compare_variants,
    format_text_report,
    summarize_variant,
    within_variant_noise,
)
from src.analyzer import GeminiAnalyzer


def _record(sample_id, variant, repeat, decision, score, **extra):
    base = dict(ok=True, json_ok=True, contract_ok=True, integrity_ok=True, cjk_ratio=0.0)
    base.update(extra)
    return ResponseRecord(sample_id=sample_id, variant=variant, repeat=repeat,
                          decision_type=decision, sentiment_score=score, **base)


@pytest.fixture
def restore_config(monkeypatch):
    """run_eval.main() switches off integrity retries on the config singleton; undo it after the test."""
    from src.config import get_config

    config = get_config()
    monkeypatch.setattr(config, "report_integrity_enabled", config.report_integrity_enabled)
    return config


def test_cjk_ratio_ignores_exempt_stock_name_and_counts_nested_values() -> None:
    data = {
        "stock_name": "贵州茅台",
        "analysis_summary": "Trend is up",
        "dashboard": {"core_conclusion": {"one_sentence": "持有"}},
    }
    # "Trend is up" -> 9 letters, "持有" -> 2 CJK; stock_name is exempt.
    assert cjk_ratio(data) == round(2 / 11, 4)
    assert cjk_ratio({"stock_name": "贵州茅台"}) == 0.0


def test_summarize_variant_rates_and_distribution() -> None:
    records = [
        _record("a", "v", 0, "buy", 70, advice_decision="buy"),
        _record("a", "v", 1, "hold", 50, advice_decision="buy", integrity_ok=False, missing_fields=["x"]),
        ResponseRecord(sample_id="b", variant="v", repeat=0, error="call: timeout"),
    ]
    summary = summarize_variant(records)
    assert summary["responses"] == 3
    assert summary["call_errors"] == 1
    assert summary["integrity_ok_rate"] == round(1 / 3, 4)
    assert summary["decision_distribution"] == {"buy": 1, "hold": 1}
    assert summary["advice_decision_agreement"] == 0.5
    assert summary["mean_sentiment_score"] == 60.0
    assert summary["top_missing_fields"] == [("x", 1)]


def test_noise_and_comparison_use_modal_decisions() -> None:
    base = [_record("a", "current", i, d, s) for i, (d, s) in enumerate([("buy", 70), ("buy", 72), ("hold", 68)])]
    base += [_record("b", "current", i, "sell", 30) for i in range(3)]
    cand = [_record("a", "english", i, "buy", 74) for i in range(3)]
    cand += [_record("b", "english", i, "hold", 45) for i in range(3)]

    noise = within_variant_noise(base)
    assert noise["decision_consistency"] == round((2 / 3 + 1.0) / 2, 3)

    cmp = compare_variants(base, cand)
    assert cmp["shared_samples"] == 2
    assert cmp["decision_agreement"] == 0.5
    assert cmp["decision_flips"] == [{"sample_id": "b", "baseline": "sell", "candidate": "hold"}]

    report = build_report(base + cand, baseline="current")
    assert set(report["comparisons"]) == {"english"}
    text = format_text_report(report)
    assert "flip b: sell -> hold" in text


def test_tied_decisions_have_no_modal_decision() -> None:
    base = [_record("a", "current", 0, "buy", 60), _record("a", "current", 1, "hold", 50)]
    cand = [_record("a", "english", 0, "buy", 60)]
    assert compare_variants(base, cand)["decision_agreement"] is None


def test_score_response_measures_first_answer_without_repair() -> None:
    analyzer = GeminiAnalyzer()
    fixture = {"stock_code": "600519", "context": {"code": "600519", "stock_name": "贵州茅台"}}
    raw = json.dumps({
        "stock_name": "贵州茅台",
        "sentiment_score": 72,
        "trend_prediction": "Bullish",
        "operation_advice": "Buy",
        "decision_type": "buy",
        "analysis_summary": "Momentum is improving",
    })
    record = ResponseRecord(sample_id="cn_600519", variant="current", repeat=0)
    run_eval.score_response(analyzer, fixture, record, raw)
    assert record.ok and record.json_ok and record.contract_ok
    assert record.decision_type == "buy"
    assert record.advice_decision == "buy"
    assert record.sentiment_score == 72.0
    assert record.cjk_ratio == 0.0
    # No dashboard in the answer, so integrity fails and the missing fields are reported, not filled.
    assert record.integrity_ok is False
    assert record.missing_fields


def test_score_response_flags_non_json_answer() -> None:
    record = ResponseRecord(sample_id="x", variant="current", repeat=0)
    run_eval.score_response(GeminiAnalyzer(), {"stock_code": "X", "context": {}}, record, "not json at all")
    assert record.ok is True
    assert record.json_ok is False
    assert record.error and record.error.startswith("json:")


def test_validate_fixtures_detects_prompt_drift() -> None:
    analyzer = GeminiAnalyzer()
    fixture = {
        "sample_id": "cn_600519",
        "stock_code": "600519",
        "report_language": "en",
        "context": {"code": "600519", "stock_name": "贵州茅台"},
        "news_context": None,
        "analysis_context_pack_summary": None,
    }
    fixture["prompt_sha256"] = capture_fixtures.prompt_sha256(
        capture_fixtures.build_prompt(analyzer, fixture, "en")
    )
    assert run_eval.validate_fixtures(analyzer, [fixture], "en") == []
    assert run_eval.validate_fixtures(analyzer, [dict(fixture, prompt_sha256="0" * 64)], "en")
    assert run_eval.validate_fixtures(analyzer, [fixture], "zh")


def test_activate_rejects_unknown_variant_and_register_is_unique() -> None:
    with pytest.raises(KeyError):
        with variants.activate("does_not_exist"):
            pass

    @contextmanager
    def _noop():
        yield

    name = "test_only_variant"
    variants.register_variant(name, _noop)
    try:
        with pytest.raises(ValueError):
            variants.register_variant(name, _noop)
        with variants.activate(name):
            pass
    finally:
        variants.VARIANTS.pop(name, None)


def test_runner_without_run_flag_never_calls_the_model(tmp_path: Path, monkeypatch, restore_config) -> None:
    analyzer_calls = []
    monkeypatch.setattr(GeminiAnalyzer, "analyze", lambda self, *a, **k: analyzer_calls.append(a))
    monkeypatch.setattr(run_eval, "validate_fixtures", lambda *a, **k: [])
    (tmp_path / "cn_600519.json").write_text(json.dumps({"sample_id": "cn_600519"}), encoding="utf-8")

    assert run_eval.main(["--fixtures", str(tmp_path)]) == 0
    assert run_eval.main(["--fixtures", str(tmp_path), "--run", "--max-calls", "1"]) == 2
    assert analyzer_calls == []


def test_runner_rejects_unknown_variant(tmp_path: Path, restore_config) -> None:
    assert run_eval.main(["--fixtures", str(tmp_path), "--variant", "nope"]) == 2


def test_capture_samples_cover_three_markets() -> None:
    samples = capture_fixtures.load_samples(capture_fixtures.DEFAULT_SAMPLES)
    assert len({s["id"] for s in samples}) == len(samples) == 30
    assert {s["market"] for s in samples} == {"ca", "hk", "us"}


def test_english_variants_replace_only_the_default_prompt() -> None:
    analyzer = GeminiAnalyzer.__new__(GeminiAnalyzer)
    analyzer._get_skill_prompt_sections = lambda: ("", "", True)  # legacy default prompt path
    rule = "exactly one JSON object"

    baseline = analyzer._get_analysis_system_prompt("en", "AAPL")
    with variants.activate("english_base"):
        english = analyzer._get_analysis_system_prompt("en", "AAPL")
    with variants.activate("english_base_strict"):
        strict = analyzer._get_analysis_system_prompt("en", "AAPL")

    assert cjk_ratio(baseline) > 0
    assert cjk_ratio(english) == 0
    assert cjk_ratio(strict) == 0
    assert rule not in english
    assert rule in strict
    assert "## Output Language (highest priority)" in english
    # The variant restores the production prompt on exit.
    assert analyzer._get_analysis_system_prompt("en", "AAPL") == baseline


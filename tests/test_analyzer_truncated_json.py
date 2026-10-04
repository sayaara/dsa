# -*- coding: utf-8 -*-
"""Truncated analysis replies and the model-aware output-token budget."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from src.analyzer import (
    ANALYSIS_MAX_OUTPUT_TOKENS_CEILING,
    ANALYSIS_MAX_OUTPUT_TOKENS_DEFAULT,
    GeminiAnalyzer,
    is_truncated_json_text,
)
from src.llm.generation_backend import GenerationError


def _analyzer() -> GeminiAnalyzer:
    with patch.object(GeminiAnalyzer, "_init_litellm", return_value=None):
        return GeminiAnalyzer()


@pytest.mark.parametrize(
    "text",
    [
        '```json\n{\n  "stock_name": "Tesla",\n  "analysis_summary": "cut of',
        '{"a": {"b": 1}, "c": [1, 2',
        '```json\n{"a": "text with a \\" quote and { brace',
    ],
)
def test_cut_off_json_is_detected(text: str) -> None:
    assert is_truncated_json_text(text) is True


@pytest.mark.parametrize(
    "text",
    [
        '```json\n{"a": 1}\n```',
        '{"a": {"b": "}"}}',
        'Here is the report: {"a": 1',
        "no json at all",
        "",
        None,
        '```json\n{"a": 1}',
    ],
)
def test_complete_or_unrelated_text_is_not_truncated(text) -> None:
    assert is_truncated_json_text(text) is False


def test_truncated_reply_gets_its_own_reason_instead_of_ambiguous_json() -> None:
    analyzer = _analyzer()
    text = '```json\n{\n  "stock_name": "Tesla",\n  "sentiment_score": 50,\n  "volume_analysis": "'

    with pytest.raises(ValueError, match="truncated_json"):
        analyzer._extract_analysis_json_object(text)
    with pytest.raises(GenerationError) as excinfo:
        analyzer._validate_json_response(text)

    assert "truncated_json" in str(excinfo.value.details) or "cut off" in str(excinfo.value)


def test_two_fences_stay_ambiguous() -> None:
    analyzer = _analyzer()
    with pytest.raises(ValueError, match="ambiguous_json"):
        analyzer._extract_analysis_json_object('```json\n{"a": 1}\n```\n```json\n{"a": 2}\n```')


def _config(model, fallbacks=()):
    return SimpleNamespace(litellm_model=model, litellm_fallback_models=list(fallbacks))


def _limits(table):
    def _info(model):
        if model not in table:
            raise KeyError(model)
        return {"max_output_tokens": table[model]}

    return _info


@pytest.mark.parametrize(
    "table, model, fallbacks, expected",
    [
        ({"big": 128000}, "big", [], ANALYSIS_MAX_OUTPUT_TOKENS_CEILING),
        ({"big": 128000, "mid": 12000}, "big", ["mid"], 12000),
        ({"big": 128000, "small": 8192}, "big", ["small"], ANALYSIS_MAX_OUTPUT_TOKENS_DEFAULT),
        ({"tiny": 4096}, "tiny", [], ANALYSIS_MAX_OUTPUT_TOKENS_DEFAULT),
        ({"big": 128000}, "big", ["unknown"], ANALYSIS_MAX_OUTPUT_TOKENS_DEFAULT),
        ({}, "unknown", [], ANALYSIS_MAX_OUTPUT_TOKENS_DEFAULT),
        ({}, "", [], ANALYSIS_MAX_OUTPUT_TOKENS_DEFAULT),
    ],
)
def test_output_budget_is_raised_only_when_every_model_allows_it(table, model, fallbacks, expected) -> None:
    analyzer = _analyzer()
    with patch("src.analyzer.litellm.get_model_info", side_effect=_limits(table)):
        assert analyzer._resolve_analysis_max_output_tokens(_config(model, fallbacks)) == expected


# --- one retry after a truncated reply -----------------------------------------------------------


def _analyze_with(call_results, *, model="anthropic/claude-sonnet-5-5", limits=None):
    from src.analyzer import AnalysisResult, _AllModelsFailedError  # noqa: F401

    analyzer = _analyzer()
    analyzer._config_override = SimpleNamespace(
        gemini_request_delay=0,
        report_language="en",
        litellm_model=model,
        litellm_fallback_models=[],
        llm_temperature=0.2,
        report_integrity_enabled=False,
        report_integrity_retry=0,
    )
    parsed = AnalysisResult(
        code="AAPL", name="Apple", sentiment_score=50, trend_prediction="Sideways",
        operation_advice="Hold", analysis_summary="ok",
    )
    seen_budgets = []

    def _fake_call(prompt, generation_config, **kwargs):
        seen_budgets.append(generation_config["max_output_tokens"])
        item = call_results[len(seen_budgets) - 1]
        if isinstance(item, BaseException):
            raise item
        return item

    table = limits if limits is not None else {model: 128000}
    with patch.object(analyzer, "is_available", return_value=True), \
         patch.object(analyzer, "_get_analysis_system_prompt", return_value="system"), \
         patch.object(analyzer, "_format_prompt", return_value="prompt"), \
         patch.object(analyzer, "_call_litellm", side_effect=_fake_call), \
         patch.object(analyzer, "_parse_response", return_value=parsed) as parse, \
         patch.object(analyzer, "_build_market_snapshot", return_value={}), \
         patch("src.analyzer.litellm.get_model_info", side_effect=_limits(table)), \
         patch("src.analyzer.persist_llm_usage"):
        result = analyzer.analyze({"code": "AAPL", "stock_name": "Apple"})
    return result, seen_budgets, parse


_TRUNCATED = '```json\n{"stock_name": "Apple", "analysis_summary": "cut of'
_USAGE = {"prompt_tokens": 1, "completion_tokens": 2, "total_tokens": 3}


def _failed(text):
    from src.analyzer import _AllModelsFailedError

    return _AllModelsFailedError("invalid", last_response_text=text, last_model="m", last_usage=_USAGE)


def test_truncated_reply_is_retried_once_with_a_larger_budget() -> None:
    result, budgets, parse = _analyze_with([_failed(_TRUNCATED), ('{"ok": 1}', "m", _USAGE)])

    assert budgets == [16384, 32768]
    assert parse.call_args[0][0] == '{"ok": 1}'
    assert result.success


def test_truncated_reply_retries_at_the_same_budget_when_the_models_cannot_go_higher() -> None:
    _result, budgets, parse = _analyze_with(
        [_failed(_TRUNCATED), ('{"ok": 1}', "m", _USAGE)],
        model="deepseek/deepseek-chat",
        limits={"deepseek/deepseek-chat": 8192},
    )

    assert budgets == [8192, 8192]
    assert parse.call_args[0][0] == '{"ok": 1}'


def test_only_one_retry_even_if_the_second_reply_is_truncated_again() -> None:
    _result, budgets, parse = _analyze_with([_failed(_TRUNCATED), _failed(_TRUNCATED + " more")])

    assert budgets == [16384, 32768]
    assert parse.call_args[0][0] == _TRUNCATED + " more"


def test_failed_retry_falls_back_to_the_truncated_reply() -> None:
    for failure in (RuntimeError("HTTP 400: max_tokens too large"), _failed(None)):
        _result, budgets, parse = _analyze_with([_failed(_TRUNCATED), failure])

        assert budgets == [16384, 32768]
        assert parse.call_args[0][0] == _TRUNCATED


def test_non_truncated_invalid_reply_is_not_retried() -> None:
    _result, budgets, parse = _analyze_with([_failed("I cannot provide JSON for this request.")])

    assert budgets == [16384]
    assert parse.call_args[0][0] == "I cannot provide JSON for this request."


# --- ANALYSIS_MAX_OUTPUT_TOKENS (explicit budget) -------------------------------------------------


def _config_with(explicit, model="big", fallbacks=()):
    return SimpleNamespace(
        litellm_model=model,
        litellm_fallback_models=list(fallbacks),
        analysis_max_output_tokens=explicit,
    )


@pytest.mark.parametrize(
    "explicit, table, model, fallbacks, expected",
    [
        (12000, {"big": 128000}, "big", [], 12000),  # used as is, even below the automatic ceiling
        (100000, {"big": 128000}, "big", [], 100000),  # may exceed the automatic ceiling
        (100000, {"big": 128000, "small": 16384}, "big", ["small"], 16384),  # capped to the smallest known limit
        (20000, {"ds": 8192}, "ds", [], 8192),  # capped to a known low limit
        (20000, {}, "unknown", [], 20000),  # limit unknown: trusted
        (20000, {"big": 128000}, "big", ["unknown"], 20000),  # a fallback with an unknown limit: trusted
        (0, {"big": 128000}, "big", [], ANALYSIS_MAX_OUTPUT_TOKENS_CEILING),  # 0 = automatic
    ],
)
def test_explicit_output_budget_is_used_and_capped_to_known_limits(explicit, table, model, fallbacks, expected) -> None:
    analyzer = _analyzer()
    with patch("src.analyzer.litellm.get_model_info", side_effect=_limits(table)):
        assert analyzer._resolve_analysis_max_output_tokens(_config_with(explicit, model, fallbacks)) == expected


def test_truncation_retry_ignores_the_explicit_budget_and_never_goes_lower() -> None:
    analyzer = _analyzer()
    with patch("src.analyzer.litellm.get_model_info", side_effect=_limits({"big": 128000})):
        assert analyzer._resolve_truncation_retry_max_output_tokens(_config_with(12000), 12000) == 32768
    with patch("src.analyzer.litellm.get_model_info", side_effect=_limits({})):
        assert analyzer._resolve_truncation_retry_max_output_tokens(_config_with(12000, "unknown"), 12000) == 12000


def test_config_parses_analysis_max_output_tokens_from_the_environment(monkeypatch) -> None:
    from src.config import Config

    monkeypatch.delenv("ANALYSIS_MAX_OUTPUT_TOKENS", raising=False)
    assert Config._load_from_env().analysis_max_output_tokens == 0
    monkeypatch.setenv("ANALYSIS_MAX_OUTPUT_TOKENS", "12000")
    assert Config._load_from_env().analysis_max_output_tokens == 12000
    monkeypatch.setenv("ANALYSIS_MAX_OUTPUT_TOKENS", "-5")
    assert Config._load_from_env().analysis_max_output_tokens == 0
    monkeypatch.setenv("ANALYSIS_MAX_OUTPUT_TOKENS", "9999999")
    assert Config._load_from_env().analysis_max_output_tokens == 131072
    monkeypatch.setenv("ANALYSIS_MAX_OUTPUT_TOKENS", "lots")
    assert Config._load_from_env().analysis_max_output_tokens == 0


def test_registry_describes_the_analysis_output_budget() -> None:
    from src.core.config_registry import get_field_definition

    field = get_field_definition("ANALYSIS_MAX_OUTPUT_TOKENS")

    assert field["category"] == "ai_model"
    assert field["data_type"] == "integer"
    assert field["default_value"] == "0"
    assert field["validation"] == {"min": 0, "max": 131072}
    assert field["is_sensitive"] is False

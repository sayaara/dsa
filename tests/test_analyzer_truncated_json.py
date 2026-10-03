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

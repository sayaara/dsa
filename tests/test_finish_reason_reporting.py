# -*- coding: utf-8 -*-
"""finish_reason reporting on the analyzer LiteLLM path and the market review."""

import logging
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from tests.litellm_stub import ensure_litellm_stub

ensure_litellm_stub()

from src.analyzer import GeminiAnalyzer  # noqa: E402
from src.llm.generation_backend import GenerationResult  # noqa: E402
from src.llm.litellm_backend import FINISH_REASON_USAGE_KEY, LiteLLMGenerationBackend  # noqa: E402
from src.market_analyzer import MarketAnalyzer, MarketOverview  # noqa: E402


def _make_analyzer() -> GeminiAnalyzer:
    cfg = SimpleNamespace(
        litellm_model="openai/gpt-4o",
        litellm_fallback_models=[],
        llm_model_list=[],
        llm_temperature=0.7,
        gemini_api_keys=[],
        anthropic_api_keys=[],
        openai_api_keys=["sk-openai-test"],
        deepseek_api_keys=[],
        openai_base_url=None,
        llm_prompt_cache_telemetry_enabled=False,
        llm_prompt_cache_hints_enabled=False,
        llm_prompt_cache_diagnostics_level="off",
    )
    return GeminiAnalyzer(config=cfg)


def _completion(finish_reason):
    return SimpleNamespace(
        choices=[SimpleNamespace(finish_reason=finish_reason, message=SimpleNamespace(content="partial review"))],
        usage=SimpleNamespace(prompt_tokens=10, completion_tokens=8192, total_tokens=8202),
    )


def test_cut_off_completion_reports_length_in_diagnostics(caplog) -> None:
    analyzer = _make_analyzer()

    with patch("src.analyzer.call_litellm_with_param_recovery", return_value=_completion("length")), \
         caplog.at_level(logging.WARNING, logger="src.analyzer"):
        result = analyzer._call_litellm(
            "prompt", {"max_tokens": 8192, "temperature": 0.7}, return_generation_result=True
        )

    assert isinstance(result, GenerationResult)
    assert result.text == "partial review"
    assert result.diagnostics == {"finish_reason": "length"}
    assert FINISH_REASON_USAGE_KEY not in result.usage
    assert "cut off by the output-token limit" in caplog.text


def test_finished_completion_keeps_usage_clean_on_the_tuple_path() -> None:
    analyzer = _make_analyzer()

    with patch("src.analyzer.call_litellm_with_param_recovery", return_value=_completion("stop")):
        text, _, usage = analyzer._call_litellm("prompt", {"max_tokens": 128, "temperature": 0.7})
        result = analyzer._call_litellm(
            "prompt", {"max_tokens": 128, "temperature": 0.7}, return_generation_result=True
        )

    assert text == "partial review"
    assert FINISH_REASON_USAGE_KEY not in usage
    assert result.diagnostics == {"finish_reason": "stop"}


def test_missing_or_non_string_finish_reason_is_ignored() -> None:
    assert GeminiAnalyzer._extract_finish_reason(SimpleNamespace(choices=[SimpleNamespace()])) is None
    assert GeminiAnalyzer._extract_finish_reason(SimpleNamespace(choices=[MagicMock()])) is None
    assert GeminiAnalyzer._extract_finish_reason(SimpleNamespace(choices=[])) is None
    assert GeminiAnalyzer._extract_finish_reason(object()) is None


def test_stream_consumer_returns_the_last_finish_reason() -> None:
    analyzer = _make_analyzer()

    def _chunk(text, finish_reason=None):
        return SimpleNamespace(
            choices=[SimpleNamespace(delta=SimpleNamespace(content=text), finish_reason=finish_reason)],
            usage=None,
        )

    text, _, finish_reason = analyzer._consume_litellm_stream(
        iter([_chunk("Hello "), _chunk("world"), _chunk("", "length")]),
        model="openai/gpt-4o",
    )

    assert text == "Hello world"
    assert finish_reason == "length"


def test_backend_moves_finish_reason_into_diagnostics_and_keeps_usage_type() -> None:
    class _MarkedUsage(dict):
        pass

    usage = _MarkedUsage({"total_tokens": 3, FINISH_REASON_USAGE_KEY: "length"})
    usage.prompt_cache_telemetry_disabled = True
    backend = LiteLLMGenerationBackend(lambda *args, **kwargs: ("text", "openai/gpt-4o", usage))

    result = backend.generate("prompt", {})

    assert result.diagnostics == {"finish_reason": "length"}
    assert result.usage == {"total_tokens": 3}
    assert getattr(result.usage, "prompt_cache_telemetry_disabled", False)


def _market_analyzer(diagnostics):
    ma = MarketAnalyzer.__new__(MarketAnalyzer)
    ma.analyzer = MagicMock()
    ma.analyzer.is_available.return_value = True
    ma.config = SimpleNamespace()
    ma.region = "us"
    generation = GenerationResult(
        text="## Review\nIndices rose and the market",
        model="openai/gpt-4o",
        provider="openai",
        backend="litellm",
        usage={},
        diagnostics=diagnostics,
    )
    patches = [
        patch.object(ma, "_get_analyzer_generation_backend_config_error", return_value=None),
        patch.object(ma, "_build_review_prompt", return_value="prompt"),
        patch.object(ma, "_get_analyzer_generation_backend_identity", return_value=("litellm", "openai/gpt-4o")),
        patch.object(ma, "_generate_market_review_with_metadata", return_value=generation),
        patch.object(ma, "_resolve_recorded_provider", return_value="openai"),
        patch.object(ma, "_inject_data_into_review", side_effect=lambda review, overview, news: review),
        patch.object(ma, "_log_context", return_value="region=us"),
        patch("src.market_analyzer.record_llm_run_started"),
        patch("src.market_analyzer.record_llm_run"),
    ]
    return ma, patches


def _run_review(diagnostics):
    ma, patches = _market_analyzer(diagnostics)
    for p in patches:
        p.start()
    try:
        return ma.generate_market_review(MarketOverview(date="2026-10-04"), [])
    finally:
        for p in reversed(patches):
            p.stop()


def test_cut_off_market_review_is_marked(caplog) -> None:
    with caplog.at_level(logging.WARNING, logger="src.market_analyzer"):
        review = _run_review({"finish_reason": "length"})

    assert review.startswith("## Review\nIndices rose and the market")
    assert review.endswith("cut off by the model's output-token limit and may be incomplete.")
    assert "status=truncated" in caplog.text


def test_finished_market_review_is_not_marked() -> None:
    assert _run_review({"finish_reason": "stop"}) == "## Review\nIndices rose and the market"
    assert _run_review({}) == "## Review\nIndices rose and the market"

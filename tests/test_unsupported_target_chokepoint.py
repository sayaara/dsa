# -*- coding: utf-8 -*-
"""Unsupported-market codes never reach a data source or the LLM.

Before this check, a code that slipped past an entry point (the bot's legacy gate, a
Chinese company name resolved to ``00700``, a watchlist entry) failed its data fetch,
and the pipeline still asked the model, using news alone. The fundamentals and
real-time paths also asked Yahoo for such codes.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from data_provider.base import DataFetcherManager
from src.core.pipeline import StockAnalysisPipeline, _unsupported_target_reason
from src.enums import ReportType
from src.services.stock_list_parser import ParseStatus, parse_analysis_target

# Text that is not a symbol (a Chinese index name, a phrase, a ``$`` cashtag) used to be guessed
# as a US ticker and analysed from news alone.
UNSUPPORTED = [
    "600519", "00700", "HK00700", "0700.HK", "7203.T", "VOD.L", "SAP.DE",
    "沪深300", "hello world", "$AAPL",
]
SUPPORTED = ["AAPL", "BRK.B", "brk-b", "^GSPC", "AAICPRC", "RY.TO", "TECK-B.TO"]


def _bare_pipeline() -> StockAnalysisPipeline:
    pipeline = StockAnalysisPipeline.__new__(StockAnalysisPipeline)
    pipeline.fetcher_manager = MagicMock()
    pipeline.analyzer = MagicMock()
    pipeline.db = MagicMock()
    return pipeline


@pytest.mark.parametrize("code", UNSUPPORTED)
def test_process_single_stock_refuses_before_any_fetch_or_llm_call(code: str) -> None:
    pipeline = _bare_pipeline()

    result = pipeline.process_single_stock(code, skip_analysis=False, single_stock_notify=False)

    assert result is not None and result.success is False
    assert result.error_message.startswith(f"Cannot analyze {code}: ")
    assert pipeline.fetcher_manager.method_calls == []
    assert pipeline.analyzer.method_calls == []
    assert pipeline.db.method_calls == []


@pytest.mark.parametrize("code", UNSUPPORTED)
def test_analyze_stock_refuses_unsupported_codes(code: str, caplog) -> None:
    pipeline = _bare_pipeline()

    with caplog.at_level("WARNING", logger="src.core.pipeline"):
        assert pipeline.analyze_stock(code, ReportType.SIMPLE, query_id="q") is None
    assert f"[{code}] unsupported target, analysis refused" in caplog.text
    assert pipeline.fetcher_manager.method_calls == []
    assert pipeline.analyzer.method_calls == []


@pytest.mark.parametrize("code", SUPPORTED)
def test_supported_codes_pass_the_check(code: str) -> None:
    assert _unsupported_target_reason(code) is None


def test_a_structured_target_decides_over_the_code() -> None:
    rejected = parse_analysis_target("600519")
    assert _unsupported_target_reason("AAPL", rejected) == rejected.unsupported_reason

    index_target = MagicMock(asset_type=ParseStatus.INDEX)
    # An index target keeps its canonical id (for example ``sh000300``), which the
    # parser alone would reject as a mainland code.
    assert _unsupported_target_reason("sh000300", index_target) is None


@pytest.mark.parametrize("code", UNSUPPORTED)
def test_realtime_quote_asks_no_source_for_unsupported_codes(code: str) -> None:
    fetcher = MagicMock()
    fetcher.name = "YfinanceFetcher"
    fetcher.priority = 0
    manager = DataFetcherManager(fetchers=[fetcher])

    assert manager.get_realtime_quote(code) is None
    fetcher.get_realtime_quote.assert_not_called()


@pytest.mark.parametrize("code", UNSUPPORTED)
def test_fundamental_context_asks_no_source_for_unsupported_codes(code: str) -> None:
    manager = DataFetcherManager(fetchers=[])
    with patch.object(manager, "_build_offshore_fundamental_context") as offshore:
        context = manager.get_fundamental_context(code)

    offshore.assert_not_called()
    assert context["capital_flow"]["status"] == "not_supported"


def test_fundamental_context_still_runs_for_supported_codes() -> None:
    manager = DataFetcherManager(fetchers=[])
    with patch.object(manager, "_build_offshore_fundamental_context", return_value={"ok": True}) as offshore:
        assert manager.get_fundamental_context("RY.TO") == {"ok": True}
    offshore.assert_called_once()

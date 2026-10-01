# -*- coding: utf-8 -*-
"""Canada (region ``ca``) in the broad-market review: profile, strategy, index fetch and region handling."""

from unittest.mock import MagicMock

import pandas as pd
import pytest

from data_provider.yfinance_fetcher import YfinanceFetcher
from src.core.market_profile import CA_PROFILE, get_profile
from src.core.market_strategy import CA_BLUEPRINT, get_market_strategy_blueprint
from src.core.trading_calendar import compute_effective_region
from src.market_analyzer import MarketAnalyzer
from src.services.daily_market_context import _REGION_LABEL_EN, _REGION_LABEL_ZH, _normalize_region
from src.utils.market_review_region import (
    MARKET_REVIEW_REGION_ORDER,
    normalize_market_review_region_lenient,
    normalize_market_review_region_strict,
)


def _analyzer(region: str = "ca", language: str = "en") -> MarketAnalyzer:
    analyzer = MarketAnalyzer.__new__(MarketAnalyzer)
    analyzer.region = region
    analyzer.profile = get_profile(region)
    analyzer.strategy = get_market_strategy_blueprint(region)
    analyzer.config = MagicMock(report_language=language, market_review_color_scheme="green_up")
    analyzer._get_review_language = lambda: language  # type: ignore[method-assign]
    return analyzer


def test_region_order_and_normalization_include_canada() -> None:
    assert MARKET_REVIEW_REGION_ORDER == ("ca", "hk", "us")
    assert normalize_market_review_region_lenient("both") == "ca,hk,us"
    assert normalize_market_review_region_lenient("US, CA") == "ca,us"
    assert normalize_market_review_region_lenient("ca") == "ca"
    assert normalize_market_review_region_strict(" us , CA ") == "ca,us"
    assert normalize_market_review_region_strict("both") == "ca,hk,us"
    with pytest.raises(ValueError):
        normalize_market_review_region_strict("ca,both")


def test_profile_and_blueprint_for_canada() -> None:
    assert get_profile("ca") is CA_PROFILE
    assert CA_PROFILE.mood_index_code == "TSX"
    assert CA_PROFILE.has_market_stats is False and CA_PROFILE.has_sector_rankings is False
    assert get_market_strategy_blueprint("ca") is CA_BLUEPRINT
    block = CA_BLUEPRINT.to_prompt_block()
    assert "Canadian Market Regime Strategy" in block
    assert "S&P/TSX" in block and "commodity" in block.lower()
    assert CA_BLUEPRINT.to_markdown_block().startswith("### VI. Strategy Framework")
    # Other regions are unaffected and unknown regions still fall back to the US profile.
    assert get_profile("hk").region == "hk"
    assert get_profile("xx").region == "us"


def test_analyzer_accepts_the_ca_region_and_uses_canadian_wording() -> None:
    analyzer = _analyzer("ca", "en")
    assert analyzer._get_market_scope_name() == "Canadian market"
    assert analyzer._get_market_scope_name("zh") == "加拿大市场"
    assert analyzer._get_turnover_unit_label() == "CAD bn"
    assert analyzer._format_turnover_value(2.5e9) == "2.50"
    assert analyzer._get_review_title("2026-10-01") == "## 2026-10-01 Canada Market Recap"
    assert "S&P/TSX Composite" in analyzer._get_index_hint()
    assert "Canadian Market Regime Strategy" in analyzer._get_strategy_prompt_block()
    assert "Strategy Framework" in analyzer._get_strategy_markdown_block()


def test_analyzer_has_a_chinese_strategy_block_for_canada() -> None:
    analyzer = _analyzer("ca", "zh")
    assert "加拿大市场三段式复盘策略" in analyzer._get_strategy_prompt_block()
    assert "宏观与商品" in analyzer._get_strategy_markdown_block()
    assert analyzer._get_turnover_unit_label() == "十亿加元"


def test_unknown_analyzer_region_still_falls_back_to_us() -> None:
    analyzer = MarketAnalyzer(region="xx", search_service=MagicMock(), analyzer=MagicMock())
    assert analyzer.region == "us"
    assert MarketAnalyzer(region="ca", search_service=MagicMock(), analyzer=MagicMock()).region == "ca"


def _hist(close: float, prev: float) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "Close": [prev, close],
            "Open": [prev - 10, close - 5],
            "High": [prev + 20, close + 10],
            "Low": [prev - 20, close - 10],
            "Volume": [1.0e9, 1.1e9],
        },
        index=pd.DatetimeIndex(["2026-09-30", "2026-10-01"]),
    )


def test_yahoo_ca_index_symbols_and_codes_are_pinned() -> None:
    yf = MagicMock()
    ticker = MagicMock()
    ticker.history.return_value = _hist(35000.0, 34800.0)
    yf.Ticker.return_value = ticker

    results = YfinanceFetcher()._get_ca_main_indices(yf)

    assert [call.args[0] for call in yf.Ticker.call_args_list] == ["^GSPTSE", "^SPCDNX"]
    assert [item["code"] for item in results] == ["TSX", "TSXV"]
    assert results[0]["name"] == "S&P/TSX Composite"
    assert results[0]["change_pct"] == pytest.approx((35000.0 - 34800.0) / 34800.0 * 100, rel=1e-3)


def test_yahoo_ca_index_fetch_degrades_when_a_symbol_fails() -> None:
    yf = MagicMock()
    good = MagicMock()
    good.history.return_value = _hist(35000.0, 34800.0)
    bad = MagicMock()
    bad.history.return_value = pd.DataFrame()
    yf.Ticker.side_effect = [good, bad]

    results = YfinanceFetcher()._get_ca_main_indices(yf)
    assert [item["code"] for item in results] == ["TSX"]

    empty = MagicMock()
    empty.history.return_value = pd.DataFrame()
    yf.Ticker.side_effect = None
    yf.Ticker.return_value = empty
    assert YfinanceFetcher()._get_ca_main_indices(yf) is None


def test_main_indices_dispatch_routes_ca_to_the_canadian_fetch(monkeypatch) -> None:
    fetcher = YfinanceFetcher()
    seen = {}
    monkeypatch.setattr(fetcher, "_get_ca_main_indices", lambda yf: seen.setdefault("ca", [{"code": "TSX"}]))
    monkeypatch.setattr(fetcher, "_get_us_main_indices", lambda yf: seen.setdefault("us", [{"code": "SPX"}]))
    assert fetcher.get_main_indices(region="ca") == [{"code": "TSX"}]
    assert "us" not in seen


def test_effective_region_filters_by_open_markets_in_canonical_order() -> None:
    assert compute_effective_region("both", {"ca", "hk", "us"}) == "ca,hk,us"
    assert compute_effective_region("both", {"ca", "us"}) == "ca,us"
    assert compute_effective_region("ca", {"ca"}) == "ca"
    assert compute_effective_region("ca", {"us"}) == ""
    assert compute_effective_region("us,ca,hk", {"ca", "hk"}) == "ca,hk"


def test_daily_market_context_labels_canada() -> None:
    assert _REGION_LABEL_ZH["ca"] == "加拿大"
    assert _REGION_LABEL_EN["ca"] == "Canada"
    assert _normalize_region("CA") == "ca"

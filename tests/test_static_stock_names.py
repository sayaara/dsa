# -*- coding: utf-8 -*-
"""Language-aware static stock names and English board labels."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from data_provider.base import DataFetcherManager
from src.data.stock_mapping import (
    STOCK_ENGLISH_NAME_MAP,
    STOCK_NAME_MAP,
    foreign_stock_identity_aliases,
    get_static_stock_name,
)
from src.search_service import SearchResult, SearchService
from src.services.name_to_code_resolver import resolve_name_to_code
from src.services.portfolio_risk_service import PortfolioRiskService


def test_english_is_the_default_language_and_returns_the_legal_name() -> None:
    assert get_static_stock_name("AAPL", "en") == "Apple Inc."
    assert get_static_stock_name("BABA", "en") == "Alibaba Group Holding Limited"
    assert get_static_stock_name("00700", "en") == "Tencent Holdings"
    assert get_static_stock_name("AAPL", "ko") == "Apple Inc."
    with patch("src.config.get_config", return_value=SimpleNamespace(report_language="en")):
        assert get_static_stock_name("AAPL") == "Apple Inc."


def test_chinese_reports_keep_the_chinese_names() -> None:
    with patch("src.config.get_config", return_value=SimpleNamespace(report_language="zh")):
        assert get_static_stock_name("AAPL") == "苹果"
        assert get_static_stock_name("00700") == "腾讯控股"
    assert get_static_stock_name("AAPL", "zh") == STOCK_NAME_MAP["AAPL"]


def test_every_mapped_ticker_has_an_english_name_and_unknown_tickers_are_empty() -> None:
    for code in STOCK_NAME_MAP:
        english = get_static_stock_name(code, "en")
        assert english and not any("一" <= ch <= "鿿" for ch in english), code
        assert english == STOCK_ENGLISH_NAME_MAP[code][0]
    assert get_static_stock_name("ZZZZ", "en") == ""
    assert get_static_stock_name("RY.TO", "en") == ""


def test_prefixed_and_suffixed_hk_forms_resolve_to_the_same_name() -> None:
    for code in ("00700", "HK00700", "00700.HK"):
        assert get_static_stock_name(code, "en") == "Tencent Holdings", code
        assert get_static_stock_name(code, "zh") == "腾讯控股", code


def test_manager_uses_the_english_name_by_default() -> None:
    manager = DataFetcherManager(fetchers=[])
    with patch("src.config.get_config", return_value=SimpleNamespace(report_language="en")):
        assert manager.get_stock_name("AAPL") == "Apple Inc."


def test_chinese_name_lookup_still_resolves_to_the_ticker() -> None:
    assert resolve_name_to_code("苹果") == "AAPL"
    assert resolve_name_to_code("腾讯控股") == "00700"


def test_identity_aliases_do_not_depend_on_the_display_name_language() -> None:
    assert foreign_stock_identity_aliases("BABA") == ("Alibaba Group Holding Limited", "Alibaba")
    assert foreign_stock_identity_aliases("AAPL.US") == ("Apple Inc.", "Apple")
    assert foreign_stock_identity_aliases("RY.TO") == ()


def _score(title: str, *, name: str, code: str = "BABA") -> SearchResult:
    item = SearchResult(title=title, snippet="", url="https://example.com/a", source="example")
    return SearchService._score_news_relevance(item, stock_code=code, stock_name=name)


def test_english_display_names_still_match_short_media_names_exactly_once() -> None:
    english = _score("Alibaba shares jump after earnings", name="Alibaba Group Holding Limited")
    chinese = _score("Alibaba shares jump after earnings", name="阿里巴巴")
    unrelated = _score("Local bakery wins award", name="Alibaba Group Holding Limited")
    assert english.relevance_score >= 45
    assert english.relevance_score == chinese.relevance_score
    assert unrelated.relevance_score < english.relevance_score


@pytest.mark.parametrize(
    ("boards", "expected"),
    [
        ([{"name": "Banks", "type": "Industry"}, {"name": "Financials", "type": "Sector"}], "Financials"),
        ([{"name": "Banks", "type": "Industry"}], "Banks"),
        ([{"name": "白酒", "type": "行业"}, {"name": "消费", "type": "概念"}], "白酒"),
        ([{"name": "Misc", "type": "Theme"}], "Misc"),
        ([], None),
    ],
)
def test_primary_board_prefers_sector_then_industry(boards, expected) -> None:
    assert PortfolioRiskService._pick_primary_board_name(boards) == expected

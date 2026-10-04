# -*- coding: utf-8 -*-
"""Market-review news queries follow the review language."""

import re
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from src.core.market_profile import get_profile
from src.market_analyzer import MarketAnalyzer

_CJK = re.compile(r"[　-〿一-鿿＀-￯]")


@pytest.mark.parametrize("region", ["us", "hk", "ca"])
def test_default_news_queries_are_english(region) -> None:
    profile = get_profile(region)

    assert len(profile.news_queries) == 3
    assert [q for q in profile.news_queries if _CJK.search(q)] == []
    assert any(_CJK.search(q) for q in profile.news_queries_zh)


def _searched_queries(region: str, language: str) -> list:
    with patch("src.market_analyzer.get_config", return_value=SimpleNamespace(report_language=language)):
        analyzer = MarketAnalyzer(region=region)
    search_service = MagicMock()
    search_service.search_stock_news.return_value = SimpleNamespace(results=[])
    analyzer.search_service = search_service

    analyzer.search_market_news()

    return [" ".join(call.kwargs["focus_keywords"]) for call in search_service.search_stock_news.call_args_list]


@pytest.mark.parametrize("language", ["en", "ko"])
@pytest.mark.parametrize("region", ["us", "hk", "ca"])
def test_english_and_korean_reviews_search_in_english(region, language) -> None:
    queries = _searched_queries(region, language)

    assert queries == get_profile(region).news_queries


@pytest.mark.parametrize("region", ["us", "hk", "ca"])
def test_chinese_reviews_keep_the_chinese_queries(region) -> None:
    assert _searched_queries(region, "zh") == get_profile(region).news_queries_zh

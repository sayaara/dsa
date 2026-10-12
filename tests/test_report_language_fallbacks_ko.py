# -*- coding: utf-8 -*-
"""Korean (ko) deterministic fallback coverage for the report-language sweep (#1614)."""

import unittest

from src.core.market_review import _get_market_review_text
from src.report_language import (
    get_no_data_text,
    get_placeholder_text,
    get_unknown_text,
)


class KoreanFallbackTextTestCase(unittest.TestCase):
    def test_placeholder_unknown_no_data_have_korean(self) -> None:
        self.assertEqual(get_placeholder_text("ko"), "미정")
        self.assertEqual(get_unknown_text("ko"), "알 수 없음")
        self.assertEqual(get_no_data_text("ko"), "데이터 없음")

    def test_market_review_titles_are_english_for_every_language(self) -> None:
        for language in ("en", "zh", "ko"):
            self.assertEqual(_get_market_review_text(language)["push_title"], "🎯 Market Review")


if __name__ == "__main__":
    unittest.main()

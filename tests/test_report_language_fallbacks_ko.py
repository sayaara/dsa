# -*- coding: utf-8 -*-
"""Retired Korean (ko) values get the English deterministic fallbacks."""

import unittest

from src.core.market_review import _get_market_review_text
from src.report_language import (
    get_no_data_text,
    get_placeholder_text,
    get_unknown_text,
)


class KoreanFallbackTextTestCase(unittest.TestCase):
    def test_placeholder_unknown_no_data_are_english_for_korean(self) -> None:
        self.assertEqual(get_placeholder_text("ko"), "TBD")
        self.assertEqual(get_unknown_text("ko"), "Unknown")
        self.assertEqual(get_no_data_text("ko"), "Data unavailable")

    def test_market_review_titles_are_english_for_every_language(self) -> None:
        for language in ("en", "zh", "ko"):
            self.assertEqual(_get_market_review_text(language)["push_title"], "🎯 Market Review")


if __name__ == "__main__":
    unittest.main()

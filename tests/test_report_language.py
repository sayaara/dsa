# -*- coding: utf-8 -*-
"""Unit tests for report language helpers."""

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from src.report_language import (
    SUPPORTED_REPORT_LANGUAGES,
    get_bias_status_emoji,
    get_default_report_language,
    get_localized_stock_name,
    get_report_labels,
    get_sentiment_label,
    get_signal_level,
    infer_decision_type_from_advice,
    localize_operation_advice,
    localize_trend_prediction,
    localize_bias_status,
    normalize_report_language,
    resolve_report_language,
)


class ReportLanguageTestCase(unittest.TestCase):
    def test_get_signal_level_handles_compound_sell_advice(self) -> None:
        signal_text, emoji, signal_tag = get_signal_level("卖出/观望", 60, "en")

        self.assertEqual(signal_text, "Sell")
        self.assertEqual(emoji, "🔴")
        self.assertEqual(signal_tag, "sell")

    def test_get_signal_level_handles_compound_buy_advice_in_english(self) -> None:
        signal_text, emoji, signal_tag = get_signal_level("Buy / Watch", 40, "en")

        self.assertEqual(signal_text, "Buy")
        self.assertEqual(emoji, "🟢")
        self.assertEqual(signal_tag, "buy")

    def test_get_signal_level_score_fallback_uses_canonical_scale(self) -> None:
        self.assertEqual(get_signal_level("", 28, "en"), ("Reduce", "🟠", "reduce"))
        self.assertEqual(get_signal_level("", 38, "en"), ("Reduce", "🟠", "reduce"))
        self.assertEqual(get_signal_level("", 42, "en"), ("Watch", "⚪", "watch"))
        self.assertEqual(get_signal_level("", 55, "en"), ("Watch", "⚪", "watch"))
        self.assertEqual(get_signal_level("", 60, "en"), ("Buy", "🟢", "buy"))
        self.assertEqual(get_signal_level("", 66, "en"), ("Buy", "🟢", "buy"))
        self.assertEqual(get_signal_level("", 72, "en"), ("Buy", "🟢", "buy"))

    def test_get_localized_stock_name_replaces_placeholder_for_english(self) -> None:
        self.assertEqual(
            get_localized_stock_name("股票AAPL", "AAPL", "en"),
            "Unnamed Stock",
        )

    def test_get_sentiment_label_preserves_higher_band_thresholds(self) -> None:
        self.assertEqual(get_sentiment_label(80, "en"), "Very Bullish")
        self.assertEqual(get_sentiment_label(60, "en"), "Bullish")
        self.assertEqual(get_sentiment_label(40, "en"), "Neutral")
        self.assertEqual(get_sentiment_label(20, "en"), "Bearish")

    def test_localize_trend_prediction_maps_chinese_model_terms_to_english(self) -> None:
        self.assertEqual(localize_trend_prediction("多头排列", "en"), "Bullish")
        self.assertEqual(localize_trend_prediction("弱势空头", "en"), "Bearish")

    def test_localize_trend_prediction_is_english_for_retired_languages(self) -> None:
        self.assertEqual(localize_trend_prediction("bullish", "zh"), "Bullish")
        self.assertEqual(localize_trend_prediction("very bearish", "zh"), "Strong Bearish")

    def test_bias_status_helpers_support_english_values(self) -> None:
        self.assertEqual(localize_bias_status("Safe", "en"), "Safe")
        self.assertEqual(localize_bias_status("警戒", "en"), "Caution")
        self.assertEqual(get_bias_status_emoji("Safe"), "✅")
        self.assertEqual(get_bias_status_emoji("Caution"), "⚠️")

    def test_infer_decision_type_from_advice_matches_chinese_phrases(self) -> None:
        self.assertEqual(infer_decision_type_from_advice("建议买入"), "buy")
        self.assertEqual(infer_decision_type_from_advice("建议持有"), "hold")
        self.assertEqual(infer_decision_type_from_advice("建议减仓"), "sell")
        self.assertEqual(infer_decision_type_from_advice("继续持有"), "hold")
        self.assertEqual(infer_decision_type_from_advice("建议洗盘观察"), "hold")
        self.assertEqual(infer_decision_type_from_advice("洗盘观察", default=""), "hold")
        self.assertEqual(infer_decision_type_from_advice("观察", default=""), "hold")
        self.assertEqual(infer_decision_type_from_advice("不建议买入"), "hold")
        self.assertEqual(
            infer_decision_type_from_advice("当前不跌破支撑位继续持有"),
            "hold",
        )
        self.assertEqual(
            infer_decision_type_from_advice("不破支撑后仍可持有"),
            "hold",
        )


class EnglishOnlyReportLanguageTestCase(unittest.TestCase):
    """Reports are English-only; retired zh/ko values and model terms still resolve to English."""

    def test_only_english_is_supported(self) -> None:
        self.assertEqual(SUPPORTED_REPORT_LANGUAGES, ("en",))

    def test_retired_and_unknown_languages_normalize_to_english(self) -> None:
        for value in ("zh", "zh-CN", "ko", "korean", "ko-KR", "kr", "fr", None):
            self.assertEqual(normalize_report_language(value), "en")
        self.assertEqual(normalize_report_language("English"), "en")
        self.assertEqual(normalize_report_language("zh", default=""), "")

    def test_labels_are_english_for_every_language(self) -> None:
        en_labels = get_report_labels("en")
        for language in ("zh", "ko", None):
            self.assertEqual(get_report_labels(language), en_labels)
        self.assertEqual(en_labels["data_sources_label"], "Data Sources")

    def test_chinese_and_korean_model_terms_map_to_english(self) -> None:
        self.assertEqual(localize_operation_advice("买入", "ko"), "Buy")
        self.assertEqual(localize_operation_advice("적극 매도", "zh"), "Strong Sell")
        self.assertEqual(localize_trend_prediction("상승", "en"), "Bullish")
        self.assertEqual(get_signal_level("매수", 72, "ko"), ("Buy", "🟢", "buy"))
        self.assertEqual(get_signal_level("매도", 30, "ko"), ("Sell", "🔴", "sell"))

    def test_korean_advice_canonicalizes_to_decision_type(self) -> None:
        self.assertEqual(infer_decision_type_from_advice("매수"), "buy")
        self.assertEqual(infer_decision_type_from_advice("매도"), "sell")
        self.assertEqual(infer_decision_type_from_advice("보유"), "hold")
        self.assertEqual(infer_decision_type_from_advice("관망"), "hold")

    def test_placeholder_stock_name_is_english(self) -> None:
        self.assertEqual(get_localized_stock_name("股票AAPL", "AAPL", "ko"), "Unnamed Stock")


class DefaultReportLanguageTestCase(unittest.TestCase):
    """Fallbacks follow the configured REPORT_LANGUAGE instead of a literal."""

    def _patch_config(self, language):
        return patch("src.config.get_config", return_value=SimpleNamespace(report_language=language))

    def test_default_is_english_for_every_configured_language(self) -> None:
        for configured in ("en", "zh", "ko"):
            with self._patch_config(configured):
                self.assertEqual(get_default_report_language(), "en")

    def test_default_falls_back_to_english_for_invalid_config(self) -> None:
        for configured in (None, "", "fr", 123):
            with self._patch_config(configured):
                self.assertEqual(get_default_report_language(), "en")

    def test_default_falls_back_to_english_when_config_fails(self) -> None:
        with patch("src.config.get_config", side_effect=RuntimeError("boom")):
            self.assertEqual(get_default_report_language(), "en")

    def test_resolve_is_english_for_every_value(self) -> None:
        for value in ("en", "ko-KR", "zh_CN", None, "", "fr", object()):
            for configured in ("zh", "en"):
                with self._patch_config(configured):
                    self.assertEqual(resolve_report_language(value), "en")


if __name__ == "__main__":
    unittest.main()

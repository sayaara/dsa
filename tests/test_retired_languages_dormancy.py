# -*- coding: utf-8 -*-
"""Chinese and Korean are retired as *defaults*, not removed (D11, R14).

On the backend an explicit ``REPORT_LANGUAGE=zh|ko`` is still honoured, so the
zh / ko tables must not rot, and the surfaces that are English by design (bot
replies, report type names) must not follow that setting. The frontend half of
this contract is ``apps/dsa-web/tests/retired_ui_languages.test.tsx``.
"""

import re
from unittest.mock import patch

import pytest

import src.report_language as report_language
from src.enums import ReportType
from tests.test_bot_reply_language import CJK, _dispatcher, _message, _strip_allowed

LANGUAGES = ("zh", "en", "ko")
HAN = re.compile(r"[㐀-鿿]")
HANGUL = re.compile(r"[가-힯]")

# Korean labels that still contain a Chinese character ("전년比", meaning year over year).
# Remove an entry once the label is fixed.
KOREAN_LABELS_WITH_HAN = {
    ("_REPORT_LABELS", "revenue_yoy_label"),
    ("_REPORT_LABELS", "net_profit_yoy_label"),
}


def _is_language_table(value) -> bool:
    return isinstance(value, dict) and len(value) >= 2 and set(value) <= set(LANGUAGES)


def _language_tables():
    """Yield (table name, entry key, {language: text}) for every localization table."""
    for name, value in vars(report_language).items():
        if name.startswith("__") or not isinstance(value, dict) or not value:
            continue
        if _is_language_table(value):
            if all(isinstance(text, dict) for text in value.values()):
                for language, entries in value.items():
                    for key, text in entries.items():
                        yield name, key, language, text
            else:
                for language, text in value.items():
                    yield name, "", language, text
        elif all(_is_language_table(entry) for entry in value.values()):
            for key, entry in value.items():
                for language, text in entry.items():
                    yield name, key, language, text


def test_language_tables_cover_all_three_languages_with_the_same_keys():
    by_entry = {}
    for name, key, language, text in _language_tables():
        by_entry.setdefault((name, key), {})[language] = text
    assert len(by_entry) > 100, "the localization tables were not discovered"

    incomplete = [entry for entry, texts in by_entry.items() if set(texts) != set(LANGUAGES)]
    assert incomplete == []
    empty = [(entry, language) for entry, texts in by_entry.items() for language, text in texts.items() if not str(text).strip()]
    assert empty == []

    labels = report_language._REPORT_LABELS
    assert set(labels["zh"]) == set(labels["en"]) == set(labels["ko"])


def test_each_language_table_keeps_to_its_own_script():
    wrong_script = set()
    for name, key, language, text in _language_tables():
        text = str(text)
        if language == "en" and (HAN.search(text) or HANGUL.search(text)):
            wrong_script.add((name, key, language))
        elif language == "zh" and HANGUL.search(text):
            wrong_script.add((name, key, language))
        elif language == "ko" and HAN.search(text) and (name, key) not in KOREAN_LABELS_WITH_HAN:
            wrong_script.add((name, key, language))
    assert wrong_script == set()

    # The known exceptions must still be real, so fixing the labels forces the list to shrink.
    ko_labels = report_language._REPORT_LABELS["ko"]
    assert all(HAN.search(ko_labels[key]) for _, key in KOREAN_LABELS_WITH_HAN)


def test_explicit_zh_and_ko_still_render_their_own_language():
    labels = {language: report_language.get_report_labels(language) for language in LANGUAGES}
    assert any(HAN.search(text) for text in labels["zh"].values())
    assert any(HANGUL.search(text) for text in labels["ko"].values())
    assert not any(HAN.search(text) or HANGUL.search(text) for text in labels["en"].values())

    advice = {language: report_language.localize_operation_advice("Buy", language) for language in LANGUAGES}
    assert HAN.search(advice["zh"])
    assert HANGUL.search(advice["ko"])
    assert not (HAN.search(advice["en"]) or HANGUL.search(advice["en"]))


@pytest.mark.usefixtures("zh_report_language_default")
def test_bot_replies_and_report_type_names_stay_english_when_report_language_is_zh():
    assert report_language.get_default_report_language() == "zh"

    dispatcher = _dispatcher()
    for content in ("/definitely-not-a-command", "/help", "/help analyze"):
        with patch("bot.dispatcher.get_dispatcher", return_value=dispatcher):
            reply = dispatcher.dispatch(_message(content))
        assert not CJK.search(_strip_allowed(reply.text, dispatcher)), (content, reply.text)

    for report_type in ReportType:
        assert not CJK.search(report_type.display_name), report_type

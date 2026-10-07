# -*- coding: utf-8 -*-
"""The ``zh_report_language_default`` fixture must not leak ``zh`` into later tests."""

import pytest

from src.config import Config
from src.report_language import get_default_report_language
from tests.conftest import set_zh_report_language_default


@pytest.mark.parametrize("singleton_exists", [True, False])
def test_zh_default_is_undone_whether_or_not_the_singleton_existed(monkeypatch, singleton_exists):
    monkeypatch.delenv("REPORT_LANGUAGE", raising=False)
    saved_instance = Config._instance
    monkeypatch.setattr(Config, "_instance", saved_instance if singleton_exists else None)
    if singleton_exists and Config._instance is not None:
        monkeypatch.setattr(Config._instance, "report_language", "en")

    inner = pytest.MonkeyPatch()
    set_zh_report_language_default(inner)
    assert get_default_report_language() == "zh"
    inner.undo()

    # The singleton built inside the helper (or the existing one) is back to the
    # environment's default, so a later test does not inherit zh.
    assert get_default_report_language() == "en"

# -*- coding: utf-8 -*-
"""Imports keep US/Canadian symbols and do not admit unsupported-market codes."""

from src.services.image_stock_extractor import _parse_codes_from_text, _parse_items_from_text
from src.services.import_parser import parse_import_from_text

_UNSUPPORTED = ["600519", "HK00700", "0700.HK", "00700", "VOD.L"]
_SUPPORTED = ["AAPL", "BRK.B", "RY.TO", "TECK-B.TO"]


def test_text_import_leaves_unsupported_codes_unresolved() -> None:
    text = "code,name\n" + "\n".join(f"{code},Name {i}" for i, code in enumerate(_UNSUPPORTED + _SUPPORTED))

    result = parse_import_from_text(text)

    assert [code for code, _, _ in result] == [None] * len(_UNSUPPORTED) + _SUPPORTED
    # Unsupported rows keep their name so the user sees what was not imported.
    assert [name for _, name, _ in result[: len(_UNSUPPORTED)]] == [f"Name {i}" for i in range(len(_UNSUPPORTED))]


def test_text_import_unsupported_code_without_name_is_shown_as_the_name() -> None:
    assert parse_import_from_text("code\n0700.HK") == [(None, "0700.HK", "medium")]


def test_image_items_drop_unsupported_codes_and_keep_canadian_symbols() -> None:
    payload = ",".join(f'{{"code":"{code.lower()}"}}' for code in _UNSUPPORTED + _SUPPORTED)

    items = _parse_items_from_text(f"[{payload}]")

    assert [code for code, _, _ in items] == _SUPPORTED


def test_image_legacy_codes_drop_unsupported_codes() -> None:
    assert _parse_codes_from_text('["600519", "RY.TO", "00700", "AAPL"]') == ["RY.TO", "AAPL"]
    assert _parse_codes_from_text("600519 RY.TO VOD.L TECK-B.TO") == ["RY.TO", "TECK-B.TO"]

# -*- coding: utf-8 -*-
"""The image extraction prompt is English and asks for symbols the app can keep."""

import json
import re

from src.services.image_stock_extractor import EXTRACT_PROMPT, _normalize_code, _parse_items_from_text

CJK_OR_FULL_WIDTH = re.compile(r"[　-〿㐀-鿿＀-￯]")


def test_extract_prompt_is_english():
    assert CJK_OR_FULL_WIDTH.findall(EXTRACT_PROMPT) == []


def test_extract_prompt_examples_are_us_and_canadian_symbols_the_normalizer_keeps():
    examples = re.findall(r"\b([A-Z]{1,6}(?:[.-][A-Z]{1,2})?(?:\.(?:TO|V))?)\b(?= [A-Z])", EXTRACT_PROMPT)
    for code in ("AAPL", "BRK.B", "RY.TO", "SHOP.TO", "TECK-B.TO", "XIU.TO"):
        assert code in EXTRACT_PROMPT
        assert _normalize_code(code) == code
    assert examples, "the prompt should list example symbols with names"
    for code in examples:
        assert _normalize_code(code) == code, code


def test_extract_prompt_output_example_parses_to_the_listed_items():
    example = EXTRACT_PROMPT.split("Output example: ", 1)[1].splitlines()[0]
    expected = [(item["code"], item["name"], item["confidence"]) for item in json.loads(example)]
    assert _parse_items_from_text(example) == expected
    assert [code for code, _, _ in expected] == ["AAPL", "RY.TO"]

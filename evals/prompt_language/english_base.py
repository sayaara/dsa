# -*- coding: utf-8 -*-
"""English default-prompt variants for the prompt-language eval.

The shipped English prompt lives in ``src/analyzer_prompt_en.py`` and is what the
``current`` variant runs. This module derives the plain translation without the
"exactly one JSON object" rule, so the eval can keep measuring what that rule is
worth.
"""

from __future__ import annotations

from src.analyzer_prompt_en import ENGLISH_DEFAULT_SYSTEM_PROMPT

STRICT_JSON_RULE = (
    "Respond with exactly one JSON object and nothing else: no text before or after it, "
    "no second JSON object, and no corrected or alternative version."
)

assert STRICT_JSON_RULE in ENGLISH_DEFAULT_SYSTEM_PROMPT

# The translation as first evaluated (4 ambiguous_json failures in 180 calls).
ENGLISH_PLAIN_SYSTEM_PROMPT = ENGLISH_DEFAULT_SYSTEM_PROMPT.replace(" " + STRICT_JSON_RULE, "")
assert STRICT_JSON_RULE not in ENGLISH_PLAIN_SYSTEM_PROMPT

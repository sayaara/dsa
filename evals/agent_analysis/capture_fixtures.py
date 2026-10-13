#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Capture frozen tool outputs for the agent analysis eval.

The capture is the chat eval's (``evals/chat_language/capture_fixtures.py``):
the same tools, arguments and fixture format, so both evals replay through one
``replay.py``. Only the defaults differ: the stocks are the prompt-language
eval's 30 samples and the fixtures go to ``evals/agent_analysis/fixtures/``.
No LLM is called; each stock costs two search-tool calls.

Usage:
    python evals/agent_analysis/capture_fixtures.py
    python evals/agent_analysis/capture_fixtures.py --sample us_AAPL
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import List, Optional

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from evals.chat_language import capture_fixtures as chat_capture

EVAL_DIR = Path(__file__).resolve().parent
DEFAULT_SAMPLES = REPO_ROOT / "evals" / "prompt_language" / "samples.json"
DEFAULT_OUT = EVAL_DIR / "fixtures"


def main(argv: Optional[List[str]] = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if "--samples" not in argv:
        argv = ["--samples", str(DEFAULT_SAMPLES)] + argv
    if "--out" not in argv:
        argv = ["--out", str(DEFAULT_OUT)] + argv
    return chat_capture.main(argv)


if __name__ == "__main__":
    sys.exit(main())

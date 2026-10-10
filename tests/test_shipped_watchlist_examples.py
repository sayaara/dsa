# -*- coding: utf-8 -*-
"""Every watchlist the repository ships as a default or example must be analyzable.

The daily workflow rejects the whole run when one ``STOCK_LIST`` token is unsupported
(``main._classify_stock_list_tokens``). Its fallback watchlist kept ``0700.HK`` after Hong
Kong was removed, so every scheduled run failed; these checks run each shipped list
through ``parse_analysis_target`` so a market removal cannot leave a stale example behind.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from src.core.config_registry import get_field_definition
from src.services.stock_list_parser import ParseStatus, parse_analysis_target, split_stock_list

ROOT_DIR = Path(__file__).resolve().parent.parent
WORKFLOW_PATH = ROOT_DIR / ".github/workflows/00-daily-analysis.yml"
ENV_EXAMPLE_PATH = ROOT_DIR / ".env.example"


def _workflow_fallback_watchlist() -> str:
    content = WORKFLOW_PATH.read_text(encoding="utf-8")
    # Literal values only; ``export STOCK_LIST="$STOCK_LIST_CONFIG"`` forwards the configured list.
    matches = re.findall(r'export STOCK_LIST="([^"$]*)"', content)
    assert len(matches) == 1, f"expected one fallback STOCK_LIST export, found {matches}"
    return matches[0]


def _env_example_watchlist() -> str:
    content = ENV_EXAMPLE_PATH.read_text(encoding="utf-8")
    matches = re.findall(r"^STOCK_LIST=(\S+)", content, flags=re.MULTILINE)
    assert len(matches) == 1, f"expected one active STOCK_LIST line, found {matches}"
    return matches[0]


def _registry_watchlists() -> list[str]:
    field = get_field_definition("STOCK_LIST")
    values = [field["default_value"]]
    values += [example.split("=", 1)[1] for example in field["examples"]]
    return values


def _doc_watchlists() -> list[str]:
    """``--stocks`` command examples and the ``STOCK_LIST`` rows of the deploy guide."""
    found = []
    for path in (ROOT_DIR / "AGENTS.md", ROOT_DIR / "README.md", ROOT_DIR / "docs/DEPLOY.md"):
        content = path.read_text(encoding="utf-8")
        found += re.findall(r"main\.py --stocks ([^\s`]+)", content)
        found += re.findall(r"^\| `STOCK_LIST` \|.*?`([^`]+)`", content, flags=re.MULTILINE)
    return found


SHIPPED_WATCHLISTS = (
    [("workflow fallback", _workflow_fallback_watchlist()), (".env.example", _env_example_watchlist())]
    + [("config registry", value) for value in _registry_watchlists()]
    + [("docs", value) for value in _doc_watchlists()]
)


def _unsupported_tokens(watchlist: str) -> list[str]:
    return [
        token
        for token in split_stock_list(watchlist)
        if parse_analysis_target(token).asset_type == ParseStatus.UNSUPPORTED
    ]


@pytest.mark.parametrize(("source", "watchlist"), SHIPPED_WATCHLISTS)
def test_shipped_watchlist_has_only_supported_targets(source: str, watchlist: str) -> None:
    assert split_stock_list(watchlist), f"{source}: empty watchlist"
    assert _unsupported_tokens(watchlist) == [], f"{source}: {watchlist}"


def test_workflow_fallback_matches_env_example_default() -> None:
    # The workflow comment documents its fallback as "the default watchlist from .env.example".
    assert _workflow_fallback_watchlist() == _env_example_watchlist()


def test_the_check_catches_removed_markets() -> None:
    assert _unsupported_tokens("AAPL,MSFT,NVDA,0700.HK") == ["0700.HK"]
    assert _unsupported_tokens("600519,hk00700,AAPL") == ["600519", "hk00700"]


@pytest.mark.parametrize("token", ["沪深300", "hello world", "$AAPL"])
def test_a_watchlist_token_that_is_not_a_symbol_stops_the_run(token: str) -> None:
    # Text that is not a symbol used to be guessed as a US ticker: the run fetched nothing and
    # still asked the LLM. It is now unsupported, so the whole run is refused up front.
    import main

    assert main._classify_stock_list_tokens(["AAPL", token], entry_label="--stocks") is None

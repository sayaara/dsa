# -*- coding: utf-8 -*-
"""Add the S&P/TSX Composite constituents to the bundled stock index.

The bundled index (``apps/dsa-web/public/stocks.index.json``) drives Web autocomplete,
symbol-to-name lookup and English name resolution. Its Canadian rows started as a
hand-curated list; this script adds every S&P/TSX Composite constituent that is not
already there.

Source: the "List of companies" table of the English Wikipedia article
"S&P/TSX Composite Index" (text under CC BY-SA 4.0; only the ticker and company name
are used). TMX's own listed-companies file is not used because its terms forbid
redistribution (see HANDOFF III.98).

Rules:

* Tickers are converted to Yahoo Finance form: ``AP.UN`` -> ``AP-UN.TO``, ``ACO.X`` ->
  ``ACO-X.TO``, ``AEM`` -> ``AEM.TO``.
* Symbols in ``NO_LONGER_TRADED`` (no Yahoo prices any more) are skipped.
* Existing rows are never changed or removed (the curated names and ETFs stay), and a
  company that leaves the index keeps its row.
* New rows use the same layout as the curated rows and the file keeps its code order
  and one-row-per-line format.

Usage::

    # Fetch the current article revision and update the index
    python scripts/generate_ca_stock_index.py

    # Pin a revision, or work offline from a saved API response or wikitext file
    python scripts/generate_ca_stock_index.py --revision 1234567890
    python scripts/generate_ca_stock_index.py --input tsx.wikitext

    # Report what would change without writing
    python scripts/generate_ca_stock_index.py --dry-run
"""

from __future__ import annotations

import argparse
import html
import json
import re
import sys
from pathlib import Path
from typing import List, Optional, Tuple

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

INDEX_PATH = REPO_ROOT / "apps" / "dsa-web" / "public" / "stocks.index.json"
ARTICLE_TITLE = "S&P/TSX Composite Index"
WIKIPEDIA_API = "https://en.wikipedia.org/w/api.php"
USER_AGENT = "dsa-ca-index-generator/1.0 (https://github.com/sayaara/dsa)"

_TABLE_RE = re.compile(r'\{\|[^\n]*id="components".*?\n\|\}', re.S)
_TICKER_RE = re.compile(r"\{\{\s*TSX link\s*\|\s*([^}|]+?)\s*\}\}", re.I)
_WIKI_LINK_RE = re.compile(r"\[\[(?:[^\]|]*\|)?([^\]]*)\]\]")
_REF_RE = re.compile(r"<ref[^>]*/>|<ref[^>]*>.*?</ref>", re.S)
_TEMPLATE_RE = re.compile(r"\{\{[^{}]*\}\}")
_TSX_TICKER_RE = re.compile(r"[A-Z0-9]{1,6}(?:\.[A-Z]{1,2})?")

# Constituents of the article revision that Yahoo no longer prices: the last bars were
# 2026-07-10 to 2026-09-02 (checked 2026-10-09). They are not added.
NO_LONGER_TRADED = frozenset({"BLX.TO", "IIP-UN.TO", "OLA.TO", "SES.TO"})


def fetch_wikitext(revision: Optional[int] = None) -> Tuple[str, int]:
    """Return ``(wikitext, revision_id)`` of the article from the Wikipedia API."""
    import requests

    params = {"action": "parse", "prop": "wikitext|revid", "format": "json", "formatversion": "2"}
    if revision is not None:
        params["oldid"] = str(revision)
    else:
        params["page"] = ARTICLE_TITLE
    response = requests.get(WIKIPEDIA_API, params=params, headers={"User-Agent": USER_AGENT}, timeout=30)
    response.raise_for_status()
    payload = response.json()
    if "error" in payload:
        raise RuntimeError(f"Wikipedia API error: {payload['error']}")
    parsed = payload["parse"]
    return parsed["wikitext"], int(parsed["revid"])


def read_input(path: Path) -> Tuple[str, Optional[int]]:
    """Read wikitext from a saved API response (JSON) or a plain wikitext file."""
    text = path.read_text(encoding="utf-8")
    try:
        payload = json.loads(text)
    except ValueError:
        return text, None
    parsed = payload["parse"]
    revid = parsed.get("revid")
    return parsed["wikitext"], int(revid) if revid is not None else None


def _clean_cell(cell: str) -> str:
    value = _REF_RE.sub("", cell)
    value = _WIKI_LINK_RE.sub(r"\1", value)
    value = _TEMPLATE_RE.sub("", value)
    # A cell may start with attributes: ``id=Foo| Foo Inc.``; keep the content only.
    value = value.rsplit("|", 1)[-1]
    value = re.sub(r"'{2,}", "", value)
    value = html.unescape(value)
    return " ".join(value.split())


def parse_constituents(wikitext: str) -> List[Tuple[str, str]]:
    """Return ``(tsx_ticker, company_name)`` pairs from the constituents table."""
    match = _TABLE_RE.search(wikitext)
    if match is None:
        raise ValueError('constituents table (id="components") not found')
    pairs: List[Tuple[str, str]] = []
    table = match.group(0).rsplit("\n|}", 1)[0]
    for block in table.split("\n|-")[1:]:
        line = block.strip()
        if not line.startswith("|"):
            continue
        cells = [cell.strip() for cell in line[1:].split("||")]
        if len(cells) < 2:
            raise ValueError(f"unexpected constituents row: {line!r}")
        ticker_match = _TICKER_RE.search(cells[0])
        if ticker_match is None:
            raise ValueError(f"no ticker in constituents row: {line!r}")
        ticker = ticker_match.group(1).strip().upper()
        if not _TSX_TICKER_RE.fullmatch(ticker):
            raise ValueError(f"unexpected TSX ticker {ticker!r}")
        name = _clean_cell(cells[1])
        if not name:
            raise ValueError(f"no company name for {ticker!r}")
        pairs.append((ticker, name))
    if not pairs:
        raise ValueError("constituents table has no rows")
    return pairs


def to_yahoo_symbol(tsx_ticker: str) -> str:
    """``AP.UN`` -> ``AP-UN.TO``; ``AEM`` -> ``AEM.TO``."""
    return f"{tsx_ticker.strip().upper().replace('.', '-')}.TO"


def build_row(symbol: str, name: str) -> list:
    upper = name.upper()
    return [symbol, symbol, name, upper, upper, [], "CA", "stock", True, 100]


def merge_rows(rows: list, constituents: List[Tuple[str, str]]) -> Tuple[list, List[list]]:
    """Return ``(merged_rows, added_rows)``; existing codes are left untouched."""
    from src.services.market_symbol_utils import get_suffix_market

    existing = {str(row[0]).upper() for row in rows}
    added: List[list] = []
    for ticker, name in constituents:
        symbol = to_yahoo_symbol(ticker)
        if get_suffix_market(symbol) != "ca":
            raise ValueError(f"{symbol!r} is not a valid Canadian symbol")
        if symbol in existing or symbol in NO_LONGER_TRADED:
            continue
        existing.add(symbol)
        added.append(build_row(symbol, name))
    merged = sorted(rows + added, key=lambda row: str(row[0]))
    return merged, added


def serialize_rows(rows: list) -> str:
    body = ",\n".join(json.dumps(row, ensure_ascii=False, separators=(",", ":")) for row in rows)
    return f"[\n{body}\n]\n"


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--input", type=Path, help="saved API response (JSON) or wikitext file")
    parser.add_argument("--revision", type=int, help="Wikipedia revision id to fetch")
    parser.add_argument("--index", type=Path, default=INDEX_PATH, help="stock index to update")
    parser.add_argument("--dry-run", action="store_true", help="report the changes without writing")
    args = parser.parse_args(argv)

    if args.input is not None:
        wikitext, revid = read_input(args.input)
    else:
        wikitext, revid = fetch_wikitext(args.revision)
    constituents = parse_constituents(wikitext)

    rows = json.loads(args.index.read_text(encoding="utf-8"))
    merged, added = merge_rows(rows, constituents)

    print(f"Source: {ARTICLE_TITLE!r} revision {revid if revid is not None else 'unknown'}")
    skipped = sum(1 for ticker, _name in constituents if to_yahoo_symbol(ticker) in NO_LONGER_TRADED)
    print(
        f"Constituents: {len(constituents)}; no longer traded: {skipped}; "
        f"already in the index: {len(constituents) - len(added) - skipped}; added: {len(added)}"
    )
    for row in added:
        print(f"  + {row[0]}  {row[2]}")
    if args.dry_run or not added:
        return 0

    from src.data.stock_index_loader import validate_stock_index_payload

    validate_stock_index_payload(merged)
    args.index.write_text(serialize_rows(merged), encoding="utf-8")
    print(f"Wrote {args.index}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

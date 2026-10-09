# -*- coding: utf-8 -*-
"""The S&P/TSX Composite generator for the bundled stock index (audit B4)."""

import json
from pathlib import Path

import pytest

from scripts.generate_ca_stock_index import (
    INDEX_PATH,
    NO_LONGER_TRADED,
    main,
    merge_rows,
    parse_constituents,
    serialize_rows,
    to_yahoo_symbol,
)

_WIKITEXT = """
==List of companies==
{| class="wikitable sortable" id="components"
! Ticker!! Company !! Sector <ref name="TMX">GICS</ref> !! Industry <ref name="TMX"/>
|-
| {{TSX link|AEM}} || [[Agnico Eagle|Agnico Eagle Mines Limited]] || Materials || Metals & Mining
|-
| {{TSX link|AC}} || [[Air Canada]] || Industrials || Transportation
|-
| {{TSX link|AP.UN}} || Allied Properties Real Estate Investment Trust || Real Estate || REITs
|-
| {{TSX link|ACO.X}} || [[ATCO|ATCO Ltd.]]<ref>note</ref> || Utilities || Regulated Utilities
|-
| {{TSX link|EIF}} ||id=Exchange Income Corporation| Exchange Income Corporation || Industrials || Transportation
|-
| {{TSX link|HR.UN}} || H&amp;R Real Estate Investment Trust || Real Estate || REITs
|-
| {{TSX link|OLA}} || Orla Mining Ltd. || Materials || Metals & Mining
|-
|}

== Exchange-traded funds ==
{| class="wikitable"
|-
| {{TSX link|XIU}} || iShares S&P/TSX 60 Index ETF
|}
"""


def _row(code, name):
    return [code, code, name, name.upper(), name.upper(), [], "CA", "stock", True, 100]


def test_parse_constituents_reads_tickers_and_names_from_the_components_table():
    assert parse_constituents(_WIKITEXT) == [
        ("AEM", "Agnico Eagle Mines Limited"),
        ("AC", "Air Canada"),
        ("AP.UN", "Allied Properties Real Estate Investment Trust"),
        ("ACO.X", "ATCO Ltd."),
        ("EIF", "Exchange Income Corporation"),
        ("HR.UN", "H&R Real Estate Investment Trust"),
        ("OLA", "Orla Mining Ltd."),
    ]


@pytest.mark.parametrize(
    "wikitext",
    [
        "no table here",
        '{| class="wikitable" id="components"\n! Ticker !! Company\n|-\n| AEM || Agnico\n|}',
        '{| class="wikitable" id="components"\n! Ticker !! Company\n|-\n| {{TSX link|AEM}} || \n|}',
        '{| class="wikitable" id="components"\n! Ticker !! Company\n|-\n| {{TSX link|AE M}} || X\n|}',
    ],
)
def test_parse_constituents_fails_loudly_on_an_unexpected_table(wikitext):
    with pytest.raises(ValueError):
        parse_constituents(wikitext)


@pytest.mark.parametrize(
    "ticker, symbol",
    [("AEM", "AEM.TO"), ("AP.UN", "AP-UN.TO"), ("ACO.X", "ACO-X.TO"), ("bbd.b", "BBD-B.TO")],
)
def test_to_yahoo_symbol(ticker, symbol):
    assert to_yahoo_symbol(ticker) == symbol


def test_merge_adds_new_symbols_keeps_existing_rows_and_skips_untraded_ones():
    curated = _row("AEM.TO", "Agnico Eagle Mines Limited (curated)")
    rows = [_row("AAPL", "APPLE")[:6] + ["US", "stock", True, 100], curated, _row("ZEB.TO", "BMO ETF")]
    merged, added = merge_rows(rows, parse_constituents(_WIKITEXT))

    added_codes = [row[0] for row in added]
    assert added_codes == ["AC.TO", "AP-UN.TO", "ACO-X.TO", "EIF.TO", "HR-UN.TO"]
    assert "OLA.TO" in NO_LONGER_TRADED and "OLA.TO" not in added_codes
    assert curated in merged and _row("ZEB.TO", "BMO ETF") in merged
    assert [row[0] for row in merged] == sorted(row[0] for row in merged)
    assert merged[merged.index(added[0])] == _row("AC.TO", "Air Canada")


def test_main_updates_an_index_file_from_saved_wikitext(tmp_path: Path, capsys, monkeypatch):
    import src.data.stock_index_loader as loader

    validated = []
    monkeypatch.setattr(loader, "validate_stock_index_payload", validated.append)
    source = tmp_path / "tsx.wikitext"
    source.write_text(_WIKITEXT, encoding="utf-8")
    index = tmp_path / "stocks.index.json"
    index.write_text(serialize_rows([_row("AEM.TO", "Agnico Eagle Mines Limited")]), encoding="utf-8")

    assert main(["--input", str(source), "--index", str(index), "--dry-run"]) == 0
    assert len(json.loads(index.read_text(encoding="utf-8"))) == 1

    assert main(["--input", str(source), "--index", str(index)]) == 0
    codes = [row[0] for row in json.loads(index.read_text(encoding="utf-8"))]
    assert codes == ["AC.TO", "ACO-X.TO", "AEM.TO", "AP-UN.TO", "EIF.TO", "HR-UN.TO"]
    assert "added: 5" in capsys.readouterr().out
    assert len(validated) == 1 and len(validated[0]) == 6


def test_bundled_index_keeps_the_generator_format():
    raw = INDEX_PATH.read_text(encoding="utf-8")
    assert serialize_rows(json.loads(raw)) == raw

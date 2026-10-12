#!/usr/bin/env python3
"""List candidate interlisted pairs (TSX + US exchange) from the bundled stock index.

The output is for review only: ``src/data/interlisted.py`` holds the reviewed pairs, and
this script never edits it. Run it after the stock index changes and review each line:

- ``NEW``: a candidate that is neither in ``INTERLISTED_PAIRS`` nor rejected below. Add it
  only when both rows are the same company and share class, and the US row is an exchange
  listing (not OTC or a depositary receipt); otherwise add it to the rejected set. A shared
  ticker alone proves nothing (``T.TO`` TELUS, ``T`` AT&T).
- ``MISSING``: a reviewed pair whose symbol is no longer in the index.

Candidates are US rows (OTC excluded) with the same base ticker as a TSX row, or whose
name starts with the same first two words.

Usage: python scripts/suggest_interlisted_pairs.py [--index PATH]
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from src.data.interlisted import INTERLISTED_PAIRS  # noqa: E402

# Candidates reviewed on 2026-10-12 and rejected: different companies that share a ticker or
# name words, depositary receipts, units and rights.
_REVIEWED_NOT_INTERLISTED = {
    ("AQN.TO", "AQNU"),
    ("ARE.TO", "ARE"),
    ("ARIS.TO", "ARIS"),
    ("ARX.TO", "ARX"),
    ("BIP-UN.TO", "BIPC"),
    ("BYD.TO", "BYD"),
    ("CCO.TO", "CCO"),
    ("CG.TO", "CG"),
    ("CNR.TO", "CNR"),
    ("CS.TO", "CS"),
    ("EDR.TO", "EDR"),
    ("FCR-UN.TO", "FCPB"),
    ("H.TO", "H"),
    ("HR-UN.TO", "HEES"),
    ("HR-UN.TO", "HRB"),
    ("IAG.TO", "IAG"),
    ("IMG.TO", "IMG"),
    ("JWEL.TO", "JWEL"),
    ("K.TO", "K"),
    ("KEY.TO", "KEY"),
    ("L.TO", "L"),
    ("L.TO", "LOBLY"),
    ("LB.TO", "LB"),
    ("LIF.TO", "LIF"),
    ("MFI.TO", "MFI"),
    ("MG.TO", "MG"),
    ("MX.TO", "MX"),
    ("NA.TO", "NA"),
    ("NA.TO", "NBHC"),
    ("NWC.TO", "NWOL"),
    ("PAAS.TO", "PAASF"),
    ("PBH.TO", "PBH"),
    ("PET.TO", "PET"),
    ("PPL.TO", "PPL"),
    ("RY.TO", "RYPRT"),
    ("SAP.TO", "SAP"),
    ("SJ.TO", "SJ"),
    ("SPB.TO", "SPB"),
    ("T.TO", "T"),
    ("TKO.TO", "TKO"),
    ("TXG.TO", "TXG"),
    ("X.TO", "X"),
}

DEFAULT_INDEX = REPO_ROOT / "apps" / "dsa-web" / "public" / "stocks.index.json"
_IGNORED_WORDS = {
    "inc", "incorporated", "corp", "corporation", "co", "company", "ltd", "limited", "plc",
    "llc", "the", "a", "b", "cl", "class", "ord", "shs", "sbvtg", "of",
}


def _name_words(name: str) -> list:
    text = re.sub(r"\([^)]*\)", " ", name.lower()).replace("&", " and ")
    return [word for word in re.sub(r"[^a-z0-9]+", " ", text).split() if word not in _IGNORED_WORDS]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--index", type=Path, default=DEFAULT_INDEX, help="stock index JSON")
    args = parser.parse_args()

    rows = [row for row in json.loads(args.index.read_text(encoding="utf-8")) if row[8] is not False]
    codes = {row[0] for row in rows}
    us_rows = [row for row in rows if row[6] == "US" and "(OTC)" not in row[2]]
    tsx_rows = [row for row in rows if row[6] == "CA" and row[0].endswith(".TO")]
    reviewed = set(INTERLISTED_PAIRS) | _REVIEWED_NOT_INTERLISTED

    for tsx_code, us_code in INTERLISTED_PAIRS:
        for code in (tsx_code, us_code):
            if code not in codes:
                print(f"MISSING  {tsx_code} / {us_code}: {code} is not in the index")

    for tsx in tsx_rows:
        base = tsx[0][: -len(".TO")]
        words = _name_words(tsx[2])
        for us in us_rows:
            us_words = _name_words(us[2])
            same_ticker = us[0] == base
            same_name = bool(words) and us_words[:2] == words[:2]
            if (same_ticker or same_name) and (tsx[0], us[0]) not in reviewed:
                print(f"NEW      {tsx[0]} ({tsx[2]})  /  {us[0]} ({us[2]})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

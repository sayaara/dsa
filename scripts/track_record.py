#!/usr/bin/env python3
"""Forward-only track record: record today's calls, or score the ledger so far.

``record`` runs after ``main.py`` in the same environment and database. It analyzes the
extra track-record stocks (``TRACK_RECORD_STOCKS``, not notified), then, for every stock
analyzed since ``--since``, appends the DSA call the reports showed and one plain-prompt
call on the same stored snapshot to the JSONL ledger. Markets closed today are skipped,
like ``main.py``, unless ``--force-run``.

``score`` fetches daily bars for every ledger stock and benchmark and writes a Markdown
report (entry at the next session's open, excess return against the market benchmark).

The ledger format, the plain prompt and the metrics are described in docs/track-record.md.

Usage:
    python scripts/track_record.py record --ledger track-record/ledger [--since ISO] [--force-run]
    python scripts/track_record.py score --ledger track-record/ledger [--out track-record/REPORT.md]
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from src.services import track_record as tr  # noqa: E402

logger = logging.getLogger("track_record")

# Room for the JSON reply; the plain arm asks for one short object.
_PLAIN_MAX_TOKENS = 600


def _parse_since(value: Optional[str]) -> datetime:
    if not value:
        return datetime.now() - timedelta(hours=26)
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    # analysis_history.created_at is naive local time.
    return parsed.astimezone().replace(tzinfo=None) if parsed.tzinfo else parsed


def _extra_codes(raw: str, analyzed: List[str], force_run: bool) -> List[str]:
    from src.core.trading_calendar import get_market_for_stock, get_open_markets_today
    from src.services.stock_list_parser import split_stock_list

    # Same normalization as STOCK_LIST in src/config.py.
    codes = [(c or "").strip().upper() for c in split_stock_list(raw or "") if (c or "").strip()]
    open_markets = None if force_run else get_open_markets_today()
    extras: List[str] = []
    for code in codes:
        if code in analyzed or code in extras:
            continue
        if open_markets is not None and get_market_for_stock(code) not in open_markets:
            logger.info("[track_record] %s: market closed today, skipped", code)
            continue
        extras.append(code)
    return extras


def _latest_rows_since(db, since: datetime) -> list:
    rows = db.get_analysis_history(days=3, limit=500)
    latest: Dict[str, object] = {}
    for row in rows:
        created = getattr(row, "created_at", None)
        if created is None or created < since or getattr(row, "report_type", None) == "market_review":
            continue
        code = str(getattr(row, "code", "") or "")
        current = latest.get(code)
        if current is None or created > getattr(current, "created_at"):
            latest[code] = row
    return list(latest.values())


def record(args: argparse.Namespace) -> int:
    from src.analyzer import GeminiAnalyzer
    from src.config import get_config
    from src.core.pipeline import StockAnalysisPipeline
    from src.storage import get_db

    config = get_config()
    if not args.force_run and getattr(config, "trading_day_check_enabled", True):
        from src.core.trading_calendar import get_open_markets_today

        if not get_open_markets_today():
            logger.info("[track_record] no supported market is open today; nothing to record")
            return 0
    since = _parse_since(args.since)
    extras = _extra_codes(args.extra_stocks, list(config.stock_list or []), args.force_run)
    if extras:
        logger.info("[track_record] analyzing %d extra stock(s): %s", len(extras), ", ".join(extras))
        pipeline = StockAnalysisPipeline(
            config=config,
            max_workers=1,
            query_source="track_record",
            save_context_snapshot=True,
            daily_market_context_enabled=True,
            daily_market_context_allow_generate=False,
        )
        pipeline.run(stock_codes=extras, send_notification=False)

    rows = _latest_rows_since(get_db(), since)
    if not rows:
        logger.warning("[track_record] no stock analysis since %s; nothing recorded", since.isoformat())
        return 1

    analyzer = GeminiAnalyzer(config=config)
    entries = []
    for row in rows:
        dsa = tr.dsa_entry(row)
        if dsa is None:
            logger.warning("[track_record] %s: no usable DSA call (failed analysis or no snapshot)", row.code)
            continue
        entries.append(dsa)
        context, news = tr.snapshot_from_record(row)
        prompt = tr.build_plain_prompt(row.code, getattr(row, "name", None), context, news)
        try:
            generated = analyzer.generate_text_with_metadata(prompt, max_tokens=_PLAIN_MAX_TOKENS)
        except Exception as exc:  # one failed call must not drop the other stocks
            logger.warning("[track_record] %s: plain call failed: %s", row.code, exc)
            continue
        reply = tr.parse_plain_reply(getattr(generated, "text", None))
        if reply is None:
            logger.warning("[track_record] %s: plain reply was not a valid decision object", row.code)
            continue
        plain = tr.plain_entry(row, reply, model=getattr(generated, "model", None))
        if plain is not None:
            entries.append(plain)

    written = tr.append_entries(Path(args.ledger), entries)
    logger.info("[track_record] %d new ledger line(s) from %d stock(s)", written, len(rows))
    return 0


def _bars(symbol: str, start: date, end: date) -> List[tr.Bar]:
    from data_provider.base import DataFetcherManager

    frame, _source = DataFetcherManager().get_daily_data(
        symbol, start_date=start.isoformat(), end_date=end.isoformat()
    )
    bars: List[tr.Bar] = []
    if frame is None or frame.empty:
        return bars
    for _, item in frame.iterrows():
        try:
            bars.append(tr.Bar(date=str(item["date"])[:10], open=float(item["open"]), close=float(item["close"])))
        except (KeyError, TypeError, ValueError):
            continue
    return bars


def score(args: argparse.Namespace) -> int:
    entries = tr.load_ledger(Path(args.ledger))
    if not entries:
        print(f"no ledger lines in {args.ledger}")
        return 1
    first = min(date.fromisoformat(str(e["as_of"])) for e in entries)
    end = date.today() + timedelta(days=1)
    bars_by_symbol: Dict[str, List[tr.Bar]] = {}
    for symbol in sorted({str(e["code"]) for e in entries} | {str(e["benchmark"]) for e in entries}):
        try:
            bars_by_symbol[symbol] = _bars(symbol, first, end)
        except Exception as exc:  # report what can be scored
            logger.warning("[track_record] %s: price fetch failed: %s", symbol, exc)
    report = tr.render_report(tr.score_ledger(entries, bars_by_symbol), entries=entries)
    if args.out:
        Path(args.out).write_text(report, encoding="utf-8")
        print(f"wrote {args.out}")
    else:
        print(report)
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    rec = sub.add_parser("record", help="append today's DSA and plain calls to the ledger")
    rec.add_argument("--ledger", required=True, help="ledger directory (one JSONL file per month)")
    rec.add_argument("--since", help="only analyses created at or after this ISO time (default: 26 h ago)")
    rec.add_argument("--extra-stocks", default=os.getenv("TRACK_RECORD_STOCKS", ""),
                     help="extra stocks to analyze for the record only (default: TRACK_RECORD_STOCKS)")
    rec.add_argument("--force-run", action="store_true", help="analyze extra stocks even when their market is closed")
    rec.set_defaults(func=record)
    sc = sub.add_parser("score", help="score the ledger against the market benchmarks")
    sc.add_argument("--ledger", required=True)
    sc.add_argument("--out", help="write the Markdown report here instead of printing it")
    sc.set_defaults(func=score)
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())

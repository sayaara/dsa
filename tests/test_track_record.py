# -*- coding: utf-8 -*-
"""Forward-only track record (``src/services/track_record.py``): ledger lines and scoring."""

import json
from datetime import datetime
from types import SimpleNamespace

import pytest

from tests.litellm_stub import ensure_litellm_stub

ensure_litellm_stub()

from scripts import track_record as cli  # noqa: E402
from src.services import track_record as tr  # noqa: E402


def _record(code="AAPL", score=62, advice="Hold", raw_extra=None, report_type="simple", trend=None, news="News."):
    context = {
        "code": code,
        "date": "2026-10-23",
        "today": {"close": 100.0, "date": "2026-10-23"},
        "trend_analysis": trend or {"ma_alignment": "MA5>MA10>MA20", "signal_score": 66, "buy_signal": "Buy",
                                    "signal_reasons": ["Trend intact"]},
    }
    raw = {"operation_advice": advice, "success": True, "confidence_level": "Medium", "model_used": "m-1"}
    raw.update(raw_extra or {})
    return SimpleNamespace(
        id=7,
        code=code,
        name="Apple Inc.",
        report_type=report_type,
        sentiment_score=score,
        operation_advice=advice,
        raw_result=json.dumps(raw),
        context_snapshot=json.dumps({"enhanced_context": context, "news_content": news}),
        news_content=None,
    )


def test_dsa_entry_records_the_displayed_action_and_the_market_benchmark():
    entry = tr.dsa_entry(_record(score=62, advice="Hold"))

    # Hold at 62 with no guardrail reason displays as Buy (decision_scale), so it is recorded as Buy.
    assert entry["arm"] == "dsa"
    assert (entry["action"], entry["decision"], entry["score"]) == ("buy", "buy", 62)
    assert (entry["as_of"], entry["market"], entry["benchmark"]) == ("2026-10-23", "us", "SPY")
    assert entry["reference_close"] == 100.0 and entry["model"] == "m-1"


def test_dsa_entry_keeps_a_neutral_action_with_a_recorded_reason():
    entry = tr.dsa_entry(_record(code="RY.TO", score=62, advice="Hold",
                                 raw_extra={"dashboard": {"decision_stability": {"reason": "Near resistance"}}}))

    assert (entry["action"], entry["decision"]) == ("hold", "hold")
    assert (entry["market"], entry["benchmark"]) == ("ca", "XIU.TO")


@pytest.mark.parametrize(
    "record",
    [
        _record(report_type="market_review"),
        _record(raw_extra={"success": False}),
        SimpleNamespace(id=1, code="AAPL", report_type="simple", sentiment_score=60, operation_advice="Hold",
                        raw_result="{}", context_snapshot=None, news_content=None),
    ],
    ids=["market review", "failed analysis", "no snapshot"],
)
def test_dsa_entry_skips_rows_that_are_not_a_stock_call(record):
    assert tr.dsa_entry(record) is None


def test_plain_prompt_hides_dsa_scoring_and_keeps_the_data_and_news():
    record = _record(news="2026-10-22 Apple beats estimates.")
    context, news = tr.snapshot_from_record(record)

    prompt = tr.build_plain_prompt("AAPL", "Apple Inc.", context, news)

    for hidden in ("signal_score", "buy_signal", "signal_reasons"):
        assert hidden not in prompt
    assert "MA5>MA10>MA20" in prompt and "Apple beats estimates" in prompt
    assert '"decision": "buy" | "hold" | "sell"' in prompt
    assert "No news was retrieved." in tr.build_plain_prompt("AAPL", None, context, None)


@pytest.mark.parametrize(
    "text, expected",
    [
        ('{"decision": "Buy", "score": 71, "confidence": "High", "rationale": "Breakout."}', ("buy", 71)),
        ('Here it is:\n```json\n{"decision": "sell", "score": 22.6}\n```', ("sell", 23)),
        ('{"note": 1} then {"decision": "hold", "score": 50}', ("hold", 50)),
        ('{"decision": "watch", "score": 50}', None),
        ('{"decision": "buy", "score": 140}', None),
        ("no json at all", None),
        ("", None),
    ],
)
def test_parse_plain_reply(text, expected):
    reply = tr.parse_plain_reply(text)
    assert (None if reply is None else (reply["decision"], reply["score"])) == expected


def test_append_entries_is_append_only_and_keeps_the_first_call_of_a_day(tmp_path):
    record = _record()
    first = [tr.dsa_entry(record), tr.plain_entry(record, {"decision": "sell", "score": 30}, model="m-1")]

    assert tr.append_entries(tmp_path, first) == 2
    rerun = tr.plain_entry(record, {"decision": "buy", "score": 80}, model="m-1")
    assert tr.append_entries(tmp_path, [rerun]) == 0

    assert [p.name for p in tmp_path.iterdir()] == ["2026-10.jsonl"]
    plain = [e for e in tr.load_ledger(tmp_path) if e["arm"] == "plain"]
    assert [(e["decision"], e["score"]) for e in plain] == [("sell", 30)]


def _bars(prices):
    # prices: list of (date, open, close)
    return [tr.Bar(date=d, open=o, close=c) for d, o, c in prices]


SESSIONS = ["2026-10-23", "2026-10-26", "2026-10-27", "2026-10-28"]


def test_forward_return_enters_at_the_next_open_and_waits_for_the_horizon():
    bars = _bars([("2026-10-23", 99, 100), ("2026-10-26", 101, 102), ("2026-10-27", 103, 104), ("2026-10-28", 105, 110)])

    assert tr.forward_return(bars, "2026-10-23", 1) == ("2026-10-26", "2026-10-26", pytest.approx(102 / 101 - 1))
    assert tr.forward_return(bars, "2026-10-23", 3) == ("2026-10-26", "2026-10-28", pytest.approx(110 / 101 - 1))
    assert tr.forward_return(bars, "2026-10-23", 4) is None  # not mature
    # A holiday or weekend as_of enters on the next real session.
    assert tr.forward_return(bars, "2026-10-24", 1)[0] == "2026-10-26"


def test_scoring_measures_excess_against_the_benchmark_per_arm():
    stock_up = _bars([(d, 100, 100 + 10 * i) for i, d in enumerate(SESSIONS)])
    stock_down = _bars([(d, 100, 100 - 10 * i) for i, d in enumerate(SESSIONS)])
    flat = _bars([(d, 100, 100) for d in SESSIONS])
    bars = {"UP": stock_up, "DOWN": stock_down, "SPY": flat}

    def call(arm, code, decision, score):
        return {"arm": arm, "code": code, "benchmark": "SPY", "as_of": "2026-10-23", "decision": decision,
                "score": score}

    entries = [
        call("dsa", "UP", "buy", 80), call("dsa", "DOWN", "sell", 20),
        call("plain", "UP", "sell", 30), call("plain", "DOWN", "buy", 70),
    ]

    rows = tr.scored_calls(entries, bars, horizon=1)
    up = next(r for r in rows if r["arm"] == "dsa" and r["code"] == "UP")
    assert up["stock_return"] == pytest.approx(0.10) and up["excess"] == pytest.approx(0.10)

    summary = tr.summarize(rows)
    assert summary["dsa"]["buy_hit_rate"] == 1.0 and summary["dsa"]["sell_hit_rate"] == 1.0
    assert summary["plain"]["buy_hit_rate"] == 0.0 and summary["plain"]["sell_hit_rate"] == 0.0
    assert summary["dsa"]["by_decision"]["buy"] == {"n": 1, "mean_excess": pytest.approx(0.10)}
    # Two calls are too few for a rank correlation.
    assert summary["dsa"]["score_excess_spearman"] is None

    report = tr.render_report(tr.score_ledger(entries, bars, horizons=(1,)), entries=entries)
    assert "## 1 trading days" in report and "| dsa | 2 |" in report and "| plain | 2 |" in report


def test_calls_without_benchmark_prices_are_not_scored():
    bars = {"UP": _bars([(d, 100, 101) for d in SESSIONS])}
    entry = {"arm": "dsa", "code": "UP", "benchmark": "SPY", "as_of": "2026-10-23", "decision": "buy", "score": 70}

    assert tr.scored_calls([entry], bars, horizon=1) == []


@pytest.mark.parametrize(
    "xs, ys, expected",
    [
        ([1, 2, 3, 4], [10, 20, 30, 40], 1.0),
        ([1, 2, 3, 4], [40, 30, 20, 10], -1.0),
        ([1, 1, 2, 2], [1, 2, 3, 4], pytest.approx(0.894427, abs=1e-6)),
        ([5, 5, 5], [1, 2, 3], None),
        ([1, 2], [1, 2], None),
    ],
)
def test_spearman(xs, ys, expected):
    assert tr.spearman(xs, ys) == expected


# ---------- CLI glue (scripts/track_record.py) ----------


def test_extra_codes_skip_emailed_duplicates_and_closed_markets(monkeypatch):
    import src.core.trading_calendar as calendar

    monkeypatch.setattr(calendar, "get_open_markets_today", lambda: {"us"})

    assert cli._extra_codes("tsla, AAPL,TSLA,TD.TO", ["AAPL"], force_run=False) == ["TSLA"]
    assert cli._extra_codes("tsla, AAPL,TSLA,TD.TO", ["AAPL"], force_run=True) == ["TSLA", "TD.TO"]
    assert cli._extra_codes("", ["AAPL"], force_run=False) == []


def test_latest_rows_since_keeps_each_stocks_latest_analysis():
    def row(code, hour, report_type="simple"):
        return SimpleNamespace(code=code, created_at=datetime(2026, 10, 23, hour), report_type=report_type)

    rows = [row("AAPL", 17), row("AAPL", 18), row("RY.TO", 9), row("MSFT", 18, "market_review"), row("NVDA", 19)]
    db = SimpleNamespace(get_analysis_history=lambda days, limit: rows)

    latest = cli._latest_rows_since(db, datetime(2026, 10, 23, 12))

    assert sorted((r.code, r.created_at.hour) for r in latest) == [("AAPL", 18), ("NVDA", 19)]

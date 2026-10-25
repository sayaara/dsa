# Forward Track Record

The track record answers one question with evidence instead of opinion: **do DSA's calls beat a plain prompt to the same model on the same data, and do either beat holding the market?** It is forward-only. Each day's calls are written down before the outcome exists and are never rewritten, so a later score cannot be produced with hindsight.

It is opt-in and off by default. The daily analysis, its reports and its notifications are unchanged whether it is on or off.

## Why it is needed

The GitHub Actions runner starts with an empty database and deletes it when the job ends, so analysis history, decision signals and backtest outcomes never accumulate in an Actions deployment. The track record keeps its own small ledger on a dedicated branch of the repository instead.

## What is recorded

After `main.py` finishes, `scripts/track_record.py record` runs in the same job and database:

1. It analyzes the extra stocks in `TRACK_RECORD_STOCKS` (the normal pipeline, without notifications). Stocks whose market is closed today are skipped, like `main.py`, unless the run is forced.
2. For every stock analyzed in this run (the emailed `STOCK_LIST` and the extra stocks), it appends two lines to the ledger:
   - `dsa`: the final action the reports showed, resolved by the same rule as every surface (`display_action_fields`, see [DecisionSignal Topic](decision-signals.md)), and its score.
   - `plain`: one call to the same model with the stored snapshot (the `enhanced_context` and news of that analysis) and a short neutral prompt (`PLAIN_PROMPT_TEMPLATE` in `src/services/track_record.py`) that asks for a decision, a 0-100 score, a confidence and one sentence. DSA's own rule-based outputs (`signal_score`, `buy_signal`, `signal_reasons`) are removed from that snapshot, because they are part of the analysis layer under test.

A day already in the ledger is kept as first written; a re-run the same day adds nothing.

### Ledger format

One JSON object per line in `ledger/<YYYY-MM>.jsonl` on the `track-record` branch:

| Field | Meaning |
| --- | --- |
| `schema_version` | `1` |
| `as_of` | The session the analysis saw (`enhanced_context.date`) |
| `code`, `market` | Stock and market (`us`, `ca`) |
| `benchmark` | The market's benchmark ETF (`MarketSpec.benchmark_symbol`: `SPY`, `XIU.TO`) |
| `arm` | `dsa` or `plain` |
| `action`, `decision` | Eight-state action (`dsa`) and the `buy`/`hold`/`sell` bucket both arms are compared on |
| `score`, `confidence` | 0-100 score and the stated confidence |
| `rationale` | The plain arm's one sentence |
| `reference_close`, `model`, `recorded_at`, `source_report_id` | Context for audits |

## How it is scored

`python scripts/track_record.py score --ledger <dir> [--out REPORT.md]` fetches adjusted daily bars for every ledger stock and benchmark (the normal data providers) and reports, per arm and for 5, 20 and 60 trading days:

- **Entry** at the open of the first session after `as_of` (the run happens after the close, so that close could not be traded); **exit** at the close of the N-th session. A call counts only once its horizon has passed.
- **Excess return**: the stock's return minus its benchmark's over the same window. Adjusted prices include dividends on both sides.
- Mean excess by decision, the buy hit rate (excess > 0), the sell hit rate (excess < 0), and the Spearman rank correlation between score and excess (does a higher score mean a better outcome).

Small samples are noise. With about 14 stocks a day and mostly `hold` decisions, expect several months of mature calls before a difference between the arms means anything.

## Enabling it in GitHub Actions

Repository variables (Settings -> Secrets and variables -> Actions -> Variables):

| Variable | Value |
| --- | --- |
| `TRACK_RECORD_ENABLED` | `true` |
| `TRACK_RECORD_STOCKS` | Extra stocks for the record only, comma-separated, e.g. `TSLA,AMZN,GOOGL,META,JPM,V,TD.TO,SHOP.TO,ENB.TO,CNQ.TO` |
| `ANALYSIS_TIMEOUT_MINUTES` | `45` (each extra stock adds about a minute to the job; the default limit is 30) |

The daily job then checks out the `track-record` branch (or starts it) before the analysis and pushes the new lines after it; the job has `contents: write` for that push. A failed record step leaves a warning and never fails the analysis.

Cost per run: one full analysis per extra stock and one short plain call per analyzed stock, plus one news search per extra stock and the extra Actions minutes. The repository is private, so Actions minutes are billed to the owner.

## Running it locally

```bash
python main.py --no-notify
python scripts/track_record.py record --ledger track-record/ledger --extra-stocks TSLA,TD.TO
python scripts/track_record.py score --ledger track-record/ledger
```

`record` reads analyses from the configured database (`DATABASE_PATH`) created in the last 26 hours, or since `--since`.

## Rollback

Set `TRACK_RECORD_ENABLED` to anything but `true` (or delete it); the workflow skips every track-record step. The `track-record` branch can be kept as history or deleted.

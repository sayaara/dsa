# Single-stock research aggregation API

This document describes the backend contract stage of Issue #2279. The goal is to let the later `/stocks/:code` workspace consume data through a single endpoint, instead of assembling quotes, history, reports, intelligence, portfolio, and monitoring calls concurrently in the browser.

## Endpoint

`GET /api/v1/stocks/{stock_code}/profile?history_days=60`

The endpoint first normalizes the input to a canonical code. Real-time quotes, history, and the report chain use the canonical code. For intelligence and monitor records that an older entry point may have persisted under an alias, reads expand the repository's existing equivalent-code set and de-duplicate by ID:

- A-shares: `SH600519`, `600519.SH` and similar converge to `600519`. When the entry point already carries an explicit `SH` / `SZ` / `BJ`, later report, intelligence, and monitor alias expansion keeps that market identity. When an explicit exchange conflicts with the code rules (such as `600519.SZ`), the endpoint returns 400 rather than stripping the exchange and querying a different instrument.
- Hong Kong: `00700`, `00700.HK`, and `HK00700` converge to `HK00700`. When a cached position already declares `market=hk`, an older short form such as `700` is zero-padded before the identity comparison.
- US tickers normalize to the bare uppercase form, so both `aapl` and `AAPL.US` converge to `AAPL`; persisted reads still query the bare ticker along with equivalent aliases such as `.US`.

The response contains six independent blocks - `quote`, `history`, `research`, `intelligence`, `portfolio`, and `monitors` - plus a top-level `evidence_quality` summary. Each block's `status` is restricted to:

| Status | Meaning |
| --- | --- |
| `fresh` | This request obtained usable data; it does not imply that every external source shares one timezone or refresh frequency |
| `partial` | The core information is usable but has an explicit limitation, for example only the report list without detail, or a portfolio relationship that comes only from cache |
| `unavailable` | No data was available this time; the reason is returned as a stable `limitations` code, exposing neither the raw exception nor any secret |

A failure in one optional block never removes the others. If the quote fails, historical reports, the structured ResearchArtifact, symbol intelligence, and monitoring rules can still be returned; if the latest report detail fails, `research.recent_reports` is still kept, `structured_report` is `null`, and the block is marked `latest_report_detail_unavailable`.

## Data sources and boundaries

- quote/history: reuses `StockService`; no new data fetcher is added.
- research: reuses `HistoryService` and the `ResearchArtifact` builder from #2291. The report query passes the market hint already resolved by the profile entry point down to the candidate-generation layer of `HistoryService`, keeping only bare-digit aliases that still resolve to the current market without a hint. For example `600519` stays compatible with older A-share records. When the market-scoped candidate set is empty, an empty page is returned directly rather than degrading to an unfiltered query. The artifact also reuses the context and raw result from the history detail, plus a separate fundamental-snapshot fallback, which preserves the dedicated earnings, dividend, and market-structure evidence along with their source counts.
- Service import boundary: the `api.v1` router is now exported lazily, so `StockProfileService -> ResearchArtifact schema` does not pull in every API endpoint in reverse. A CLI, a standalone script, or a unit test can import the profile service directly without importing `api.app` first.
- intelligence: reuses the symbol-scope query in `IntelligenceService`, and stays compatible with canonical codes, exchange prefixes and suffixes, Hong Kong prefixes and suffixes, mixed case. An ambiguous bare code that cannot be resolved back to the current market without a hint never enters a `global` query. Query aliases are de-duplicated by casefold identity, and the repository's symbol-only case-insensitive filter handles historical casing, which avoids duplicate count and select work. If any alias or market query fails, the block keeps a partial limitation, so an empty-but-successful result for the remaining queries is not misreported as confirmed absence of intelligence.
- portfolio: reads only `PortfolioRepository.list_cached_position_identities()`, and resolves an older bare code using each cached position's own market; a holding counts only when the market matches the profile identity. Opening a stock page never triggers a live valuation or a snapshot write, so the status is fixed at `partial` and includes `cached_positions_only`.
- monitors: reuses `AlertService.list_rules()`, aggregating pages with a case-insensitive symbol filter and de-duplicating `single_symbol` rules under the canonical code and its equivalent historical aliases.

This stage adds no Web routes or pages, wires up no Home/Watchlist/Screening/Portfolio/Report entry points, and includes no calendar events. The later Web PR must consume this endpoint and render each block status separately; multi-request page aggregation must not be reintroduced. Calendar events become a separate block once the #2307 contract lands.

## Rollback

Reverting this PR removes the profile schema, service, endpoint, tests, and documentation. There is no database migration, configuration change, or data cleanup step.

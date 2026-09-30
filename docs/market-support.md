# Market support and boundaries

## Primary and planned markets

| Market | Status | Data path |
|---|---|---|
| United States | **Primary** | Daily bars: Finnhub, Alpha Vantage, Yahoo Finance, Longbridge (Longbridge first when configured). Realtime: Yahoo Finance or Longbridge first, supplemented by Finnhub and Alpha Vantage. Fundamentals: Yahoo Finance. |
| Hong Kong | **Primary** | Daily bars: Yahoo Finance, Longbridge, Futu. Realtime: `futu,longbridge,yfinance` by default (Futu only when OpenD is configured). Fundamentals: Yahoo Finance. |
| Canada (TSX / TSXV) | Planned, priority 3 | Not implemented yet; expected to route through Yahoo Finance suffixes such as `.TO` and `.V`. |
| Mainland China (A-shares) | Legacy, scheduled for removal | efinance, AkShare, Tushare, Tencent, Pytdx, Baostock and TickFlow. HK no longer uses AkShare or Tushare by default; AkShare remains an opt-in HK realtime source through `FUTU_HK_REALTIME_SOURCE_PRIORITY`. |
| Japan / Korea / Taiwan | **Removed** | Codes such as `7203.T`, `005930.KS` and `2330.TW` are rejected as unsupported. |

Market-code predicates that do not depend on any regional fetcher live in `data_provider/market_codes.py`.

## Removed markets

Japan, Korea and Taiwan support was removed, including their Yahoo suffix routing, market-review regions,
trading calendars, Taiwan institutional-flow data, portfolio partial-valuation handling and the JP/KR
stock-index seed rows. `MARKET_REVIEW_REGION` now accepts `cn`, `hk`, `us` and `both`.

Stock codes with the removed suffixes (`.T`, `.KS`, `.KQ`, `.TW`, `.TWO`) are rejected with an
"exchange suffix ... is no longer supported" message instead of being reclassified as US or mainland codes.

## Suffix-market mechanism (for Canada)

The generic Yahoo suffix-market mechanism in `src/services/market_symbol_utils.py` was kept, with an empty
registry. Adding a market is one `SuffixMarketSpec` entry (for Canada, `("ca", ("TO", "V"), ...)`) plus its
trading-calendar exchange code, timezone and closing-auction window in `src/core/trading_calendar.py`, and adding
the market to the Yahoo entry in `DataFetcherManager._DAILY_MARKET_FETCHER_SUPPORT`.

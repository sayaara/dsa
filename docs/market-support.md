# Market support and boundaries

## Supported markets

| Market | Status | Data path |
|---|---|---|
| United States | **Primary** | Daily bars: Finnhub, Alpha Vantage, Yahoo Finance, Longbridge (Longbridge first when configured). Realtime: Yahoo Finance or Longbridge first, supplemented by Finnhub and Alpha Vantage. Fundamentals: Yahoo Finance. |
| Hong Kong | **Primary** | Daily bars: Yahoo Finance, Longbridge, Futu. Realtime: `futu,longbridge,yfinance` by default (Futu only when OpenD is configured). Fundamentals: Yahoo Finance. |
| Canada (TSX / TSXV / CSE / NEO) | **Supported** (analysis) | Yahoo Finance symbols with the `.TO`, `.V`, `.CN` and `.NE` suffixes (for example `RY.TO`, `SHOP.TO`, `ABX.V`, `TECK-B.TO`). Daily bars, realtime quotes and fundamentals come from Yahoo Finance only; the TSX trading calendar (XTSE, `America/Toronto`) drives the trading-day filter. About 60 large TSX names are in the bundled stock index for name search. Market review supports it as region `ca` (S&P/TSX Composite and TSX Venture Composite from Yahoo Finance); `MARKET_REVIEW_REGION` accepts `ca`, `hk`, `us` and `both` (all three). Bare symbols without a suffix are always read as US tickers, so write `RY.TO`, not `RY`. |
| Mainland China (A-shares) | **Removed** | Six-digit codes and the `sh`/`sz`/`bj`/`csi` prefix and suffix forms are rejected as unsupported; the China data fetchers were deleted. |
| Japan / Korea / Taiwan | **Removed** | Codes such as `7203.T`, `005930.KS` and `2330.TW` are rejected as unsupported. |

Market-code predicates that do not depend on any regional fetcher live in `data_provider/market_codes.py`.

## Removed markets

Japan, Korea and Taiwan support was removed, including their Yahoo suffix routing, market-review regions,
trading calendars, Taiwan institutional-flow data, portfolio partial-valuation handling and the JP/KR
stock-index seed rows. `MARKET_REVIEW_REGION` accepts `ca`, `hk`, `us` and `both`.

Stock codes with the removed suffixes (`.T`, `.KS`, `.KQ`, `.TW`, `.TWO`) are rejected with an
"exchange suffix ... is no longer supported" message instead of being reclassified as US or mainland codes.

## Suffix-market mechanism

The generic Yahoo suffix-market mechanism in `src/services/market_symbol_utils.py` registers Canada as one
`SuffixMarketSpec` entry (`market="ca"`, suffixes `TO`, `V`, `CN`, `NE`, and an alphanumeric base pattern that also
accepts Yahoo's hyphenated class and unit markers). Numeric-base markets use `digit_lengths` instead of `base_pattern`.
A registered suffix always wins over the US dotted-share-class pattern (`is_us_stock_code` returns False for it), and a
registered suffix with an invalid base is rejected by `parse_analysis_target` instead of being guessed as a US ticker.

Adding another market is one `SuffixMarketSpec` entry plus its trading-calendar exchange code, timezone and
closing-auction window in `src/core/trading_calendar.py`, the market in the Yahoo entry of
`DataFetcherManager._DAILY_MARKET_FETCHER_SUPPORT`, its prompt wording in `src/market_context.py`, its currency
suffix in `NotificationService._CURRENCY_SUFFIX`, and the market in the API/web market unions.

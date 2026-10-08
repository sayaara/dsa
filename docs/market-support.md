# Market support and boundaries

## Supported markets

| Market | Status | Data path |
|---|---|---|
| United States | **Primary** | Daily bars: Finnhub, Alpha Vantage, Yahoo Finance, Longbridge (Longbridge first when configured). Realtime: Yahoo Finance or Longbridge first, supplemented by Finnhub and Alpha Vantage. Fundamentals: Yahoo Finance. |
| Canada (TSX / TSXV / CSE / NEO) | **Supported** | Yahoo Finance symbols with the `.TO`, `.V`, `.CN` and `.NE` suffixes (for example `RY.TO`, `SHOP.TO`, `ABX.V`, `TECK-B.TO`). Daily bars, realtime quotes and fundamentals come from Yahoo Finance only; the TSX trading calendar (XTSE, `America/Toronto`) drives the trading-day filter. About 60 large TSX names are in the bundled stock index for name search. Market review supports it as region `ca` (S&P/TSX Composite and TSX Venture Composite from Yahoo Finance). Bare symbols without a suffix are always read as US tickers, so write `RY.TO`, not `RY`. |
| Hong Kong | **Not currently supported** | Codes such as `0700.HK`, `HK00700`, `HK.00700` and bare 4-5 digit codes are rejected as unsupported, and no data source is asked for them. Hong Kong data stored before the removal (portfolio trades, history, decision signals) is kept and still readable; Hong Kong positions get no price. Hong Kong may return as a registry market (see below). |
| Mainland China (A-shares) | **Removed** | Six-digit codes and the `sh`/`sz`/`bj`/`csi` prefix and suffix forms are rejected as unsupported; the China data fetchers were deleted. |
| Japan / Korea / Taiwan | **Removed** | Codes such as `7203.T`, `005930.KS` and `2330.TW` are rejected as unsupported. |
| Other exchanges | **Not supported** | Any other Yahoo exchange suffix (`VOD.L`, `SAP.DE`, `BHP.AX`, `RELIANCE.NS`, ...) is rejected as unsupported ("exchange suffix ... is not supported") instead of being read as a US dotted ticker. A single letter after a 1-5 letter ticker stays a US share class (`BRK.B`, `BF.B`), except `.L` (London) and `.F` (Frankfurt). The check is `unsupported_exchange_suffix` in `src/services/market_symbol_utils.py`, derived from the registered suffixes. |

`MARKET_REVIEW_REGION` accepts `ca`, `us` and `both` (both markets).

## Market registry

`src/core/market_registry.py` is the single list of supported markets. Each `MarketSpec` holds a market's code,
name and label, currency, exchange-calendar code (`exchange-calendars`), timezone, regular-session length (the
intraday decision-signal lifetime), closing-auction window and, for suffix markets, its Yahoo symbol suffixes with
either a base pattern or numeric base lengths. The trading calendar, the suffix-symbol parser, portfolio markets and
default currencies, market-review and Market Light regions, the data-capability matrix and the analysis prompt
currency all read from it.

`tests/test_market_registry.py` fails when a registered market lacks its per-market content, so a half-added market
fails in CI instead of silently falling back to US wording.

### Adding a market

For example Hong Kong again (`.HK`), London (`.L`), Paris (`.PA`) or Tokyo (`.T`):

1. Add a `MarketSpec` to `MARKETS` in `src/core/market_registry.py`. Symbol suffixes make it a Yahoo suffix market:
   it is parsed by `parse_analysis_target` and fetched through Yahoo Finance by the generic suffix path, with no
   market-specific routing. Numeric-base markets (Hong Kong, Tokyo) set `symbol_digit_lengths`; alphanumeric ones
   set `symbol_base_pattern`.
2. Add the content `tests/test_market_registry.py` asks for: a `MarketProfile` (`src/core/market_profile.py`), a
   `MarketStrategyBlueprint` (`src/core/market_strategy.py`) and the prompt role and guidelines in
   `src/market_context.py`.
3. Add the market-review title in `src/core/market_review.py` and the review index quotes in
   `YfinanceFetcher.get_main_indices`.
4. Add the market to the API `Literal` enums (they cannot read the registry: `api/v1/schemas/portfolio.py`,
   `decision_signals.py`, `intelligence.py`, `stocks.py`, `src/schemas/market_light.py`), the currency suffix in
   `NotificationService._CURRENCY_SUFFIX`, the stock-index markets (`SUPPORTED_STOCK_INDEX_MARKETS` in
   `src/services/stock_index_remote_service.py` with the web `Market` type and autocomplete badge), and the web
   market unions and option lists in `apps/dsa-web`.
5. Remove the market's "not currently supported" rejection in `src/services/stock_list_parser.py` if it has one
   (Hong Kong does: `_UNSUPPORTED_HK_CODE_RE`), and the matching refusal in `DataFetcherManager` (`_is_hk_market`).

## Removed markets

Japan, Korea and Taiwan support was removed, including their Yahoo suffix routing, market-review regions,
trading calendars, Taiwan institutional-flow data, portfolio partial-valuation handling and the JP/KR
stock-index seed rows. Stock codes with the removed suffixes (`.T`, `.KS`, `.KQ`, `.TW`, `.TWO`) are rejected with an
"exchange suffix ... is no longer supported" message instead of being reclassified as US or mainland codes.

Hong Kong was removed on 2026-10-07: its registry entry, market-review content, Hang Seng index quotes, the
HK-only Futu market-data fetcher and fundamentals adapter (`FUTU_HK_REALTIME_SOURCE_PRIORITY`), Longbridge and
Yahoo Hong Kong symbol mapping, and the Hong Kong rows of the bundled stock index. The Futu portfolio import
(`--portfolio futu`) still imports US positions and skips Hong Kong ones.

## Suffix-market mechanism

`src/services/market_symbol_utils.py` builds its `SuffixMarketSpec` list from the registry entries that declare
suffixes (today only Canada: `TO`, `V`, `CN`, `NE`, with an alphanumeric base pattern that also accepts Yahoo's
hyphenated class and unit markers). A registered suffix always wins over the US dotted-share-class pattern
(`is_us_stock_code` returns False for it), and a registered suffix with an invalid base is rejected by
`parse_analysis_target` instead of being guessed as a US ticker.

# Market support and boundaries

## Primary and planned markets

| Market | Status | Data path |
|---|---|---|
| United States | **Primary** | Daily bars: Finnhub, Alpha Vantage, Yahoo Finance, Longbridge (Longbridge first when configured). Realtime: Yahoo Finance or Longbridge first, supplemented by Finnhub and Alpha Vantage. Fundamentals: Yahoo Finance. |
| Hong Kong | **Primary** | Daily bars: Yahoo Finance, Longbridge, Futu. Realtime: `futu,longbridge,yfinance` by default (Futu only when OpenD is configured). Fundamentals: Yahoo Finance. |
| Canada (TSX / TSXV) | Planned, priority 3 | Not implemented yet; expected to route through Yahoo Finance suffixes such as `.TO` and `.V`. |
| Mainland China (A-shares) | Legacy, scheduled for removal | efinance, AkShare, Tushare, Tencent, Pytdx, Baostock and TickFlow. HK no longer uses AkShare or Tushare by default; AkShare remains an opt-in HK realtime source through `FUTU_HK_REALTIME_SOURCE_PRIORITY`. |
| Japan / Korea / Taiwan | Secondary | Yahoo Finance suffix codes. Taiwan is scheduled for removal with the Asia cleanup. |

Market-code predicates that do not depend on any regional fetcher live in `data_provider/market_codes.py`.

## Japan/Korea single-stock suffix-only MVP (Issue #1718, Refs #1718)

The current stage supports entering Yahoo Finance suffix codes for Japanese and Korean stocks by hand, which routes them into the existing single-stock analysis, history persistence, and basic report display. Web autocomplete ships with a seed index of common Japanese and Korean stocks, searchable by suffix code, Chinese or English name, or common alias.

Supported formats:

- Japan: `7203.T`, `6758.T`
- Korea KOSPI: `005930.KS`
- Korea KOSDAQ: `035720.KQ`

Constraints and boundaries:

- When a bare code is entered by hand, the local and remote stock pools are searched first. If a bare code such as `005930` or `000660` matches a Japanese or Korean entry such as `005930.KS` or `000660.KS`, the analysis is submitted for the matched market. If the stock pool has no match, the existing 6-digit rule still applies and it falls back to A-share semantics, which keeps the cross-market ambiguity a traceable boundary.
- Japanese and Korean suffix recognition is centralized in the shared market-code utility, so data-source routing, prompt market recognition, the trading calendar, and bare-code resolution in the stock index all reuse the same rules, which reduces rule drift as more markets are added.
- Japanese and Korean daily bars and basic real-time or near-real-time quotes go only through `YfinanceFetcher`; A-share-specific sources such as AkShare, Tushare, efinance, Pytdx, and Baostock are never attempted. yfinance quotes carry quality metadata such as `market`, `currency`, `data_quality`, and `missing_fields` where possible.
- Fundamentals reuse the existing lightweight offshore yfinance path. A-share-specific capabilities such as capital flow, the dragon-tiger list, and sector data degrade to `not_supported`, and the offshore fundamental context also records the provider, `as_of`, `data_quality`, and any missing blocks.
- The report prompt now carries Japanese and Korean market semantics, which avoids applying A-share concepts such as price limits, northbound capital, the dragon-tiger list, or margin trading.
- The trading calendar registers `jp: XTKS / Asia/Tokyo` and `kr: XKRX / Asia/Seoul`. Japanese regular phases recognize pre-market, intraday, lunch break, the 15:25-15:30 closing auction, post-market, and non-trading days; Korean regular phases recognize pre-market, intraday, the 15:20-15:30 closing auction, post-market, and non-trading days. If the local `exchange-calendars` version lacks a calendar, the existing fail-open/fail-closed semantics are unchanged.

Compatibility and rollback (addressing the structured-scanner hits):

- `#1815` only adds optional field metadata to the `yfinance` quote and fundamental context (such as `market`, `currency`, `data_quality`, `missing_fields`, and `provider`). It changes no LLM provider/model/base URL, configuration schema, runtime environment variable, database field, stored cache serialization, or message protocol version.
- For configuration semantics related to this PR, no provider, model, or base URL was added or replaced, and no configuration cleanup or migration branch was introduced. Saved configuration is untouched, and the rollback is to revert this commit.
- The external API boundary remains the existing `yfinance` fetch path (including `Ticker`, `history`, and `fast_info`) and the existing fallbacks. No API gateway or host was added or migrated, and `YFINANCE_PRIORITY` is the only visible parameter affected. The JP/KR main indices map to Yahoo symbols as follows (verifiable):
  - Nikkei 225: `^N225` (<https://finance.yahoo.com/quote/%5EN225/>)
  - TOPIX: `^TOPX` (<https://finance.yahoo.com/quote/%5ETOPX/>)
  - KOSPI: `^KS11` (<https://finance.yahoo.com/quote/%5EKS11/>)
  - KOSDAQ: `^KQ11` (<https://finance.yahoo.com/quote/%5EKQ11/>)
  - Dependency version: `yfinance>=0.2.0` in `requirements.txt`; regression coverage is in `tests/test_yfinance_jp_kr_indices.py` and `tests/test_yfinance_hk_indices.py`.
- Compatibility and rollback: `MARKET_REVIEW_REGION` keeps a valid comma-separated subset (such as `cn,us`) and preserves the full behaviour of `both`. An invalid or empty value falls back to `cn`, and saved configuration is never cleared or migrated.
- Runtime boundary: JP/KR indices are fetched item by item under the market_review fail-open convention. One failure never blocks the remaining indices or other markets, and when neither market has a usable main index quote the result is a locally visible `None`/empty while the main flow continues with the other markets or degrades directly.
- Compatibility evidence: the quote and fundamental context pass through to downstream consumers in `data_provider/base.py` and `realtime_types.py` using the existing `getattr` and optional-field conventions, so the new fields are never required for reading or writing. There is no configuration migration script, and no change was observed in the provider/model/base URL fallback paths.
- Rollback: if the new metadata fields cause a compatibility problem somewhere, ignore them first and run with the existing market-detection and quote-display path. If necessary, revert this commit, or restore the old behaviour by removing the `jp`/`kr` `MarketSymbol` entries and the routing extension.

Not promised:

- No promise of real-time quotes; Yahoo Finance data may be delayed or have missing fields.
- No promise of complete fundamentals, industry/sector data, market breadth, or advance/decline counts. JP/KR market review v1 provides only the main indices, news leads, and a template/LLM review; it provides no Japanese or Korean market breadth or sector ranking.
- No promise of a complete Japanese or Korean stock universe. Web autocomplete currently covers only the common instruments in the in-repository seed index (expanded to roughly 30 leading names each), and an unmatched query can still be entered as a full suffix code.
- No complete JPY/KRW FX, cost, or market-value accounting in Portfolio; those fields only open up the market type so frontend and backend validation do not reject it.

Rollback: remove `jp`/`kr` market recognition, the trading-calendar registration, the YFinance routing extension, the Web/API type allowances, the Japanese and Korean seed indices under `scripts/stock_index_seeds/`, and delete the capability statement in this document.

## Japan/Korea market review v1 (Issue #1815 Phase 2)

Market review adds `jp` and `kr` to `MARKET_REVIEW_REGION`, and includes them in the multi-market order of `both`: `cn,hk,us,jp,kr`.

Supported scope:

- `jp`: fetches Nikkei 225 `^N225` and TOPIX `^TOPX` through Yahoo Finance and produces a Japanese market review. Verifiable pages:
  - `^N225`: <https://finance.yahoo.com/quote/%5EN225/>
  - `^TOPX`: <https://finance.yahoo.com/quote/%5ETOPX/>
- `kr`: fetches KOSPI `^KS11` and KOSDAQ `^KQ11` through Yahoo Finance and produces a Korean market review. Verifiable pages:
  - `^KS11`: <https://finance.yahoo.com/quote/%5EKS11/>
  - `^KQ11`: <https://finance.yahoo.com/quote/%5EKQ11/>
- The Web settings page accepts a comma-separated subset in the `MARKET_REVIEW_REGION` text box (such as `cn,jp` or `cn,us,jp,kr`); the trading-day check filters `both` down to the markets open that day using `XTKS / Asia/Tokyo` and `XKRX / Asia/Seoul`.
- The review strategy, news search terms, prompt market semantics, and Chinese and English notification titles are all handled through separate JP/KR profiles.

Notes (compatibility and acceptance):

- Live data availability comes from the Yahoo Finance index pages and their API contract. The current implementation covers only the index routing and degradation behaviour in `data_provider/yfinance_fetcher.py`, and makes no stability promise about real-time quote connectivity.
- Local automated verification for this item defaults to offline regression: `tests/test_yfinance_jp_kr_indices.py`, `tests/test_yfinance_hk_indices.py` (shared mapping and fallback), and `tests/test_trading_calendar.py` (trading-day filtering). To add a live availability check, visit the Yahoo Finance pages above once from a networked environment.

- External compatibility boundary (the current implementation's default assumptions):
  - Data source: `yfinance` (lower bound `yfinance>=0.2.0` in `requirements.txt`)
  - Long-term constraint: `^N225`, `^TOPX`, `^KS11`, and `^KQ11` must have retrievable quote pages on Yahoo Finance. A failure to retrieve counts as index-level unavailability, and the `market_review` fail-open mechanism degrades to the markets that are available without interrupting the main flow.
- Compatibility verification (reviewable):
  - <https://finance.yahoo.com/quote/%5EN225/>
  - <https://finance.yahoo.com/quote/%5ETOPX/>
  - <https://finance.yahoo.com/quote/%5EKS11/>
  - <https://finance.yahoo.com/quote/%5EKQ11/>
  - Reproducible online verification command (optional):
```bash
python - <<'PY'
from yfinance import Ticker
for symbol in ("^N225", "^TOPX", "^KS11", "^KQ11"):
    data = Ticker(symbol).history(period="5d")
    print(symbol, "rows", len(data))
PY
```

Boundaries:

- JP/KR market review v1 provides no advance/decline counts, price-limit counts, industry/sector rankings, or capital-flow statistics; `breadth` still appears in the structured payload only when market-breadth data exists.
- A single failed JP/KR index fetch is skipped under the existing yfinance fail-open logic and never drags down the other indices or markets.
- If `exchange-calendars` lacks the matching exchange calendar, the existing trading-day fail-open/fail-closed semantics continue to apply.

Rollback: remove `jp` / `kr` from the valid values of `MARKET_REVIEW_REGION`, the Web settings enumeration, MarketProfile/MarketStrategy, `_MARKET_REVIEW_MARKETS`, and this document.

## Taiwan

The Taiwan path has recently converged from an early MVP into a first-class single-stock analysis market: market recognition, data routing, the trading calendar and market phases, YFinance daily bars and basic quotes, the main indices, the service-layer/API/Web market enumerations, TWD currency labelling, the institutional-flows report block, and LLM prompt consumption are all wired up. The boundaries that remain are: the Taiwan stock-pool seed and autocomplete, market review with `MARKET_REVIEW_REGION=tw`, Market Light alerts, and complete Taiwan market breadth and sector rankings are not yet included.

Supported formats:

- Listed (TWSE): `2330.TW`, `0050.TW`
- Over-the-counter (TPEx): `6488.TWO`, `5483.TWO`
- The code base is 4-6 digits (4 for ordinary shares, up to 6 for ETFs and others, such as `00878.TW` and `006208.TW`), which is wider than the 4-5 digits used by the Japanese `.T` suffix.

Constraints and boundaries:

- **Strictly suffix-only**: a bare code such as `2330` or `00878` never enters Taiwan semantics (`detect_market` / `get_market_for_stock` return `tw` only for an explicit `.TW` or `.TWO` suffix). There is no built-in Taiwan stock index or seed resolution yet, so Web autocomplete makes no promise of a complete Taiwan stock pool; enter the full suffix code by hand when there is no match.
- Taiwan daily bars and basic real-time or near-real-time quotes go only through `YfinanceFetcher`; A-share-specific sources such as AkShare, Tushare, efinance, Pytdx, and Baostock are never attempted.
- Fundamentals reuse the existing lightweight offshore yfinance path. The `institution` block additionally consumes Taiwan institutional-investor data and renders it into the report, while A-share-specific capabilities such as capital flow, the dragon-tiger list, and sector data degrade to `not_supported`.
- The report prompt now carries Taiwan market semantics (New Taiwan dollar, the three major institutional investors, and the TWSE/TPEx ±10% price limit), and injects institutional net buy/sell figures into the LLM analysis context, which avoids applying A-share concepts such as northbound capital or the dragon-tiger list.
- The trading calendar registers `tw: XTAI / Asia/Taipei`. TWSE trades continuously from 09:00 to 13:30 with no lunch break; the 13:25-13:30 closing auction is modelled as a 5-minute heuristic window (`_CLOSING_AUCTION_WINDOW_MINUTES["tw"]=5`, and `market_phase` can return `closing_auction`). JP and KR also have closing-auction windows filled in for their regular sessions (JP 15:25-15:30, KR 15:20-15:30). If the local `exchange-calendars` version lacks a calendar, the existing fail-open/fail-closed semantics are unchanged.
- The main indices are the weighted index `^TWII` and the OTC index `^TWOII`.
- Institutional flows data layer: `TwInstitutionalFetcher` (`data_provider/tw_institutional_fetcher.py`) provides daily foreign, investment-trust, dealer, and total 三大法人 net buy/sell figures for listed (TWSE T86, the legacy `rwd` endpoint) and OTC (TPEx OpenAPI) stocks. The unit is **shares**; a whole-market single-day cache is keyed by date plus market and then filtered per stock, and the TPEx Minguo-to-Gregorian year conversion has unit-test coverage. An API failure, rate limit, empty response, or missing field always **fails open** to no data rather than interrupting the analysis. It applies only to `.TW` and `.TWO` and does not change any existing market flow. The data comes from government open data under the Open Government Data License, version 1.0 (OGDL v1), which permits commercial use and redistribution with attribution.
- The institutional-flows fetcher has concurrent-cache stampede protection and circuit breakers split by TWSE and TPEx. The TPEx OpenAPI serves only the latest trading day, so passing an explicit date that does not match the served day fails open to no data, which prevents wrong-day figures from silently reaching a report.
- Taiwan financial amounts are labelled TWD as 「新台币」, which avoids falling back to the default 「元」 used in an A-share context.

Not promised:

- No promise of real-time quotes; Yahoo Finance data may be delayed or have missing fields.
- No promise of complete fundamentals, industry/sector data, market breadth, advance/decline counts, or Taiwan market review; `MARKET_REVIEW_REGION` still accepts only `cn/hk/us/jp/kr/both` or a comma-separated subset of those markets.
- The Taiwan stock index/seed and Web autocomplete are still not fully wired up; the alert `MarketRegion` and the backend Market Light alerts remain `cn/hk/us` and do not include `tw`.
- No complete TWD FX, cost, or market-value accounting in Portfolio; Taiwan is currently a partial-valuation market there.

Rollback: remove `tw` market recognition, the trading-calendar registration, the YFinance routing extension, the institutional-flows data layer and report consumption, the TWD labelling, the service-layer and API market enumerations, and the frontend market-type allowance, then delete the capability statement in this document.

## Japan/Korea Portfolio and Market Light boundaries (Issue #1815 Phase 3)

Portfolio allows JP/KR accounts, trades, and position snapshots into the existing path, but marks the account and position snapshots `data_quality=partial` and states `realtime_quote_best_effort`, `fx_and_cost_basis_partial`, and `sector_and_risk_metrics_limited` through `limitations`. It makes no promise of complete JPY/KRW FX, cost, market value, sector concentration, or portfolio risk metrics.

- The JP/KR account, trade, cash-ledger, and corporate-action APIs remain creatable and queryable. No JPY/KRW FX source, tax model, lot-size or tick-size validation, or industry mapping is added at this stage.
- Market Light snapshots and Market Light alerts still support only `cn` / `hk` / `us`.
- The Web alert market dropdown does not show `jp` / `kr`, and the backend `normalize_market_region()` returns an explicit unsupported error for them.
- In the Web settings page, `MARKET_REVIEW_REGION` converges from a fixed enum dropdown to a free-text input, which can save comma-separated subsets such as `cn,us,jp` or `cn,hk,us`. That UI change affects only the market-review configuration, not the Market Light alert market enumeration.
- Existing `MARKET_REVIEW_REGION` values of `cn`, `hk`, and `us` can be kept as they are. To preserve the three-market review boundary that `both` meant before the JP/KR extension, change it to `cn,hk,us`; keep using `both`, or configure `cn,hk,us,jp,kr` explicitly, only when you want the five-market review.
- This round's boundary work changes no persistence semantics for the LLM provider, model, or base URL, and performs no default-model, runtime-configuration cleanup, or write-back. A configuration update is still an **atomic upsert** (`ConfigManager.apply_updates`), so saving or importing writes only the submitted keys, and uncommitted values such as `LITELLM_MODEL`, `LITELLM_FALLBACK_MODELS`, `AGENT_LITELLM_MODEL`, `VISION_MODEL`, and `OPENAI_BASE_URL` are preserved rather than cleared.
- Directly verifiable configuration-compatibility evidence: this round added or replaced no external provider, model, or base URL, and still uses LiteLLM OpenAI-compatible routing (<https://docs.litellm.ai/docs/providers/openai_compatible>), the OpenAI Chat Completions request shape (<https://platform.openai.com/docs/api-reference/chat/create>), and the per-provider official source links maintained centrally in the [LLM provider configuration guide](llm-providers.md#official-sources-and-compatibility). The current runtime dependency window is `litellm>=1.80.10,!=1.82.7,!=1.82.8,<1.99.0` in `requirements.txt`. Older configuration has no migration script or cleanup branch, and saving or importing still writes only the submitted keys through `ConfigManager.apply_updates`. The rollback path is restoring `MARKET_REVIEW_REGION` from the pre-change `.env` or configuration backup, or reverting this PR; existing runtime configuration such as `LITELLM_CONFIG`, `LLM_CHANNELS`, `LLM_OPENAI_*`, `LITELLM_MODEL`, `AGENT_LITELLM_MODEL`, `LITELLM_FALLBACK_MODELS`, `VISION_MODEL`, and `OPENAI_*` needs no migration. The regression evidence is `tests/test_system_config_service.py::SystemConfigServiceTestCase::test_update_market_review_region_does_not_trigger_runtime_model_cleanup` and `tests/test_config_env_compat.py::test_market_review_region_updates_do_not_change_llm_provider_model_contract`.
- Web UI visual evidence: when the Market Light alert target scope is switched to the broad market, the market region dropdown shows only A-shares, Hong Kong, and US, and not Japan or Korea; the settings page renders `MARKET_REVIEW_REGION` as a text box accepting comma-separated values. This repository does not store one-off screenshot evidence, so the equivalent evidence is the assertions in `apps/dsa-web/src/components/alerts/__tests__/AlertRuleForm.test.tsx`, `apps/dsa-web/src/components/settings/__tests__/SettingsField.test.tsx`, and `apps/dsa-web/tests/system_config_i18n.test.ts`.

Rollback: remove the `data_quality` and `limitations` extensions from the Portfolio snapshot and restore the previous market-enumeration boundary notes in the alert frontend and backend. For a full rollback, remove `jp`/`kr` market recognition, the trading-calendar registration, the YFinance routing extension, the Web/API type allowances, the Japanese and Korean seed indices under `scripts/stock_index_seeds/`, and delete the capability statement in this document.

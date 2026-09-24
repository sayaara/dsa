# Screening Engine

DSA maintains its stock-screening capability as part of the main project. The implementation is based on [AlphaSift](https://github.com/ZhuLinsen/alphasift) at commit [`9f522747caafd3c0b1ddb7e14d5cf44c8580b6cf`](https://github.com/ZhuLinsen/alphasift/commit/9f522747caafd3c0b1ddb7e14d5cf44c8580b6cf), modified and distributed under the Apache License 2.0. Derived files keep their source headers, the license lives at `src/services/screening/LICENSE`, and the third-party notice is `THIRD_PARTY_NOTICES.md` in the repository root.

## Code boundaries

- `src/services/screening/`: snapshots, daily bars, strategy loading, filtering, scoring, risk, LLM reranking, and the hotspot implementation.
- `src/services/screening/strategies/`: the screening strategy YAML files released with each DSA version.
- `src/services/screening/pipeline.py`: the direct entrypoint to the screening flow.
- `src/services/screening_service.py`: DSA business orchestration. It calls the pipeline directly and owns configuration, data-source context, response normalization, caching, and error mapping.
- `src/storage.py`: persists completed screening runs on DSA's existing SQLAlchemy/SQLite infrastructure rather than a separate file database.
- `api/v1/endpoints/screening.py`: the `/api/v1/screening` API.
- `apps/dsa-web/src/api/screening.ts` and `StockScreeningPage.tsx`: the web client and its presentation layer.

The service layer calls `screening.pipeline`, `screening.strategy`, and `screening.hotspot` statically. The core logic uses no module-name probing, dynamic adapters, or multiple routing layers, so the code structure, error boundaries, and packaging collection targets are all defined directly by the main project.

## Configuration

Disabled by default:

```dotenv
SCREENING_ENABLED=false
```

The web Basic settings page exposes a Screening toggle. Enabling it shows the Screening entry in the left navigation and allows strategy, hotspot, and screening tasks to run; disabling it hides the entry, and the screening API keeps rejecting business requests.

Common options:

```dotenv
SCREENING_DATA_DIR=data/screening
SCREENING_SNAPSHOT_CACHE_TTL_SEC=300
SCREENING_SOURCE_CALL_TIMEOUT_SEC=
SCREENING_HOTSPOT_CALL_TIMEOUT_SEC=8
SCREENING_HOTSPOT_SEARCH_TIMEOUT_SEC=12
SCREENING_SNAPSHOT_CALL_TIMEOUT_SEC=60
SCREENING_DAILY_CALL_TIMEOUT_SEC=20
SCREENING_EASTMONEY_MIN_INTERVAL_SEC=1.0
SCREENING_EASTMONEY_JITTER_SEC=0.3
```

The path, cache, timeout, and rate-limit options affect the screening path only. `SCREENING_SNAPSHOT_CACHE_TTL_SEC` defaults to 300 seconds; set it to `0` to disable reuse of a fresh snapshot. A positive `SCREENING_HOTSPOT_CALL_TIMEOUT_SEC` is the total budget for one call of the default hotspot provider — sector listing, constituents, or the direct-detail fallback. Later fallbacks and parallel constituent sources share the same deadline, and the remaining time is passed down to the terminable AkShare subprocess and the HTTP socket. Setting it to `0/off/disabled` removes only that overall budget; each real data source keeps its own hard timeout. `SCREENING_HOTSPOT_SEARCH_TIMEOUT_SEC` is the end-to-end deadline for a user-initiated news search, shared as one absolute deadline by the cache-owner wait, re-contention, and the provider subprocess; `0/off/disabled` falls back to the safe default of 12 seconds rather than waiting indefinitely. Treat `.env.example` as the complete reference.

## API contract

| Path | Method | Behavior |
| --- | --- | --- |
| `/api/v1/screening/status` | GET | Returns the feature toggle, engine status, contract version, reference project, and data-source health |
| `/api/v1/screening/strategies` | GET | Returns the screening strategies |
| `/api/v1/screening/hotspots` | GET | Reads cached hotspot topics, or refreshes them explicitly |
| `/api/v1/screening/hotspots/{topic}` | GET | Returns the topic's narrative, constituents, and core stocks; with `include_search=true` it searches recent news on demand |
| `/api/v1/screening/screen` | POST | Runs a screen synchronously; an anonymous `variant_seed` may be passed to produce a bounded near-score candidate mix on each run |
| `/api/v1/screening/screen/tasks` | POST | Submits a background screening task; the request fields match the synchronous endpoint |
| `/api/v1/screening/screen/tasks/{task_id}` | GET | Queries task progress, errors, or the final result |
| `/api/v1/screening/history` | GET | Queries summaries of recently completed screening runs by strategy and market |
| `/api/v1/screening/history/{run_id}` | GET | Reads one persisted, complete screening result |
| `/api/v1/screening/source-history` | GET | Aggregates snapshot-source hits, errors, and degradations across historical runs |

Background tasks use `report_type=screening_screen`. The web client stores the active task ID and resumes polling when the page is restored. Task status reports the whole-market snapshot, candidate context, LLM reranking, final scoring, and news-event enrichment stages separately. Completed results are also written to the DSA database, so they remain queryable by `run_id` after a service restart.

## Core flow

```text
Strategy loading
  -> Whole-market snapshot and field normalization
  -> Hard filters
  -> Factor scoring and risk adjustment
  -> Candidate context enrichment
  -> LLM reranking (degradable)
  -> Risk / portfolio constraints and near-score candidate rotation
  -> DSA quote / fundamental / news enrichment of the top candidates
  -> Normalized API response and DSA database persistence
  -> User opts into DSA single-stock deep analysis
```

- Within a short TTL the whole-market snapshot prefers reusing the most recent successful result. A new cache entry records the full, ordered data-source priority and is reused only when the current priority matches the one recorded at write time, so a fallback source's result within the same source chain can still accelerate later requests, while changing the source configuration triggers a fresh live read. After the cache expires, sources are tried in configured priority order; a single source failing degrades to the next one, and source health plus a last-good cache are recorded. None of the current Sina, Efinance, AkShare/Eastmoney, or Tushare snapshot endpoints offer an incremental cursor or change sequence, so reuse within the TTL costs zero requests but the full table must still be re-read once the TTL expires. Comparing before-and-after differences locally cannot reduce upstream transfer volume, so it is not advertised as "incremental fetching".
- When `TUSHARE_TOKEN` is set, Tushare is preferred by default; otherwise the chain starts at Sina. An explicit `SNAPSHOT_SOURCE_PRIORITY` always wins.
- Daily bars prefer a request-scoped fetcher that reuses DSA's historical quote path, and only fall back to the screening engine's own source degradation when that returns nothing. The bridge does not replace process-level functions, so overlapping screening requests never share a wrapper or block each other.
- Only a limited candidate context is gathered before LLM reranking; quotes, fundamentals, news, and summaries are added for the final candidates only, which keeps the request volume down.
- The default local `scorecard` covers the full shortlist, so every candidate that could enter near-score rotation is scored on the same final basis. When several post-analyzers are chained, the list is re-ranked on the latest scores after each step, so the `POST_ANALYSIS_MAX_PICKS` cap for the later `dsa` and `external_http` analyzers applies to the genuine current leaders. Remote state is recorded against the candidates actually submitted, and an over-limit code in an external response never rewrites a candidate that was not submitted; with remote analysis enabled, rotation happens only among candidates that completed the same analysis.
- The model, channel, base URL, extra headers, fallbacks, timeout, and token cap are injected for the scope of a single call and never rewrite the user's configuration. Even when the primary model's HTTP call succeeds, an empty body, non-JSON content, or insufficient coverage still moves on to the configured fallback models. The final JSON must appear in a `content` block or an `output` block; `reasoning_content` (chain of thought) is treated as internal scaffolding and never as the final result.
- A hotspot list refresh and a long screening run can proceed in parallel. The list does not prefetch details in bulk by default: a topic's details are loaded when the user selects it. After an explicit refresh, if the current topic is still selected, the web client re-fetches that topic bypassing the detail cache, so the list and the details come from the same refresh.
- Hotspot constituents are fetched from Eastmoney and Tonghuashun in parallel and merged on a fixed source priority, so response ordering never changes the fields of a duplicated stock. A positive `SCREENING_HOTSPOT_CALL_TIMEOUT_SEC` is the shared budget for one whole call of the default provider, covering the sector list, the constituents, and the direct-detail fallback used after an engine failure. The terminable AkShare/Eastmoney subprocess and the Tonghuashun HTTP connect/read timeouts each consume only the remaining time, and a fallback never gets a fresh full budget. The direct-detail fallback no longer starts an extra real-time quote prefetch that the budget could not forcibly reclaim; quote fields come from the already-governed constituent source result. A timed-out subprocess is terminated, killed, and reaped. A process-level concurrency slot caps the number of active tasks, and the method waits for accepted workers to finish before returning, so no background thread is left behind. When the whole-call budget is disabled, each individual source keeps its default hard timeout, and one source failing does not prevent the other source or the local core-stock fallback.
- "Search latest news" reuses the provider priority, SearXNG public-instance support, result cache, and request coalescing of DSA's native search service. For a given cache key only the owner may start the provider chain; when the owner produces no cacheable result, waiters re-contend and requests that do not win ownership keep waiting — but the cache wait, contention, and provider execution share the request's absolute deadline and never regain a full timeout after queueing. The search only adds events and catalysts that carry a link; it never infers sector constituents from page content. Enriched records are appended to the presentation narrative and the raw timeline separately and never overwrite an existing `timeline`. The search is user-initiated, and its summary is compressed locally and deterministically without calling an LLM. The response distinguishes results, a valid empty result, and a timeout/capacity/provider failure through `available`, `no_results`, and `unavailable`, so the web client no longer reports a failed run as "no recent news". Search enrichment exists only in that one response; it is not written to the shared hotspot detail cache and does not renew it, so a default detail request never sees search state or waits on a search. A provider subprocess releases its process-level capacity whether it fails at startup, during execution, or during cleanup.
- When a live hotspot request fails, the last-good cache is preferred; with no cache, a stable empty state and an explicit error are returned.

## Result rotation

The web client generates an anonymous seed locally in the browser that carries no user information, and passes it as `variant_seed` with synchronous and background screening requests. When Web Storage cannot be read or written, the same temporary seed is reused from module memory for the current page session, so the synchronous and background entrypoints stay consistent. The server combines the anonymous seed with the run ID, market, and strategy as perturbation input: different browsers, and different runs in the same browser, may see different stocks among candidates of comparable quality.

The perturbation is not random rescoring and it does not bypass the strategy: hard filters, risk vetoes, factor and LLM scores, final scoring, and the portfolio-concentration penalty all run first. Local scoring covers the full shortlist by default; when remote post-analysis with a candidate cap is enabled, only candidates that completed the same analysis can take part in rotation. The candidate order produced by the analyzer is the authoritative input order for rotation, and ties are no longer re-sorted by stock code. The first half of the original top-N, and any candidate clearly above the cut-off score, are always protected; only the slots in the second half may be drawn from the near-score pool of candidates no more than 1.5 points below the original cut-off, and selected candidates keep that input relative order. The seed is not written into screening results or run history. With no `variant_seed`, or with the rotation ratio set to 0, the strict input top-N is returned, which keeps scripts and older clients working.

## Caching and persistence

| Data | Location | Lifetime / behavior |
| --- | --- | --- |
| Whole-market snapshot | `data/screening/snapshot.last_good.json` | Reused directly within 5 minutes by default without a fallback marker; after expiry live sources are queried, and if every live source fails the cache can still be used within the maximum staleness limit and marked stale/fallback |
| Per-stock daily bars | `data/screening/daily_history/` | Keyed by code, source, and lookback window, with a 24-hour TTL by default; an expired cache may be used and marked stale when every live source fails |
| Industry / concept mapping | `data/screening/industry_provider_cache/` | 24-hour TTL by default, and sector-heat history is kept for trend calculation |
| Hotspot list and history | `data/screening/hotspots.json`, `hotspot.history.jsonl` | Written on an explicit refresh; falls back to the most recent usable snapshot when the live call fails |
| Hotspot details | `data/screening/hotspot_details/` | 30-minute TTL by default. Only structured base details are cached; an explicit news search neither writes to nor renews this cache. On a live failure an expired detail may be returned along with its staleness |
| DSA real-time quotes | the quote cache in `DataFetcherManager` | 10-minute TTL by default, following `REALTIME_CACHE_TTL` |
| DSA fundamentals / capital flow | the fundamentals cache in `DataFetcherManager` | 120-second TTL by default, following `FUNDAMENTAL_CACHE_TTL_SECONDS` |
| DSA news / disclosure events | the in-memory cache in `SearchService` | Successful results have a 10-minute TTL by default; concurrent requests for the same topic are coalesced in the parent process while the real provider chain runs in a rate-limited, terminable subprocess; queries restart after a service restart |
| Full screening result | the `screening_runs` table in the DSA database | Written idempotently by `run_id` on completion; a database write failure does not block the main screening flow |

The candidate-context module also supports a 24-hour file cache, but the DSA integration disables its independent news and disclosure fetching by default and uses DSA's own news, fundamentals, and real-time quote paths instead, so one candidate never queries two sets of data sources.

## The boundary between the two kinds of strategy

DSA contains two kinds of strategy file with different purposes:

| Location | Problem it solves | Loaded by | Execution stage |
| --- | --- | --- | --- |
| `src/services/screening/strategies/*.yaml` | Which candidates to screen out of the whole market | `src/services/screening/strategy.py` | Snapshot filtering, factor scoring, risk, and ranking |
| `strategies/*.yaml` | How to analyze one stock and reach a conclusion | `src/agent/skills/base.py` | DSA Agent / report analysis |

Even where names such as `shrink_pullback` and `volume_breakout` coincide, the two use different directories, schemas, and loaders and never override each other. A screening strategy can declare through `analysis_skills` which analysis skill the next stage should use, and the web client's further in-depth analysis action carries those skills explicitly. A screening strategy with no declared mapping keeps using the user's current selection or the default analysis strategy; no unreliable forced mapping is applied.

## Reuse of DSA's native capabilities

- Quotes: daily bars call DSA's `DataFetcherManager` first and only enter the screening module's own multi-source fallback when that returns nothing; final candidates are still enriched with DSA real-time quotes.
- Fundamentals and news: final candidates reuse DSA's fundamentals context and `SearchService`. Capital flow comes from the DSA fundamentals context, major disclosure, earnings, and share-reduction events call DSA's `search_stock_events`, and hotspot news search follows its data-source priority, recency filtering, caching, and in-request coalescing — isolating only the real provider call into a terminable subprocess rather than maintaining a second news entrypoint.
- Models: DSA's LiteLLM model, channel, fallback, base URL, extra headers, timeout, and token configuration are used as they are.
- Tasks and pages: the DSA background task queue, web polling, and the desktop app's same-origin web assets are reused.
- Storage and follow-up analysis: run results are written to the DSA database, and a candidate can enter DSA's native single-stock analysis carrying its strategy skill.

Measured against the fixed reference commit, the raw-data and screening capabilities — snapshots, daily bars, US equities, industry/concept mapping, hotspots, candidate news/disclosures/capital flow, field normalization, filtering, scoring, risk, ranking, and data-source circuit breaking — are all covered, with disclosures/events and capital flow wired into native event search and the fundamentals context at the DSA orchestration layer. The reference project additionally ships a standalone CLI/server, a JSON file store, report rendering, a doctor command, run and data-source history, and T+N evaluation. This implementation adopts only the run history and data-source history that DSA genuinely lacked and connects them to the DSA database. The CLI/server is not rebuilt, and T+N evaluation and performance statistics keep using DSA's existing BacktestService so that no second source of backtest truth appears. Live source health is already returned by `/status`, and historical stability is covered by `/source-history`.

## Benefits

1. The screening service, strategies, API, web client, and packaging scripts evolve in one version, which avoids contract drift.
2. The service layer has a single native call path, so the status probe and business requests reflect the same implementation.
3. Docker and desktop artifacts collect the same module and strategy resources directly, so deployments are more consistent.
4. Data-source degradation, scoring, and strategy changes can be reviewed and regression-tested end to end in the main repository.
5. The source commit, license, and per-file attribution are explicit, which makes selectively syncing upstream fixes straightforward later.

## Risks and controls

| Risk | Impact | Control |
| --- | --- | --- |
| A larger maintenance surface in the main repository | DSA absorbs data-source and strategy problems directly | Module boundaries, contract tests, and CI packaging probes constrain it together |
| Gradual divergence from the reference project | Upstream fixes cannot be applied wholesale | Pin the reference revision, compare module by module, and port selectively |
| Data-source rate limits or field changes | Snapshot, hotspot, or daily-bar degradation | Timeouts, retries, source health, and a last-good cache |
| LLM timeout or malformed output | Reranking unavailable or explanation fields missing | An unstructured response moves on to the fallback models; if all fail, the factor ranking is kept and the attempted models and failure reasons are returned |
| Result rotation widening candidate differences | Borderline candidates may differ between browsers | Only the near-score tail positions rotate, so hard filters, risk vetoes, scores, and the leading candidates stay fixed; rotation is off with no seed |
| Cache directory changes | An old cache is not reused automatically after an upgrade | The new directory is isolated as `data/screening`; back it up before upgrading if needed |
| Run history growth | Full candidate results increase database size | The history endpoint returns summaries only by default, and operators can manage it with existing database backup/retention policy |
| Configuration and API renames | Existing automation needs updating | Call out `SCREENING_ENABLED` and `/api/v1/screening` explicitly in the release notes |
| Missing license attribution | Release compliance risk | Keep the LICENSE, THIRD_PARTY_NOTICES, and derived-file headers |

Screening results are for research and decision support only. They are not investment advice, and they guarantee neither returns nor data completeness.

## Updating the reference implementation

AlphaSift is a reference source, not an automatic sync source. When updating:

1. record the target commit and any license change;
2. compare the DSA-specific modifications in `src/services/screening/` and port selectively, module by module;
3. update the derived-file headers, `REFERENCE_REVISION`, and `THIRD_PARTY_NOTICES.md`;
4. check the pipeline, API/web fields, data-source degradation, strategy resources, and the frozen packaging;
5. update this document and `docs/CHANGELOG.md`, then verify the backend, web, Docker, and desktop builds.

## Rollback

- Business rollback: set `SCREENING_ENABLED=false` and restart. Ordinary single-stock analysis, reports, notifications, and stock Q&A are unaffected.
- Code rollback: revert the commit that introduced the screening engine and rebuild the backend, Docker, and desktop artifacts.
- Data rollback: to keep the screening cache and run history, back up `data/screening/` and the DSA database first; a code rollback never deletes `screening_runs` user data on its own.

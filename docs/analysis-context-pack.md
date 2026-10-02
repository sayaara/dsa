# AnalysisContextPack: the P0 inventory, the P1/P2 contracts, P3 runtime consumption, P4 visibility, P5 data quality, the #1386 P6 linkage, and the #1389 P6 migration and rollback

This page is the topic document for Issue #1389. It records the real sources, consumption paths, and field-state boundaries of DSA's current analysis context, plus the `AnalysisContextPack` internal contract, the builder, runtime consumption, low-sensitivity visibility, data-quality scoring, the alert/holdings/history/backtest linkage, and the migration and rollback boundaries. P0 owns the inventory of current behavior and the contract boundary. P1 adds only the internal schema/envelope, the block catalog, the type conventions, and redacted serialization. P2 only assembles a pack from artifacts the pipeline already has. P3 only wires the low-sensitivity summary into the ordinary analysis and Agent initial prompts. P4 only wires the low-sensitivity overview into the history detail, the synchronous analysis response, completed task status, and the web report page. P5 completes data-quality scoring, the `fetch_failed` status, prompt data limitations, and low-sensitivity overview display within the same `PACK_VERSION = "1.0"`. #1386 P6 reuses that same public overview for the alert, holdings, history, backtest, and notification linkage, and adds an optional auxiliary `portfolio` block during a manual holdings analysis. #1389 P6 only completes the documentation, configuration visibility, and the migration and rollback notes, adding no pack runtime, pack feature flag, DB migration, or schema version.

## Terminology and boundaries

The repository currently has several data surfaces named context or snapshot, so P0 must disambiguate them first, to avoid describing an existing runtime structure as a future pack.

| Term | Current meaning | Main current consumers | P0 boundary |
| --- | --- | --- | --- |
| `storage.get_analysis_context()` | The brief technical context generated in `src/storage.py` from the last two days of OHLCV in the database, containing `today`, `yesterday`, `volume_change_ratio`, `price_change_ratio`, `ma_status`, and so on. The current implementation accepts `target_date` but still reads the latest two days. | The main ordinary analysis path, the Agent tool `get_analysis_context` | Recorded as the historical technical input source; it is not treated as equivalent to the future pack. |
| `enhanced_context` | The prompt context that `src/core/pipeline.py` builds during ordinary analysis from the brief DB context, live quotes, chips, trend, fundamentals, and language information. | `src/analyzer.py` prompt rendering, `_build_context_snapshot()` | Recorded as the current prompt input surface; P0 changes no field name or structure. |
| `analysis_history.context_snapshot` | The persisted snapshot written to the history table after an analysis completes. Ordinary analysis usually contains `enhanced_context`, `news_content`, `realtime_quote_raw`, and `chip_distribution_raw`; the Agent path saves `initial_context`. | History detail, the synchronous analysis/status responses, backtesting, some fundamentals fallback display | Recorded as the persisted consumption surface; `context_snapshot.enhanced_context.date` compatibility must be preserved. |
| Agent executor message context | The context `AgentExecutor._build_user_message()` injects into the first user message on the `AGENT_ARCH=single` path, currently the stock code, report type, output language, `realtime_quote`, `chip_distribution`, and `news_context`. | The single Agent's first LLM message | Records the fields visible in the first round today; P0 adds no runtime injection. |
| Agent orchestrator `AgentContext` | The shared multi-agent context `AgentOrchestrator._build_context()` writes on the `AGENT_ARCH=multi` path, which can pre-inject `realtime_quote`, `daily_history`, `chip_distribution`, `trend_result`, and `news_context`. | The Technical / Intel / Risk / Decision multi-agent chain | Recorded as the orchestrator's internal shared data surface; it does not pre-inject `fundamental_context`, and whether `trend_result` exists depends on whether the caller passed it. |

## P0 scope and non-goals

P0 exists so that P1/P2/P3 can design `AnalysisContextPack` against real repository boundaries, rather than reshaping the runtime ahead of time.

- P0 covers the context inventory of the seven paths: ordinary analysis, Agent, alerts, holdings, backtesting, history, and notifications.
- P0 fixes the field quality status words; P1 has added the `AnalysisContextPack` internal schema, but it still adds no builder, wires in no runtime, and exposes no complete pack.
- P0 adds no builder, no configuration option, and no database field, and changes no API, report, history, or notification payload.
- P0 wires in no runtime and changes no analysis, Agent, alert, holdings, backtest, or notification logic under `src/`.
- P0 does not pack-ify `market_review`, `market_light`, or the market-light topic snapshot; those are recorded only as other `report_kind` / topic consumption boundaries inside the history snapshot.
- P0 did not add `fetch_failed` to the field quality status words at the time; P5 has added that status within the same 1.0 umbrella, to distinguish "not supported" from "this fetch failed".
- P0 does not expand implementation detail into the README; this page is a topic document, discoverable through the `docs/INDEX.md` entrypoint.

## P1 internal contract

P1 lands `src/schemas/analysis_context_pack.py`, defining only the internal schema/envelope so the P2 builder and P3 runtime consumption reuse the same structure. P1 populates no runtime data, adds no fetcher, changes no prompt, writes no history/task/report metadata, and exposes no complete pack to the API, web, bot, desktop, or notifications.

The P1 schema contains:

- `PACK_VERSION = "1.0"`, marked on the contract through `AnalysisContextPack.pack_version`.
- `ContextFieldStatus`: the first P1 version allows only `available`, `missing`, `not_supported`, `fallback`, `stale`, `estimated`, and `partial`; P5 has added `fetch_failed`, meaning the field or block explicitly failed to fetch this time, which does not mean the whole analysis failed.
- `AnalysisSubject`: the top-level identity slot, containing only `code`, `stock_name`, and `market`; `exchange`, `currency`, and `industry` are left for later extension. The P2 builder does not extend the P1 schema and does not add a duplicate `identity` block.
- `AnalysisContextItem`: a field-level input item containing `status`, `value`, `source`, `timestamp`, `fallback_from`, `missing_reason`, `warnings`, and `metadata`.
- `AnalysisContextBlock`: a block-level grouping containing `status`, `items`, `source`, `timestamp`, `warnings`, and `metadata`, where `items` is a `Dict[str, AnalysisContextItem]`.
- `DataQuality`: P1 keeps only the `warnings` and `metadata` containers; P5 has added `overall_score`, `level`, `block_scores`, and `limitations`, all still low-sensitivity and carrying no raw payload.
- `AnalysisContextPack`: the top-level envelope containing `pack_version`, `subject`, `phase`, `blocks`, `data_quality`, `metadata`, and `created_at`.

Time field conventions:

- `AnalysisContextPack.created_at` uses `datetime`, which `model_dump(mode="json")` emits as an ISO 8601 string.
- `AnalysisContextItem.timestamp` and `AnalysisContextBlock.timestamp` use `Optional[str]` and are specified as ISO 8601 datetime strings. The P1 schema validates that format at construction time, rejecting a date-only value, natural-language time, or slash-separated date; the P2 builder does not force a second conversion when it reuses an existing artifact timestamp.

Status semantics:

- `block.status` expresses the whole block's availability.
- `item.status` expresses field-level quality.
- P1 does not implement automatic aggregation from `item.status` to `block.status`.

P1 Block Catalog:

| block key | P1 meaning | P1 boundary |
| --- | --- | --- |
| `quote` | Live quote and pricing inputs | Defines the expressible slot only; it fetches and populates nothing. |
| `daily_bars` | The complete daily window and the most recent complete daily date | P1 does not determine a partial bar. |
| `technical` | Technical indicators, price/volume structure, and patterns | P1 generates no indicator. |
| `fundamentals` | Valuation, growth, profitability, earnings, and shareholder returns | P1 adds no fundamentals fetcher. |
| `news` | News, disclosures, sentiment, and catalyst inputs | P1 changes nothing about news search. |
| `portfolio` | Whether the stock is held, the account summary, cost, quantity, position, and a stale summary | P1 includes no trade ledger, cash ledger, or complete account privacy data. |
| `chip` / `capital_flow` | Chips, capital flow, and major-player behavior | Extension keys for later; P1 allows only the contract expression. |
| `events` / `market_context` | Risk events, market breadth, indices, sectors, and the hotspot environment | Extension keys for later; `market_review` / `market_light` are not part of the first single-stock pack. |

The `phase` field accepts only the output of #1386 `MarketPhaseContext.to_dict()` and stays a `Dict[str, Any]`; it does not redefine the phase enum or a phase sub-model.

The redaction boundary:

- `AnalysisContextPack.to_safe_dict()` runs `model_dump(mode="json")` first, then calls `redact_sensitive_mapping()`.
- `redact_sensitive_mapping()` performs only key-based recursive redaction over dicts and lists, replacing a value with `[REDACTED]` when the key or phrase matches `api_key`, `access_token`, `refresh_token`, `authorization_header`, `webhook_url`, `password`, `cookie`, `secret`, `token`, `sendkey`, `license_key`, and so on.
- P1 does not scan ordinary string values, does not apply URL regex redaction, and does not treat `data_api` or a bare `api` / `key` as a sensitive match, so this contract does not expand into a general secrets engine.

## P2 builder contract

P2 adds `AnalysisContextBuilder`, but the first version is an assembler only: it builds the internal `AnalysisContextPack` from artifacts the ordinary analysis pipeline already holds. "Reuse existing data sources" in the issue's acceptance criteria means, in this slice, reusing the artifacts the pipeline has already fetched — `realtime_quote`, `base_context`, `enhanced_context`, `trend_result`, `chip_data`, `fundamental_context`, `news_context`, and so on. The builder itself is zero-fetch and calls no database, fetcher, SearchService, Agent tool, or specific provider.

The P2 input contract uses `PipelineAnalysisArtifacts`: `code`, `stock_name`, `market`, `phase`, `base_context`, `enhanced_context`, `realtime_quote`, `trend_result`, `chip_data`, `fundamental_context`, `news_context`, `news_result_count`, and `metadata`. The single-stock `build()` and the batch `build_batch()` reuse the same structure, so the P3 runtime wiring does not change the signature again.

The P2 block assembly boundary:

- `subject` still writes only the three fields `code`, `stock_name`, and `market` and does not extend `AnalysisSubject`.
- `phase` accepts only the `MarketPhaseContext.to_dict()` output that was passed in, and never infers it back from `enhanced_context`.
- `quote` is assembled from `realtime_quote`; when absent it is `missing`. A `source=fallback` or an explicit `fallback_from` maps to `fallback`, while `source` keeps the real successful source. `fallback_from` is filled in only when the artifact or metadata supplies it explicitly; otherwise only a stable warning code is recorded and no provider chain is fabricated.
- `quote` passes through the #1386 P3 fields `fetched_at`, `provider_timestamp`, `is_stale`, `stale_seconds`, and `fallback_from`. The status precedence is fixed at `STALE > FALLBACK > AVAILABLE`: an explicit marker such as `is_stale=True`, `price_stale`, `quote_stale`, or `quote_stale_seconds` marks it `stale`; `stale_seconds` with `is_stale=False` is metadata only and does not infer stale on its own. The builder only maps upstream artifacts and performs no quality scoring.
- `daily_bars` expresses only the complete daily window, preferring `base_context.today`, `base_context.yesterday`, `base_context.date`, and `base_context.data_missing`; a date-only value goes into `value` or `metadata` and is never written to `timestamp`.
- `is_partial_bar`, `is_estimated`, and `estimated_fields` on `enhanced_context.today` go into `technical` first; when they are missing, the older heuristic of `enhanced_context.today.data_source` being `realtime:*` still applies. Partial and estimated go only into `technical`, `daily_bars` carries no partial/estimated marker, and the warning is `intraday_realtime_overlay`.
- `technical` prefers reusing `trend_result.to_dict()`; with no trend artifact it is `missing`.
- `chip` reuses `chip_data.to_dict()`; with no chip artifact it defaults to `missing`, and it is marked `not_supported` only when the input metadata or artifact says so explicitly.
- `fundamentals` reads only the `fundamental_context` parameter: `ok` maps to `available`, `not_supported` to `not_supported`, `partial` to `partial`, and since P5 `failed` maps to `fetch_failed` plus the stable reason code `fundamental_pipeline_failed`; the original `errors[]` text is never written.
- `news` is `available` for a non-blank string and `missing` when blank or absent; `news_result_count` goes into the pack metadata.

P2 does not assemble `portfolio`, `events`, or `market_context`, and does not split `capital_flow` into its own block; the first version keeps it in the fundamentals coverage/source-chain metadata. At the time, P2 also changes no prompt, lets neither ordinary analysis nor the Agent runtime consume the pack, writes no history/task/report metadata, and exposes no complete pack to the API, web, bot, desktop, or notifications. P5 only adds low-sensitivity scoring, the `fetch_failed` refinement, and the prompt limitations on top of the existing builder, and adds no fetcher.

## P3 Runtime Consumption

P3 wires in runtime consumption after the P2 `AnalysisContextBuilder`, but limits the consumption surface to the low-sensitivity `analysis_context_pack_summary`. `StockAnalysisPipeline` is the only producer of that summary: it completes `PipelineAnalysisArtifacts` -> `AnalysisContextBuilder.build()` -> `format_analysis_context_pack_prompt_section()` inside both the ordinary analysis path and the Agent path. Downstream, the analyzer, the single agent, and the multi-agent chain receive only the summary string; none of them builds a complete pack itself or reads the raw block item values from `AnalysisContextPack.to_safe_dict()`.

The ordinary analysis prompt order is fixed as: basic information -> the #1386 `market_phase_context` rendered block -> `analysis_context_pack_summary` -> the existing technical, live-quote, and news blocks. `analysis_context_pack_summary` contains only the subject, `pack_version`, block `status` / `source` / `warnings` / `missing_reason`, `metadata.news_result_count`, `data_quality.warnings`, and the P5 low-sensitivity data limitations; it must never emit a raw payload such as `news.content`, `trend_result`, `chip`, or `fundamental_context`.

The Agent path likewise passes only the summary. `AgentExecutor._build_user_message()` inserts the summary after the market phase section and before the pre-fetched JSON; `AgentOrchestrator._build_context()` puts the summary only into `ctx.meta["analysis_context_pack_summary"]` and is forbidden to write `ctx.data`; `BaseAgent._build_messages()` inserts the summary after the market phase user message and before `_inject_cached_data()`. After the `_ensure_agent_history()` prefetch, the Agent path reads `storage.get_analysis_context()` once as the low-sensitivity status source for `daily_bars`, marking `daily_bars_missing` only when the read fails or no context is available; that read is fail-open and never writes the raw daily payload into the Agent runtime context. The Agent's first round does not reuse the ordinary analysis news retrieval, so a `missing` `news` block is the expected P3 state.

At the time, P3 persisted no complete pack, added no API/Web/Bot/Desktop field, changed no report JSON schema, and wrote the summary into neither `analysis_history.context_snapshot`, task status, nor report metadata; the history snapshot and the diagnostic snapshot strip the runtime prompt keys `market_phase_context`, `analysis_context_pack`, and `analysis_context_pack_summary`. P4 adds the low-sensitivity overview on top of that, with visibility covering only the history detail, the synchronous analysis response, completed task status, and the web report page; P5 keeps reusing the summary consumption path and does not change the LLM output JSON schema. Agent tool-level pack cache reuse remains future work.

## #1381 daily market context

Outside AnalysisContextPack, #1381 adds a small daily market-environment summary channel, so that `market_review` / `market_light` are not pack-ified directly. `DAILY_MARKET_CONTEXT_ENABLED` is on by default. When `MARKET_REVIEW_ENABLED=true` and `DAILY_MARKET_CONTEXT_ENABLED=true`, `StockAnalysisPipeline` loads the day's market context per stock market (`hk` / `us` / `ca`): it first reuses a same-day, same-market record in `analysis_history(code=MARKET, report_type=market_review)`, and only when there is no same-day record does it call `run_market_review(..., return_structured=True, send_notification=False)` to generate the context, using a process-level cache so one pipeline does not generate it twice and a market review lock to serialize generation across concurrent CLI and scheduled paths. `DAILY_MARKET_CONTEXT_ENABLED=false` disables only the low-sensitivity summary injection and the conservative guardrail for single-stock analysis, not the market review itself.

**Background:** `#1381` focuses on reusing and controlling the fallback of the day's market context in single-stock analysis, and changes neither the existing intraday phase, the daily report, nor the status modeling architecture. This section stays consistent with the #1381 entry under [Unreleased] in `docs/CHANGELOG.md` and can serve as the convergence boundary for this round's change notes.
**Scope (this round's implementation):** `#1381` covers only the backend runtime's market-context injection, same-day/target-trading-day reuse control, and the conservative guardrail. It does not include a standalone API, standalone presentation of web phase results, structured persistence of a four-stage daily report, or a new daily-report status table. The main entrypoints involved are `main.py` (scheduling and `--no-market-review`), `src/core/pipeline.py`, `src/core/market_review.py`, `src/services/daily_market_context.py`, `src/analyzer.py`, `src/analysis_context_pack_overview.py`, `src/agent/executor.py`, `src/agent/orchestrator.py`, `src/agent/agents/base_agent.py`, and `src/daily_market_context_guardrail.py`; on the web side only the `DAILY_MARKET_CONTEXT_ENABLED` setting's copy and help text are synced, with no new phase-result display.
**Acceptance closure boundary:** this PR corresponds only to the runtime wiring and guardrail sub-goal of `#1381`. Unless the standalone API, the web phase display, four-stage daily report persistence, and the daily-report status table land and are verified in later changes, Issue #1381 must not be marked fully accepted.
**Acceptance criteria:** this round is accepted against the runtime and configuration entrypoints only, and does not include the standalone API/Web UI phase display raised during the PR. The current acceptance path is limited to `tests/test_main_schedule_mode.py`, `tests/test_pipeline_daily_market_context.py`, `tests/test_daily_market_context.py`, `tests/test_daily_market_context_guardrail.py`, `tests/test_agent_executor.py`, `tests/test_config_env_compat.py`, `tests/test_config_registry.py`, and `apps/dsa-web/tests/system_config_i18n.test.ts`. The key coverage points are: `--no-market-review` prevents market-review generation; `DAILY_MARKET_CONTEXT_ENABLED=false` disables single-stock context injection while keeping the market review; one schedule run reuses the same `target_date`; multi-market context loading (`hk,us`); `daily_market_context` is injected exactly once in one analysis main path; and both the ordinary analysis and Agent paths apply the guardrail without leaking the raw `market_review_payload`.
**Compatibility and risk:** `#1381` changes no `provider/model/base_url`, no default model, and no configuration cleanup/backfill/migration semantics, and adds no database or runtime configuration table change. `main.py::_bootstrap_environment`, `src/core/pipeline.py`, `src/analyzer.py`, `src/agent/executor.py`, `src/agent/orchestrator.py`, `src/agent/agents/base_agent.py`, `src/services/daily_market_context.py`, and `src/daily_market_context_guardrail.py` consume the LLM and market-review context only on the existing read path and add no `SystemConfig` save or write-back branch. The official compatibility basis follows `LiteLLM OpenAI-compatible` and `OpenAI Chat Completion` (see "Compatibility evidence and verification boundary" below); rollback is an ordinary release rollback (reverting the relevant commits), optionally with a restart and cleanup of `env_file` / `--env-file` / process-level identically named environment overrides to restore the user's persisted historical configuration.
**Compatibility evidence and verification boundary:** this round only reads configuration through the existing LLM configuration path, adds no `.env` write branch, and adds no configuration migration/cleanup/write-back entrypoint. The official basis follows `LiteLLM OpenAI-compatible` <https://docs.litellm.ai/docs/providers/openai_compatible> and `OpenAI Chat Completion` <https://platform.openai.com/docs/api-reference/chat/create>; the version constraints are the current window for `litellm` and `openai` in `requirements.txt`. The traceable code paths are `main.py::_bootstrap_environment`, `src/analyzer.py::_init_litellm`, `src/agent/agents/base_agent.py::_get_analyzer_config` (read-only), `src/agent/executor.py`, `src/agent/orchestrator.py`, `src/core/pipeline.py`, `src/services/daily_market_context.py`, and `src/daily_market_context_guardrail.py`. The regression verification points are `tests/test_config_env_compat.py`, `tests/test_config_registry.py`, `tests/test_system_config_service.py`, `tests/test_system_config_api.py`, `tests/test_llm_channel_config.py`, and `tests/test_market_review_runtime.py`.

Ordinary analysis and Agent analysis receive only low-sensitivity fields: `daily_market_context` (region, trade_date, summary, risk_tags, source, and an optional position_cap) and the `daily_market_context_summary` prompt section. The complete `market_review_payload`, raw news, secrets, and notification configuration are never passed. The ordinary analysis prompt inserts the market summary after the market phase section and before the technical data; the single-agent and multi-agent paths insert the same summary after the market phase and before the pre-fetched data. Agent free chat injects it only when the caller already supplied `daily_market_context` / `daily_market_context_summary`, and never triggers a market review automatically for each chat.

Result post-processing adds a conservative market-environment guardrail: when the summary or the tags show `high_risk`, `market_cooling`, `conservative`, or `low_position_cap` in a conservative or high-risk context, a model `buy` decision (including buy-type advice such as buying immediately, chasing, or adding aggressively) is softened to wait-and-see or a small position pending confirmation, and high confidence is lowered to medium. The guardrail modifies only that run's `AnalysisResult` and the low-sensitivity limitation note in the dashboard, and adds no database table or API field. Rollback means reverting the #1381 service, prompt injection, and guardrail code; existing market-review history stays compatible.

## P4 history records, task status, and web visibility

P4 projects the `AnalysisContextPack` that P3 already builds into the public low-sensitivity `analysis_context_pack_overview`. That overview is produced by a dedicated renderer, and the public API must never return `AnalysisContextPack.to_safe_dict()` or a complete pack dump directly. The renderer emits only allow-listed fields: `pack_version`, `created_at`, `subject.code` / `stock_name` / `market`, each block's `key` / `label` / `status` / `source` / `warnings` / `missing_reasons`, `counts` by block status, the top-level `data_quality.warnings`, and `metadata.trigger_source` / `metadata.news_result_count`. P5 adds a low-sensitivity `data_quality` object to the same overview without duplicating the top-level `warnings`.

The overview emits no `blocks.*.items`, `items.value`, `news.content`, `trend_result`, `chip`, or `fundamental_context` raw payload, and no sensitive key or value such as `api_key`, `token`, `cookie`, `webhook_url`, `password`, `secret`, `authorization`, `sendkey`, or `license_key`.

P4's persistence surface writes `analysis_context_pack_overview` only at the top level of `analysis_history.context_snapshot`. Runtime prompt fields are still stripped from `enhanced_context` and the history snapshot: `market_phase_context`, `analysis_context_pack`, and `analysis_context_pack_summary` never enter the public history detail or task status. With `SAVE_CONTEXT_SNAPSHOT=false` the whole `analysis_history.context_snapshot` is not persisted, so neither the overview, `market_phase_summary`, `enhanced_context`, nor the raw snapshot fields reach the database; older records, and records with no overview, keep returning empty fields without affecting history detail reads.

The public API field is fixed at `report.details.analysis_context_pack_overview`, which the web client reads as `analysisContextPackOverview` after deep camelCasing. The wiring covers:

- The `GET /api/v1/history/{record_id}` history detail.
- The `AnalysisResultResponse.report.details` returned by the synchronous `POST /api/v1/analysis/analyze` — but the overview depends on a persisted `analysis_history.context_snapshot`, so with `SAVE_CONTEXT_SNAPSHOT=false` a new record is not guaranteed to return one.
- A completed `GET /api/v1/analysis/status/{task_id}`, including in-memory queue enrichment and the DB completed fallback.

The `details.context_snapshot` the API returns to the web client passes through `sanitize_context_snapshot_for_api()`, which strips the top-level `analysis_context_pack_overview` so the raw snapshot panel neither duplicates it nor lets it be exported as a complete context; the overview is taken out separately by `extract_analysis_context_pack_overview()`. The Agent path and the ordinary analysis path write the same overview shape, and `metadata.news_result_count` may be empty when the Agent has no news count.

P4's web presentation renders `AnalysisContextSummary` on the report detail page only, positioned after the strategy levels and news and before the run diagnostics. That area is collapsed by default; the collapsed header shows the available count, the missing count, any non-zero other status counts, and the trigger source, and each expanded block shows only its status, source, warnings, and explanation. When the source is empty it shows “未记录输入来源”; the explanation line translates a known missing reason into the reason, its impact on this analysis, and a short handling suggestion, keeping the diagnostic code in parentheses, and falls back to generic advice by block status for an unknown reason. Degraded states with no missing reason, such as `fallback`, `stale`, `estimated`, and `partial`, are explained on the same line, with no new handling, scope, or evidence field. The report page's related news is loaded by a separate endpoint, and its presence or absence must not be inferred from the overview's `metadata.news_result_count`: the news area states only that it is supplementary news for the report page, while the input block states only whether news entered this LLM analysis, so the two data scopes are not conflated into one result set. The expanded area still shows the status counts and the news result count. Since P5 the collapsed header also shows the quality score and level, and the expanded view shows `limitations` and the `fetch_failed` status. With no overview, no placeholder is rendered. In #1386 P4b the web client shows the `report.meta.market_phase_summary` phase label on the same report detail page and keeps reusing that low-sensitivity data-quality summary; it does not widen the public surface of the complete pack, the prompt summary, raw payloads, or snapshot internals. P4/P5 do not cover the AnalysisContextPack data-quality summary on a pending/processing TaskPanel or in-progress SSE overview visibility, and change neither the notification summary, the Bot/Desktop-specific display, nor the `market_review` overview.

## P5 data-quality scoring and prompt data limitations

P5 does not raise `PACK_VERSION`, adds no fetcher, adds no configuration option, and performs no history migration. Within those limits it completes three things: internal low-sensitivity data-quality scoring, a model-agnostic prompt data-limitations block, and a low-sensitivity visibility extension of the existing `analysis_context_pack_overview`. #1389 P5 still changes no LLM output JSON schema and does no forced post-processing rewrite; #1386 P5 consumes this low-sensitivity input quality and emits the intraday action fields and guardrail result in the report's `dashboard.phase_decision`.

The status contract adds `fetch_failed`, for "this field or block explicitly failed to fetch this time". The first version uses it only when an existing artifact fails explicitly, for example `fundamental_context.status == "failed"`. Empty news, unconfigured search, a missing live quote artifact, and missing chips keep their existing `missing` / `not_supported` semantics, so a capability that is simply not enabled is not misreported as a fetch failure. `fetch_failed` does not mean the whole analysis failed.

`DataQuality` adds these low-sensitivity fields and keeps the old `warnings` / `metadata`:

- `overall_score: Optional[int]`: a 0-100 total score.
- `level: Optional["good"|"usable"|"limited"|"poor"]`: `>=85 good`, `>=70 usable`, `>=55 limited`, otherwise `poor`.
- `block_scores: Dict[str, int]`: the status score of the six fixed blocks.
- `limitations: List[str]`: at most 5 stable limitation notes, in `block: status` form.

Scoring covers the six fixed blocks only and is not renormalized when an auxiliary block is missing, so a block added later does not automatically affect the total. The weights are fixed at `quote=25`, `daily_bars=25`, `technical=25`, `news=10`, `fundamentals=10`, and `chip=5`; the status scores are fixed at `available=100`, `partial=75`, `estimated=75`, `not_supported=70`, `fallback=65`, `stale=50`, `missing=35`, and `fetch_failed=25`. The total is `round(sum(block_score * weight) / 100)`.

`limitations` lists the core blocks `quote` / `daily_bars` / `technical` first for `stale`, `fallback`, `missing`, `fetch_failed`, `partial`, and `estimated`, then the auxiliary blocks `news` / `fundamentals` / `chip` for `fetch_failed`, `fallback`, and `stale`. A merely missing auxiliary block does not enter the limitation list, so missing news, unconfigured search, and an unsupported capability are not read as bullish or bearish.

The prompt data limitations are rendered only inside `format_analysis_context_pack_prompt_section()`, immediately after the pack summary, so ordinary analysis, the single agent, and the multi-agent chain all share one consumption path. Chinese output uses `数据限制` and English output uses `Data Limitations`; the score line is emitted only when a real score exists. If `quote`, `daily_bars`, or `technical` is in a degraded state, the prompt explicitly requires the final JSON's `confidence_level` not to be `高` / `High`. The prompt still uses only status/source/warnings/missing_reason and the low-sensitivity score, and emits no raw payload, news body text, raw trend values, secret, token, or webhook.

After the P5 score and limitations and before the confidence/safety rules, #1386 P2-full adds a minimal `phase × degraded data` cross constraint: when `AnalysisContextPack.phase` comes from a valid `MarketPhaseContext` and `quote`, `daily_bars`, or `technical` is degraded, the prompt adds only how data quality limits intraday judgment, the opening plan, or a conservative analysis in the current phase. It does not replace the P5 confidence/safety rules and does not restate the phase-only copy from `market_phase_context`. When `pack.phase` is missing, is not a dict, or carries an invalid phase, it is fail-open and keeps only the generic P5 data limitations.

The overview extends the existing public surface only: the `analysis_context_pack_overview.data_quality` allow-list contains `overall_score`, `level`, `block_scores`, and `limitations`, and does not publish `warnings` a second time. `render_analysis_context_pack_overview()`, `extract_analysis_context_pack_overview()`, and the persisted sanitizer all clean that object; an older overview with no `data_quality` still reads normally. `details.context_snapshot` keeps stripping the top-level `analysis_context_pack_overview` and does not publish the complete pack.

## P6 alert, holdings, history, and backtest linkage

#1386 P6 adds no pack version and exposes no complete pack to more public surfaces. It only reuses the `analysis_context_pack_overview` that P4/P5 already defined and the `market_phase_summary` that #1386 already defined:

- An alert trigger record is still written to the existing `alert_triggers.diagnostics` text field; when the diagnostics can be JSON-encoded, the worker merges `analysis_visibility.analysis_context_pack_overview`, whose source may only be an overview the evaluator already carries or a history snapshot from the last 30 days. Old plain-text diagnostics are never overwritten, the API derived field is empty, and the source is `legacy_text`.
- A manual holdings analysis builds a low-sensitivity `portfolio_context` through the API and passes it into the pipeline; the builder then adds an optional `portfolio` block to the pack. That block contains only the account ID/name, symbol, market, currency, quantity, average cost, total cost, unrealized PnL, price source/provider/date/stale/available, and the cost method — no trade ledger, cash ledger, news body text, prompt, secret, or webhook.
- The `portfolio` block is auxiliary, with `metadata={"auxiliary": true, "quality_weighted": false}`, and changes neither the weights, the total score, nor the limitations of P5's six fixed blocks `quote`, `daily_bars`, `technical`, `news`, `fundamentals`, and `chip`.
- `portfolio_context` is passed through inside task execution only; `TaskInfo.to_dict()`, the task list, and the SSE `task_created/task_started/task_completed/task_failed/task_progress` payloads never expose that object.
- The history list, single-stock history, StockBar, and backtest results read only the public `market_phase_summary` at the top level of `context_snapshot`; an old record, `SAVE_CONTEXT_SNAPSHOT=false`, or a parse failure returns `null` / `unknown` without failing.
- The backtest phase filter buckets purely on the public summary: `premarket` stays premarket, `intraday|lunch_break|closing_auction` becomes intraday, `postmarket` stays postmarket, and `non_trading|missing|invalid` becomes unknown. With a phase filter, the repository first reads the results and snapshots in bulk under SQL conditions and the service layer buckets them before paging and computing statistics, so no temporary filtering happens after API-layer paging.
- The notification summary consumes only `market_phase_summary` and `analysis_context_pack_overview.data_quality`, emitting the phase, the trigger source, the partial-bar warning, the quality level, and the first two limitations; it emits no raw pack, no `analysis_context_pack_summary` prompt string, no news body text, and no sensitive holdings detail.

## P6 documentation, migration, and rollback

P6 changes none of the P1-P5 runtime behavior; it only turns the contracts, visibility, configuration, migration, and rollback boundaries that already landed into stable documentation. It adds no pack enable/disable feature flag, does not raise `PACK_VERSION = "1.0"`, adds no API parameter, changes no report JSON schema, and performs no database migration.

Four data surfaces must be understood separately:

| Data surface | Location | Visibility | P6 boundary |
| --- | --- | --- | --- |
| The internal complete pack | The `AnalysisContextPack` / `AnalysisContextBuilder` output | Internal runtime use only | Not a public API, not written to history, and carrying no promise of a stable external wire contract. |
| The low-sensitivity LLM summary | `analysis_context_pack_summary` | The ordinary analysis, single agent, and multi-agent prompts | Contains only the subject, the pack version, block status/source/warnings/missing reason, the news result count, and the data limitations; it contains no `items.value`, news body text, trend/chip/fundamentals raw payload, secret, token, or webhook. |
| The public low-sensitivity overview | `report.details.analysis_context_pack_overview` | History detail, the synchronous analysis response, completed task status, the web report page | Emits only allow-listed fields and the `data_quality` low-sensitivity score; it emits no complete pack, prompt summary, or raw payload. |
| The historical context snapshot | `analysis_history.context_snapshot` | Read after persistence by history, the API, the web client, and diagnostics | `details.context_snapshot` passes through `sanitize_context_snapshot_for_api()`, which strips `analysis_context_pack_overview` and `market_phase_summary` so the raw panel does not republish the stable summary. |

The summary visibility matrix:

| Consumer | Exposed | Not exposed |
| --- | --- | --- |
| The LLM prompt | The `analysis_context_pack_summary` low-sensitivity status summary and data limitations | The complete pack, `items.value`, news body text, trend/chip/fundamentals raw payload, secret/token/webhook |
| `GET /api/v1/history/{record_id}` | `report.details.analysis_context_pack_overview` | The complete pack, the prompt summary, a raw `analysis_context_pack_overview` duplicate |
| The synchronous `POST /api/v1/analysis/analyze` | `report.details.analysis_context_pack_overview`, provided this run's history already persisted `analysis_history.context_snapshot` | The complete pack, the prompt summary |
| A completed `GET /api/v1/analysis/status/{task_id}` | `status.result.report.details.analysis_context_pack_overview` | The complete pack, the prompt summary |
| The web report page | The `AnalysisContextSummary`, collapsed by default, showing block status, source, warnings, an explanation with impact/suggestion/diagnostic code, the quality score, and the limitations | The complete pack, raw payloads, the prompt summary, the status of the news results the report page loads separately |
| The raw `details.context_snapshot` | The stripped history snapshot | The top-level `analysis_context_pack_overview` and `market_phase_summary` |
| Notification, Bot, and Desktop-specific display | P6 adds no dedicated display | The complete pack, the prompt summary, raw payloads |

The full set of field quality statuses stays `available`, `missing`, `not_supported`, `fallback`, `stale`, `estimated`, `partial`, and `fetch_failed`. These statuses explain input data quality and do not indicate whether the analysis task, an alert, a backtest, or notification delivery itself succeeded or failed.

The redaction boundary:

- The complete `AnalysisContextPack` never enters the public API, the web client, notifications, the Bot, or a Desktop-specific display.
- `AnalysisContextPack.to_safe_dict()` is an internal safe-serialization helper only; the public overview must still be projected through `render_analysis_context_pack_overview()`.
- Neither `analysis_context_pack_summary` nor the overview may emit `items.value`, news body text, a `trend_result`, `chip`, or `fundamental_context` raw payload, an API key, a token, a cookie, a complete webhook URL, an email password, a secret, an authorization value, a sendkey, or a license key.
- A persisted overview must pass through `extract_analysis_context_pack_overview()` or the persisted sanitizer when read back; the API transparency panel must keep stripping the top-level stable summary through `sanitize_context_snapshot_for_api()`.

The migration boundary:

- P6 performs no DB migration; an old history record with no `analysis_context_pack_overview` or `data_quality` returns empty fields, and the report still reads normally.
- `SAVE_CONTEXT_SNAPSHOT=true` is the default and keeps persisting `analysis_history.context_snapshot` as the source of historical transparency and diagnostics.
- With `SAVE_CONTEXT_SNAPSHOT=false` or the CLI `--no-context-snapshot`, the whole `analysis_history.context_snapshot` is not persisted. In other words, new history stores none of it, including `enhanced_context`, `market_phase_summary`, `analysis_context_pack_overview`, `diagnostics`, `realtime_quote_raw`, and the other raw snapshot fields.
- Turning persistence off does not affect this run's `AnalysisContextPack` construction, the `analysis_context_pack_summary` injected into the prompt, or the in-memory `result.diagnostic_context_snapshot`.

Rollback options:

| Method | Effect | What it cannot do |
| --- | --- | --- |
| A release or code rollback of the P3-P5 changes | Removes the pack prompt summary, the overview, and the data-quality wiring | - |
| `SAVE_CONTEXT_SNAPSHOT=false` or `--no-context-snapshot` | Stops saving new history `context_snapshot` values, so the overview, phase summary, and raw snapshot are no longer published from new history | It cannot turn off this run's pack construction or the low-sensitivity summary in the LLM prompt |
| A runtime pack master switch | Does not exist today | An env variable cannot turn off the P3-P5 pack wiring; that needs a code rollback or a separate later design |

## Field quality statuses

P0 fixes the future pack's field quality statuses at seven words first; P5 adds `fetch_failed` within the same 1.0 umbrella. They describe the quality of a field or block, not whether a business process succeeded.

| Status | Meaning | Example boundary |
| --- | --- | --- |
| `available` | The field exists, its source and timestamp are explicable, and the current path can use it normally. | A live quote returns a price and a source; the historical K-line window satisfies the computation. |
| `missing` | The current path needs the field, but nothing was fetched or the value is empty. | The database has no recent daily bars and ordinary analysis reaches a `data_missing` result. |
| `not_supported` | The current market, data source, or path does not support the field, and it must not be misreported as an error. | Some markets have no chip distribution or capital flow. |
| `fallback` | The preferred source was unavailable, so a backup source or older path was used. | A holdings price falls back from the live quote to the historical close. |
| `stale` | The field exists, but it is not fresh enough. | `price_stale` / `fx_stale` in a holdings valuation. |
| `estimated` | The field is an estimate and must not be treated as complete fact. | Filling today's bar with the live price intraday and generating a technical estimate from it. |
| `partial` | The block is partly available and partly missing. | A market-light `data_quality=partial`, or a tool returning `partial_cache`. |
| `fetch_failed` | The current path confirms a fetch was attempted but failed this time. | `fundamental_context.status == "failed"` maps to a fundamentals block fetch failure. |

## Existing status mapping

The repository already has plenty of status words. P0 only establishes a mapping or an explicit non-mapping, so that business result statuses are not mixed into the field quality enumeration later.

| Existing word or field | Current location | Suggested relationship | Notes |
| --- | --- | --- | --- |
| `data_missing` | The ordinary analysis result for missing history | Maps to `missing` | This is a core input that is missing, not a business success status. |
| `cache_hit` / `partial_cache` | The Agent history-data tool | `partial_cache` maps to `partial` | `cache_hit` is source/cache metadata, not a quality status. |
| `source` / `data_source` / `realtime_source` | Data sources, alerts, the context snapshot | No mapping | These are source metadata and should be stored alongside the field quality status. |
| `price_source=missing` | The holdings snapshot | Maps to `missing` | It means the valuation price is unavailable. |
| `price_stale` / `fx_stale` | The holdings snapshot | Maps to `stale` | Keep the original fields as business metadata. |
| `triggered` / `skipped` / `degraded` / `failed` | Alert evaluation and records | No mapping | These are rule evaluation or record results, not field-level quality statuses. |
| `insufficient_data` / `completed` / `error` | The backtest service | No mapping | These are backtest execution statuses; the pack summary may explain what triggered them. |
| `sent` / `no_channel` / `partial_failed` / `all_failed` | Notification sending | No mapping | These are delivery results and cannot be read back as analysis input quality. |
| `data_quality=ok/partial/unavailable` | The market light | `partial` maps across, and `unavailable` maps to `missing` or `not_supported` depending on the field | P0 does not bring the market light into the first single-stock pack. |
| `fetch_failed` | A data-quality refinement | P5 maps it to `fetch_failed` | Used only when an existing artifact fails explicitly; it does not mean the whole analysis failed. |

## The seven-path inventory

### Ordinary analysis

The main ordinary analysis path assembles its input in `src/core/pipeline.py`: it reads `storage.get_analysis_context()` first, then adds live quotes, chips, trend analysis, news, fundamentals, and the report language as available, and finally hands everything to `src/analyzer.py` to render the prompt. The main duplication today is that live fields exist simultaneously in `enhanced_context.realtime`, `realtime_quote_raw`, and the report meta, and the naming carries several source fields such as `source`, `data_source`, and `realtime_source`.

The first pack version can extract the single-stock core identity, quote, daily bars, technicals, news, fundamentals, and data-quality summary from the ordinary analysis path; P0 changes neither `_enhance_context()`, `_build_context_snapshot()`, nor the analyzer prompt.

### Agent

The Agent has three data surfaces that must be recorded separately. The Agent path in `src/core/pipeline.py` builds `initial_context`, which always contains `fundamental_context` and adds `trend_result` when available, and is finally persisted as the Agent path's `context_snapshot`. `AgentExecutor._build_user_message()` applies only to `AGENT_ARCH=single`, and its first message explicitly injects only already-fetched context such as `realtime_quote`, `chip_distribution`, and `news_context`, with no explicit injection of `fundamental_context` or `trend_result`. `AgentOrchestrator._build_context()` applies to `AGENT_ARCH=multi` and can pre-inject `realtime_quote`, `daily_history`, `chip_distribution`, `trend_result`, and `news_context`; those fields enter `AgentContext` and are injected into the stage agent messages as pre-fetched data, but the orchestrator does not pre-inject `fundamental_context`. `trend_result` is not naturally present and depends on whether the caller passed it.

The Agent tools also call `get_realtime_quote`, `get_daily_history`, `get_chip_distribution`, `get_analysis_context`, `get_stock_info`, and similar tools independently, which can easily duplicate what ordinary analysis prefetched. Pack generation currently reuses only the daily-bar availability state from `storage.get_analysis_context()` after the Agent history prefetch, and neither reuses nor exposes the complete tool-level pack cache; whether to do deeper data-quality scoring and tool cache reuse is a P5 decision.

### Alerts

The alert path evaluates rules, records trigger history, and dispatches notifications in `src/services/alert_worker.py`; for the field semantics see [the real-time alert center](alerts.md). Alert statuses such as `triggered`, `skipped`, `degraded`, and `failed` are rule evaluation or record statuses and cannot be written into the field quality enumeration directly.

The first pack version does not treat alert rule evaluation as an input block; alerts later consume only the pack's field quality summary, such as whether the core quote fell back, went stale, or was partial.

### Holdings

The holdings snapshot aggregates the account, positions, cost, price, FX, and risk inputs in `src/services/portfolio_service.py`, with the API output structure in `api/v1/schemas/portfolio.py`. It already has fields such as `price_source`, `price_provider`, `price_date`, `price_stale`, `price_available`, and `fx_stale`.

The first pack version can record whether the stock is held, the account summary, cost, quantity, position, unrealized PnL, and the price/FX stale summary, but it includes no trade ledger, cash ledger, corporate action, or complete account privacy data.

### Backtesting

The backtest service consumes historical analysis records and daily data in `src/services/backtest_service.py` and `src/repositories/backtest_repo.py`. The existing `parse_analysis_date_from_snapshot()` depends on `analysis_history.context_snapshot.enhanced_context.date` to parse the analysis date.

P0 must mark `enhanced_context.date` as a compatibility boundary. A later pack may add a clearer date field, but it must not delete or rename the current date location in the history snapshot without a migration.

### History

History detail returns `raw_result`, `news_content`, `context_snapshot`, and other fields in `src/services/history_service.py`, `api/v1/endpoints/history.py`, and `api/v1/schemas/history.py`. The synchronous analysis/status response also reads `context_snapshot.enhanced_context`, `realtime_quote_raw`, and the fundamentals fallback in `api/v1/endpoints/analysis.py`.

P0 only records the history consumption surface. The complete pack should not be public by default in the history detail or the public API; if P4 needs to show something later, it should expose the summary, the source, and the degradation notes first.

### Notifications

The notification path consumes `AnalysisResult`, the dashboard, the market snapshot, data_sources, and other output in `src/notification.py`, and records delivery statuses such as `sent`, `no_channel`, `partial_failed`, and `all_failed`; for the channel configuration and boundaries see [the notification capability baseline](notifications.md).

Notifications are not a factual data layer and must never record a delivery failure as an input quality failure. Later they should consume the pack summary only where it is needed, for example to say that the live quote is degraded, that fundamentals are missing, or that the news sources are thin.

## Source anchors

| Area | Anchor |
| --- | --- |
| Ordinary analysis | `src/core/pipeline.py`, `src/storage.py`, `src/analyzer.py` |
| Agent | `src/agent/orchestrator.py`, `src/agent/executor.py`, `src/agent/tools/data_tools.py` |
| Alerts | `src/services/alert_worker.py`, `docs/alerts.md` |
| Holdings | `src/services/portfolio_service.py`, `api/v1/schemas/portfolio.py` |
| Backtesting | `src/services/backtest_service.py`, `src/repositories/backtest_repo.py` |
| History | `src/services/history_service.py`, `api/v1/endpoints/history.py`, `api/v1/endpoints/analysis.py`, `api/v1/schemas/history.py` |
| Notifications | `src/notification.py`, `docs/notifications.md` |

## Compatibility and safety boundaries

- `analysis_history.context_snapshot.enhanced_context.date` is the current backtest date-parsing compatibility point, which P1/P2 must not break without a migration.
- The complete pack is not public by default to history, the API, the web client, or notifications; P4/P5 publish only the `analysis_context_pack_overview` low-sensitivity summary, source, fallback, stale, missing reason, block status counts, and the `data_quality` low-sensitivity score.
- The pack, the logs, the history snapshot, and API responses must never record an API key, token, cookie, complete webhook URL, email password, private environment variable, or any other secret.
- Quality metadata such as `source`, `timestamp`, `fallback`, `stale`, and `partial` exists only to explain input limitations and is never used to block an analysis, unless the existing core path was already fail-fast.
- The #1386 premarket and intraday phase awareness is important background for the later `phase` / `data_quality` fields; P0 records the relationship only and wires in no runtime.

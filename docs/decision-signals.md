# DecisionSignal Topic

This page closes out #1390 P7 and explains how DSA distils the AI recommendations produced by single-stock analysis, the Agent, alerts, and portfolio risk into a queryable, reviewable, and retrospectively assessable `DecisionSignal` asset. It is a structured index layered on top of reports; it replaces neither the Markdown report, `operation_advice`, the three-state `decision_type`, alert rules, nor a real trading system.

## Capability boundary

- A `DecisionSignal` records only the recommendation, evidence summary, risks, watch conditions, lifecycle, and provenance. It places no orders and rebalances nothing.
- A failed write, a failed extraction, a failed alert-signal association, and a failed notification send never block the main analysis, the alert trigger, or report persistence.
- #1756 promoted `decision_profile` to a real field and corrected the server-side filter, deduplication, refresh, and active-invalidation semantics; #1757 added user-confirmed reassess persistence on top of that formal field contract. Neither adds an environment variable, a config registry entry, or `.env.example` content.
- There is currently no `DECISION_SIGNAL_*` toggle; disabling or rolling back the signal feature is done by reverting the corresponding code.

## Fields and enumerations

The core fields are defined in `api/v1/schemas/decision_signals.py` and cover:

- Identity and provenance: `stock_code`, `stock_name`, `market`, `source_type`, `source_agent`, `source_report_id`, `trace_id`, `decision_profile`, `trigger_source`.
- Recommendation semantics: `action`, `action_label`, `confidence`, `score`, `horizon`, `market_phase`, `plan_quality`, `status`.
- Plan and explanation: `entry_low`, `entry_high`, `stop_loss`, `target_price`, `invalidation`, `watch_conditions`, `reason`, `risk_summary`, `catalyst_summary`.
- Evidence and quality: `evidence`, `data_quality_summary`, `metadata`.
- Lifecycle: `expires_at`, `created_at`, `updated_at`.

Enumerated values:

| Field | Values |
| --- | --- |
| `market` | `us`, `ca` |
| `source_type` | `analysis`, `agent`, `alert`, `market_review`, `manual` |
| `market_phase` | `premarket`, `intraday`, `lunch_break`, `closing_auction`, `postmarket`, `non_trading`, `unknown` |
| `action` | `buy`, `add`, `hold`, `reduce`, `sell`, `watch`, `avoid`, `alert` |
| `horizon` | `intraday`, `1d`, `3d`, `5d`, `10d`, `swing`, `long` |
| `decision_profile` | `conservative`, `balanced`, `aggressive`; a database `NULL` means legacy / unknown |
| `plan_quality` | `complete`, `partial`, `minimal`, `unknown` |
| `status` | `active`, `expired`, `invalidated`, `closed`, `archived` |

The web UI must map these wire values to user-readable labels in the current UI language; API responses keep the raw enumerated values.

## Canonical scoring and action semantics

Single-stock analysis, the technical-scoring fallback, the report-presentation fallback, and `DecisionSignal` extraction all share the `decision-scale-v1` scale. `decision_type` is kept only as `buy|hold|sell` for compatible statistics; the finer executable semantics come from the eight-state `action`.

- Two user-visible fields coexist: `operation_advice` keeps the textual wording (for example "持有观察"), while `action` is the unified eight-state decision value (for example `hold/watch/reduce`) used for risk control, backtesting, and list display. A newly generated report, or one rescored before final save, should keep the two consistent. When a historical record or a compatibility payload still shows a semantic conflict, `action` is the preferred field for structured surfaces such as lists, backtests, and DecisionSignal, and `operation_advice` is kept as explanatory text only.

| score | signal key | `action` | legacy `decision_type` | Meaning |
| --- | --- | --- | --- | --- |
| 80-100 | `strong_buy` | `buy` | `buy` | Strong buy: a high-win-rate opportunity with an executable buy/add plan |
| 60-79 | `buy` | `buy` | `buy` | A moderately positive opportunity; a few unconfirmed items are acceptable |
| 40-59 | `watch` | `watch` | `hold` | Signals disagree or confirmation is weak; wait for the trigger condition |
| 20-39 | `reduce` | `reduce` | `sell` | Risk has risen clearly; reduce exposure first |
| 0-19 | `sell` | `sell` | `sell` | The trend or risk has deteriorated markedly; exit first |

When `score >= 60` but the final `action` is `hold/watch`, or `score < 40` but the final `action` is still `hold/watch`, an explicit guardrail explanation is required — for example `dashboard.decision_stability.reason`, `dashboard.decision_score_calibration.guardrail_reason`, or `metadata.guardrail_reason`. A risk-control downgrade keeps `raw_score`, `adjusted_score`, `raw_action`, `final_action`, and the reason. A neutral action with no explicit reason is aligned to `buy/reduce/sell` by canonical score during DecisionSignal extraction.

## Lifecycle, deduplication, and status

`src/services/decision_signal_service.py` is the main entrypoint for the signal lifecycle:

- An explicitly supplied `horizon` and `expires_at` win.
- With no `horizon`, an `alert` — or the premarket, intraday, lunch-break, or closing-auction phase — defaults to `intraday`; postmarket, non-trading, an unknown phase, or a missing phase defaults to `3d`.
- An `intraday` expiry time prefers the low-sensitivity `metadata.market_phase_summary.minutes_to_close/minutes_to_open`; when that is missing, the market's fallback TTL applies.
- `expired`, `invalidated`, `closed`, and `archived` cannot be restored to `active` directly through `PATCH /status`.
- Same-source deduplication prefers `(source_report_id, source_type, market, stock_code, decision_profile, action, horizon, market_phase)`; with no report but a `trace_id`, the trace dimension is used.
- `decision_profile` is part of signal identity: `NULL` matches only `NULL`, and a non-empty profile matches only the same profile. Exact dedup, relaxed dedup, horizon/phase fill, expired refresh, active invalidation, and stale backfill invalidation all follow that same-profile rule.
- A new opposing active signal marks only the previous active signal of the same profile as `invalidated`, and records the invalidation source in metadata. Different non-`NULL` profiles can coexist even when their actions are opposed.
- An expired duplicate refresh never rewrites `decision_profile`; it can only refresh a record of the same profile.

## API

The currently public endpoints are described by `api/v1/endpoints/decision_signals.py` and `docs/architecture/api_spec.json`:

- `POST /api/v1/decision-signals`: creates, or deduplicates on the same-source key, and returns `{ item, created }`.
- `GET /api/v1/decision-signals`: a paged query supporting market, stock, action, phase, `decision_profile`, source, status, time range, and holdings filters. Omitting `decision_profile` or passing it empty adds no profile condition and returns every profile; `decision_profile=unknown` queries `NULL` rows; a valid profile matches exactly.
- `GET /api/v1/decision-signals/{signal_id}`: fetches one record.
- `PATCH /api/v1/decision-signals/{signal_id}/status`: updates the status and optional metadata.
- `GET /api/v1/decision-signals/latest/{stock_code}`: fetches a stock's latest active signal.
- `POST /api/v1/decision-signals/outcomes/run`: triggers retrospective evaluation explicitly.
- `GET /api/v1/decision-signals/outcomes`, `GET /api/v1/decision-signals/outcomes/stats`, `GET /api/v1/decision-signals/{signal_id}/outcomes`: query retrospective results and statistics.
- `GET/PUT /api/v1/decision-signals/{signal_id}/feedback`: reads or writes useful / not-useful feedback.
- `POST /api/v1/decision-signals/reassess`: recomputes the signal under a different decision profile from the source historical report snapshot. `persist=false` previews only; `persist=true` has the server recompute and save the result if it passes the guardrail.

These endpoints inherit the existing `/api/v1/*` administrator authentication; with `ADMIN_AUTH_ENABLED=true` a valid administrator session cookie is required.

## Historical performance by decision profile

#1758 appends `profile_calibration` to the existing `GET /api/v1/decision-signals/outcomes/stats` response, adding no endpoint, database table, configuration option, or quote request. The previous global statistics fields and the eight single-dimension breakdowns keep their original meaning. One sample is still one `(signal_id, horizon, engine_version)` outcome record, and different review horizons for the same signal are counted separately, so the figure must not be read as a count of distinct signals.

`profile_calibration.minimum_completed_sample_size` is fixed at `30`, and the breakdowns are:

- `decision_profile`
- `decision_profile_action`
- `decision_profile_horizon`
- `decision_profile_market_phase`
- `decision_profile_data_quality_level`
- `profile_source`

Every bucket's `dimensions` are structured fields, not concatenated strings. Profile calibration resolves its sources as follows:

- `decision_profile` reads the associated signal's current formal field; `NULL` or an invalid value falls into `unknown` and never falls back to `balanced`.
- `profile_source` reads the associated signal's current metadata and accepts only `auto_default`, `backfill_defaulted`, `legacy_unknown`, and `user_selected`; anything else falls into `unknown`. This is a current attribution rather than a snapshot at outcome time, so statistics can shift after metadata is legitimately replaced.
- `action`, `horizon`, `market_phase`, and `data_quality_level` read the outcome's frozen fields. When a new outcome is created, data quality prefers the explicit level in `data_quality_summary`; only when the summary is missing, or valid JSON carries no explicit level, does the normalized `metadata.data_quality_level` apply. An existing outcome is never silently rewritten by this read rule.

Each bucket applies the `completed >= 30` threshold independently: neither the parent bucket, the global sample, nor a sibling bucket can unlock it. Below the threshold the counts are still returned, but `hit_rate_pct`, `avg_stock_return_pct`, `miss_rate_pct`, `unable_rate_pct`, and `max_adverse_excursion_pct` are all `null`, and the web UI shows only the sample size and "Insufficient sample size; for observation only." Above the threshold:

- The hit rate is `hit / (hit + miss)` and the miss rate is `miss / (hit + miss)`; neutral outcomes enter neither denominator.
- The unable-to-evaluate rate is `unable / total`.
- The average interval return follows the existing mean of `stock_return_pct` across completed outcomes, and does not represent strategy or portfolio return.
- Maximum adverse excursion uses only the prices already stored on the outcome. `buy/add/hold/watch/alert` uses `(start_price - min_low) / start_price` and `sell/reduce/avoid` uses `(max_high - start_price) / start_price`, with a floor of 0. A row is not computable when a price is missing or non-finite, or when the starting price is not positive. A bucket returns the maximum across computable rows; with no computable row it is `null`, and no quote is fetched to fill the metric in.

Inside the existing signal performance card, the web UI offers Conservative / Balanced / Aggressive as three user entrypoints, defaults to Balanced, and provides only the two breakdown views "by suggested action" and "by review horizon". It does not rank or recommend a profile, and it adds no request, route, navigation entry, or setting. An older backend without `profile_calibration` still shows the original statistics card.

## Reassess preview and persist

`reassess` uses only the persisted historical report snapshot behind `source_report_id`. `persist=false` is for previewing before the user confirms; `persist=true` recomputes server-side from the same `source_report_id + decision_profile` and trusts no decision field from the earlier preview or a client cache.

The request supports only:

```json
{
  "source_report_id": 123,
  "decision_profile": "aggressive",
  "persist": false
}
```

Contract boundaries:

- `source_report_id` is the single source of truth, and reassessment reads only the persisted historical report snapshot behind it.
- The request allows only `source_report_id`, `decision_profile`, and `persist`. `signal_id` is unsupported, and client-submitted authoritative fields such as `action`, `score`, `confidence`, `horizon`, `invalidation`, `stop_loss`, `target_price`, `metadata`, `scoring_breakdown`, and `guardrail_result` are not accepted; an extra field returns HTTP 422 rather than being silently ignored.
- Reassessment never silently fetches live quotes, and never fills a historical snapshot in with current market data.
- Source-report validation is identical in preview and persist: a missing or invalid `source_report_id` returns HTTP 422; a report that does not exist returns HTTP 404 `source_report_not_found`; a non-single-stock report returns HTTP 400 `unsupported_report_type`; a persisted snapshot too thin to produce a decision signal returns HTTP 400 `unsupported_report_snapshot`. Persist additionally requires the source report to have a valid `created_at`, otherwise it returns HTTP 400 `unsupported_report_snapshot` and writes nothing; preview does not depend on that storage lifecycle field.
- Data quality is normalized to `high`, `medium`, `low`, `poor`, or `unknown`, and the guardrail uses only the normalized level.
- A successful preview returns `preview`, `item=null`, and `created=false`. It writes nothing and enters neither the list, nor latest, nor the timeline.
- A successful persist returns `preview=null`, the backend-authoritative `item`, and `persist_status`. `persist_status=created` means newly created; `existing` means a record with the same fielded identity already exists and was not rewritten; `refreshed` means an existing record was reused and refreshed under the established expired-refresh / dimension-fill semantics. The compatibility field `created` is `true` only in the `created` case. `persist_status` describes this write's disposition only and does not imply that `item.status` is active: a newly created historical signal may still be returned as `expired/invalidated` because it has lapsed or has been superseded by a newer opposing signal.
- Reassess persist and lazy backfill share one historical lifecycle: `created_at` is anchored to the source report's time, and `expires_at` is computed from the report time, the horizon, the market, and the persisted `market_phase_summary`. The phase summary keeps only `phase/session_date/minutes_to_open/minutes_to_close`; a lifetime is never re-derived from the save-day or live quotes.
- Invalidation ordering between opposing signals of the same profile is likewise decided by a historical signal's immutable `created_at`, and an expired refresh's `updated_at` does not change historical precedence. Saving an older report must never retire a newer opposing signal; a historical item still within its lifetime but already superseded by a newer opposing signal is returned as `invalidated`, and the API returns the final database state after invalidation processing.
- A `created` item is written with `source_type=analysis`, the original `source_report_id`, `source_agent=decision_profile_reassess`, `trigger_source=web:decision_profile_reassess`, and the formal `decision_profile`. Its metadata stores `profile_source=user_selected`, `profile_policy_version`, `signal_generation_version`, `scoring_version`, `scoring_breakdown`, `data_quality_level`, and the complete `guardrail_result`.
- An `existing` item keeps its original source fields and metadata unchanged. For example, when ordinary analysis has already generated a `balanced/auto_default` signal with the same identity, confirming a balanced reassess again returns that record: it is not overwritten to `user_selected`, and success is not claimed as a new creation. A terminal-state existing record is never reactivated.
- A `refreshed` item keeps its immutable original creation provenance (`source_type`, `source_report_id`, `source_agent`, `trigger_source`, `created_at`, and so on) and follows the two established sub-semantics of the #1756 repository: an expired refresh updates the decision fields that are allowed to change, the lifetime, and this reassess's audit metadata; an active relaxed dimension-fill only fills in a missing horizon or market phase and keeps the original metadata. The client must treat the backend item as authoritative and must not infer from `refreshed` alone that metadata has been replaced.
- `guardrail_result` is machine audit data recording `raw_action`, `final_action`, `passed`, `violations`, `adjustments`, and `adjusted`; `warnings` is the user-readable summary. Tests and client logic should depend on a warning's stable `code`, with `message` used only for first-version display.
- `MIN_ACTIONABLE_CONFIDENCE = 0.5`. Every `buy/add` additionally requires a horizon, an invalidation or stop loss, a valid price relationship, and data quality that is not `poor/unknown`; an aggressive `buy/add` further requires an explicit invalidation and does not accept a `long` horizon.
- Missing confidence or invalidation, or insufficient data quality, downgrades auditably to `watch` and records `passed=true, adjusted=true`. When price relationships contradict each other, no valid plan can be saved without rewriting the historical snapshot's semantics, so `passed=false` is recorded instead.
- A preview-only `passed=false` is still presented with HTTP 200, and the UI must make `blocked_reason` prominent. When a persist recomputation yields `passed=false`, the response is HTTP 400 `guardrail_blocked` carrying `blocked_reason` and structured `warnings`; nothing is written and `created=true` is not returned.
- Every persist recomputation must satisfy `guardrail_result.passed=true` before entering the write path, and the `item.action` of a `created/refreshed` result equals this run's `guardrail_result.final_action`. `existing` returns the original record with its original metadata and never fabricates an audit for this run.
- Default analysis and lazy backfill still generate `balanced` only. A user may explicitly select and confirm saving balanced, conservative, or aggressive, and conservative/aggressive are never generated automatically.
- Aggressive is not a model sampling-temperature setting, and it does not generate all three profile signals automatically.

## Web presentation

The web entrypoint is `/decision-signals`:

- The default query is `status=active`.
- The top of the page provides a page-level current-stock path, independent of the advanced list filters. Once the user submits a primary stock, picks an autocomplete candidate, or clicks a candidate chip, latest active and the timeline share that one applied stock context; editing the input draft alone triggers neither a latest nor a timeline query.
- Current-stock candidates show recently analyzed stocks first. With no historical candidate, or when loading historical candidates fails, it degrades to popular stocks that are active and rank high on popularity in the stock index. Candidates are a manual click entrypoint only, and no query is submitted automatically on page load; when neither history nor the stock index is available, only a no-candidate degradation message is shown.
- The current-stock context shows the applied code, name, and derivable market, and offers a clear action. Clearing returns latest and the timeline to their guidance state without affecting the advanced list filters or the list's source-detail drawer.
- The advanced list filters support market, stock code, action, market phase, source, source report ID, and status. They are not the same thing as the current-stock context and never contaminate the latest-active query.
- The single-stock signal timeline reuses the existing `GET /api/v1/decision-signals` list API and adds no timeline endpoint. The timeline queries only after a non-empty current stock has been applied; with no current stock it shows the guidance state and fetches no market-only or global timeline.
- The timeline supports only the `30d`, `90d`, and `180d` ranges, defaults to `90d`, and requests at most 100 records at a time. If the response reports `total > items.length`, the web UI shows "Only the latest 100 signals are shown. Narrow the time range." rather than silently presenting an incomplete history.
- The timeline filter keeps its own market, range, and status form plus a query button. When a new current stock is selected and a market can be derived, the timeline market is initialized once at that moment; the user may change the market afterwards, and a query uses the form snapshot taken when the button was pressed.
- The timeline status filter supports only `all` and `active`: `all` sends no `status`, and `active` sends `status=active`. P1 provides no terminal status filter and does no terminal filtering on the frontend.
- The timeline supports a profile filter, reusing the list API's server-side `decision_profile` query; `unknown` is used only to filter and display legacy `NULL` rows. The ordinary advanced list gains no profile filter.
- Signal performance statistics keep the global reviewed-outcome meaning. They are not the count of currently visible signals and do not change with the current stock or the advanced list filters. When the reviewed sample count is 0, the web UI shows a zero-sample empty state rather than a row of `0/-` metrics.
- The web UI reads the formal `decision_profile` field first and falls back to legacy metadata only when the field is missing. A signal whose profile is historically missing or invalid is shown as `unknown` and never mislabelled as `balanced`.
- The market filter supports `us/ca` in the API, the service layer, and the web frontend. Alert (market light) market support is also `us/ca`.
- The detail drawer shows the action, status, score, confidence, horizon, plan quality, market phase, price plan, risks, watch conditions, evidence, data quality, and metadata.
- A reassess preview can be started from the detail drawer or from a page context that already has a source report ID; the entrypoint is disabled when no source report ID is available. The preview itself joins neither the list, nor latest, nor the timeline. Once it passes the guardrail, the user can confirm saving it a second time. Saving re-requests with `persist=true` and, on success, uses only the backend `item` from the response. `created`, `existing`, and `refreshed` produce different feedback: existing is never described as newly created, a terminal-state existing record is never optimistically injected into active latest or the timeline, and only created/refreshed update the relevant views according to the returned status and refresh them. The web UI never assembles a preview into a local signal.
- Guardrail adjustment warnings raised while saving stay visible. If the persist recomputation is blocked by the guardrail, the web UI shows `blocked_reason` and the structured warnings, keeps the preview so the user can understand why, and does not add the failed result to the timeline.
- The home-page analysis form offers no `decision_profile`; the default automatic path still uses `balanced` only.
- The web UI can mark a signal only as `closed`, `invalidated`, or `archived`; it offers no way to restore a terminal status to active.
- A historical report's detail view no longer embeds the `source_type=analysis` signals bound to that report, and opening a report detail no longer triggers a `source_report_id` signal query. To see a report's source signals, go to the `/decision-signals` page and filter precisely by source report ID, or open the `/decision-signals?sourceReportId=<recordId>` deep link. Both that filter and the deep link use the exact `source_type=analysis + source_report_id` query, which preserves the best-effort lazy-backfill entrypoint for older reports.
- The portfolio page queries the latest active signal for each unique holding asynchronously; a single failed query shows a degradation notice only and blocks neither the portfolio snapshot nor the other holdings' signals.

Every user-visible enumeration must use an i18n label; technical IDs, stock codes, API field names, environment keys, and URL examples may stay in English.

## Decision profile identity

Since #1756, `decision_profile` is a formal nullable field on `decision_signals`, while metadata keeps the compatibility fields:

- `decision_profile=balanced`
- `profile_source=auto_default`: the ordinary new-analysis generation path.
- `profile_source=backfill_defaulted`: the historical-report lazy backfill path.
- `profile_policy_version=decision-profile-v1`
- `signal_generation_version=legacy-report-extractor-v1`
- `decision_signal_metadata_version=decision-signal-metadata-v1`

- On a new write, a valid top-level `decision_profile` wins; a top-level explicit `null`, empty value, or invalid value is rejected outright. Only when the top level is absent does a valid `metadata.decision_profile` serve as fallback; when both are absent, or the metadata profile is invalid, `balanced` is written by default.
- A new write also syncs `metadata.decision_profile` to the formal field value so the two sources cannot conflict. Omitted or explicit `null` metadata is treated as absent, an object is shallow-copied, and a non-object is rejected.
- On PATCH, omitted metadata keeps the previous value, an explicit `null` clears it to SQL `NULL`, and an object replaces the whole payload. When the formal profile is not `NULL`, it overrides a conflicting value in metadata; when the formal profile is a legacy `NULL`, the profile key is removed from the request object and the formal field is not promoted.
- An automatic invalidation write follows the same formal-field authority: when the formal profile is not `NULL`, the metadata profile is synced; with a legacy `NULL`, only the invalidation information is appended, the original legacy metadata is kept, and no profile is injected or deleted.
- Legacy / unknown is represented by a database `NULL` only. Ordinary automatic generation and lazy backfill write neither `scoring_version` nor `scoring_breakdown`; only a user-initiated reassess path generates and audits those fields according to the profile policy. This does not mean three profiles are generated automatically, and it does not include #1758's profile-aware outcome calibration.
- Lazy backfill semantics: omitting the profile keeps the old `source_type=analysis + source_report_id` lazy backfill; `decision_profile=balanced` can produce a balanced backfill; `decision_profile=unknown`, `conservative`, and `aggressive` create no row automatically. Backfill and reassess persist share the source-report time, the historical TTL, and the superseded rule, so there is no second historical lifecycle.

## Market-structure metadata

When ordinary single-stock analysis or Agent single-stock analysis carries `market_structure_context`, automatic `DecisionSignal` extraction appends these low-sensitivity fields to metadata:

- `market_structure_version`
- `market_theme_version`
- `stock_market_position_version`
- `market_structure_status`
- `primary_theme`
- `theme_phase`
- `stock_role`
- `market_structure_risk_tags`

These fields exist only to explain the thematic background a signal sits in. They take no part in `action`, `score`, `horizon`, the same-source dedup key, or lifecycle computation. They are also not proof of thematic leadership: when `market_structure_risk_tags` or missing evidence shows that constituents or leader stocks are incomplete, clients and retrospective analysis should treat the thematic evidence as degraded.

The `provider` / `dataset` fields in the snapshot come from market-structure extraction metadata. They are post-run persisted evidence and take no part in LLM provider/model routing, `base URL` resolution, `.env` write-back, or configuration migration; the verifiable scope is `src/schemas/market_structure.py`.

## Alerts, notifications, and portfolio risk

- A real stock-level alert trigger prefers associating the latest active signal for the same instrument, and writes a low-sensitivity `decision_signal_summary` into `alert_triggers.diagnostics`.
- With no active signal, the alert worker creates only a minimal `source_type=alert/action=alert` signal.
- An alert signal's `trace_id=alert-rule-<hash>` is used only for best-effort deduplication of same-source retries, and never overwrites an active signal itself.
- Notifications reference only public summary fields: `action`, `horizon`, `reason`, `watch_conditions`, `risk_summary`, `source_report_id`.
- The `reason` in a notification is shown in full after redaction, so a fixed character count cannot cut it off mid-sentence; `watch_conditions` and `risk_summary` keep their compact summary caps.
- Notifications must never emit a signal's `metadata`, `evidence`, raw diagnostics, webhook URL, token, or cookie.
- `decision_signal_risk` in `GET /api/v1/portfolio/risk` counts only active `sell/reduce/alert` signals among current holdings, and fails open when the query fails.

See `docs/alerts.md` and `docs/notifications.md` for more alert and notification detail.

## Retrospective evaluation and feedback

P5 stores user feedback and retrospective results in sidecar tables rather than extending the main `decision_signals` table:

- `decision_signal_feedback` stores each signal's latest `useful|not_useful` feedback, an optional reason or note, and the source.
- `decision_signal_outcomes` stores retrospective evaluation results idempotently by `(signal_id, horizon, engine_version)`.
- The current `engine_version=decision-signal-v1`.
- Retrospective evaluation supports only the daily-bar-verifiable `1d/3d/5d/10d`. `intraday/swing/long`, non-directional actions, missing prices, and insufficient forward bars write `eval_status=unable` with an explicit `unable_reason`.
- Evaluation freezes statistical dimensions such as action, market, market_phase, source_type, source_agent, plan_quality, data_quality_level, and holding_state, so historical statistics do not depend on a later live join.

## Redaction and the low-sensitivity boundary

Signal writes and status updates use `sanitize_decision_signal_text()` and `sanitize_decision_signal_payload()` from `src/utils/sanitize.py`:

- Text fields, JSON fields, and short display text are redacted before writing.
- Coverage includes sensitive keys, Bearer, Authorization/Cookie headers or assignments, token-like strings, webhook URLs, URL userinfo, and URLs carrying sensitive query or fragment parameters.
- Ordinary evidence URLs are kept so sources stay traceable.
- `trace_id` is a same-source dedup identity field. If it contains a credential that would be redacted, the API rejects the request rather than storing an identity value broken by redaction.
- The web UI's JSON view shows only backend-redacted data and must not reassemble raw diagnostics or configuration values.

The global acceptance criterion for P7 is confirming that the signal pool, notification summaries, and web presentation leak no tokens, cookies, webhook URLs, API keys, email passwords, or other sensitive information.

## Migration and rollback

#1756 performs a non-destructive migration on SQLite.

Migration notes:

- No new `.env`, `.env.example`, or web setting is needed after upgrading.
- An existing SQLite database only runs `ALTER TABLE ADD COLUMN decision_profile` when the column is missing; `decision_signals` is neither dropped nor rebuilt, and no old index is deleted.
- The migration creates the profile-aware indexes idempotently and parses `metadata_json` defensively row by row: only a valid `metadata.decision_profile` is backfilled into the formal field, while invalid JSON, a non-object, or an invalid profile stays `NULL`. The startup log records counts of backfilled, invalid JSON, non-object, invalid profile, and skipped existing profile rows; those counts are diagnostic only and never block startup.
- Old historical reports are not backfilled in bulk. A best-effort lazy backfill happens only on an explicit call to the signal list endpoint, or when the web AI recommendation page triggers the precise `source_type=analysis + source_report_id` query by source report ID and finds no match.
- Existing `decision_signals`, feedback, and outcome data stay compatible.

Rollback notes:

- There is currently no `DECISION_SIGNAL_*` toggle; the way to roll back signal extraction and writing is to revert the relevant code.
- After a rollback, ordinary report persistence, alert triggering, notification sending, and the main portfolio-risk flow still run on their established paths.
- A rollback never deletes historical `decision_signals`, `decision_signal_feedback`, or `decision_signal_outcomes` data automatically; if cleanup is needed, a maintainer should define a separate data-cleanup policy.

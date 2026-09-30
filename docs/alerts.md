# Real-Time Alert Center

This document records the runtime baseline, data contracts, phased implementation scope, and compatibility boundaries of the Issue #1202 alert center.

## Current baseline

Runtime alerting is currently scheduled by the background worker in `src/services/alert_worker.py`, and the underlying rule evaluation reuses the EventMonitor rule model in `src/services/alert_service.py` and `src/agent/events.py`.

- Configuration entrypoints: `AGENT_EVENT_MONITOR_ENABLED`, `AGENT_EVENT_MONITOR_INTERVAL_MINUTES`, `AGENT_EVENT_ALERT_RULES_JSON`.
- Runtime entrypoint: `main.py` registers the `agent_event_monitor` background task in schedule mode. Each round, the background worker reads the persisted active rules and stays compatible with the legacy `AGENT_EVENT_ALERT_RULES_JSON`.
- Notification delivery: a trigger reuses `NotificationService.send(..., route_type="alert")` and keeps honoring the notification gateway's alert routing configuration.
- Web/system configuration validation: `src/services/system_config_service.py` validates `AGENT_EVENT_ALERT_RULES_JSON` both as JSON and against the rule semantics.

The current runtime supports three kinds of rule:

| `alert_type` | Direction field | Threshold field | Current semantics |
| --- | --- | --- | --- |
| `price_cross` | `direction`: `above` / `below` | `price` | The live price crosses a fixed price upward or downward |
| `price_change_percent` | `direction`: `up` / `down` | `change_pct` | The live change reaches the given percentage |
| `volume_spike` | - | `multiplier` | The latest volume exceeds the given multiple of the 20-day average volume |

`sentiment_shift`, `risk_flag`, and `custom` are placeholders for future extension only; the current runtime does not accept them as executable rules.

## Legacy configuration compatibility

`AGENT_EVENT_ALERT_RULES_JSON` remains the legacy runtime rule source. It is never migrated, deleted, overwritten, or rewritten automatically in a user's existing `.env` or web configuration.

- An empty string or an empty array means no legacy rule is configured. Schedule mode still registers the background worker so that persisted active rules created later through the API can be evaluated without a restart.
- Web/system configuration saving runs strict validation: invalid JSON, a missing field, an invalid direction, an invalid threshold, or an unsupported rule type must all return a configuration error.
- Runtime loading may skip a single invalid rule and keep the remaining valid rules working, so one bad entry cannot break the whole schedule process.
- The current worker uses an in-process fingerprint to avoid repeatedly pushing a persistently true condition. That is not the alert center's cooldown model, and it provides no cooldown state across processes or restarts.

## Data contracts

The contracts below exist so that the later P1+ API, worker, web, and storage implementations align. P0 defines the fields and semantic boundaries only; it does not imply that these persisted entities exist yet.

### `alert_rule`

A manageable alert rule.

| Field | Notes |
| --- | --- |
| `id` | Rule ID; a legacy JSON rule has no persisted ID in P0 |
| `name` | A user-readable name; generated from the rule type and target when not supplied |
| `target_scope` | Target scope, for example single symbol, watchlist, portfolio, market |
| `target` | The target instrument or a target reference, for example a stock code, watchlist ID, or portfolio ID |
| `alert_type` | Rule type; P1 initially allows only `price_cross`, `price_change_percent`, and `volume_spike` |
| `parameters` | Rule parameters, for example `direction`, `price`, `change_pct`, `multiplier` |
| `severity` | Alert level, for example info, warning, critical |
| `enabled` | Whether the rule is enabled |
| `cooldown_policy` | The cooldown policy; P0 defines the field only, and P4 implements the execution semantics |
| `notification_policy` | The notification policy; it reuses the `NotificationService` alert route by default |
| `source` | Creation source, for example legacy_env, web, api, import |
| `created_at` / `updated_at` | Creation and update time |

### `alert_trigger`

One real or recordable rule trigger.

| Field | Notes |
| --- | --- |
| `id` | Trigger record ID |
| `rule_id` | The matching rule ID; a legacy env rule may record a temporary reference |
| `target` | The target that actually triggered |
| `observed_value` | The observed value, for example the current price, the change percentage, or the volume multiple |
| `threshold` | The trigger threshold |
| `reason` | A readable trigger reason |
| `data_source` | The data source or provider |
| `data_timestamp` | The data time; when missing it must not be faked as the current time |
| `triggered_at` | The trigger time |
| `status` | Trigger status, for example triggered, skipped, degraded, failed |
| `diagnostics` | Redacted diagnostic information |

### `alert_notification`

One notification attempt for a trigger.

| Field | Notes |
| --- | --- |
| `id` | Notification attempt ID |
| `trigger_id` | The matching trigger record ID |
| `channel` | The notification channel |
| `attempt` | Which attempt this is |
| `success` | Whether it succeeded |
| `error_code` | A structured error code |
| `retryable` | Whether a retry is advisable |
| `latency_ms` | The duration |
| `diagnostics` | Redacted send diagnostics; must contain no token, complete webhook URL, email password, or bot secret |
| `created_at` | The attempt time |

### `alert_cooldown`

Cooldown state at the rule or target level.

| Field | Notes |
| --- | --- |
| `rule_id` | The matching rule ID |
| `target` | The cooldown target |
| `severity` | An optional level dimension |
| `last_triggered_at` | The most recent trigger time |
| `cooldown_until` | The cooldown end time |
| `reason` | The cooldown reason |
| `state` | The current state, for example active, expired |
| `updated_at` | The update time |

## Storage approach evaluation

The repository already has a SQLite storage layer and a repository/service split:

- `src/storage.py` manages the SQLite connection, the SQLAlchemy ORM models, and `DatabaseManager`.
- `src/repositories/` holds the data-access layer, for example `PortfolioRepository`.
- `src/services/` holds the business service layer, for example `PortfolioService` and `PortfolioRiskService`.
- The default database path follows the existing configuration and usually lands at `data/stock_analysis.db`.

When P1/P2 implement alert persistence, reusing those patterns is recommended: define the alert ORM models in the storage layer, wrap CRUD and queries in the repository layer, and handle rule validation, evaluation state, notification results, and cooldown semantics in the service layer. P0 creates no table and changes no existing database.

If a later PR needs a schema change, it must also supply:

- Idempotent initialization: repeated startup or repeated initialization must not damage existing data.
- Backward compatibility: with the alert center unconfigured, daily analysis, ask-stock, notifications, market review, and portfolio features are unaffected.
- Rollback notes: the minimal rollback is at least reverting the PR; if a new table or index was created, say whether data is kept and how to clean it up manually.
- Data migration boundary: `AGENT_EVENT_ALERT_RULES_JSON` must never be migrated, deleted, or overwritten automatically unless the user runs an explicit import.

## P1 Alert API MVP

P1 adds the backend Alert API and schema, locking down the alert center's minimal API contract without wiring in a web page or the background worker.

- New API file: `api/v1/endpoints/alerts.py`.
- New schema file: `api/v1/schemas/alerts.py`.
- API scope:
  - `GET /api/v1/alerts/rules`
  - `POST /api/v1/alerts/rules`
  - `GET /api/v1/alerts/rules/{rule_id}`
  - `PATCH /api/v1/alerts/rules/{rule_id}`
  - `DELETE /api/v1/alerts/rules/{rule_id}`
  - `POST /api/v1/alerts/rules/{rule_id}/enable`
  - `POST /api/v1/alerts/rules/{rule_id}/disable`
  - `POST /api/v1/alerts/rules/{rule_id}/test`
  - `GET /api/v1/alerts/triggers`
  - `GET /api/v1/alerts/notifications`
- The first version still supports only `price_cross`, `price_change_percent`, and `volume_spike`; future types such as `sentiment_shift`, `risk_flag`, and `custom` return a structured unsupported error.
- The `test` endpoint performs a one-off dry-run evaluation only: it sends no notification and writes no real trigger record or notification attempt.
- `cooldown_policy` / `notification_policy` are reserved fields in P1: the API can store and return that opaque configuration, but it does not execute cooldown or custom notification semantics.
- API responses must be redacted and must not echo a token, complete webhook URL, email password, cookie, or bot secret.
- `AGENT_EVENT_ALERT_RULES_JSON` remains the legacy configuration entrypoint; P1 does not migrate, delete, overwrite, or rewrite legacy configuration automatically.

P1 non-goals:

- No web alert-center page, route, or sidebar entry is added.
- The schedule worker does not load persisted active rules, and merging or deduplicating persisted rules against legacy JSON is not implemented.
- Real `alert_trigger` / `alert_notification` writes are not implemented; P1 provides the query endpoints and the table structure only.
- `alert_cooldown` execution semantics are not implemented.
- MACD, KDJ, CCI, RSI, portfolio-risk, and Market Light alert rules are not implemented.

## P2 alert evaluation worker

P2 moves the schedule runtime from building a legacy `EventMonitor` once at startup to a background worker that evaluates persisted active rules and legacy JSON rules every round.

- `AGENT_EVENT_MONITOR_ENABLED` remains the master switch, and the background task name stays `agent_event_monitor`.
- Each round, the worker reads the `alert_rules` with `enabled=true` from the database and re-parses `AGENT_EVENT_ALERT_RULES_JSON`; a new API rule does not require restarting the schedule process.
- Database rules and legacy rules are deduplicated by `target_scope + target + alert_type + canonical(parameters)`, with the database rule winning a conflict; legacy configuration is never migrated, deleted, or rewritten automatically.
- Each rule is evaluated independently, and a single failure writes only a `failed` evaluation status without affecting the other rules that round or the main analysis flow.
- In P2, `alert_triggers` records a minimal evaluation history: `triggered`, `skipped`, `degraded`, and `failed`. A normal `not_triggered` writes no history, so polling cannot flood the table.
- Missing live quotes, a missing field, or a non-evaluable situation records `skipped`; unavailable or structurally incomplete daily data records `degraded`; the diagnostics are redacted.
- A trigger still calls `NotificationService.send(..., route_type="alert")`; the in-process fingerprint only avoids repeatedly pushing a persistently true condition and does not execute `cooldown_policy`.

P2 non-goals:

- No web alert-center page, route, or sidebar entry is added.
- `alert_notifications` is not written, and per-channel notification attempts are not recorded.
- `alert_cooldown`, `cooldown_policy`, and `notification_policy` execution semantics are not implemented.
- MACD, KDJ, CCI, RSI, portfolio-risk, and Market Light alert rules are not implemented.

## P3 web alert center MVP

P3 adds the `/alerts` alert-center entrypoint to the WebUI so a user can manage the three current runtime rule types without editing legacy JSON directly.

- A new Alerts entry appears in the sidebar, and the page supports a rule list, pagination, an enabled/disabled filter, and a rule-type filter.
- The rule creation form supports only the `single_symbol` target scope and the three currently executable rule types:
  - `price_cross`: `direction` is `above` / `below`, plus a `price`.
  - `price_change_percent`: `direction` is `up` / `down`, plus a `change_pct`.
  - `volume_spike`: a `multiplier`.
- Rule operations support enable, disable, delete, and a one-off dry-run test.
- The dry-run test shows only the fields `AlertRuleTestResponse` declares: rule ID, status, whether it triggered, the observed value, and a message. Extended diagnostic fields such as `threshold`, `data_source`, and `data_timestamp` need the backend schema to expose them explicitly before they can be shown.
- The trigger history shows the `triggered`, `skipped`, `degraded`, and `failed` records the P2 worker has written; a normal `not_triggered` is still not written to history.
- The notification-attempt area queries only the existing `GET /api/v1/alerts/notifications`. Because the P2 runtime writes no per-channel notification attempt, it usually shows the “暂无通知尝试记录” empty state today, rather than inferring a delivery result from the trigger status.
- The web page exposes no `AGENT_EVENT_ALERT_RULES_JSON` editing entrypoint, and never migrates, deletes, or rewrites legacy configuration automatically.

P3 non-goals:

- No backend API, schema, storage, or worker behavior is added or modified.
- Rule editing, advanced target/source filtering, watchlist/portfolio targets, technical-indicator rules, and Market Light linkage are not implemented.
- `cooldown_policy` / `notification_policy` are not executed, and `alert_notifications` is not written.

## P4 notification results and persisted cooldown

P4 gives a real alert trigger a debuggable notification result, and gives persisted rules created through the Alert API a business cooldown state that survives a restart.

- A persisted rule's `triggered` history deduplicates the same data point by `rule_id + target + data_source + data_timestamp`: one trigger event keeps only the earliest `alert_triggers` row, and a repeated polling hit reuses the existing trigger record. When `data_timestamp` is missing, no deduplication is applied, so data points that cannot be proven to share a source are not merged by mistake. Even when the result is later suppressed by cooldown or notification noise suppression, the matching notification attempt or synthetic suppression state is still recorded through `alert_notifications`.
- `alert_notifications` records real per-channel notification attempts, including `channel`, `success`, `error_code`, `retryable`, `latency_ms`, and redacted `diagnostics`.
- Non-channel send states are recorded through synthetic channels:
  - `__cooldown__`: suppressed by the alert business cooldown, `error_code="cooldown_active"`.
  - `__cooldown_read_failed__`: suppressed temporarily by the worker's in-process fallback after reading the persisted cooldown state failed, `error_code="cooldown_read_failed"`.
  - `__noise_suppressed__`: suppressed by notification-infrastructure noise suppression, `error_code="noise_suppressed"`.
  - `__no_channel__`: the alert route matched no usable notification channel.
  - `__dispatch__`: a notification dispatch-level fallback or exception.
- Cooldown layering:
  - On the normal path, a persisted rule uses `alert_cooldowns` as its alert business cooldown, no longer decided by the worker's in-process fingerprint. Only when reading the persisted cooldown state fails does an in-process fingerprint step in temporarily, which prevents one rule from pushing every round while the database is unhealthy.
  - A legacy `AGENT_EVENT_ALERT_RULES_JSON` rule keeps using the worker's in-process fingerprint and never writes `alert_cooldowns`.
  - `notification_noise.py` remains the global safety net at the notification-infrastructure layer. It is not an alert business cooldown, and something it suppresses neither writes nor extends `alert_cooldowns`.
- A database rule's `cooldown_policy.cooldown_seconds` is normalized to a non-negative integer; when missing, the default 24-hour business cooldown applies, and `0` disables the database business cooldown.
- `GET /api/v1/alerts/rules` returns a read-only `last_triggered_at` / `cooldown_until` / `cooldown_active` summary. `cooldown_active` is computed by the backend under the same cooldown-time semantics, so the web client never parses a naive ISO string locally to infer the state.
- The web alert center displays cooldown state and notification results read-only, and offers no cooldown-policy editing form.

P4 non-goals:

- No technical-indicator, holdings, watchlist, portfolio, or Market Light alert rules are added.
- Target-level cross-rule merged cooldown is not implemented; target-level merging is left to the holdings/market linkage stage.
- The notification channel gateway is not rewritten; `NotificationService.send()` keeps its compatible boolean return, and structured results are provided through a new compatible interface.
- The legacy `AGENT_EVENT_ALERT_RULES_JSON` is not migrated, deleted, or rewritten automatically.

## P5 technical-indicator rules

P5 adds daily technical-indicator rules to the existing Alert API, web alert center, and the `src/services/alert_worker.py` evaluation path. Rules are still written to `alert_rules`, and triggering, degradation, failure, notification results, and persisted cooldown keep reusing the P2-P4 `alert_triggers`, `alert_notifications`, and `alert_cooldowns` semantics.

The `alert_type` values and `parameters` P5 supports:

| alert_type | parameters | Trigger semantics |
| --- | --- | --- |
| `ma_price_cross` | `direction=above|below`, `window` defaults to `20`, an integer in `[2,250]` | The close crosses MA(window) upward/downward on the edge |
| `rsi_threshold` | `direction=above|below`, `period` defaults to `12`, an integer in `[2,250]`, `threshold` is required and in `0..100` | RSI crosses the threshold upward/downward on the edge |
| `macd_cross` | `direction=bullish_cross|bearish_cross`, `fast_period=12`, `slow_period=26`, `signal_period=9`, all in `[2,250]` with `fast_period < slow_period` | DIF/DEA golden/death cross on the edge |
| `kdj_cross` | `direction=bullish_cross|bearish_cross`, `period=9`, `k_period=3`, `d_period=3`, all in `[2,250]` | K/D golden/death cross on the edge |
| `cci_threshold` | `direction=above|below`, `period` defaults to `14`, an integer in `[2,250]`, `threshold` is required and finite | CCI crosses the threshold upward/downward on the edge |

Evaluation rules:

- The first version uses the daily close uniformly and does no minute bars.
- An edge trigger compares only the last two closed daily bars. When the current level already satisfies the threshold without an edge, `not_triggered` is still returned, so a rule created today does not report historical state as a new trigger.
- An edge trigger includes the case where the previous bar exactly equals the threshold or the zero line: `above` / `bullish_cross` uses `prev <= threshold < current`, and `below` / `bearish_cross` uses `prev >= threshold > current`.
- Partial-bar handling uses a server local time-zone heuristic only: when the current local time is before 16:00, a last row whose date equals the local today, or whose date cannot be determined, is discarded conservatively. It does not distinguish A-share, Hong Kong, and US market time zones or trading calendars. The Issue #1386 P0 market-phase baseline is not wired into technical-indicator rules yet, and precise alert partial-bar determination is left to a later stage.
- `src/services/alert_indicators.py` normalizes OHLCV itself and computes MA, RSI, MACD, KDJ, and CCI, without depending on the fetcher's precomputed MA5/MA10/MA20.
- RSI uses Wilder's EMA / SMMA: `avg_gain = gain.ewm(alpha=1/period, adjust=False).mean()`, and `avg_loss` likewise, rather than a rolling SMA.
- MACD uses `EMA(fast_period) - EMA(slow_period)` for DIF, with DEA the `EMA(signal_period)` of DIF; a golden/death cross compares DIF-DEA crossing 0 on the edge.
- KDJ computes RSV from the highest and lowest prices of the last `period` days, then derives K/D from EMAs with `alpha=1/k_period` and `alpha=1/d_period`; a golden/death cross compares K-D crossing 0 on the edge.
- CCI uses the typical price `(high + low + close) / 3` and computes `(TP - MA(TP)) / (0.015 * mean_deviation)` from the `period`-day mean and mean absolute deviation.
- `compute_required_bars(alert_type, params)` defines the minimum number of valid closed bars: MA=`window+1`, RSI=`period+1`, MACD=`slow_period+signal_period+1`, KDJ=`period+k_period+d_period+1`, CCI=`period+1`.
- The fetch window is `requested_days = min(max(required_bars * 3, required_bars + 30), 365)`. The API rejects a period combination with `required_bars > 365`, so a rule can never be created with a permanently insufficient sample. Within one worker round, daily data is cached by `(stock_code, requested_days)` and released when the round ends.
- Missing data, a missing column, or fewer valid samples than `required_bars` writes `degraded`; a data-source exception follows the `volume_spike` semantics and returns `evaluation_error` / `failed` with no notification sent.

Compatibility boundary:

- `AGENT_EVENT_ALERT_RULES_JSON` is still the legacy JSON path and supports only the three rule types `price_cross`, `price_change_percent`, and `volume_spike`; P5 technical indicators are created only through the Alert API or the web UI.
- The legacy `AlertType` and `_RUNTIME_SUPPORTED_ALERT_TYPES` in `src/agent/events.py` are not extended.
- A P5 create/update parameter error follows the existing Alert API error contract: HTTP 400 + `validation_error`; an unsupported type returns HTTP 400 + `unsupported_alert_type`.
- The web alert center only extends the existing creation form, list display, type filter, and dry-run test; no rule editor is added. A dry-run test writes no trigger history, and the API response keeps the three states `triggered` / `not_triggered` / `evaluation_error`, with the `degraded` status the worker writes visible through the trigger history.
- After reverting the P5 PR, technical-indicator rule records already in the database are kept. Older code hitting an unsupported `alert_type` while loading rules in the worker skips it, which does not stop the three legacy rule types from running. To clean them up, a maintainer must confirm and delete the relevant `alert_rules` rows by hand.

P5 non-goals:

- MACD histogram expansion/contraction is not supported.
- KDJ overbought/oversold zone rules are not supported.
- MA-to-MA dual moving-average crosses are not supported.
- Minute bars, precise market-calendar determination, and precise multi-market time-zone partial bars are not supported.
- Legacy `AGENT_EVENT_ALERT_RULES_JSON` technical-indicator rules are not supported.
- No DSL, rule engine, new database table, or technical-indicator rule engine inside the analysis report pipeline is introduced.

## P6 holdings and watchlist linkage

P6 adds the `watchlist`, `portfolio_holdings`, and `portfolio_account` target scopes to the existing Alert API, web alert center, and `src/services/alert_worker.py` evaluation path. Rules are still written to `alert_rules`, and triggering, degradation, failure, notification results, and persisted cooldown keep reusing the P2-P4 `alert_triggers`, `alert_notifications`, and `alert_cooldowns` semantics, with no new table or migration.

### The P6 scope/type matrix

| `target_scope` | `target` | Allowed `alert_type` | Evaluation |
| --- | --- | --- | --- |
| `single_symbol` | A stock code | The three P1 price/volume rules plus P5 technical indicators | One rule, one instrument |
| `watchlist` | `default` | The three P1 price/volume rules plus P5 technical indicators | Refreshes and reads the current `STOCK_LIST` each round, expanding by stock code |
| `portfolio_holdings` | `all` or an active account ID | The three P1 price/volume rules plus P5 technical indicators | Expands symbols from the non-zero holdings in the portfolio snapshot, deduplicated by symbol |
| `portfolio_account` | `all` or an active account ID | `portfolio_stop_loss`, `portfolio_concentration`, `portfolio_drawdown`, `portfolio_price_stale` | Account-level risk evaluation, not expanded to single instruments |

When creating or updating a rule, `watchlist` / `portfolio_holdings` do not validate the parent `target` as a stock code; `portfolio_account` forbids price, volume, and technical-indicator types; and with `target=<id>`, `portfolio_holdings` and `portfolio_account` validate that the account exists and is active, returning HTTP 400 + `validation_error` when it does not. The legacy `AGENT_EVENT_ALERT_RULES_JSON` supports neither watchlist, portfolio, nor technical-indicator extensions, and keeps supporting only `price_cross`, `price_change_percent`, and `volume_spike` on `single_symbol`.

### Target Identity Contract

P6 separates the displayable target from the persistable target:

| Case | `effective_target` | `display_target` |
| --- | --- | --- |
| `single_symbol` | `<symbol>` | `<symbol>` |
| A `watchlist` expanded sub-target | `<symbol>` | `自选股 - <symbol>` |
| A `portfolio_holdings` expanded sub-target | `<symbol>` | `持仓 - <symbol>` |
| `portfolio_account target=all` | `account:all` | `全部账户` |
| `portfolio_account target=<id>` | `account:<id>` | `账户 <id>` |

- `alert_triggers.target`, `alert_cooldowns.target`, and the P4 `rule_id + target + data_source + data_timestamp` deduplication all use `effective_target`.
- `RuntimeAlertRule.key` uses `{parent_key}|{effective_target}` for an expanded sub-target, so the in-process fallback used when a database cooldown read fails cannot let different sub-targets of one parent rule suppress each other.
- `display_target` is never written to `alert_triggers.target`; it is used only in the notification title, in the dry-run `target_results`, and in the web UI.
- P6 does not merge notifications for the same instrument across rules: a stock matched by both a watchlist sub-rule and a standalone `single_symbol` rule is recorded and notified once per rule.

### Dry-run aggregation

- For a batch rule, `POST /api/v1/alerts/rules/{rule_id}/test` returns the aggregate fields `evaluated_count`, `triggered_count`, `degraded_count`, `skipped_count`, and `target_results`.
- The expanded-target soft cap is 100. In a dry run, targets beyond the soft cap are recorded as a `degraded` aggregate result and logged. At runtime the worker evaluates only the first 100 expanded targets and logs a warning, and it writes no `alert_triggers` history for the overflow itself.
- A dry run evaluates with bounded concurrency, a 10-second per-target timeout, and a 30-second total evaluation timeout; unfinished targets are recorded as `skipped`.
- If any target triggers, the top-level `status=triggered`. With no trigger but at least one successful evaluation, skip, or degradation, the top-level `status=not_triggered`. Only when expansion is impossible or everything fails does it return `evaluation_error`.
- An empty watchlist or empty holdings: a dry run returns `not_triggered` and gives `record_status=skipped` in `target_results`; the worker writes a `skipped` history entry.
- `degraded_count` counts the entries with `record_status=degraded` across all expanded evaluation results. `target_results` shows the first 20 only, ordered with triggered first, then degraded/failed, then by target.

### Portfolio risk rules

| `alert_type` | Parameters | Observed value | Trigger semantics |
| --- | --- | --- | --- |
| `portfolio_stop_loss` | `mode=near|breach`, defaulting to `near` | The largest `loss_pct` among affected instruments | `near` uses `stop_loss.near_alert`, and `breach` counts only the items with `is_triggered=true`; at most one trigger per account per round |
| `portfolio_concentration` | - | `concentration.top_weight_pct` | `top_weight_pct >= portfolio_risk_concentration_alert_pct` |
| `portfolio_drawdown` | - | `drawdown.max_drawdown_pct` | Reuses `drawdown.alert` from `PortfolioRiskService`; `current_drawdown_pct` is written to diagnostics |
| `portfolio_price_stale` | - | The number of holdings with a stale or missing price | Any position with `price_stale=true` or `price_available=false` |

Portfolio diagnostics must contain `account_id` (or `all`), `currency`, `as_of`, `price_stale`, `fx_stale`, `data_available`, and `top_affected_symbols`. `portfolio_stop_loss`, `portfolio_concentration`, and `portfolio_drawdown` reuse `PortfolioRiskService.get_risk_report()`; `portfolio_price_stale` reuses the position price metadata from `PortfolioService.get_portfolio_snapshot()`.

### The web UI and the cooldown summary

- The web creation form gains a target-scope selector. `watchlist` / `portfolio_holdings` show only the price/volume/P5 technical-indicator types, and `portfolio_account` shows only the four portfolio risk types.
- When loading the account list fails for `portfolio_holdings` / `portfolio_account`, the form keeps the `all` option and shows the error.
- `cooldown_active` in the rule list is accurate for `single_symbol` and `portfolio_account`. For `watchlist` / `portfolio_holdings` it is a parent-rule summary that does not represent each sub-target's cooldown state; a sub-target's cooldown comes from the trigger history and `effective_target`.
- The dry-run UI shows the aggregate counts and at most 20 `target_results` rows.

P6 non-goals:

- P7 Market Light is out of scope.
- Pre-earnings and pre-ex-dividend reminders are out of scope; those rules need a stable date contract and a separate follow-up.
- Sector-level concentration alerts are out of scope; P6 concentration uses the symbol-level `top_weight_pct`.
- Cross-rule notification merging for the same instrument, minute bars, precise multi-market time-zone determination, and legacy JSON extensions are all out of scope.

## Phase awareness and public-summary linkage (Refs #1386 P6)

This section describes the #1386 P6 alert visibility linkage, which is distinct from the "P6 holdings and watchlist linkage" above. This linkage adds no alert table, performs no migration, and triggers no lightweight LLM analysis automatically; it only writes the phase/pack summary that was already public at trigger time into the existing trigger history.

- `AlertTriggerItem` keeps the `diagnostics` string and gains the derived fields `market_phase_summary`, `analysis_context_pack_overview`, and `analysis_visibility_source`.
- A real `status=triggered` worker record merges the sibling key `analysis_visibility` into the JSON diagnostics, containing `market_phase_summary`, `analysis_context_pack_overview`, and `source`. Old plain-text diagnostics keep their original text, the API derived fields return `null`, and the source returns `legacy_text`.
- `analysis_visibility_source` takes the values `alert_trigger_market_context`, `analysis_history_snapshot`, `evaluator_snapshot`, `legacy_text`, or `null`.
- A symbol target builds the trigger-time phase with `get_market_for_stock(normalize_stock_code(effective_target))`. A `target_scope=market` uses `normalize_market_region(target)` directly and never infers `cn|hk|us` as a stock code. When an account-level target cannot resolve to one market, the summary is allowed to fall back to `unknown`.
- `analysis_context_pack_overview` comes only from an overview the evaluator already carries, or from a historical snapshot within the last 30 days. The recent-history query reuses the history service's code-variant candidates and runs best-effort with a short in-batch cache; a missing or unparsable result returns `null` and no pack is fabricated.
- Alert notifications emit the public summary only: the phase label, trigger source, partial-bar warning, data-quality level, and the first two limitations. A notification must not emit the raw context pack, the prompt, news body text, the complete diagnostics JSON, a webhook URL, a token, or sensitive holdings detail.
- The web alert history shows a phase badge, the data-quality level, and an empty state for limitations; an older trigger record with no public summary does not affect reading the list.
- #1390 P6 reuses `DecisionSignal` further: a real stock-level trigger prefers associating the latest active signal for the same instrument and writes a low-sensitivity `decision_signal_summary` into diagnostics; with no active signal it creates only a minimal `source_type=alert/action=alert` signal. `trace_id=alert-rule-<hash>` is used only for best-effort idempotent deduplication of same-source retries and never overwrites an active signal. A newly created alert signal writes no `market_phase`, so one rule cannot create duplicates across phases. A `market` or `portfolio_account` trigger, an overflow, or a trigger that cannot be resolved to a specific stock creates no single-stock signal.

For the DecisionSignal fields, redaction, and the migration and rollback boundary, see [the DecisionSignal topic](decision-signals.md).

The #1386 P7 user boundary: alert linkage only explains the phase and data-quality summary that was already public at trigger time. It does not start a lightweight intraday LLM analysis automatically, and it adds no alert table, rule type, environment variable, or migration. For a phase-aware analysis, still go through the analysis API or the web manual analysis entrypoint; an alert notification keeps only the phase label, trigger source, partial-bar warning, data-quality level, and the first two limitations.

Rolling back this linkage only requires reverting the worker/API/web changes; an existing `diagnostics.analysis_visibility` survives as ordinary JSON diagnostics, and older code does not read that sibling key.

## P7 structured market-light alerts

P7 adds `target_scope=market` to the existing Alert API, web alert center, and `src/services/alert_worker.py`. It consumes the structured `MarketLightSnapshot`, parses no Markdown, does not extend the legacy `AGENT_EVENT_ALERT_RULES_JSON`, and adds no table. Market review history still writes one `analysis_history(code=MARKET, report_type=market_review)` row; a multi-market review stores the snapshot map of the markets actually reviewed, keyed by region, in `context_snapshot.market_light_snapshots`.

### The P7 scope/type matrix

| `target_scope` | `target` | Allowed `alert_type` | Parameters | Trigger semantics |
| --- | --- | --- | --- | --- |
| `market` | `cn` / `hk` / `us` | `market_light_status` | `statuses=["red","yellow"]`, allowing only `red/yellow`, defaulting to `["red","yellow"]` | Triggers when the current `MarketLightSnapshot.status` is in the list |
| `market` | `cn` / `hk` / `us` | `market_light_score_drop` | `min_drop > 0` | `prev.score - current.score >= min_drop`, with `prev.trade_date < current.trade_date` |

Scope/type validation is a two-way constraint: `target_scope=market` can use only the two Market Light rules, and a `market_light_*` rule can use only `target_scope=market`. The `target` is `strip().lower()`-ed and restricted strictly to `cn|hk|us|jp|kr`; an invalid target returns HTTP 400 + `validation_error`.

### The `MarketLightSnapshot` contract

The structured snapshot fields are `region`, `trade_date`, `status`, `score`, `label`, `temperature_label`, `reasons`, `guidance`, `dimensions`, and `data_quality`. In the first version `trade_date` is always `MarketOverview.date`; P7 does not parse a provider quote as-of.

`dimensions` uses the canonical scorer as its single source, so `build_market_light_snapshot()`, the market-review injection block, and the alert service do not each reimplement scoring. `_build_market_temperature()` is only a thin wrapper; the market-light `status` thresholds stay `60/40`, and the temperature-label thresholds stay `70/55/40`.

| dimension | `available=true` condition | fallback score |
| --- | --- | --- |
| `breadth` | `has_market_stats && (up_count + down_count) > 0` | `50` |
| `index` | `indices` is non-empty with at least one `change_pct != None` | `50` |
| `limit` | `has_market_stats && (limit_up_count + limit_down_count) > 0` | `50` |

`data_quality=unavailable` means `index.available=false`, and both market rules return `skipped` and send no notification. `partial` means at least one dimension fell back, and `ok` means all three are available. `market_light_status` can trigger under `ok/partial`; a `partial` trigger must carry `missing_dimensions` in its diagnostics. `market_light_score_drop` compares the canonical aggregate score directly; a `partial` on either side still allows the comparison, but the diagnostics must carry `partial_comparison=true` and `missing_dimensions`.

### Baseline, trading day, and deduplication

- Market review persistence must build the `MarketLightSnapshot` from the same `MarketOverview` used to generate the report; fetching quotes a second time during persistence is forbidden.
- `load_previous_snapshot(region, before_trade_date)` scans `analysis_history(code=MARKET, report_type=market_review)`, skips legacy rows that lack `context_snapshot.market_light_snapshots[region]`, first picks the largest `snapshot.trade_date` below `before_trade_date`, then takes the newest valid snapshot within that same `trade_date` by `created_at DESC, id DESC`. A backfill for an older trading day inserted later cannot overwrite the correct baseline.
- If the target `trade_date` has only a corrupt snapshot, `market_light_score_drop` returns `degraded` rather than silently falling back to an even older trading day for a best-effort comparison.
- The first version of `market_light_score_drop` compares across trading days only. With no previous-trading-day baseline, or with a same-day baseline, it returns `skipped`; a query or parse exception returns `degraded`.
- For `target_scope=market` the worker applies a per-region trading-day gate and honors `TRADING_DAY_CHECK_ENABLED` / `config.trading_day_check_enabled`. With the check disabled, evaluation proceeds; with the check enabled on a non-trading day for the region, it returns `skipped` and does not fetch the current snapshot.
- The trigger history writes `target=<region>`, `observed_value=<score>`, `data_source=market_light`, and `data_timestamp=<trade_date 00:00:00>`, reusing the P4 `rule_id + target + data_source + data_timestamp` deduplication.

### The web UI and the rollback boundary

- The web alert center gains the `market` scope, a region selector, parameter controls for the two market rules, a type filter, region display, and parameter display; the API snake_case mapping uses `statuses` and `min_drop`.
- The legacy `AGENT_EVENT_ALERT_RULES_JSON` does not support market rules; P7 does not update `.env.example`, because no configuration option was added.
- P7 does not add index-drop, sector-anomaly, or limit-structure-deterioration rules, minute bars, precise multi-market time-zone quote as-of parsing, or a DSL/rule engine.

## P8 user configuration and deployment boundaries

P8 adds no rule type, API, table structure, or worker behavior; it organizes the capabilities already merged in P0-P7 into configuration notes for users and deployers. The alert worker registers only in schedule mode, the core switch is still `AGENT_EVENT_MONITOR_ENABLED`, and the polling interval is still `AGENT_EVENT_MONITOR_INTERVAL_MINUTES`. Notification channels keep using the alert route; see `NOTIFICATION_ALERT_CHANNELS` and `route_type=alert` in [the notification configuration](notifications.md).

### Local configuration

When running `python main.py --schedule`, `python main.py --serve --schedule`, or an equivalent built-in schedule mode locally, setting `AGENT_EVENT_MONITOR_ENABLED=true` starts the background alert worker, and `AGENT_EVENT_MONITOR_INTERVAL_MINUTES` controls the polling interval.

There are two rule sources:

- Persisted rules from the Alert API or the web alert center: the recommended entrypoint, supporting `single_symbol`, `watchlist`, `portfolio_holdings`, `portfolio_account`, and `market`, and covering live price, change percentage, volume, daily technical indicators, portfolio risk, and market-light rules.
- The legacy `AGENT_EVENT_ALERT_RULES_JSON`: compatible only with the three basic `single_symbol` rules `price_cross`, `price_change_percent`, and `volume_spike`. It does not support P5 technical indicators, P6 watchlist/portfolio, or P7 market light. The system never migrates, deletes, or rewrites legacy JSON automatically.

### Docker

The repository's `docker/Dockerfile` defaults to `python main.py --schedule`, so setting `AGENT_EVENT_MONITOR_ENABLED=true` inside the container is enough to enable the alert worker in schedule mode. Web/API persisted rules depend on the application database, so a Docker deployment must keep the `data/` database volume; otherwise a container rebuild loses the rules, trigger history, notification attempts, and cooldown state. Legacy JSON is still injected through an environment variable and is not a Docker-specific configuration system.

### GitHub Actions

The bundled `.github/workflows/00-daily-analysis.yml` is a one-shot analysis workflow. It calls `python main.py`, `python main.py --market-review`, or `python main.py --no-market-review`; it does not run the `--schedule` background alert worker and does not map the `AGENT_EVENT_*` variables. Simply adding `AGENT_EVENT_MONITOR_ENABLED` or `AGENT_EVENT_ALERT_RULES_JSON` to repository secrets or variables will not make the default Actions run start polling for alerts.

Alert polling inside GitHub Actions needs a separate later PR to settle the schedule startup method, the env mapping, the rule source, and the persistent-database strategy; P8 changes no existing workflow.

### Web and desktop

The web alert center at `/alerts` is the main entrypoint for persisted rules: it can create, enable, disable, and delete rules, run a one-off dry-run test, and show the trigger history, notification attempts, and read-only cooldown state. The list cooldown state for a batch rule is a parent-rule summary; whether a sub-target is in cooldown comes from the `target` / `effective_target` in the trigger history.

The desktop app adds no native alert management interface; desktop users reuse the `/alerts` page of the built-in or external WebUI. A desktop rollback needs no extra state cleanup.

### Status, notifications, and rollback

The worker writes `triggered`, `skipped`, `degraded`, and `failed` to `alert_triggers` as evaluation history; a normal non-trigger writes no history. `skipped` means the rule had no evaluable condition that round — for example a non-trading day for a market, or a missing previous-trading-day baseline. `degraded` means the data source, the portfolio snapshot, a historical snapshot, or parsing hit an exception, so the result cannot be used to trigger a notification.

A real trigger writes to `alert_notifications` and `alert_cooldowns`; a persisted rule deduplicates one data point best-effort by `rule_id + target + data_source + data_timestamp`. A legacy JSON rule keeps using the in-process fingerprint only and writes no persisted cooldown.

Rolling back P8 only requires reverting the documentation, configuration notes, and web copy changes; there is no database migration or user-data cleanup. When rolling back an earlier phase, persisted rules already created are not deleted automatically — follow the phase rollback notes below.

## Phase boundaries

- P0: this document, the contracts, the storage evaluation, and the compatibility tests.
- P1: the Alert API MVP, covering only the three existing runtime rule types in its first version.
- P2: unifying the alert evaluation worker with the runtime so persisted active rules and legacy JSON coexist.
- P3: the web alert center MVP.
- P4: trigger history, notification results, and cooldown state.
- P5: technical-indicator rules.
- P6: holdings and watchlist linkage.
- P7: market light and market linkage.
- P8: documentation, migration, and closeout.

## P0 non-goals

- P0 adds no `api/v1/schemas/alerts.py` or Alert API.
- P0 adds no web alert-center page, route, or sidebar entry.
- P0 adds no database table, repository, or migration.
- P0 does not implement writing trigger history, notification results, or cooldown state.
- P0 does not migrate, delete, or overwrite `AGENT_EVENT_ALERT_RULES_JSON` automatically.
- P0 does not implement MACD, KDJ, CCI, RSI, portfolio-risk, or Market Light alert rules.
- P0 does not rewrite `NotificationService` or the notification routing framework.

## Rollback

- P0 is a documentation and test closeout. To roll back P0 alone, revert the matching PR; there is no database, configuration, or user-data migration to handle.
- P1 adds Alert API code and the `alert_rules` / `alert_triggers` / `alert_notifications` SQLite tables. The minimal rollback is reverting the P1 PR, which removes the API, service, repository, schema, and ORM definitions — but the SQLite tables and data already created by `Base.metadata.create_all()` are not deleted automatically. To clean them up, a maintainer must delete the relevant tables by hand after confirming the historical data is no longer needed.
- P3 is a web and documentation change. The minimal rollback is reverting the P3 PR; it deletes no existing rule, trigger history, or legacy JSON configuration.
- P4 adds the `alert_cooldowns` SQLite table and starts writing `alert_notifications`. The minimal rollback is reverting the P4 PR; the `alert_cooldowns`, `alert_triggers`, and `alert_notifications` data already created is not deleted automatically. To clean it up, a maintainer must confirm and delete the matching tables or rows by hand.
- P5 adds technical-indicator rules supported by the Alert API and the web UI. The minimal rollback is reverting the P5 PR; the P5 `alert_rules` rows already created are not deleted automatically, and older code will skip unsupported `alert_type` values while the worker loads rules, which does not affect the three legacy rule types. To clean them up, a maintainer must confirm and delete the relevant rule rows by hand.
- P6 adds watchlist, portfolio-holdings, and portfolio-account rules supported by the Alert API and the web UI. The minimal rollback is reverting the P6 PR; there is no new table or migration, and the P6 `alert_rules` already created are kept. Disabling or deleting the non-`single_symbol` P6 rules before rolling back is recommended; otherwise an older worker may evaluate the parent `target` of a `watchlist` / `portfolio_holdings` rule as a stock code and generate failed/skipped noise, while the portfolio-specific `alert_type` values are skipped while the worker loads rules.
- P7 adds the `market` rules supported by the Alert API and the web UI, plus the market-review `market_light_snapshots` historical snapshot. The minimal rollback is reverting the P7 PR; there is no new table or migration, and the P7 `alert_rules` already created are kept. Disabling or deleting the `target_scope=market` rules before rolling back is recommended; an older worker will skip the unsupported `market_light_*` types or generate configuration noise because it does not recognize the scope/type.

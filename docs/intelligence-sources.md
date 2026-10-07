# News / intelligence sources MVP

The first version of Issue #1707 focuses on compliant news-source collection, local persistence, and queryable evidence. It does not mix RSS/Atom into the on-demand search semantics, and it does not add a separate sentiment page by default.

## Capabilities

- Supports configuring RSS / Atom HTTP(S) news sources.
- Supports querying the built-in RSS/Atom templates and creating testable, toggleable sources from them; all built-in defaults can also be created in one action.
- Persists source configuration, enabled state, scope, and the most recent fetch status.
- Fetched entries land in `intelligence_items`, storing the title, summary, URL, source, publication time, fetch time, market, and scope.
- De-duplicates by URL; entries with no URL fall back to the key `no-url:intel:<hash>`.
- Supports the `symbol` / `market` / `sector` scopes and the `us` / `ca` / `global` market markers.
- Batch fetching is fail-open: one failing source never blocks the others or the main analysis path.
- Supports retention cleanup, which keeps the intelligence pool from growing without bound.

## Security boundary

A custom URL goes through basic validation:

- Only absolute `http` / `https` URLs are allowed;
- A URL carrying a username or password is rejected;
- `localhost`, `.local`, loopback, private, link-local, reserved, shared, and multicast addresses are rejected;
- Environment proxies (such as `HTTP_PROXY`, `HTTPS_PROXY`, and `ALL_PROXY`) are disabled explicitly during resolution and fetching, which prevents bypassing the validation boundary through a proxy;
- At connection time the target host's DNS resolution is validated again, which prevents post-validation drift to a restricted address;
- The final URL after redirects is validated again;
- Error messages redact common `token` / `key` / `secret` query parameters.

Explicit non-goals: no anti-scraping countermeasures, no simulated login, no cookie harvesting, and no unauthorized direct scraping of portals.

## Configuration

```env
NEWS_INTEL_RETENTION_DAYS=30
NEWS_INTEL_FETCH_TIMEOUT_SEC=8
NEWS_INTEL_MAX_ITEMS_PER_SOURCE=50
NEWS_INTEL_AUTO_FETCH_ENABLED=false
```

`NEWS_INTEL_AUTO_FETCH_ENABLED` is off by default. When set to `true`, single-stock analysis, Agent analysis, and market review each perform one fail-open automatic refresh before reading the local intelligence pool: missing built-in sources are created and enabled, existing but disabled built-in defaults are re-enabled, and then every enabled source is fetched and written to `intelligence_items`. To avoid hitting external sites once per stock, there is a 60-minute cooldown within the running process; during the cooldown the local database is reused.

## API

All endpoints live under `/api/v1/intelligence`.

- `POST /sources`: create a news source.
- `GET /sources`: query news sources.
- `GET /sources/templates?market=us`: query the built-in source templates.
- `POST /sources/templates/{template_id}`: create a source from a built-in template, optionally overriding the name, enabled state, scope, and description.
- `POST /sources/defaults`: create every built-in default source in one call. The endpoint is idempotent: an existing source with the same name returns `created=false` and is not inserted twice. Without an explicit `enabled`, sources are created as `false`; pass `{ "enabled": true }` to enable them by default.
- `POST /sources/test`: test a payload without persisting it.
- `POST /sources/{source_id}/fetch?dry_run=false`: fetch a single source.
- `POST /sources/fetch-enabled`: fail-open fetch of every enabled source.
- `GET /items?scope_type=market&market=us&days=7`: query intelligence entries.

To complete "create source -> fetch -> persist -> analysis consumption" automatically in a local `.env`, in Docker, or in any runtime that passes environment variables through explicitly, set:

```env
NEWS_INTEL_AUTO_FETCH_ENABLED=true
```

That switch represents the user's explicit consent for the runtime to reach the configured external RSS/Atom HTTP sources. It is off by default to avoid unconfirmed external requests and changes to the analysis prompt input.

> Note: the switch only takes effect when it is visible in the executing process's environment variables. The bundled `00-daily-analysis.yml` uses an allowlist mapping strategy for `env`, so a variable that is not mapped explicitly is never injected into the runtime even when a same-named repository Variable or Secret exists. The default workflow therefore does not pick this switch up automatically. To enable the capability in the bundled daily analysis job, add the variable to the workflow explicitly, or run locally / in Docker with the environment variable configured directly.

## Suggested follow-up integration

On top of the first baseline, the analysis path reads the local intelligence pool on a best-effort basis:

- Traditional single-stock analysis reads `symbol=<stock code>` intelligence first and supplements it with `market`-level intelligence for the same market. The content is appended to the existing `news_context` and saved alongside the AnalysisContextPack summary and the historical `news_content`.
- Agent analysis injects local intelligence evidence through `news_context` as well, so the Agent does not have to search again to see news that is already stored.
- Market review merges `market`-level intelligence for the same market into the market news list, so the prompt, the structured payload, and the report's news field all show the source links.
- With `NEWS_INTEL_AUTO_FETCH_ENABLED=true`, those entry points first perform a fail-open automatic refresh of the local pool; a failed refresh never blocks the analysis.
- This capability only adds a local intelligence consumption path. It does not change model names, provider/base URLs, the default model strategy, the fallback strategy, the pre-`save_context_snapshot` cleanup logic, or runtime configuration semantics. It is compatible with existing deployments, and rolling back means removing the local intelligence entry points or the local source configuration and data.

Later PRs can continue improving evidence display in reports, and the Web settings and report-viewing entry points.

## Compatibility and rollback (Issue #1707)

- This feature does not change third-party LLM provider semantics, and adds no provider/model/base URL/default-model strategy/runtime routing or configuration migration branch.
- The model/API compatibility risk raised by the structured scanner does not apply to this change: the `news_context` injection path only reuses the existing LLM analysis input construction flow (`src/core/pipeline.py`, `src/market_analyzer.py`, `src/analyzer.py`), and adds no `.env` writes, pre-save cleanup, or clear/backfill logic.
- Rollback: `revert` this PR. To downgrade the configuration only, disable and remove the local source configuration (the `sources` table and the existing `intelligence_items`). Existing models, providers, and other historical analysis paths are unaffected.

## Reusable PR description content (Issue #1707)

- Refs: `#1707`
- Compatibility conclusion: this change only adds a local intelligence consumption path. It does not change model names, provider/base URLs, the default model strategy, the fallback strategy, pre-save cleanup logic, or runtime configuration migration. The `news_context` and `market_review_payload` extensions are best-effort additions and do not affect the existing contract or compatibility boundary.
- Rollback plan: the minimal path is `revert this PR`. To downgrade the integration only, disable and clean up the local intelligence sources at runtime (`sources` and `intelligence_items`).

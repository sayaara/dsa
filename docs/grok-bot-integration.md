# Grok Bot integration

This page explains how [daily_stock_analysis](https://github.com/ZhuLinsen/daily_stock_analysis) (DSA) integrates with [Grok Bot](https://x.ai/bot), the xAI AI-teammate product launched on **2026-08-11** (not ordinary Grok chat).

It adds no APIs, environment variables, providers, or runtime branches. Grok Bot only consumes the existing REST / Skill contracts.

## Tell the two paths apart first

| Path | What it is | How to configure | What it is not |
| --- | --- | --- | --- |
| **Grok as the analysis model** | LiteLLM connects directly to `xai/*` and DSA writes reports with Grok | `XAI_API_KEY` + `LITELLM_MODEL=xai/<official model ID>`, see the [LLM Configuration Guide](LLM_CONFIG_GUIDE.md) | Not the Grok Bot product |
| **Grok Bot as a teammate** | A teammate with a persistent cloud computer, Skills, Routines, MCP/Connectors, and computer use | The bot calls DSA's deployed HTTP API, or runs `python main.py` on its own computer | Do not configure the bot as `LITELLM_MODEL` |

Both paths can run at once: DSA uses `xai/grok-*` for analysis, and Grok Bot then reads the reports and `DecisionSignal` records.

## Recommended integration order

1. Make the DSA API continuously reachable first: `python main.py --serve-only` or Docker. GitHub Actions only runs scheduled jobs and does not expose the API long-term.
2. Add a Skill inside Grok Bot (adapt the `SKILL.md` example from the [openclaw Skill](openclaw-skill-integration.md) directly, or use [`docs/examples/grok_bot/SKILL.md`](examples/grok_bot/SKILL.md)).
3. For intraday monitoring or a morning briefing, have a bot routine query `DecisionSignal` instead of repeatedly running a full analysis.
4. Only once the bot reliably calls the HTTP API should you consider exposing the same endpoints through an MCP connector. This repository **does not provide an MCP server in P0**.

## Skill: trigger single-stock analysis

The same main entry point openclaw uses. Bots and routines should **default to `async_mode: true`**:

```http
POST {DSA_BASE_URL}/api/v1/analysis/analyze
Content-Type: application/json

{
  "stock_code": "600519",
  "report_type": "detailed",
  "force_refresh": true,
  "async_mode": true
}
```

- Asynchronous: returns 202 plus a `task_id`, then poll `GET /api/v1/analysis/status/{task_id}` until `status: completed`. The finished report is in `result.report` (`TaskStatus.result` is an `AnalysisResultResponse`); do not read `report` at the response root.
- Do not switch to an asynchronous rerun after a synchronous timeout. After a synchronous timeout the server's `_handle_sync_analysis` keeps running and never enters `TaskQueue`, so sending `async_mode: true` bypasses queue de-duplication and produces duplicate LLM cost and duplicate pushes.
- Use `async_mode: false` only when the HTTP timeout is at least 300 seconds and a user is waiting for a single result. The report in a synchronous response is at the root under `report`.
- Health check: `GET /api/health`.
- Ask-stock Agent (requires `AGENT_MODE=true`): `POST /api/v1/agent/chat`.

Result-reading conventions (identical to the openclaw Skill, which avoids parallel fields):

- Free text: `report.summary.operation_advice`, `trend_prediction`, `analysis_summary` (prefixed with `result.` on the asynchronous path)
- Structured action: the optional `action` / `action_label` (the eight states `buy|add|hold|reduce|sell|watch|avoid|alert`)
- When an older history record lacks the field, fall back to `operation_advice`; the legacy three-state statistics still key on `decision_type`

The Grok Bot Skill body is in [`docs/examples/grok_bot/SKILL.md`](examples/grok_bot/SKILL.md), and the [openclaw Skill](openclaw-skill-integration.md) example can be reused. The environment variable is `DSA_BASE_URL` in both cases.

## Skill: market review

`POST {DSA_BASE_URL}/api/v1/analysis/market-review` always returns a 202 acceptance body plus a `task_id`, not the review text. The request body accepts `send_notification` and `region`.

Poll `GET /api/v1/analysis/status/{task_id}` until `status: completed`, then read `market_review_report` or `market_review_payload` from the top level of `TaskStatus` (not from `result.report`).

## Routine: consuming DecisionSignal

Do not let a routine rerun the analysis every time. The public query endpoints are:

| Purpose | Endpoint |
| --- | --- |
| Latest active signal for a stock | `GET /api/v1/decision-signals/latest/{stock_code}` |
| Paginated filtering | `GET /api/v1/decision-signals` |
| Outcome statistics | `GET /api/v1/decision-signals/outcomes/stats` |
| Useful / not useful feedback | `GET/PUT /api/v1/decision-signals/{signal_id}/feedback` |

For the fields and lifecycle, see the [DecisionSignal topic](decision-signals.md). `DecisionSignal` records a recommendation only; it never places an order or rebalances a position.

When the bot needs low-sensitivity context, use the public overview from [AnalysisContextPack](analysis-context-pack.md) rather than stuffing the full `context_snapshot` into a Skill prompt.

## MCP / Connectors / computer use

- **MCP**: wrap the REST endpoints above as tools (`analyze_stock`, `get_latest_signal`, `market_review`). This repository deliberately ships no MCP server, which avoids a second source of truth drifting from the FastAPI contract.
- **Connectors**: Grok Bot can sign in to Feishu, email, and similar services; DSA's own notification channels still use the webhooks already in `.env` and need not be relayed through the bot.
- **Computer use**: only suitable for running `python main.py --stocks 600519,AAPL` or `python main.py --market-review` when the bot's cloud computer has already cloned the repository and configured `.env`. HTTP remains the default recommendation, because it makes authentication, timeouts, and asynchronous tasks easier.

## Authentication

By default the DSA API requires no authentication. With `ADMIN_AUTH_ENABLED=true`, only a post-login cookie is supported today - **bearer tokens are not**. If Grok Bot can only send `Authorization: Bearer`, either keep the API unauthenticated and restrict the listening network range, or add separate authentication at the reverse proxy. Do not treat `XAI_API_KEY` as an authentication secret for the DSA API.

## Explicitly out of scope

- Registering Grok Bot as a LiteLLM managed channel.
- Adding `GROK_BOT_*` environment variables.
- Duplicating a parallel `DecisionSignal` / `AnalysisContextPack` schema.
- Promising on this page that a particular `grok-*` model works within the current `litellm` constraint. Take model names from the [xAI documentation](https://docs.x.ai/docs) and verify them with `python scripts/check_env.py --llm`.

## Minimum acceptance

1. DSA: `python scripts/check_env.py --config`; if you are using an xAI model, also run `python scripts/check_env.py --llm`.
2. `GET {DSA_BASE_URL}/api/health` succeeds.
3. The bot Skill obtains `operation_advice` or `action` for a real code (such as `AAPL` or `600519`), reading from `result.report` on the asynchronous path.
4. Market review returns `market_review_report` or `market_review_payload` from the status endpoint, rather than only a 202 acceptance.
5. A routine can read the JSON from `GET /api/v1/decision-signals/latest/{stock_code}` without rerunning an analysis.

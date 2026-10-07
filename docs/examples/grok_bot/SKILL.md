---
name: daily-stock-analysis
description: Calls the daily_stock_analysis API to analyze stocks. Use it when the user says things like 「分析茅台」, "analyze AAPL", 「帮我看看 600519」, or asks for a market review. Prefer the stock code.
---

# daily_stock_analysis

This skill is for the Grok Bot (the 2026-08-11 AI teammate). It calls a deployed DSA over HTTP; do not configure the bot as a LiteLLM provider.

It needs the `DSA_BASE_URL` environment variable (the DSA API root, with no trailing slash).

## When to use it

- Analyzing one or several stocks
- Querying a stock's latest DecisionSignal (a morning-brief or watch routine)
- A market review

## Workflow

1. Extract the stock code: `AAPL` for the US, `RY.TO` / `ABX.V` for Canada. Hong Kong, mainland China and Taiwan codes are not supported. With only a company name, ask the user for the code first.
2. For a full analysis, POST `{DSA_BASE_URL}/api/v1/analysis/analyze`. **Use async from the start for a routine, or for any analysis likely to exceed the bot's HTTP timeout** — never start synchronously and switch to async afterwards. After a synchronous timeout the server's `_handle_sync_analysis` keeps running and never enters the `TaskQueue`, so a later `async_mode: true` bypasses queue deduplication and produces duplicate billing and duplicate pushes.

```json
{
  "stock_code": "<code>",
  "report_type": "detailed",
  "force_refresh": true,
  "async_mode": true
}
```

After a 202 plus a `task_id`, poll `GET {DSA_BASE_URL}/api/v1/analysis/status/{task_id}` until `status: completed`. The finished report is in `result.report`, not the `report` at the response root.

Use `async_mode: false` only when the bot's HTTP timeout is 300 seconds or more and the user is waiting on a single synchronous result. After a synchronous timeout, do not re-run it asynchronously; first check whether the stock already has a job in flight (409 / status), or read the latest DecisionSignal.

3. When you only need the latest recommendation and no re-analysis: `GET {DSA_BASE_URL}/api/v1/decision-signals/latest/{stock_code}`.
4. Market review: `POST {DSA_BASE_URL}/api/v1/analysis/market-review` always returns 202 plus a `task_id`, not the review body. Poll the same status endpoint and, once complete, read the top-level `market_review_report` or `market_review_payload` (not `result.report`).
5. If the health check fails, start with `GET {DSA_BASE_URL}/api/health`.

## How to present the result

- Synchronous analysis: `report.summary.operation_advice`, `trend_prediction`, `analysis_summary`
- Asynchronous analysis: `result.report.summary.operation_advice`, `result.report.summary.trend_prediction`, `result.report.summary.analysis_summary`
- Structured action: `action` / `action_label` (`buy|add|hold|reduce|sell|watch|avoid|alert`); under `result.report.summary` when asynchronous
- Plan: synchronous `report.strategy.ideal_buy` / `stop_loss` / `take_profit`; asynchronous `result.report.strategy.*`
- Market review: `market_review_report` (text) or `market_review_payload` (structured)
- When a field is missing, fall back to `operation_advice`; the legacy three-state statistics still use `decision_type`
- A DecisionSignal only shows a recommendation: it places no order and rebalances nothing

## Errors

| Status | Handling |
| --- | --- |
| Connection failure | Check that DSA is running and that `DSA_BASE_URL` is correct |
| 400 | Check `stock_code` |
| 409 | The stock is already being analyzed; check the status of the existing `existing_task_id` rather than starting another analysis |
| 500 | Read the DSA logs; confirm `LITELLM_MODEL` and its key (including the optional `XAI_API_KEY`) |

With `ADMIN_AUTH_ENABLED=true`, the current API accepts a cookie only, not a Bearer token. Do not treat `XAI_API_KEY` as a DSA API key.

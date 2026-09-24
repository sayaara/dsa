# openclaw Skill integration guide

This document explains how to call the daily_stock_analysis REST API from an [openclaw](https://github.com/openclaw/openclaw) Skill, so stock analysis can be triggered from an openclaw conversation.

## Overview

- **Integration approach**: an openclaw Skill calls the daily_stock_analysis (DSA) REST API over HTTP
- **When it applies**: you already run the DSA API service and want to trigger analysis from an openclaw conversation (for example "帮我分析茅台" or "analyze AAPL")
- **Similar consumers**: [Grok Bot](https://x.ai/bot), launched on 2026-08-11 (Skills / Routines / MCP / computer use), uses the same REST contract - do not create a parallel API. See [Grok Bot integration](grok-bot-integration.md).

## Prerequisites

1. **daily_stock_analysis must be running**: run `python main.py --serve-only` or deploy with Docker, so the API stays available
2. **openclaw needs HTTP capability**: for example `system.run` executing curl, or a built-in HTTP tool such as api-tester
3. **Note**: GitHub Actions only runs scheduled jobs and does not expose the API long-term, so run DSA locally or in Docker

## Core API reference

| Endpoint | Method | Purpose |
|------|------|------|
| `/api/v1/analysis/analyze` | POST | Trigger analysis (the main entry point) |
| `/api/v1/analysis/status/{task_id}` | GET | Asynchronous task status |
| `/api/v1/agent/chat` | POST | Agent strategy ask-stock (requires `AGENT_MODE=true`) |
| `/api/health` | GET | Health check |

### Analysis request body

```json
{
  "stock_code": "600519",
  "report_type": "detailed",
  "force_refresh": true,
  "async_mode": false
}
```

- `stock_code`: the stock code (required)
- `report_type`: `simple` | `detailed` | `brief`
- `force_refresh`: boolean, whether to force a refresh (ignoring the cache)
- `async_mode`: boolean. `false` returns synchronously; `true` returns 202 plus a `task_id` that must be polled

**Note**: `force_refresh` and `async_mode` are booleans, not strings.

### Example response (synchronous mode)

```json
{
  "query_id": "abc123def456",
  "stock_code": "600519",
  "stock_name": "贵州茅台",
  "report": {
    "summary": {
      "analysis_summary": "...",
      "operation_advice": "持有",
      "action": "hold",
      "action_label": "持有",
      "trend_prediction": "看多",
      "sentiment_score": 75
    },
    "strategy": {
      "ideal_buy": "1850",
      "stop_loss": "1780",
      "take_profit": "1950"
    }
  },
  "created_at": "2026-03-13T10:00:00"
}
```

## Important limitations

- **Stock codes only**: the API does not accept Chinese names (such as 「茅台」). Resolve them on the Skill side, or ask the user for a code such as 600519 or AAPL
- **Synchronous mode is slow**: with `async_mode: false` a single analysis takes roughly 2-5 minutes, so make sure the openclaw or HTTP client timeout is long enough
- **Asynchronous mode**: `async_mode: true` returns 202 plus a `task_id`; poll `GET /api/v1/analysis/status/{task_id}` until `status: completed`

## Stock code formats

| Type | Format | Examples |
|------|------|------|
| A-shares | 6 digits | `600519`, `000001`, `300750` |
| Beijing Stock Exchange | 6 digits starting with 8/4/92, with an optional `BJ` prefix or `.BJ` suffix | `920748`, `BJ920493`, `920493.BJ` |
| Hong Kong | hk + 5 digits | `hk00700`, `hk09988` |
| US | 1-5 letters (optional .X suffix) | `AAPL`, `TSLA`, `BRK.B` |
| US indices | SPX/DJI/IXIC and similar | `SPX`, `DJI`, `NASDAQ`, `VIX` |

## Configuration

Configure this in `~/.openclaw/openclaw.json`:

```json
{
  "skills": {
    "entries": {
      "daily-stock-analysis": {
        "enabled": true,
        "env": {
          "DSA_BASE_URL": "http://localhost:8000"
        }
      }
    }
  }
}
```

- Local deployment: `http://localhost:8000` or `http://127.0.0.1:8000`
- Remote deployment: replace with the real URL
- **Recommended**: do not end `DSA_BASE_URL` with a `/`

## Error response format

| Status | error field | Meaning |
|--------|-------------|------|
| 400 | `validation_error` | Bad parameters (a missing stock_code, for example) |
| 409 | `duplicate_task` | That stock is already being analyzed; a duplicate submission is refused |
| 500 | `internal_error` / `analysis_failed` | An error occurred during analysis |

## Complete SKILL.md example

Save the following to `~/.openclaw/skills/daily-stock-analysis/SKILL.md`:

```markdown
---
name: daily-stock-analysis
description: Call the daily_stock_analysis API to run intelligent stock analysis. Use it when the user says things like 「分析茅台」, "analyze AAPL", or 「帮我看看 600519」. Stock codes only; Chinese names are not supported.
metadata:
  {"openclaw": {"requires": {"env": ["DSA_BASE_URL"]}, "primaryEnv": "DSA_BASE_URL"}}
---

## Trigger conditions

Use this Skill when the user asks for analysis of a stock (for example 「分析茅台」, "analyze AAPL", or 「帮我看看 600519」).

## Workflow

1. **Extract the stock code**: identify the code in the user's message (600519, AAPL, hk00700, and so on). If the user gives only a Chinese name such as 「茅台」, ask for the stock code, or apply a common mapping (茅台 -> 600519).
2. **Call the API**: send a POST request to `{DSA_BASE_URL}/api/v1/analysis/analyze` with the body:
   ```json
   {"stock_code": "<extracted code>", "report_type": "detailed", "force_refresh": true, "async_mode": false, "skills": ["bull_trend"]}
   ```
   > `skills` is an optional array of strategy IDs. The historical `strategies` field is still accepted for compatibility, but `skills` is preferred.
3. **Wait for the response**: a synchronous analysis takes roughly 2-5 minutes, so make sure the HTTP client timeout is long enough (at least 300 seconds is recommended).
4. **Parse the result**: take `operation_advice`, `trend_prediction`, and `analysis_summary` from `report.summary`, and `ideal_buy`, `stop_loss`, and `take_profit` from `report.strategy`, then present them concisely. External integrations may continue reading only the free-text `operation_advice`; for a structured display, prefer the optional `action` / `action_label` (the eight states `buy|add|hold|reduce|sell|watch|avoid|alert`). When an older history record lacks the field, fall back to displaying the `operation_advice` text, but that fallback is not equivalent to a stable API action, and the legacy three-state statistics still key on `decision_type`.
5. **Error handling**:
   - Connection failure: suggest checking that DSA is running and that DSA_BASE_URL is correct
   - 400: check the stock_code format
   - 409: that stock is already being analyzed; retry later or query the task status
   - 500: suggest checking the DSA logs

## Stock code formats

- A-shares: 6 digits (600519, 000001)
- Beijing Stock Exchange: 6 digits starting with 8/4/92, with a BJ prefix or .BJ suffix (920748, BJ920493, 920493.BJ)
- Hong Kong: hk + 5 digits (hk00700)
- US: 1-5 letters (AAPL, TSLA, BRK.B)
- US indices: SPX, DJI, IXIC and similar
```

## Agent strategy ask-stock (optional)

If daily_stock_analysis has `AGENT_MODE=true` enabled, you can call the Agent strategy ask-stock endpoint, which supports multi-turn conversation and several strategies (Chan theory, moving-average golden cross, and others):

```bash
# Replace {DSA_BASE_URL} with your configured API address (such as http://localhost:8000)
curl -X POST {DSA_BASE_URL}/api/v1/agent/chat \
  -H 'Content-Type: application/json' \
  -d '{"message": "用缠论分析 600519", "session_id": "optional-session-id"}'
```

The response contains `content` (the analysis conclusion) and `session_id` (used for multi-turn conversation).

## Troubleshooting

| Symptom | Likely cause | Suggested action |
|------|----------|----------|
| Connection failure | DSA is not running, wrong port, firewall | Confirm `python main.py --serve-only` has started, and check `DSA_BASE_URL` |
| 400 error | Bad or missing stock_code format | Check the code format (see the table above) and make sure the body contains `stock_code` |
| 500 error | AI configuration, data source, or network problem | Check the DSA logs and confirm `LITELLM_MODEL` and the matching key (such as `GEMINI_API_KEY` / `XAI_API_KEY`) are configured |
| Agent 400 | Agent mode is not enabled | Set `AGENT_MODE=true` in DSA's `.env` |
| Analysis timeout | The synchronous wait is too long | Increase the HTTP client timeout, or switch to `async_mode: true` and poll the status |

## Authentication

By default the DSA API requires no authentication. If `ADMIN_AUTH_ENABLED=true` is set in `.env`, the Skill call must carry the cookie obtained after login; how you do that depends on openclaw's HTTP tool capabilities (the API currently supports cookie authentication only, not bearer tokens).

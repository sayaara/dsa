# Run Diagnostics and Data Reliability 1.0 (Phase 2)

This document records the backend scope delivered in #1391 Phase 2: building on the Phase 1 `trace_id` and provider-run records to produce a user-readable run diagnostic summary, plus a copyable redacted troubleshooting text.

## Scope of this round

- Adds `RunDiagnosticSummary` aggregation, which reports an overall status:
  - `normal`
  - `degraded`
  - `failed`
  - `unknown`
- The summary covers these critical paths:
  - Real-time quotes
  - Daily bar data
  - News search
  - LLM
  - Notifications
  - History persistence
- `AnalysisService` appends an optional `diagnostic_summary` to synchronous and asynchronous task results.
- Adds a history-report diagnostics API:

```http
GET /api/v1/history/{record_id}/diagnostics
```

`record_id` accepts either the history record's primary key ID or a `query_id`, and returns the diagnostic summary together with `copy_text`.

## Copyable troubleshooting information

`copy_text` is plain text aimed at issues and troubleshooting. It contains:

- `trace_id`
- `query_id`
- `stock_code`
- `trigger_source`
- The overall `data_status`
- A short status for real-time quotes, daily bars, news, LLM, notifications, and history persistence
- The primary cause

Before it is generated, the run-diagnostics redaction rules are applied, which keeps tokens, API keys, Authorization headers, cookies, webhook URLs, email passwords, proxy credentials, and similar sensitive values out of the output.

## Compatibility boundary

- This round adds no configuration options, does not change data-source priority, and does not change the fallback strategy.
- This round changes no LLM/provider/base URL/configuration-migration semantics; it only adds diagnostic fields in the history snapshot plus a query endpoint.
- The API only appends optional fields and adds a read-only endpoint; older clients can ignore both.
- When an older report has no `context_snapshot.diagnostics`, the endpoint returns `unknown` rather than an error.
- Notification diagnostics are recorded in the current task context. If a history report had no notification evidence when it was saved, the summary shows the notification result as unknown.
- A failure while generating the diagnostic summary must never affect report reading or the main analysis flow.

### Clarifying the structured detection alert

- The automated scanner flags a "model/provider/base URL compatibility risk" because `src/agent/factory.py` added **numeric safety fallbacks** for `agent_max_steps` and `agent_orchestrator_timeout_s` (`_coerce_config_int`), so the scan may misread that as a configuration-sensitive path. The hit comes from test and routing protection, not from a runtime configuration or compatibility-semantics change.
- When a numeric setting holds an invalid value, the system logs a `warning` to the `src.agent.factory` logger (for example `[AgentFactory] Invalid value for agent_max_steps...`) and falls back to the default. The log is there to diagnose "the parameter did not take effect" problems, independently of model/provider/base URL compatibility.
- This round is confirmed to perform no silent migration, clearing, or rewriting:
  - `src/core/pipeline.py` and `src/services/analysis_service.py` only add diagnostic records; they do not modify any `litellm_model`, `agent_litellm_model`, `openai_base_url`, or channel `LLM_*` field in `Config`.
  - `_coerce_config_int` in `src/agent/factory.py` only computes `max_steps` and `timeout_seconds` while building execution parameters, and never writes back to the `config` object. The original `litellm_model`, `agent_litellm_model`, and `openai_base_url` values pass through the construction path intact.
  - This round triggers no runtime cleanup, persistence write-back, or migration flow on `Config`, so there is no risk of a write-back rewriting the runtime configuration.
- Regression coverage: `tests/test_agent_pipeline.py::TestAgentConfig::test_build_agent_executor_does_not_mutate_llm_route_config` and `tests/test_agent_pipeline.py::TestAgentConfig::test_build_agent_executor_multi_arch_does_not_mutate_llm_route_config` assert explicitly that those fields keep their original values after `build_agent_executor`.
- Rollback path: to restore the old behaviour, remove the commits from this round, or drop the `diag_*` fields from the `context_snapshot` / `RunDiagnosticSummary` deserialization path. The main path and the model/provider configuration need no extra migration or repair.

## Suggested verification

```bash
python -m pytest tests/test_run_diagnostics_p2.py tests/test_run_diagnostics_p1.py
python -m py_compile src/services/run_diagnostics.py src/services/history_service.py api/v1/endpoints/history.py api/v1/schemas/history.py
```

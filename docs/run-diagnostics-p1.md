# Run Diagnostics and Data Reliability 1.0 (Phase 1)

This document records the minimal runtime scope delivered in #1391 Phase 1: a unified `trace_id`, plus structured provider attempts recorded for the first set of critical data paths.

## Scope of this round

- When an API / Web asynchronous task is created, `TaskInfo` uses `task_id` as the default `trace_id`.
- The task list, task status, and SSE events gain a `trace_id` field; older clients can ignore it.
- Synchronous analysis uses the current `query_id` as the default `trace_id`.
- The pipeline establishes a lightweight diagnostic context at runtime, spanning daily-bar preparation and single-stock analysis.
- `data_provider/base.py` records `ProviderRun`-style events for these paths:
  - `daily_data`
  - `realtime_quote`
- Diagnostic records are written to the in-memory context and saved with the analysis under `context_snapshot.diagnostics`; older history records without the field remain compatible.

## `ProviderRun` fields

The first version keeps the field set minimal:

- `trace_id`
- `data_type`
- `provider`
- `operation`
- `success`
- `latency_ms`
- `error_type`
- `error_message_sanitized`
- `fallback_to`
- `record_count`
- `created_at`

Error summaries are redacted at a basic level, which keeps tokens, API keys, Authorization headers, cookies, and webhook URLs containing sensitive parameters out of the output.

## Stability boundaries

- A failed diagnostic record only logs a warning; it never affects the main analysis, data-source fallback, or history persistence.
- This round adds no configuration options, does not change data-source priority, and does not change the fallback strategy.
- This round adds no Web display components. `trace_id` and provider runs land in the API, SSE, and history snapshot first, so Phase 2/3 aggregation and display can reuse them.

## Suggested verification

```bash
python -m pytest tests/test_run_diagnostics_p1.py tests/test_analysis_api_contract.py::AnalysisApiContractTestCase::test_get_analysis_status_normalizes_completed_queue_result_contract
python -m py_compile src/services/run_diagnostics.py src/services/task_queue.py src/services/analysis_service.py src/core/pipeline.py data_provider/base.py api/v1/schemas/analysis.py api/v1/endpoints/analysis.py
```

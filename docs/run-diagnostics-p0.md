# Run Diagnostics and Data Reliability 1.0 (Phase 0)

This document defines **Phase 0 (P0)** of #1391: converging the contract boundaries and limiting this round's runtime fixes, without introducing new pages or changing the global analysis strategy and the core fallback semantics.

## Goals

- Give later implementation a shared vocabulary: `trace_id`, critical-path records, diagnostic summary, redacted troubleshooting information.
- Define the first stage's scope clearly, so the requirement does not expand into a full observability platform.
- Fix the fail-open, security, and retention baselines to reduce regression risk.

## Documentation scope (this round)

- This file is the Phase 0 contract and acceptance-boundary document. The current PR is docs plus a runtime fix, and this round also completes the A-share code attribution boundaries in `baostock_fetcher.py`, `pytdx_fetcher.py`, and `tushare_fetcher.py`, with regression coverage from `tests/test_a_share_fetcher_code_conversion.py`.
- The attribution boundary must cover both bare and prefixed codes (such as `000001`, `000001.SZ`, `SH000001`, `SH.000001`, `SZ000001`, `SZ.000001`), so SH/SZ prefix semantics are not misclassified.
- Absent a new requirement to migrate LLM provider/model/base URL semantics, this round narrows the Tushare A-share attribution range to `600/601/603/605/688` and `000/001/002/003/300/301`, with regression coverage for the `605`, `001`, `003`, and `301` cases. That range change is not considered an extension of provider configuration or routing policy.

## Non-goals

- No OpenTelemetry / APM / Grafana-style monitoring system.
- No p95 figures, full provider call details, or a complete operations panel in the first version.
- No changes to the existing data-source priority, analysis strategy, or notification strategy.
- No changes to the LLM provider list, base URLs, `llm_call` runtime parameters, or `REPORT_*` configuration semantics and migration path; this round is limited to A-share code attribution parsing and diagnostic field boundaries.

### Acceptance boundary (this round)

- This round is a `fix` (docs plus runtime fix). The change only narrows A-share code attribution semantics; it does not change the provider list, base URLs, `llm_call` runtime semantics, or the `REPORT_*` configuration migration path.
- In `data_provider/baostock_fetcher.py`, `data_provider/pytdx_fetcher.py`, and `data_provider/tushare_fetcher.py`, this round handles only:
  - Bare and suffixed codes: `000001`, `000001.SH`, `000001.SZ`
  - Prefixed codes: `SH000001`, `SH.000001`, `SZ000001`, `SZ.000001`
- The `SH000001` / `SH.000001` / `SZ000001` / `SZ.000001` cases are a correctness blocker and need regression coverage from `tests/test_a_share_fetcher_code_conversion.py`.
- The minimum regression scope is `python -m pytest tests/test_a_share_fetcher_code_conversion.py` plus `./scripts/ci_gate.sh`, with results and blockers reported in the PR description.
- The preferred rollback is restoring those three files to their pre-merge state; the rest of the scope should not be reverted along with them.

## Terminology and contracts (P0 draft)

### 1) `trace_id`

- Meaning: a single correlation ID for one analysis run.
- Requirements:
  - Each analysis task has exactly one `trace_id`.
  - It may be generated at the entry point, or mapped from an existing task ID (a Web task, for example).
  - It appears in logs and structured diagnostics so troubleshooting can correlate them.

### 2) `RunDiagnosticSummary`

- Meaning: a short run diagnostic summary intended for users.
- Suggested fields (kept minimal in the first version):
  - `trace_id`
  - `status`: `ok` / `degraded` / `failed`
  - `data_status`: whether the critical data paths degraded
  - `notify_status`: a summary of the notification result
  - `error_hint`: a short redacted cause
- Note: this is a user-facing capability, not an internal full event log.

### 3) Critical-path records (minimum set)

The first version only requires recording the outcome of these key nodes (success/failure/degraded plus a short reason):

- `realtime_quote`
- `daily_data`
- `llm_call`
- `report_persist`
- `notification_dispatch`

> Note: `news`, `fundamental`, `capital_flow` and similar paths are deferred to a later extension and are not blockers for the first version.

## Security and stability boundaries (mandatory in P0)

### Fail-open

- A failed diagnostic record must not block the main analysis flow.
- Even when the diagnostic write fails, an analysis result must still be produced (unless the main flow itself fails).

### Redaction

- Copyable troubleshooting information must never contain secrets, tokens, complete webhook URLs, or user account identifiers.
- Error text should be summarized, which avoids leaking sensitive raw content returned by a third party.

### Retention

- The retention period for diagnostic data should be configurable, or cleanable in one place.
- The default policy should be conservative (keeping only the necessary time window, for example), which avoids unbounded growth.

### Compatibility

- New fields should be appended, without breaking existing API / Web / Desktop read paths.
- Older history records lacking the new fields must degrade safely.

## Phase 0 deliverables

- [x] Goals and non-goals defined, preventing scope creep.
- [x] Minimum contracts for `trace_id` and `RunDiagnosticSummary` defined.
- [x] Critical-path coverage for the first version defined.
- [x] Fail-open, redaction, retention, and compatibility baselines fixed.

## Later stages (described only, not implemented in P0)

- Phase 1: `trace_id` propagation plus minimal critical-path records.
- Phase 2: generate and persist `RunDiagnosticSummary`, supporting copyable redacted troubleshooting information.
- Phase 3: a minimal Web display (collapsed by default), plus documentation and rollback notes.

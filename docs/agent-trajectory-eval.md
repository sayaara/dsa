# Agent trajectory evaluation (minimal version, Refs #1956)

## Purpose

`evals/agent_trajectory/` provides a **minimal, offline-runnable trajectory evaluation pipeline**: it runs one golden sample against a real `tool_calls_log + AgentResult` and emits a structured JSON report plus a short readable text summary. The evaluation is a **reporter, not a gate** - a metric violation only shows up in the report. It never fails the process and never enters the CI gate.

- The metrics layer (`metrics.py`) is pure functions: it consumes only the trajectory log and the golden samples, imports nothing from `src/`, makes no network calls, calls no LLM, and can be unit-tested offline.
- The entry point (`run_eval.py`) builds a real executor through `build_agent_executor()`, uses the same execution-capture hook as `src/core/pipeline.py`, and consumes real output.
- The entry point supports **single-agent runs only** (`AGENT_ARCH=single`, the default). With `AGENT_ARCH=multi` the factory returns an orchestrator whose trajectory is a concatenation of per-stage local step numbers and whose `total_steps` is the stage count, which is incompatible with the single-runner metric contract. The entry point reports this clearly before building and exits (exit code 1).
- The entry point validates the golden samples against the real tool registry: a misspelled or outdated `expected_tools` entry is judged an invalid sample (exit code 1), rather than silently scoring it as a low hit rate.
- This change freezes the **minimal metric contract**. Extended semantics such as stock guards and the Codex `arguments_summary` dialect are explicitly deferred to later PRs (see "Out of scope" at the end).

## Quick start

```bash
# Run a single sample (real LLM, depends on the locally configured model)
python evals/agent_trajectory/run_eval.py --sample 600519_technical

# Run every sample and emit structured JSON (keyed by sample id)
python evals/agent_trajectory/run_eval.py --all --json-out eval_report.json
```

Arguments:

| Argument | Description |
| --- | --- |
| `--sample ID` / `--all` | Required, pick one: run a single golden sample or all of them |
| `--golden-path PATH` | A custom golden JSON path (defaults to `golden_samples.json` next to the module) |
| `--json-out PATH` | Write a structured JSON report (a keyed object when used with `--all`) |

Exit codes: `0` the run succeeded (violations included); `1` golden loading failed (including an `expected_tools` entry absent from the real tool registry), sample selection failed, tool-registry loading failed, executor construction failed (including the `AGENT_ARCH=multi` refusal), or the run failed (including the executor returning `success=false`, for example an unconfigured provider, an LLM error, a timeout, exhausted max_steps, or a dashboard parse failure); `2` usage error.

## The frozen minimal metric contract

For each `tool_calls_log` entry (the runner contract: every item has `step / tool / arguments / success / duration / result_length / cached`, optionally `timeout` / `guarded`), only the following are counted:

| Metric | Definition |
| --- | --- |
| `expected_hit_rate` / `missing_expected` | Expected tools are matched **by tool name** (this version does not judge per stock); `expected_total` is the de-duplicated expected count |
| `optional_tools_used` | Tools actually called outside the expected set; recorded as a violation when `allow_optional_tools=false` |
| `redundant_calls` | Every occurrence of the same (tool, args-key) pair after the first, regardless of success. args-key = `json.dumps(arguments, sort_keys=True, default=str)`, following the same idea as the runtime cache key |
| `retries` | A repeat of the same (tool, args-key) pair immediately after a **failure**; `retries` is a subset of `redundant_calls`. A success clears the failure state for that pair, so `fail -> success -> success` counts 1 retry (the later success counts only as redundant) |
| `failed_calls` | The number of entries with `success=false` |
| `cached_calls` | The number of entries with `cached=true` (runner semantics: reusing a non-retryable failed result) |
| `distinct_steps` / `max_steps_touched` | The larger of the log steps and `AgentResult.total_steps` (the final answer-only turn produces no tool call, so the log underestimates); `max_steps_touched` is the heuristic `max(step) >= allowed_max_steps` |

## Golden sample schema

`golden_samples.json` is an array with these fields:

| Field | Type | Description |
| --- | --- | --- |
| `id` | string | Unique sample id (required) |
| `task_description` | string | The task text handed to the executor (required) |
| `stock_code` | string | Passed through verbatim as runner context (`{"stock_code": ...}`); an empty string means no context, and it does not affect scoring |
| `expected_tools` | string[] | Expected tool names (required, non-empty, no duplicates) |
| `allowed_max_steps` | int | Step-budget heuristic (default 10, at least 1) |
| `allow_optional_tools` | bool | Whether tools outside the expected set are tolerated (default true) |

Validation: the loading path (`load_golden_samples`) rejects an invalid sample outright, while the direct-construction path (`compute_trajectory_metrics`) reports each violation with exactly the same wording as the validator, so the two paths keep the same contract by construction. `known_tool_names` can be injected with the real tool registry for membership validation (the metrics layer itself imports nothing from `src/`); the `run_eval.py` entry point injects the real tool registry automatically.

## JSON report schema

A single sample:

```json
{
  "sample_id": "600519_technical",
  "task_description": "…",
  "stock_code": "600519",
  "metrics": { "expected_hit_rate": …, "expected_total": …, "…": "… 11 fields in total" },
  "violations": ["…"]
}
```

With `--all --json-out`, the outer value is a `{sample_id: <the object above>}` keyed object.

## Out of scope (later PRs)

- Per-stock hit judgement and guard interception semantics (`guarded` / out-of-bounds call violations)
- Recognizing the Codex App Server `arguments_summary` dialect
- Any `.env` / runtime configuration or CI gate (this PR changes nothing under `src/` and does not affect the existing analysis flow)

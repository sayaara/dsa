# Agent analysis eval

## Purpose

In agent mode the pipeline builds the report from `AgentExecutor.run`: a tool loop under `AGENT_SYSTEM_PROMPT` (strategies picked) or `LEGACY_DEFAULT_AGENT_SYSTEM_PROMPT` (the implicit `bull_trend` default) in `src/agent/executor.py`, ending in a decision dashboard. Changing those prompts, or the tool-output text the model reads, changes the report, and the unit suite cannot detect the effect because it mocks the LLM. The other evals do not cover this path: the [prompt-language eval](prompt-language-eval.md) drives only `GeminiAnalyzer.analyze`, the [chat-language eval](chat-language-eval.md) drives Agent Chat's free-text replies, and the [trajectory eval](agent-trajectory-eval.md) scores only which tools are called. `evals/agent_analysis/` measures the dashboard and the tool loop together.

The eval is a **reporter, not a gate**: it never fails CI and never calls a model in the offline test suite.

## How it works

1. **Capture** (`capture_fixtures.py`) is the chat eval's capture with other defaults: for each of the prompt-language eval's 30 stocks (`evals/prompt_language/samples.json`) it calls the real Agent tools once (quote, daily history, stock info, the technical tools, the two search tools, market indices) and stores the results in `evals/agent_analysis/fixtures/`. No LLM is called; each stock costs two search-tool calls.
2. **Replay** (`run_eval.py`) builds the production single-agent executor with `build_agent_executor`, as the pipeline does, and swaps only its tool registry for the chat eval's replay registry (same tool surface; a call the fixture cannot answer gets a "no data" error and is counted as off-fixture). It sends the pipeline's request (`Analyze stock {code} ({stock_name}) and return the full decision dashboard JSON.`) with the context every pipeline run carries: code, name, report type, report language and the real-time quote. The market phase, daily market context, market structure, context-pack summary and news context blocks are left out; they are English already and depend on stored state.
3. **Metrics** (`metrics.py`, pure functions). The dashboard is scored, without any repair, on the prompt-language eval's scale: JSON validity (the dashboard parser found an object), minimal-contract validity, report integrity (required fields present when parsed by the analyzer's parser; the pipeline's agent-result conversion backfills missing fields, so it is not used), decision distribution, `operation_advice` / `decision_type` consistency, mean score, English share, the noise floor across repeats and the per-sample comparison against the baseline. The tool loop is scored with the chat eval's trajectory measures: workflow tools hit, phase order, failed, redundant and off-fixture calls, steps, tokens and the system-prompt hashes seen.

Variants live in `variants.py`. `current` builds the executor with no strategy picked, so it runs the legacy default prompt unless `AGENT_SKILLS` is configured, and is the baseline. `skills` selects the prompt-language eval's `EVAL_SKILLS` explicitly and runs `AGENT_SYSTEM_PROMPT`. To measure a change to the agent prompts or tool labels, run the same variants on a checkout without the change and on one with it, with the same `--fixtures`, and compare the two JSON reports; a template experiment can instead be registered with `patched_agent_prompts`.

## Quick start

```bash
# 1. Capture tool outputs (needs market-data network access; uses the configured search keys)
python evals/agent_analysis/capture_fixtures.py

# 2. Validate samples, fixtures and variant templates and print the plan (no model calls)
python evals/agent_analysis/run_eval.py --variant current --variant skills

# 3. Run: 30 samples x 2 variants x 3 repeats = 180 agent runs
python evals/agent_analysis/run_eval.py --run --variant current --variant skills --repeats 3 --max-runs 180 --json-out agent_eval.json
```

| Argument | Description |
| --- | --- |
| `--sample ID` | Only this sample (repeatable; both scripts) |
| `--variant NAME` | Variant to run (repeatable); defaults to `current` |
| `--repeats N` | Runs per sample and variant (default 3) |
| `--run` | Call the model; without it the runner only validates and plans |
| `--max-runs N` | Refuse to start when the plan needs more agent runs (default 0) |
| `--english-threshold X` | Maximum CJK share of the dashboard text for it to count as English (default 0.05) |
| `--json-out PATH` | Write the report and every per-run record as JSON |
| `--fixtures PATH` / `--samples PATH` | Other fixture directory or sample list |

## Notes

- Fixtures contain market data and third-party news text, so `evals/agent_analysis/fixtures/` is git-ignored. Recapture when a tool's output format changes; the runner refuses fixtures captured under a different `REPORT_LANGUAGE` or holding tools that are no longer registered.
- Cost: each run makes one model call per loop step (about four to six for the full workflow, at most `AGENT_MAX_STEPS`), and every call resends the system prompt, the request and the tool results so far. The plan line prints the upper bound. Transport-level retries and model fallback configured in the LLM router can add calls.
- The eval needs the single-agent executor (`AGENT_ARCH=single`, the default). The multi-agent orchestrator is not covered.
- Usage and evidence rows go to a throwaway database, never to `data/stock_analysis.db`.
- Exit codes: 0 = ran or validated, 1 = fixture or setup failure (including no LLM configured with `--run`), 2 = usage error or plan above `--max-runs`.

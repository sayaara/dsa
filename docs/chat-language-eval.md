# Chat-prompt language evaluation

## Purpose

The Agent Chat system prompts in `src/agent/executor.py` (`CHAT_SYSTEM_PROMPT`, used when skills are selected, and `LEGACY_DEFAULT_CHAT_SYSTEM_PROMPT`, used for the implicit built-in `bull_trend` default) are written in Chinese; English replies come from the "Output Language" block appended to them. Translating them changes what the model reads on every chat turn, and the unit suite cannot detect the effect because it mocks the LLM. `evals/chat_language/` measures that effect before a translated chat prompt ships.

The [prompt-language eval](prompt-language-eval.md) cannot do this: it drives only `GeminiAnalyzer.analyze`, while chat is a multi-step tool loop with free-text replies. This eval is a **reporter, not a gate**: it never fails CI and never calls a model in the offline test suite.

## How it works

1. **Capture** (`capture_fixtures.py`) calls the real Agent tools once per stock in `samples.json` (6 US and 4 Canadian stocks), with their default arguments: quote, daily history, stock info, the four technical tools, `search_stock_news` and `search_comprehensive_intel`, plus `get_market_indices` for `us` and `ca`. Each result is stored frozen to JSON values (or as its serialized text when freezing would change what the model reads); a failed call stores its error. No LLM is called, and database writes go to a throwaway database under the output directory.
2. **Replay** (`replay.py`, `run_eval.py`) builds the production chat executor with `build_agent_chat_executor` (the LiteLLM backend, the configured skills and `AGENT_MAX_STEPS`) and replaces only its tool registry with a copy whose handlers return the captured outputs. The model sees the same tool declarations, and the runner serializes the replayed results exactly as it serialized the live ones. Calls are matched on the tool name plus `stock_code` (or `region`); other arguments such as `days` are ignored. A call the fixture cannot answer (another stock, or a tool that reads saved DSA state such as `get_analysis_context`) gets a "No data available" error and is counted as an off-fixture call. Each sample question is then asked as a fresh chat turn per variant and repeat; conversation rows go to a throwaway database.
3. **Metrics** (`metrics.py`, pure functions) report per variant: the share of replies written in English (CJK share of the reply at or below `--english-threshold`), whether the four workflow tools the prompts prescribe were all called (`get_realtime_quote`, `get_daily_history`, `analyze_trend`, `search_stock_news`), whether they were called one phase per step in phase order, off-fixture, failed and redundant tool calls, steps, tokens and latency. Decision samples append a fixed instruction to end with `Decision: buy|hold|sell`, so the stance is read from that line instead of guessed from prose; the stance noise floor (consistency across repeats) is reported next to the comparison against the baseline (per-sample modal stance agreement and flips, and the English, workflow and phase-order rate deltas). A difference smaller than the noise floor is not evidence of a prompt effect.

Variants live in `variants.py`. `current` is the shipped prompt and the baseline; which template it runs follows the configured skills, as in production. A translated prompt is registered there with `patched_chat_prompts(chat_prompt=..., legacy_prompt=...)` and compared with `--variant current --variant <name>`. Before running, the runner checks that every variant's templates keep all the placeholders `prepare_agent_chat` fills (`market_role`, `market_guidelines`, `default_skill_policy_section`, `skills_section`, `language_section`).

Not covered: the Codex chat backend (`CODEX_CHAT_SYSTEM_PROMPT`), multi-agent chat (`AGENT_ARCH=multi`, rejected at startup), and multi-turn conversations (every turn starts a new session).

## Quick start

```bash
# 1. Capture tool outputs (needs market-data network access; each stock makes two search-tool calls)
python evals/chat_language/capture_fixtures.py

# 2. Validate samples, fixtures and variant templates and print the plan (no model calls)
python evals/chat_language/run_eval.py

# 3. Run: 10 samples x 1 variant x 2 repeats = 20 chat turns
python evals/chat_language/run_eval.py --run --repeats 2 --max-turns 20 --json-out chat_eval.json
```

| Argument | Description |
| --- | --- |
| `--sample ID` | Only this sample (repeatable; both scripts) |
| `--variant NAME` | Variant to run (repeatable); defaults to `current` |
| `--repeats N` | Turns per sample and variant (default 2) |
| `--run` | Call the model; without it the runner only validates and plans |
| `--max-turns N` | Refuse to start when the plan needs more chat turns (default 0) |
| `--english-threshold X` | Maximum CJK share for a reply to count as English (default 0.05) |
| `--json-out PATH` | Write the report and every per-turn record as JSON |

## Notes

- Fixtures contain market data and third-party news text, so `evals/chat_language/fixtures/` is git-ignored. Recapture when a tool's output format changes; the runner refuses fixtures captured under a different `REPORT_LANGUAGE` or holding tools that are no longer registered.
- Cost: each turn makes one model call per loop step (about five for the full workflow, at most `AGENT_MAX_STEPS`), and every call resends the system prompt, the question and the tool results so far. The plan line prints the upper bound. Transport-level retries and model fallback configured in the LLM router can add calls.
- The eval needs the single-agent LiteLLM chat backend (`AGENT_ARCH=single`, `AGENT_BACKEND=auto` or `litellm`).
- Exit codes: 0 = ran or validated, 1 = fixture or setup failure (including no LLM configured with `--run`), 2 = usage error or plan above `--max-turns`.

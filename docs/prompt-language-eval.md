# Prompt-language evaluation

## Purpose

The analyzer's base system prompt and per-stock user prompt were written in Chinese, with English reports coming from an "Output Language (highest priority)" block appended to that Chinese base. Both are English now: the default prompt and the request since F4 (HANDOFF.md III.46-III.61), the skill-driven prompt since audit A7 (III.126). A prompt change alters what the model reads, and the unit suite cannot detect the effect because it mocks the LLM. `evals/prompt_language/` measures that effect before a prompt change ships.

It replays frozen analyzer inputs through `GeminiAnalyzer.analyze` under each prompt variant, several times each, and compares the model's **first** answer. The eval is a **reporter, not a gate**: it never fails CI and never runs in the offline test suite.

## How it works

1. **Capture** (`capture_fixtures.py`) runs the real data pipeline for each sample in `samples.json` (15 US and 15 Canadian symbols; the Hong Kong samples were replaced on 2026-10-07, so results before that date are not directly comparable) and records exactly what `analyze()` receives: the context, the news context and the context-pack summary. No LLM is called, nothing is sent to notification channels, and history rows go to a throwaway database under the output directory. A fixture is saved only when the prompt rebuilt from its JSON form is byte-identical to the live prompt; its SHA-256 is stored.
2. **Replay** (`run_eval.py`) rebuilds each fixture's prompt and refuses to run if it no longer matches the captured hash (code or data drift, or a different `REPORT_LANGUAGE`). It then calls the model once per sample, variant and repeat, with integrity retries disabled so the answer is scored before any repair.
3. **Metrics** (`metrics.py`, pure functions) report per variant: JSON validity, minimal-contract validity, report integrity (required fields present without repair), the buy/hold/sell distribution, `operation_advice` / `decision_type` consistency, mean sentiment score, the share of answers written in English (CJK share of text values at or below `--english-threshold`, `stock_name` exempt), and median latency. The **noise floor** (decision consistency and score spread across repeats of the same variant) is reported next to the **comparison** against the baseline (per-sample modal decision agreement, decision flips, mean score delta); a difference smaller than the noise floor is not evidence of a prompt effect.

Variants live in `variants.py`. `current` is the shipped prompt and the baseline, and `english_plain` the English system prompt without the one-JSON-object rule. The `chinese_base` and `chinese_user_prompt` variants, which compared against the Chinese default prompt and the Chinese analysis request, were removed with those prompts when reports became English-only (audit A9); a new prompt is registered there as a context manager (for example one that patches `_get_analysis_system_prompt`) and compared with `--variant current --variant <name>`. `skills` runs the skill-driven prompt (`GeminiAnalyzer.SYSTEM_PROMPT`) with an explicit selection of `EVAL_SKILLS`, the path a request takes when the user picks strategies; to measure a change to that path or to the strategy files, run `--variant skills` on a checkout without the change and on one with it, with the same `--fixtures`, and compare the two JSON reports.

## Quick start

```bash
# 1. Capture inputs (needs network access to market data; use production's search keys so news is included)
python evals/prompt_language/capture_fixtures.py

# 2. Validate fixtures and print the call plan (no model calls)
python evals/prompt_language/run_eval.py

# 3. Run: 30 samples x 1 variant x 3 repeats = 90 calls
python evals/prompt_language/run_eval.py --run --repeats 3 --max-calls 90 --json-out prompt_eval.json
```

| Argument | Description |
| --- | --- |
| `--sample ID` | Only this sample (repeatable; both scripts) |
| `--variant NAME` | Variant to run (repeatable); defaults to `current` |
| `--repeats N` | Calls per sample and variant (default 3) |
| `--run` | Call the model; without it the runner only validates and plans |
| `--max-calls N` | Refuse to start when the plan needs more calls (default 0) |
| `--english-threshold X` | Maximum CJK share for an answer to count as English (default 0.05) |
| `--json-out PATH` | Write the report and every per-call record as JSON |

## Baseline (US/CA, default prompt)

Recorded 2026-10-13 on `main` at `89bad5e` with `claude-sonnet-5-5`: `--variant current`, 30 fixtures (15 US, 15 CA, captured 2026-10-12) x 3 repeats = 90 calls, 0 call errors. Use it as the reference for later prompt changes on the default path.

| Metric | Value |
| --- | --- |
| JSON / contract / integrity / English | 100% / 100% / 100% / 100% (CJK share 0) |
| Decisions buy / hold / sell | 10 / 75 / 5 |
| Mean score | 50.6 |
| Noise floor: decision consistency | 97.8% (28/30 samples identical on all repeats; BMO hold/sell, TSLA buy/hold) |
| Noise floor: score standard deviation | 0.93 |
| Median latency | 43 s |

For comparison, the skill-driven prompt (`--variant skills`, same sample set, 2026-10-12) gave buy/hold/sell 14/73/3, mean score 51.4 and the same 97.8% decision consistency. A change that moves the modal decision on more than two of the 30 samples, or the mean score by more than about one point, is outside the noise floor.

### After the A-share data rules were removed (2026-10-24)

The chip-structure, profit-ratio and main-fund-flow rules were removed from the prompts (baseline section 3 is now volume confirmation, and the request no longer carries the "chip data unavailable" block). Measured on the same 30 fixtures as the baseline above, re-hashed for the new request (see Notes), `--variant current`, 3 repeats, `claude-sonnet-5-5`, 0 call errors:

| Metric | Baseline (2026-10-13) | After (2026-10-24) |
| --- | --- | --- |
| JSON / contract / integrity / English | 100% / 100% / 100% / 100% | 100% / 100% / 100% / 100% |
| Decisions buy / hold / sell | 10 / 75 / 5 | 10 / 74 / 6 |
| Mean score | 50.6 | 50.3 |
| Decision consistency | 97.8% (28/30) | 97.8% (28/30) |
| Score standard deviation | 0.93 | 0.83 |
| Median latency | 43 s | 44 s |

Modal decision agreement 29/30 (`us_TSLA` hold -> buy, mean score 59 -> 61, already one of the two unstable samples), mean score delta -0.33: inside the noise floor. Use the "After" column as the reference for later changes to the default path. The skill-driven path was not re-measured.

## Notes

- Fixtures contain market data and third-party news text, so `evals/prompt_language/fixtures/` is git-ignored. Recapture when the analyzer's prompt formatting changes; replay refuses stale fixtures. To compare a request change on the same data instead, copy the fixtures and re-record each `prompt_sha256` with `build_prompt` under the new code (keep the old hash next to it), then compare the new run with the stored report of the old one.
- Cost scales with fixtures x variants x repeats; each call sends the full system and user prompt. Transport-level retries and model fallback configured in the LLM router can add calls beyond the plan.
- Exit codes: 0 = ran or validated, 1 = fixture or setup failure (including no LLM configured with `--run`), 2 = usage error or plan above `--max-calls`.

# HANDOFF

Session handoff for the **English-language migration** of the DSA repo.
Written 2026-09-19; **last updated 2026-09-30** (see "Current state" below, then **III.30-III.31 for the active US/HK-focus work**, and III.14-III.27 for the English migration).
Read this plus `AGENTS.md` before doing anything.

There have been **three separate projects**, in this order:

| | Project | Status |
|---|---|---|
| **Part I** | Source **comments and docstrings** -> English | **COMPLETE and independently verified** |
| **Part II** | **Primary resources** (governance, config template, docs) -> English | **COMPLETE** - all tiers done; see II.2b |
| **Part III** | **The product itself** -> English-only (retire the zh/ko runtime surface) | **IN PROGRESS** - frontend F1/F3/F5 done (III.10-III.12); backend fallbacks, API docs/messages, progress/CLI/sender text done (III.13-III.15); merged-report headings and the Portfolio page done (III.20); bot replies done (III.21); Settings schema text and service messages done (III.22); frontend source guard and full-width punctuation cleanup done (III.23); strategy alias guard tests done (III.24); retired-language dormancy tests done (III.25); Korean year-over-year labels fixed (III.26); strategy display names localize (III.27); prompt eval built but not run (III.16); **F2 deferred by decision, F4 (prompt translation) blocked on the eval**; the frontend source guard is a per-file ratchet, so Chinese added to a file that already has an allowance is not caught until its number is raised (III.23) |

**A fourth project started 2026-09-30: make the product US/HK-first and remove Asian markets** (III.30 done and merged as PR #3; III.31 JP/KR/TW removal done on branch `feat/remove-asia-markets`, PR not yet opened; mainland China is next). **Read III.31 first for what to do next on that project.** The English migration (Part III) is otherwise paused: read III.1 for its scope decisions, III.6 for its risks,
**III.27 for its last session**, and **III.19 for its open items**. Part I is retained below because its decision log (D1-D8)
still governs; several Part I statements (D3 "no git", §11 "do not git init", R1 "noisy
baseline") are **superseded** and are marked in place.

## Current state at a glance (2026-09-30)

| Topic | State |
|---|---|
| **Version control** | **The repo is now a git repo** (D3 reversed by the user on 2026-09-24). Remote: `https://github.com/sayaara/dsa`, branch `main`. The user's standing instruction (2026-09-30) is to update this file, commit and push after each unit of work; work goes on feature branches and reaches `main` through a PR (#3 merged). English messages, no `Co-Authored-By` (`AGENTS.md`). Destructive or outward-facing steps (force-push, tags, merging, deleting branches) still need confirmation. |
| **Machine** | Moved to `C:\ara\ai-vs-code-projects\DSA`. The scratchpads referenced in Parts I/II (`C:\Users\AVEERA~1\...`) **do not exist on this machine**; git history is now the rollback, not snapshots. |
| **Python** | `.venv` is **Python 3.11.9** (matches Docker `python:3.11-slim-bookworm` and CI), built from the unmodified `requirements.txt`. The system default Python here is 3.14; on 3.14 only the `tiktoken<0.12` pin has no wheel (see III.17). Resolved versions: `pandas` 3.0.x, `numpy` 2.4.x, `litellm` 1.98.0, `tiktoken` 0.11.0. |
| **Backend tests (Windows)** | **Green**: `pytest -m "not network"` = 6,529 passed / 65 skipped / **0 failed** (2026-09-30, full run after III.31; the count fell from 6,801 because about 110 JP/KR/TW tests were deleted). Two flakes surfaced since III.18 and were fixed at the root (III.20). R1's "~88 failures that move between runs" no longer applies on Windows; treat any failure as real. |
| **Frontend gates** | `tsc` 0 errors, `npm run lint` 0 errors / 2 pre-existing warnings, `npm run build` passes, full `vitest` 1,201 passed in one run plus the flaky files passing alone (2026-09-30, after III.31; that run had no load timeouts, but `DecisionSignalsPage` and `HomePage` have timed out under the parallel run before and pass alone, so treat a failure there as a load flake). |
| **Node.js** | **Node 24.19.0 / npm 11.17** installed with `winget` on 2026-09-29 (CI uses Node 20; `package.json` allows `>=20.19 <27`). The bash tool's PATH does not see it, so run frontend commands from PowerShell with `$env:Path = "C:\Program Files\nodejs;" + $env:Path`. |
| **CI** | PR #3 (Phases 1-2): **green** (`backend-tests` 1-3/3, `backend-gate`, `ai-governance`, `docker-build`; `web-gate` and desktop jobs skipped by the path filter). `feat/remove-asia-markets` (III.31): **no PR yet, so CI has not run.** `gh` is not installed here; PRs are created through the built-in browser (signed in to GitHub) using the compare URL `https://github.com/sayaara/dsa/compare/main...<branch>?expand=1`, and CI results must be read from the PR's Checks tab. After each push, look at the Actions tab of `sayaara/dsa`. `CLAUDE.md` was fixed to be a tracked symlink (III.20), which should unblock `ai-governance` and the `backend-tests` jobs that `need` it. |
| **Line endings** | `core.autocrlf` rewrites working files to CRLF after a commit (`CLAUDE.md` symlinks are also off: `core.symlinks=false`). Scripts that edit `docs/CHANGELOG.md` or source by bytes must detect `\r\n` first. |
| **LLM** | **No LLM or search key is configured on this machine** (no `.env`). Anything that needs a model (the prompt eval, F4) is blocked on the user adding their production keys. |

Commits made since the import (oldest first):

| Commit | Content |
|---|---|
| `16b0d47` | Import of the working tree as it stood after Parts I/II and III.10-III.13 |
| `8d7615d` | Report-language fallbacks resolve from `REPORT_LANGUAGE` instead of `"zh"` (III.14) |
| `cf0bcc9` | Batch A: OpenAPI documentation strings (III.15) |
| `a6f9b87` | Batch B: API runtime messages (III.15) |
| `2aa77fb` | Batch C: run-flow / diagnostics / progress / CLI / sender text (III.15) |
| `953a1fe` | Prompt-language eval harness (III.16) |
| `98e6f9c` | Analyzer progress messages (III.15) |
| `5dc71e6` | Windows test stabilisation + local CLI backend fix (III.18) |
| `6cc3308` | HANDOFF update through 2026-09-27 |
| `49df11a` | Local CLI prompt files keep `\n` line endings on Windows (III.20) |
| `32e411d` | Conversation history queries break `created_at` ties by `id` (III.20) |
| `b0addd7` | Float-rounding tolerance in the bounded topic search deadline test (III.20) |
| `c90cc1a` | Merged report / Feishu doc headings follow `REPORT_LANGUAGE` (III.20) |
| `bccc96a` | `CLAUDE.md` tracked as a symlink to `AGENTS.md` (III.20) |
| `54cd586` | Portfolio page translated to English (III.20) |
| `bbb04f8` | HANDOFF update through 2026-09-29 |
| `bac0b3a` | Bot replies translated to English (III.21) |
| `a54b20a` | HANDOFF update for the bot reply translation |
| `4c3978b` | Settings schema text and service messages translated to English (III.22) |
| `73bb41b` | HANDOFF update for the Settings translation |
| `41d6d24` | Full-width punctuation removed from English UI text; frontend no-Chinese source guard (III.23) |
| `c526524` | HANDOFF update for the frontend guard |
| `c950088` | Guard tests for the Chinese aliases and display names in `strategies/*.yaml` (III.24) |
| `9a62865` | HANDOFF update for the strategy alias guard |
| `83c02b0` | Dormancy tests for the retired zh / ko languages (III.25) |
| `3935701` | HANDOFF update for the dormancy tests |
| `36eb462` | Korean year-over-year labels use Hangul only (III.26) |
| `66a91c6` | HANDOFF update for the Korean label fix |
| `22b778a` | Strategy display names resolve in the report language map (III.27) |

---

# PART II - English-primary resources (COMPLETE)

## II.1 Objective

Make every **primary developer-facing resource** English-only, while **keeping the
product's runtime localization fully intact** (zh / en / ko reports, zh / en UI).

User decisions on record (all explicit):

- **Flip in place**, not a parallel English mirror. English becomes canonical.
- **Upstream sync is not a concern**, so divergence from `ZhuLinsen/daily_stock_analysis`
  is acceptable.
- **README is English-only.**
- **Delete** the Chinese variants rather than keeping them as translations.
- The post-refactor audience is **English-speaking only**.

The boundary that has not changed: **prose in English, quoted literals verbatim.**
Runtime strings, LLM prompts, localization data, live API values, parser tokens and
example inputs all stay as they are.

## II.2 Current state

| Phase | Scope | State |
|---|---|---|
| 0 - harness | Markdown/env equivalence tooling | ✅ done |
| 1 - governance | `AGENTS.md`, `SKILL.md`, `PULL_REQUEST_TEMPLATE.md`, copilot mirror | ✅ done |
| 2 - config template | `.env.example` (442 CJK lines -> 5) | ✅ done |
| 3 - paired docs | all 7 `*_EN.md` promoted + `_EN`/`README_CHT` deleted | ✅ done |
| 4 Tier A | 17 zero-coupling orphan docs (~22,000 chars) | ✅ done |
| 4 Tier B | 4 `config_registry`-linked docs + anchor remap + INDEX cleanup | ✅ done |
| 4 Tier C | 5 test- and code-coupled docs + their test retargeting | ✅ done |
| 4 Tier D | docs subdirs, `.claude/skills`, `.github`, `strategies/README.md`, YAML comments | ✅ done |

**Every tier of Part II is complete.** What remains is deliberately excluded, not unfinished
- see II.6 and the residual table in II.9.

## II.2a What Tier B/C/D actually changed

| Area | Files | Notes |
|---|---|---|
| Tier B | `llm-providers.md`, `screening-engine.md`, `deploy-webui-cloud.md`, `TUSHARE_STOCK_LIST_GUIDE.md` | `market-support.md` anchor remapped to `#official-sources-and-compatibility` |
| Tier C | `analysis-context-pack.md`, `multi-strategy-contract.md`, `alerts.md`, `notifications.md`, `decision-signals.md` | 3 doc tests retargeted; 4 source docstrings updated; `config_registry.py` anchor remapped |
| Tier D | `docs/docker/`, `docs/bot/*`, `docs/examples/grok_bot/*`, `.claude/skills/*`, `.github/ISSUE_TEMPLATE/*`, `00-daily-analysis.yml`, `docker-publish.yml`, `ghcr-dockerhub.yml`, `auto-tag.yml`, `docker-compose.yml`, `litellm_config.example.yaml`, `strategies/README.md` | workflow step name changed, so `generate_notification_actions_env_table.py` and 2 tests were updated with it |

**Source changes outside docs** (all comment/constant only):

- `src/agent/orchestrator.py`, `src/agent/protocols.py`, `src/agent/skills/synthesis.py` (x2)
  - docstring `§"..."` citations follow the translated `multi-strategy-contract.md` headings.
- `src/core/config_registry.py` - one deep-link anchor into `analysis-context-pack.md`.
- `scripts/generate_notification_actions_env_table.py` - `ANALYZE_STEP_NAME` follows the
  renamed workflow step (`执行股票分析` -> `Run stock analysis`).

**Tests retargeted** (assertion strings only, never the assertion's meaning):
`test_alerts_docs.py` (75 tokens), `test_analysis_context_pack_docs.py` (94),
`test_decision_signal_docs.py` (3), `test_searxng_env_docs.py` (6),
`test_daily_analysis_workflow_notification_env.py` (3), `test_daily_analysis_workflow_llm_env.py` (2).
The replacement scripts are in the session scratchpad and are replayable.

**Defects fixed in passing** (all pre-existing, all caused by the earlier `_EN` promotion):

- `docs/FAQ.md` -> `LLM_CONFIG_GUIDE.md#example-4-ollama` (dead anchor)
- `docs/full-guide.md` -> `LLM_CONFIG_GUIDE.md#41-vision-model-image-stock-code-extraction` (dead anchor)
- `.github/ISSUE_TEMPLATE/config.yml` -> `README.md#-快速开始` (dead anchor; README is English now)
- `docs/analysis-context-pack.md` cited `docs/INDEX.md` twice in one sentence
- `docs/INDEX.md` had an empty `## Languages` section and 13 stale `(Chinese-only)` markers

## II.2b Validation of the Tier B/C/D work

Run on a frozen tree, 2026-09-19:

| Gate | Result |
|---|---|
| `flake8 . --select=E9,F63,F7,F82` | 0 |
| Full `pytest -m "not network"` | 88 failed / 6,717 passed / 5 skipped |
| Set difference vs. the Phase-3 run (85 / 6,720) | 3 "new" failures, 0 newly passing |
| `anchors.py` (source -> doc) | 109 references, all resolve |
| `docanchors.py` (doc -> doc, new tool) | 52 links, all resolve |
| `generate_notification_actions_env_table.py --check` | exit 0 |
| Targeted doc/workflow/contract suites | 349 passed |

**The 3 "new" failures are R1 flakes, not regressions.** Proven, not assumed:

- `test_local_cli_backend.py::test_output_stat_error_is_structured_and_kills_process_group`
  and `::test_output_too_large_kills_process_group` are **both present in the original
  pre-change Part I baseline** (`baseline_full.txt`, 88/6,717). They merely happened to pass
  during the Phase-3 run.
- `test_runtime_scheduler_service.py::test_blocked_scheduled_analysis_times_out_and_allows_next_run`
  and `test_output_too_large_kills_process_group` **both pass when re-run in isolation**.
- Neither test file reads anything this work changed. `test_local_cli_backend.py` imports
  `_FIELD_DEFINITIONS` from `config_registry`, but reads only `is_sensitive` and `title`;
  the single change to that module was one `href` anchor string.
- The same isolated run surfaced 12 failures in `test_local_cli_backend.py` including five
  `test_nonzero_exit_previews_redact_*` that had **passed** in the full run - the set moves in
  both directions, exactly as R1 says. These tests spawn real subprocesses with 30-second
  sleeps and race a 3-second PID-file deadline.

`scripts/check_ai_assets.py` reports `CLAUDE.md must be a symlink to AGENTS.md`. This is
**pre-existing** - the file predates this session and is a plain text file containing the
string `AGENTS.md`, a Git symlink artifact on Windows. It was left alone.

## II.2c Where the remaining CJK is, and why

Nothing below is unfinished work.

| File(s) | Chars | Why it stays |
|---|---:|---|
| `docs/CHANGELOG.md` | 43,938 | **FROZEN** - `build_release_notes.py` parses `### 发布亮点`, 16+ tests hard-code entries |
| `.github/workflows/stale.yml`, `pr-review.yml` | 607 | Emit Chinese **to the public** on GitHub issues - runtime output |
| `docs/image-extract-prompt.md` | 268 | The fence **is** `EXTRACT_PROMPT`, byte-identical to source |
| `docs/share-images.md` | 137 | A sample report body |
| `tests/fixtures/notification_reports/*.md` | 273 | Report fixtures - runtime samples asserted by tests |
| `strategies/*.yaml` | ~8,700 | `aliases`, `instructions` (a Chinese LLM prompt) and `display_name` are live runtime data |
| `MIGRATION_REPORT.md`, `HANDOFF.md`, `updated_product_overview.md` | 337 | Our own reports, quoting preserved literals |
| Everything else (~500 chars across 18 docs) | ~500 | Quoted literals: live UI/report strings (`未纳入新闻面证据`, `自选股 - <symbol>`), config values (`FEISHU_WEBHOOK_KEYWORD=股票日报`, `DISCORD_BOT_STATUS=A股智能分析 \| /help`, `EMAIL_SENDER_NAME` default), example inputs (`贵州茅台`, `上证50`, `我的策略`), and Taiwan terminology (`三大法人`) |

## II.3 Tooling (scratchpad, OUTSIDE the repo)

> **2026-09-27: not available on the current machine.** The paths below belong to the
> previous machine; git history (`16b0d47` onward) is now the record and the rollback.

```
C:\Users\AVEERA~1\AppData\Local\Temp\claude\C--Ara-DSA\74184fe6-79b2-4f9f-9535-945bd0808678\scratchpad
```

Tier B/C/D added tools and replay scripts in a second scratchpad; both still exist on disk:

```
C:\Users\AVEERA~1\AppData\Local\Temp\claude\C--Ara-DSA\74c0fda1-4edf-4f08-a411-16eb6c459b1f\scratchpad
```

| File | Purpose |
|---|---|
| `mdguard.py` | **The Markdown safety net.** `snapshot/verify/diff/restore/residual <batch>`. Enforces that code fences, inline code, link targets, heading-level sequence, table shape and HTML-comment payloads survive a translation unchanged. Self-tested 8/8. |
| `envguard.py` | Same idea for `.env.example`: every `KEY=value` token **anywhere** (active lines *and* commented examples) must survive byte-identical, plus line count and comment/blank structure. Self-tested 7/7. |
| `envapply.py` | Applies a line-targeted TSV to `.env.example`; refuses the write outright if `envguard` would fail afterwards. |
| `anchors.py` | Resolves every `<doc>.md#anchor` reference in source against live headings using GitHub's slug algorithm. **Run this after every doc promotion.** |
| `docanchors.py` | **New.** The other half of `anchors.py`: resolves every Markdown -> Markdown anchor (in-document tables of contents and doc-to-doc deep links), which break the same way when a heading is translated. Unlike `anchors.py` it does not strip leading hyphens, so emoji-prefixed headings resolve. |
| `fencediff.py` | **New.** Prints a unified diff of chosen code fences between a snapshot and the working tree. This is what makes a `mdguard` fence CHECK auditable instead of a guess. |
| `cmpfail.py` | **New.** Set-difference of two `pytest -rf` runs, printing NEW failures and newly passing tests separately. This is the R1 gate. |
| `sections.py` | Section-level drift report between two docs. Useful but **positional** - it over-reports when a translation reorders sections (see II.5). |
| `mdsnapshots/` | Pre-edit snapshots per batch - the only rollback, since this is not a git repo. |
| `snapshots/phase0-full/` | 132 non-code files snapshotted before anything was touched. |
| `env_b0*.tsv` | Every `.env.example` edit payload, replayable in order. |

## II.4 Remaining work

**None inside the agreed Part II scope.** The exclusions below are decisions, not a backlog.

The only loose thread worth a future decision is `updated_product_overview.md`: it is a
generated report of the Part I migration, and its §5.4 still describes the bilingual doc
pairs that Phase 3 deleted. It is a dated report rather than a live contract, so it was
left alone deliberately; regenerate or annotate it if it is ever treated as current.

## II.5 Hard-won lessons - read before continuing

1. **Never bulk-promote a translation without a structural check.** On
   `docs/market-support.md` an entire section ("Japan/Korea market review v1") plus its
   verification fence was dropped because the source file read was truncated. `mdguard`
   caught it as `heading structure changed: 5 -> 4`. It would otherwise have shipped as a
   silent documentation deletion.
2. **Check whether Chinese text is decorative or functional before translating it.**
   Three files had text that looks like prose but is load-bearing, verified by grep:
   - `src/share_image.py` **parses** `核心结论`, `作战计划`, `止损位` and four more from report Markdown.
   - `src/services/empty_news.py` **emits** the two news-disclosure strings verbatim.
   - `docs/image-extract-prompt.md`'s fence **is** `EXTRACT_PROMPT`, byte-identical to source.
   Each would have been a behaviour-breaking change.
3. **A blind `_EN -> primary` string remap creates duplicates.** It produced
   `docs/DEPLOY.md,docs/DEPLOY.md` in `ci.yml` three separate times, and redundant
   variables in test files. Dedupe as part of the remap, not afterwards.
4. **Do not edit the tree while a full regression runs.** A run that overlapped edits
   reported 4 phantom failures; all 4 passed on a stable tree.
5. **`sections.py` over-reports.** It aligns positionally, so a *reordered* section reads
   as missing. Coverage has to be confirmed by reading, not by a metric.
6. **Guard over-strictness is real but must be fixed symmetrically.** `envguard` flagged
   translated parentheticals as changed values; the fix normalizes trailing punctuation on
   *both* sides, so a genuine value change still fails.

## II.6 Scope discovered late - NOT yet inventoried in any tier

The Tier A-C inventory only scanned `docs/*.md` at top level. A repo-wide scan finds more:

| Area | Files | Chars | Notes |
|---|---:|---:|---|
| `docs/` subdirectories | 7 | 5,143 | `docker/zeabur-deployment.md` (2,001), `bot/feishu-bot-config.md` (1,441), `bot/discord-bot-config.md` (819), `examples/` |
| `.claude/skills/*/SKILL.md` | 4 | 2,623 | repository collaboration skills; in scope as governance |
| `.github/` | 10 | 1,887 | `ISSUE_TEMPLATE/*`, workflow step names |
| `strategies/*.yaml` | ~16 | ~8,700 | **OUT OF SCOPE - runtime.** See below |

**`strategies/*.yaml` must NOT be translated.** Each file carries `aliases:` (live
natural-language matching vocabulary for bot commands), an `instructions:` block that is a
**Chinese LLM prompt**, and `display_name:` which keys into the `report_language.py`
localization map. English strategy names already reach users through localization.
`strategies/README.md` (652 chars) is prose and *is* in scope.

**Two `.github` workflows are also out of scope**: `stale.yml` and `pr-review.yml` emit
Chinese *to the public* on GitHub issues, which is runtime output, not developer prose.

**`docs/CHANGELOG.md` (43,938 chars) is FROZEN.** `build_release_notes.py` parses
`### 发布亮点` from it, and 16+ test assertions hard-code its Chinese entry text.
Translating it breaks release automation and the test suite. New entries use the English
type tokens (`feat`/`improve`/`fix`/`docs`/`test`/`chore`) already specified in `AGENTS.md`.

## II.7 Per-doc loop

```bash
SP="C:/Users/AVEERA~1/AppData/Local/Temp/claude/C--Ara-DSA/74184fe6-79b2-4f9f-9535-945bd0808678/scratchpad"
python "$SP/mdguard.py" snapshot <batch> <files...>   # skip if snapshot exists
# read the WHOLE file, translate prose, keep quoted literals verbatim
python "$SP/mdguard.py" verify <batch>                # audit every reported diff
python "$SP/anchors.py"                               # must stay "all anchors resolve"
./.venv/Scripts/python.exe -m pytest <coupled tests> -q --no-header --tb=line
```

A `CHECK` from `mdguard` is not automatically a failure - it means *audit the diff*. A
fence change is acceptable when only comments, prose or placeholders moved and every
command, path, key and identifier is intact. Print the diff and confirm that before moving on.

## II.8 Do not do

- **Do not** translate `strategies/*.yaml` bodies, `docs/CHANGELOG.md`, the
  `notifications.md` managed table, the `image-extract-prompt.md` fence, or the
  `share-images.md` sample report.
- **Do not** promote a doc without reading it end to end first.
- **Do not** run a full regression while editing.
- **Do not** weaken a guard to make a file pass; audit the diff instead, and if the guard
  really is too strict, fix it symmetrically and re-run its self-tests.

---

# PART I - Source comments and docstrings (COMPLETE)

> **STATUS: complete and independently verified.** All 13 batches finished 2026-09-19; a
> later session re-verified every completion claim from scratch, fixed 2 spacing defects
> and corrected one over-strong claim about the test delta - see `MIGRATION_REPORT.md`,
> especially §9. The decisions (§3, D1-D8) and risk register (§7, R1-R6) below remain
> accurate and govern Part II as well. The progress table (§2) and the remaining-work
> sections (§8, §9) are **superseded** by the report.
>
> Part I used a different scratchpad, recorded in §4. It still exists on disk and its
> tooling and snapshots work as documented.

## 1. Objective

**Overall:** Translate all non-English **developer comments and docstrings** in the DSA
codebase into professional English, with **zero executable behaviour change**.

~~**Current task:** Batch-by-batch translation, 13 batches. Batches 01–07 done, batch 08
(`data_provider/`) in progress.~~ — **stale**, all 13 batches are complete; see
`MIGRATION_REPORT.md`.

**Acceptance criteria**
- Executable code identical before/after (proven by AST + token equivalence, not eyeballing).
- No new test failures vs the recorded baseline.
- Runtime strings, logs, exception/error text, notifications, report text, UI text, LLM
  prompts and localization resources are **untouched**.
- The existing zh / en / ko report+UI capability keeps working in full.

---

## 2. Current State

> **Superseded 2026-09-24:** the repo is now a git repository with a GitHub remote (see
> "Current state" at the top). The paragraph below describes the Part I era.

**Repo is NOT a git repository.** `git rev-parse` fails. The user explicitly declined git
(see §3). There is no branch, no commit, no `git diff`. All changes are **uncommitted
working-tree edits**.

| Batch | Files | State |
|---|---|---|
| 01-api | 18 | ✅ done |
| 02-notif-sender | 13 | ✅ done |
| 03-data-layer | 5 | ✅ done |
| 04-core | 7 | ✅ done |
| 05-services | 14 | ✅ done |
| 06-bot | 20 | ✅ done |
| 07-agent | 10 | ✅ done |
| **08-data-provider** | 14 | **🔶 6 done / 8 TODO** |
| 09-src-root | 16 | ⬜ pending |
| 10-repo-root | 3 | ⬜ pending |
| 11-scripts | 5 | ⬜ pending |
| 12-frontend | 30 | ⬜ pending |
| 13-tests | 54 | ⬜ pending |

Progress: **75,030 → 48,066** CJK chars remaining in comments/docstrings (~36% done).
Of the 48,066, roughly **700 is intentional preserved-literal residual** in finished
batches (see §7); the rest is genuine remaining work.

**Batch 08 exact state** — TODO files and editable-line counts:
```
akshare_fetcher.py 321 | base.py 263 | tushare_fetcher.py 225
efinance_fetcher.py 183 | yfinance_fetcher.py 115 | pytdx_fetcher.py 107
baostock_fetcher.py 85  | longbridge_fetcher.py 26
```
Done in 08: `__init__.py`, `us_index_mapping.py`, `realtime_types.py`,
`alphavantage_fetcher.py`, `yfinance_fundamental_adapter.py`, and
`tw_institutional_fetcher.py` (deliberate no-op, see §3).

---

## 3. Important Decisions

**D1 — Policy reversed: English is mandatory.**
`AGENTS.md:27` previously said English was *not* required for comments/docstrings. User
directed changing it. Amended to three rules at `AGENTS.md:27-29` (Chinese text, matching
the doc). Logged in `docs/CHANGELOG.md` `[Unreleased]` as `[文档]`.
*Trade-off:* governance docs stay Chinese (D4), so the rule reads in Chinese — accepted as
consistent with doc-scope decision.

**D2 — Localization exception is "prose English, quoted literals verbatim".**
User asked to keep localization support and allow docstrings that localization needs.
Derived precisely: the 9 modules with language-keyed (`zh`/`en`/`ko`) dicts are the real
localization core, and 4 of them already have zero non-English comments. The category that
matters is docstrings **quoting live localized strings**. Canonical example:
`src/services/empty_news.py` module docstring quotes `未纳入新闻面证据`, a fragment of the live
`_ZH_NOT_CONFIGURED`. Prose → English; quoted literal → unchanged.

**D3 — No git.** User said "skip the git — work without git". Rollback and diff audit are
done via snapshot copies + AST equivalence instead (§4 tooling).
**Superseded 2026-09-24:** the user asked for `git init`; the tree was committed as `16b0d47`
and pushed to `https://github.com/sayaara/dsa`.

**D4 — Scope stays code-only.** User chose "None — keep code-only scope". **Excluded:**
`.env.example`, `AGENTS.md` body, `.github/copilot-instructions.md`,
`.github/instructions/*`, all of `docs/**`. Only `.py/.ts/.tsx/.js/.jsx` comments and
docstrings are in scope.

**D5 — Frontend gets the real gate.** User chose "Install deps, run the real gate".
`npm ci` is already done in `apps/dsa-web`. Pre-change frontend baseline captured.

**D6 — Delivery = working tree + written report.** No patch export, no durable snapshot
copy-out (both explicitly declined).

**D7 — `tw_institutional_fetcher.py` intentionally untouched.** Its prose is already English;
the Chinese is official Taiwan market terminology and literal government open-data dataset
names (三大法人, 上市/上櫃, 民國/西元, 外陸資). Translating breaks correspondence to the real API.

**D8 — Edits are applied via line-targeted JSON payloads, never free-hand.** Replacing one
line with one line keeps line numbers stable, which makes every payload replayable in order.

---

## 4. Relevant Files

### Tooling (lives OUTSIDE the repo — session scratchpad, persists on disk)
Base path (record this, a fresh session gets a different default scratchpad):
```
C:\Users\AVEERA~1\AppData\Local\Temp\claude\C--Ara-DSA\0dbf11d1-6593-4cad-bf5a-664bbf308124\scratchpad
```
| File | Why it matters |
|---|---|
| `guard.py` | **The safety net.** `snapshot/verify/diff/restore <batch>`. `verify` compares AST with docstrings stubbed + token stream (catches indentation); TS/JS = strip comments, require byte-identical remainder. Self-tested on 8 cases. |
| `apply.py` | Applies a JSON edit payload. **Refuses** if `old` text mismatches or the target line is not a real docstring/comment node, and if the result would not parse. |
| `lines.py` | Prints every CJK-bearing line with line number + role (`doc` / `comment` / `STRING-skip`). This is how you find work. |
| `dump.py` | Coarser per-item dump; `lines.py` is usually better. |
| `batches.json` | The 13 batch → file-list manifest. Authoritative. |
| `baseline_full.txt` | **Pre-change full-suite baseline: 88 failed / 6717 passed.** Diff against this. |
| `srcread_tests.txt` | The 18 test files that read source as text. Run these every batch. |
| `checkbatch.sh` | Post-batch gate: `bash checkbatch.sh <batch>` → AST verify + flake8 + srcread tests vs baseline. |
| `GLOSSARY.md` | Domain term table + **7 hard rules**. Read before translating. |
| `b0*.json`, `e*.json`, `fix1.json` | Every edit applied so far, replayable in order. |
| `snapshots/01-api … 08-data-provider` | Pre-edit originals = the only rollback. |
| `fe_baseline.txt` | Frontend pre-change baseline. |

### Repo files modified
| Path | Why | Modified |
|---|---|---|
| `AGENTS.md` | Policy source of truth; rules at lines 27-29 | ✅ |
| `docs/CHANGELOG.md` | `[Unreleased]` entry at line 16 | ✅ |
| 97 source files across `api/ src/ bot/ data_provider/` | The migration itself | ✅ |
| `HANDOFF.md` | This file | ✅ new |

### Repo files that matter but must NOT be edited
`src/report_language.py`, `src/schemas/decision_action.py`, `src/market_phase_summary.py`,
`src/services/decision_signal_summary.py` (localization cores — already zero non-English),
`apps/dsa-web/src/i18n/uiText.ts`, `locales/featureText.ts`, `locales/settingsHelp.ts`,
`utils/systemConfigI18n.ts` (zero Chinese dev comments — nothing to do).

---

## 5. Changes Made

~1,900 line-level edits across 97 source files, all comment/docstring-only.
Every change is recorded in the `b0*.json` / `e*.json` payloads in the scratchpad —
**read those rather than diffing by hand**. To see a real diff for any finished batch:
```bash
python <scratchpad>/guard.py diff 06-bot
```
Plus two documentation edits: `AGENTS.md:27-29` (the policy) and `docs/CHANGELOG.md:16`.

Side effect: `npm run build` refreshed `static/` (gitignored build output, not source).
`.venv/` was created at repo root (gitignored).

---

## 6. Commands / Tests Run

```bash
# env (already done)
python -m venv .venv && ./.venv/Scripts/python.exe -m pip install -r requirements.txt pytest pytest-timeout flake8
cd apps/dsa-web && npm ci                       # exit 0

# baseline (recorded)
./.venv/Scripts/python.exe -m pytest -m "not network" --timeout=120 -o timeout_method=thread \
  -p no:cacheprovider -q --no-header --tb=no -rf     # 88 failed, 6717 passed, 5 skipped
./.venv/Scripts/python.exe -m flake8 . --count --select=E9,F63,F7,F82   # 0
cd apps/dsa-web && npm run lint                 # 0 errors, 2 pre-existing warnings
cd apps/dsa-web && npm run build                # ✓ built in 38.95s

# per-batch gate (use this)
bash <scratchpad>/checkbatch.sh <batch-name>
```

**Results so far:** AST/token equivalence **97 files, 0 failures**. flake8 critical **0**.
Targeted suites all green: 684 api/core, 376 core, 335 notification, 82 bot, 224 agent,
183 tokenizer. Full regression after batch 05: 90 failed / 6715 passed — **no new failures**
attributable to the migration (see §7).

---

## 7. Known Problems / Risks

**R1 — Baseline is noisy and partly non-deterministic (confirmed).** *Superseded on Windows
2026-09-27: the causes were fixed or quarantined and the offline suite is at 0 failures (III.18).
Any new failure is now real, not noise.* 88 baseline failures,
overwhelmingly platform-related on Windows: process-group kill/reap, macOS codesign tests,
sqlite concurrency, local-CLI subprocess. Several are **load-sensitive and flip between
runs**. CI runs `ubuntu-latest` and is much greener. ⇒ The gate is **"no NEW failures"**,
never "identical failure set".

**R2 — `test_search_service_concurrency::test_bounded_topic_search_provider_receives_only_remaining_deadline`** fails
but is **NOT ours** — proven by reverting all 5 batches and re-running: still fails on a
pristine tree. 0.2s budget with two 0.03s sleeps. Ignore it.

**R3 — Comment LENGTH can break tests (real regression, already fixed once).** Some tests
anchor on a string in a source file and assert another token appears within a fixed window.
English runs longer than Chinese. `tests/test_notification_empty_news_disclosure.py::
test_count_set_to_zero_once_search_is_attempted` broke this way (span grew 376→666 vs a
600 limit); fixed by condensing to **570 — only 30 chars of headroom**. Do not add prose
near `src/core/pipeline.py:690-700`.

**R4 — `bot/dispatcher.py` must never contain the substring `except Exception` in a comment.**
`tests/test_bot_dispatcher_async.py:309` asserts its absence from the function source.

**R5 — Three comment lines carry tool directives.** Keep the directive byte-exact, translate
only the prose after the dash: `src/agent/news_evidence.py:85` (`# pragma: no cover`),
`src/services/name_to_code_resolver.py:371` and
`tests/test_name_to_code_resolver.py:563` (`# noqa: BLE001`).

**R6 — `.env.example` has a Chinese comment indexed by a test.**
`tests/test_searxng_env_docs.py` does `env_example.index("# SearXNG 实例地址")`. Out of scope
per D4 — leave it alone.

**R7 — Scratchpad is outside the repo.** *Resolved: git is the rollback now.* If it is cleaned, snapshots (rollback) and tooling
are gone. The JSON payloads still document every change, and AST equivalence means rollback
is a convenience not a necessity, but re-snapshot before editing a new batch.

**Intentional residual (NOT missed work), ~700 chars in finished batches:** preserved example
values (`贵州茅台`, `京东方Ａ`, `五 粮 液`, `机器人`=300024), live localized strings
(`股票分析报告`, `未纳入新闻面证据`), literal command keywords the code matches (`完整`/`详细`),
the NLP keyword vocabularies in `web_intent_types.py`/`web_intent_tokenizer.py`, Chinese `§`
section names cross-referencing `docs/multi-strategy-contract.md`, verbatim GitHub issue/PR
title quotes in `src/data/stock_mapping.py`, and Taiwan market terms (D7).

---

## 8. Remaining Work

1. **Finish batch 08** — 8 fetcher files listed in §2. Snapshot already taken.
2. **Batch 09-src-root** (16 files, 14,227) — biggest single batch; includes
   `src/analyzer.py`, `src/storage.py`, `src/config.py`, `src/notification.py`,
   `src/search_service.py`, `src/stock_analyzer.py`, `src/formatters.py`.
3. **Batch 10-repo-root** (3 files, 1,120) — `main.py`, `server.py`, `webui.py`.
4. **Batch 11-scripts** (5 files, 2,334).
5. **Batch 12-frontend** (30 files, 2,469) — TS/TSX. After editing, run the **real gate**
   per D5: `cd apps/dsa-web && npm run lint && npm run build`, compare to `fe_baseline.txt`.
   `guard.py verify` handles TS via comment-strip byte comparison.
6. **Batch 13-tests** (54 files, 14,671) — last, highest risk of R3.
7. **Full regression**, diff against `baseline_full.txt`.
8. **Write the final migration report** (the deliverable per D6): summary, modifications by
   area, protected localization, ambiguous items, validation results, executable-code audit,
   categorized residual non-English, final status.

### Per-batch loop
```bash
SP="C:/Users/AVEERA~1/AppData/Local/Temp/claude/C--Ara-DSA/0dbf11d1-6593-4cad-bf5a-664bbf308124/scratchpad"
python "$SP/guard.py" snapshot <batch> <files...>      # skip if snapshot exists
python "$SP/lines.py" <file>  | grep -v 'STRING-skip'  # find editable lines
# author a JSON payload: [{"file","line","kind":"doc"|"comment","old","new"}]
python "$SP/apply.py" "$SP/<payload>.json"
bash "$SP/checkbatch.sh" <batch>
```

---

## 9. Next Immediate Action

Run `python "$SP/lines.py" data_provider/longbridge_fetcher.py | grep -v 'STRING-skip'`
(26 lines, smallest remaining) and translate it as a JSON payload, then work up through
`baostock_fetcher.py` → `pytdx_fetcher.py` → `yfinance_fetcher.py` → `efinance_fetcher.py`
→ `tushare_fetcher.py` → `base.py` → `akshare_fetcher.py`. Run
`bash "$SP/checkbatch.sh" 08-data-provider` after each payload.

---

## 10. Critical Context

- The user wants **English-first source for developers** while **keeping the product
  multilingual**. These are not in tension: prose is English, data stays localized.
- "use only English" was a direction against **bilingual** comments (replace, don't append),
  not a direction to translate localization data.
- Discovery finding worth keeping: this repo's Chinese is not only UI text. There are
  **Chinese NLP keyword tables** (`_NEGATION_HINTS_ZH`, `_STRUCTURAL_RISK_PHRASE_HINTS`,
  `_BROAD_BOARD_KEYWORDS`) that are live matching vocabulary against Chinese LLM output.
  They look like prose and are not.
- `AGENTS.md` forbids `git commit` without explicit confirmation, and forbids
  `Co-Authored-By` in commit messages.
- `AGENTS.md` requires the full prompt in the PR body if `EXTRACT_PROMPT` in
  `src/services/image_stock_extractor.py` changes. It was **hash-verified unchanged**
  (`fdbc52882f6fb0f5`). Keep it that way.
- Verified early and still true: **no docstring is consumed programmatically** — no
  `inspect.getdoc`, no Sphinx/autodoc. The two `description=__doc__` scripts already had
  English module docstrings. Bot help text comes from `description`/`usage` **properties**,
  not docstrings.

---

## 11. Do Not Do

- ~~**Do not** `git init`, commit, or create a branch. Rejected by the user.~~ *Superseded
  2026-09-24: git is in use; commit/push only with explicit user confirmation (`AGENTS.md`).*
- **Do not** translate runtime strings, logs, exception/error text, notification or report
  text, UI strings, LLM prompts, or localization dictionaries.
- **Do not** touch `.env.example`, `AGENTS.md` body prose, `.github/instructions/*`, or
  `docs/**` (D4).
- **Do not** translate quoted literals inside comments: localized values, example inputs,
  stock/index/sector names, identifiers, GitHub issue titles, doc `§` section names.
- **Do not** edit files free-hand with Edit/Write. Use a JSON payload + `apply.py` so the
  change is replayable (this bit once — an over-broad `guard.py restore` wiped 12
  Edit-tool-made files that had no replay script).
- **Do not** `restore` a batch wider than the one being diagnosed.
- **Do not** change executable code to make a test pass. If a test breaks, condense the
  comment (R3) or revert.
- **Do not** declare a batch done on `guard.py verify` alone — run `checkbatch.sh`.

---

## 12. Verification Checklist

- [ ] `guard.py verify <batch>` → `FAIL=0` for every batch.
- [ ] `flake8 . --select=E9,F63,F7,F82` → `0`.
- [ ] `checkbatch.sh` srcread-test diff → "no new failures" for every batch.
- [ ] Full `pytest -m "not network"` → no failure absent from `baseline_full.txt`
      (ignore R1 timing flakes and R2).
- [ ] `cd apps/dsa-web && npm run lint && npm run build` → matches `fe_baseline.txt`
      (0 errors, 2 warnings, build ✓).
- [ ] `EXTRACT_PROMPT` unchanged. **The recorded `fdbc52882f6fb0f5` has no algorithm attached
      to it, so do not compare a fresh hash against it.** Verify by equality instead: the fence
      in `docs/image-extract-prompt.md` must still contain the prompt body from
      `src/services/image_stock_extractor.py` verbatim. Confirmed 2026-09-19 after Tier D
      (blake2b-8 of the body is `558774b9e2f30807`; the file's mtime predates every Tier B/C/D edit).
- [ ] Residual CJK re-scan: every remaining comment/docstring occurrence is an
      intentional preserved literal, itemized in the final report.
- [ ] No CJK left in comments/docstrings that is plain prose.
- [ ] Final migration report written (§8 item 8).

---

# PART III - English-only product (IN PROGRESS - see III.10 onward)

Written 2026-09-19, in the same session that verified Part II, as a plan. *Execution
started 2026-09-20; III.1-III.9 are the original plan and III.10 onward record what was done.*

Parts I and II made the *repository* English. Part III makes the *product* English: it
retires the zh/ko runtime surface that Parts I and II were explicitly careful to preserve.
That inversion is the most important thing to understand before starting - every "do not
touch" rule in II.8 and §7 exists because runtime localization was in scope to *protect*.
Under Part III it is in scope to *remove*.

## III.1 Scope decisions on record

User decisions, taken 2026-09-19 (all explicit):

- **D9 - Depth: "surface lock + English internals."** Force the product to English, *and*
  translate the Chinese LLM system prompts and `strategies/*.yaml` instruction blocks so
  the system is English end to end including what is sent to the model. The localization
  **skeleton stays** (`report_language.py`, `UI_TEXT`, the `Record<UiLanguage, ...>`
  shapes); the zh/ko **content** is retired. Deliberately not a full teardown - see D11.
- **D10 - A-shares and Hong Kong stay supported.** The product keeps its Chinese markets.
  Therefore Chinese *data* - stock names, sector names, Chinese news headlines - keeps
  flowing through the system and appearing on screen. Part III delivers an English
  **product surface over inherently Chinese data**, not a Chinese-free application. This
  is the hard floor; see R9.
- **D11 - Keep the localization machinery dormant, do not delete it.** The zh/ko code
  paths become unreachable rather than removed. Reason: 40 backend modules import
  `report_language`, and the Chinese-to-canonical parse maps are a genuine safety net when
  a model emits Chinese for a Chinese-listed stock (R10). Full removal was offered and
  declined.

## III.2 Current measured state

Repo-wide CJK scan (excluding `.venv`, `node_modules`, `__pycache__`, `static`, `data`,
`logs`): **249,568 chars across 570 files.**

| Area | Chars | Files |
|---|---:|---:|
| `apps/dsa-web/` (frontend) | 90,612 | 140 |
| `docs/` | 48,439 | 20 |
| `src/` | 46,182 | 131 |
| `tests/` | 34,826 | 181 |
| `data_provider/` | 7,269 | 15 |
| `strategies/` | 6,275 | 16 |
| `api/` | 6,047 | 19 |
| `scripts/` | 2,769 | 6 |
| root and misc | 2,547 | 17 |
| `bot/` | 2,335 | 18 |
| `.github/` | 1,773 | 5 |
| `apps/dsa-desktop/` | 494 | 2 |

**The headline number is misleading.** Classified by what the work actually is:

| Class | Chars | What it means |
|---|---:|---|
| **Data floor - permanent** | ~37,000 | `apps/dsa-web/public/stocks.index.json` (33,269) is the A-share universe; names are data carrying pinyin search keys. Plus sector and industry names from providers. Untranslatable by D10. |
| **Frozen by decision** | ~44,000 | `docs/CHANGELOG.md` (43,938). Still parsed by `build_release_notes.py`, and 16+ tests hard-code entries. Unchanged from II.6. |
| **Delete, not translate** | ~38,000 | zh/ko halves of i18n maps that **already have complete English siblings**. Verified: `uiText.ts` zh at 3-960 and en at 962-1917, symmetric; `settingsHelp.ts` `settingsHelpZhCN` at 17-1274 and `settingsHelpEnUS` at 1275+; `featureText.ts` inline zh/en pairs; and ~15,285 chars of the same pattern decentralized across 57 component files (for example `AnalysisContextSummary.tsx` `BLOCK_LABELS` carries zh + en + ko). |
| **Genuine translation** | ~28,000 | ~22,500 CJK across 19 prompt-bearing `src/` modules - of which the prompt literals are the real target, the remainder being zh-branch strings that fall into "delete" - plus 5,608 chars of `strategies/*.yaml` `instructions:` blocks. |
| **Test retargeting** | ~34,800 backend, ~19,300 frontend | Assertion payloads, not prose. Mechanical but voluminous. |

**Conclusion: the translation surface is ~28k chars, not 250k.** Most of the CJK is either
permanent data, frozen, or already has an English counterpart written.

## III.3 What is already done (inherited, no work needed)

This is the most important finding for sizing. **English is not a feature to be built - it
already works.**

- **Prompt-level English is first-class.** `src/analyzer.py:2392-2404` appends an
  `## Output Language (highest priority)` block instructing the model to keep JSON keys and
  write every human-readable value in English. The same pattern exists in
  `src/agent/executor.py:483-506`, `src/agent/agents/decision_agent.py:138-146` and
  `src/analyzer.py:4473-4479`.
- **Report parsers are already dual-anchored.** `src/share_image.py:975,1063,1077` match
  Chinese and English section names side by side, so English reports already parse for
  share-image generation.
- **The i18n English side is complete**, in all three frontend resources and in the
  in-component label maps (III.2).
- **`report_language.py` already canonicalizes English input** - its operation-advice map
  accepts `strong buy` / `buy` / `hold` alongside the Chinese and Korean equivalents.

What is *not* done: the **base** system prompts are still Chinese, with English layered on
top as an override; zh remains the default and is user-selectable; and
`strategies/*.yaml` `instructions:` are Chinese prompts with no English form.

## III.4 What remains - phased

| Phase | Scope | Primary risk |
|---|---|---|
| **0 - Classification** | Split every CJK occurrence into translate / delete / keep. The whole plan depends on this being right; a misclassification is a behaviour break, not a typo. Extend the Part II `mdguard`/`envguard` pattern with a `classify.py`. | R10, R13 |
| **1 - Surface lock** | `REPORT_LANGUAGE` defaults to `en` and rejects zh/ko at the `normalize_report_language` chokepoint; API schemas (`analysis.py`, `history.py`, `decision_signals.py`) constrain rather than remove the field so the contract does not break; frontend `UiLanguage` narrows to `'en'` and the language toggle is removed. | R12 |
| **2 - Frontend zh/ko retirement** | Delete the zh/ko halves of `uiText.ts`, `settingsHelp.ts`, `featureText.ts` and the 57 in-component label maps. Keep the `Record<UiLanguage, ...>` shape so types and call sites are untouched. | R11 |
| **3 - Backend zh/ko retirement** | Same treatment for the localized-branch helpers across the 40 `report_language` consumers. **Keep** the Chinese-to-canonical parse maps (D11 / R10). | R10 |
| **4 - English internals** | Translate the Chinese base system prompts (`analyzer.py`, `executor.py`, `market_analyzer.py`, `core/market_strategy.py`) and the 5,608 chars of `strategies/*.yaml` `instructions:`. **The only phase that changes model behaviour.** | **R8** |
| **5 - Test retargeting** | 28 backend test files coupled to prompt text (8,473 chars), 29 coupled to `report_language`/zh/ko, 119 others carrying CJK (14,964 chars), and 79 frontend test files (19,348 chars). | R11, R3 |
| **6 - Validation and docs** | Full regression under the R1 set-difference gate, `npm run lint && npm run build` against `fe_baseline.txt`, `anchors.py` and `docanchors.py`, a `docs/CHANGELOG.md` `[Unreleased]` entry, and screenshots of affected reports and pages per `AGENTS.md`. | R1 |

### Explicitly out of scope for Part III

- `docs/CHANGELOG.md` - frozen (II.6), unchanged by D9.
- `strategies/*.yaml` `aliases:` and `display_name:` - `aliases` is live bot-matching
  vocabulary, `display_name` keys into the `report_language.py` map. Only `instructions:`
  is translated. See R13.
- `stocks.index.json` and all provider-supplied names - data floor (D10).
- `.github/workflows/stale.yml` and `pr-review.yml` - these emit Chinese to the public on
  GitHub issues; developer-facing governance, not product surface.
- `data_provider/tw_institutional_fetcher.py` - D7 still stands.

## III.5 Effort

**~20-33 engineer-days, roughly 4-7 calendar weeks solo, or ~3-4 weeks if execution is
AI-assisted with human review - which is how Parts I and II were actually run.**

| Phase | Days | Notes |
|---|---:|---|
| 0 - Classification | 2-3 | Highest leverage. Do not compress this. |
| 1 - Surface lock | 2-3 | Small diff; `normalize_report_language` is a real chokepoint. |
| 2 - Frontend retirement | 3-5 | ~60 files, mostly deletion. |
| 3 - Backend retirement | 3-5 | 40 consumer modules, mostly deletion. |
| 4 - English internals | 5-8 | **Eval-dominated, not translation-dominated.** |
| 5 - Test retargeting | 4-6 | ~255 test files carry CJK; volume, not difficulty. |
| 6 - Validation and docs | 2-3 | |

**The estimate's wildcard is Phase 4.** Translating the prompts is perhaps a day of
writing; establishing that the English prompts produce analysis of equivalent quality is
all the rest. That cost is a function of how much evidence is demanded, not of repo size,
and no unit test measures it. Every other phase is bounded and predictable.

Assumptions: one engineer with the Part I/II tooling and scratchpads available; no git, so
snapshot discipline is manual (R12); the `evals/` harness is usable for Phase 4.

## III.6 Risks

Inherited and still governing: **R1** (noisy, partly non-deterministic baseline - 88
failures that move in both directions, so the gate is a set difference and never a fixed
count), **R3** (English prose runs longer than Chinese and can break fixed-window span
assertions; `src/core/pipeline.py:690-700` has ~30 chars of headroom), **R4**, **R5**.

New to Part III:

- **R8 - Prompt translation changes model behaviour. This is the dominant risk.** The
  Chinese prompts are tuned artefacts. An English rewrite can shift JSON schema adherence,
  decision distribution, refusal rate and narrative quality. **No test in the suite detects
  this** - the suite mocks the LLM. Parts I and II were safe precisely because they had a
  provable invariant (AST and token equivalence). Phase 4 has none, by construction:
  changing the strings *is* the change.
- **R9 - The product cannot become Chinese-free, and this must be accepted up front.**
  Under D10 the app keeps analysing A-shares and HK. Stock names, sector names and news
  headlines arrive in Chinese from akshare/tushare/efinance. An English-only *surface* over
  Chinese *data* is the deliverable. If "English-only app" is later read as "no Chinese
  characters anywhere", the project will be judged failed on delivery.
- **R10 - Do not delete the Chinese parse maps.** The operation-advice and signal maps
  parse *model output*. A model asked about a Shanghai-listed name may still answer in
  Chinese despite the directive. These maps are the graceful-degradation path and are cheap
  to keep. D11 covers this.
- **R11 - Test coupling is broad and shallow.** ~255 files carry CJK assertions. Each fix
  is trivial; the risk is that a bulk remap silently changes an assertion's *meaning*
  rather than its *string* - exactly the failure mode II.5 lesson 3 describes.
- **R12 - No git, and this time no invariant.** *Resolved 2026-09-24 by `git init` (see the top).* D3 still holds: no branch, no diff, no
  revert. Parts I and II tolerated that because equivalence was provable. Part III's changes
  are intentionally behaviour-changing, so a bad edit cannot be detected mechanically and
  cannot be rolled back except from scratchpad snapshots - which live in a temp directory
  (R7).
- **R13 - `strategies/*.yaml` becomes deliberately half-Chinese.** After Phase 4 each file
  has English `instructions:` beside Chinese `aliases:` and `display_name:`. That looks like
  unfinished work to the next reader and will invite a "cleanup" that breaks bot command
  matching.
- **R14 - Dormant-code drift.** D11 leaves zh/ko paths unreachable but present. Over time
  they rot untested. This is an accepted cost of reversibility, but it should be a conscious
  one rather than a discovery.

## III.7 Risk mitigations - options

**For R8 (prompt behaviour), pick one:**

| Option | Cost | Confidence |
|---|---|---|
| **A - Golden-set A/B eval.** Freeze ~30 symbols across A-share / HK / US, run the zh-prompt and en-prompt variants through the real model, and diff decision-type distribution, JSON validity rate and schema conformance. | 3-5 days | Highest. The only option that actually measures the risk. |
| **B - Schema-conformance gate only.** Assert the English prompts still yield valid JSON with the required keys over a small live sample. Catches structural breakage, not quality regression. | 1 day | Medium. |
| **C - Staged rollout behind config.** Ship English prompts behind a flag defaulting to the Chinese prompt, then flip after a period of live comparison. | 1-2 days to build | High, but it defers the decision and adds another dormant branch on top of D11. |
| **D - Translate prompts last, or not at all.** Phases 1-3 alone already deliver an English product surface, because the output-language directive works today (III.3). Phase 4 is the *internals* half of D9 and is separable. | 0 | Highest - the risk is simply not taken. Reduces D9 to "surface lock". |

**Recommendation: A, with D as the fallback.** If a golden-set eval cannot be funded, defer
Phase 4 rather than ship unvalidated prompts - the user-visible outcome of Phases 1-3 is
nearly identical, because English output already works.

**For R12 (no rollback, no invariant):**

- **Strongly recommended: `git init` before Phase 1.** D3 declined git when the work was
  provably equivalent. That justification does not survive Part III. A local repo with no
  remote costs nothing, contradicts no stated constraint (upstream sync was already
  abandoned in II.1), and converts an unrecoverable migration into a recoverable one.
- If git stays declined: snapshot every phase using the Part II `mdguard snapshot` pattern
  extended to `.py` / `.ts`, and **copy the scratchpad inside the repo tree** so R7 cannot
  delete the only rollback.

**For R9 (expectation management):** write the data floor into `README.md` and
`PRODUCT_OVERVIEW.md` as an explicit product statement during Phase 6, not as a caveat
discovered at acceptance. One sentence is enough: the interface, reports and analysis are
English; instrument names and source headlines appear as the exchange publishes them.

**For R11 (test volume):** reuse the Part II discipline exactly - line-targeted replayable
payloads (D8), never free-hand edits, and `cmpfail.py` as the set-difference gate after
every phase. Retarget assertion *strings* only; if a fix requires changing what an
assertion *means*, stop and treat it as a product decision.

**For R13:** add a header comment to each `strategies/*.yaml` stating that `aliases` and
`display_name` are intentionally not English, and add a test asserting `aliases` still
contains its Chinese tokens, so a future cleanup fails loudly.

**For R14:** add one test per retired language asserting the path is unreachable, so
dormancy is a tested contract rather than an assumption.

## III.8 Suggested sequencing

Phases 0 -> 1 -> 2 -> 3 -> 6 deliver **an English-only product surface** and stay reversible
in behaviour terms. Treat that as **Milestone 1** and validate it end to end.

Phase 4, plus its eval and Phase 5's prompt-coupled tests, is **Milestone 2** and should be
gated on the R8 decision above. Splitting the milestones this way means the risky half can
be deferred or dropped without stranding the safe half.

## III.9 First action when Part III starts

Build `classify.py` (Phase 0). For every CJK occurrence in the repo it must emit one of
`TRANSLATE`, `DELETE-ZH-KO-BRANCH`, `KEEP-DATA`, `KEEP-PARSE-MAP` or `KEEP-FROZEN`, together
with the deciding evidence: does it have an `en` sibling, is it a dict key matched against
model output, does a test index into it? Everything downstream is mechanical once that file
is trustworthy, and nothing downstream is safe until it is.

## III.10 Frontend milestone - F1 + F3 DONE (2026-09-20)

Executed the two phases that together deliver an English-only frontend surface. F2
(deleting the dormant zh/ko halves) and F5 (test retargeting) were deliberately
deferred; F4 and F6 are untouched.

**Rollback:** no git (D3 still holds). Pre-change snapshot of `apps/dsa-web/src`
(286 files) is at `<scratchpad>/snap-f1f3/src`. Replay scripts: `t_llm.py`,
`t_screen.py`, `t_bulk.py` in the same scratchpad.

### F1 - language lock

| File | Change |
|---|---|
| `utils/uiLanguage.ts` | `resolveInitialUiLanguage` / `getRuntimeInitialLanguage` always return `'en'`; new exported `UI_LANGUAGE` constant. localStorage and `navigator.language` no longer select the UI language. `normalizeUiLanguage` / `persistUiLanguage` kept (tests import them). |
| `contexts/UiLanguageContext.tsx` | `language` is constant `'en'`; `setLanguage` is an inert no-op; `document.documentElement.lang = 'en'`. **The no-provider `fallbackContext` previously resolved to `UI_TEXT.zh` - that was a live Chinese fallback and is now `en`.** |
| `utils/reportLanguage.ts` | `normalizeReportLanguage` always returns `'en'`, so report chrome is English regardless of the language stored on a record. |
| `components/i18n/UiLanguageToggle.tsx` | **Deleted**, with its 4 mount sites (`Shell`, `ShellHeader`, `SidebarNav`, `LoginPage`) and `contexts/__tests__/UiLanguageContext.test.tsx`. |

**The `UiLanguage` type was deliberately NOT narrowed to `'en'`.** Narrowing it makes
every `Record<UiLanguage, ...>` literal carrying a `zh` key a type error across ~60
files, which is exactly F2. Keeping the type is what let F1 stay surgical.

### F3 - translate hardcoded display strings

~500 replacements across 44 files. Largest: `LLMChannelEditor.tsx` (1,726 CJK chars),
`StockScreeningPage.tsx` (1,565), `api/error.ts` (583), `ChatPage.tsx` (521).

**Deliberately preserved - these match data or model output, not display copy (R10).**
Translating any of them is a behaviour break:

| Location | What it matches |
|---|---|
| `utils/decisionAction.ts` (matcher bodies, ~282 chars) | Chinese operation-advice text in model output. English branches already exist beside them; both paths coexist. |
| `pages/StockScreeningPage.tsx` `HOTSPOT_ICON_RULES` | Chinese A-share sector/topic names from the providers. Commented in place. |
| `pages/StockScreeningPage.tsx` `formatEnrichmentSummary` | Back-end `DSA行情/新闻/事件` markers - pattern kept, replacement translated. |
| `api/error.ts` `includesAny(...)` token lists | Back-end error text. Commented in place. |
| `ReportOverview.tsx`, `RunFlowEventList.tsx`, `'市场阶段'` strippers in 4 files | Chinese field names / prefixes in report data. |
| `ChatPage.tsx` + `chatStockCode.ts` intent regexes | Chinese chat input. Harmless but inert for English users - see the gap noted below. |
| `types/analysis.ts` `SentimentLabel` | A zh/en/ko **union type**: a parse contract for stored records. Its mapper is language-branched, so it already returns English. F2 territory. |
| `ChatPage.tsx` example `stock_name` values, `types/stockIndex.ts` doc comments | A-share names = data (D10) and preserved-literal examples. |

### Coupled edits worth knowing about

1. **`api/error.ts` title <-> `StockScreeningPage.tsx` comparison.** The title
   `'选股任务不可恢复'` is authored by the *frontend* (keyed off the English
   `errorCode`), and `isUnrecoverableScreenTaskError` compares against it. Both were
   translated together to `'Screening task cannot be recovered'`. An initial read
   mistook it for back-end text - it is not. The comparison is string-based and
   therefore fragile; a follow-up should compare `errorCode` instead.
2. **Run-flow edge labels.** `useRunFlowSnapshot.ts` and `topologyViewModel.ts` emit
   labels that `RunFlowGraph.getEdgeLabel` matches. Only `调用`/`详情` were mapped
   through i18n; `降级/重试/生成/保存/通知` fell through raw and **rendered Chinese even
   in English mode**. Producers and matcher were translated together.
3. `formatAmount` in `StockScreeningPage.tsx` used the Chinese units 亿/万. It now uses
   B/M/K. **This changes displayed magnitudes**, deliberately.
4. `NotificationTestPanel.tsx` / `IntelligentImport.tsx` had `language === 'en' ? … : …`
   ternaries; the dead zh branch was dropped and the now-unused `language` params removed.

### Validation

| Gate | Result |
|---|---|
| `tsc --noEmit -p tsconfig.app.json` | **0 errors** |
| `npm run lint` | **0 errors, 2 warnings** - byte-identical to the recorded baseline (both pre-existing `react-hooks/exhaustive-deps` in `StockScreeningPage`) |
| `npm run build` | **✓ built in 38.87s** (baseline 38.95s) |
| `npx vitest run` | **601 failed / 604 passed / 2 skipped (1207)**, 59 of 102 files |
| F3-scope residual CJK | 716 chars, every one itemized as intentional above |

**The 601 test failures are expected F5 work, not regressions.** The suite pins
`localStorage['dsa.uiLanguage'] = 'zh'` and asserts Chinese labels
(e.g. `expect(screen.getByText('韩股'))`). The UI is English now, so those assertions
cannot pass. Nothing was done to hide this; F5 is where it gets fixed.

### Known gaps left open on purpose

- **F2 not done.** The zh/ko halves of `uiText.ts`, `settingsHelp.ts`, `featureText.ts`
  and ~10 in-component label maps are still present, just unreachable. ~38k chars of
  dead weight, and R14 (dormant-code drift) starts accruing now.
- **F5 not done.** 601 failing frontend tests, above.
- **Chat intent detection is now inert.** The Chinese-only regexes for "compare these
  two stocks" / "switch to X" no longer match anything an English user would type.
  Adding English patterns is a feature, not a translation, so it was left out of F3 -
  but the capability is effectively off for the new audience. Worth a decision.
- **Report *bodies* are still whatever the back end stored.** F1 makes report chrome
  English; narrative text on existing records stays Chinese until the back-end default
  is flipped, and old records never change (R-F3).

## III.11 F5 - test retargeting PARTIAL (2026-09-20)

**601 -> 174 failures; 604 -> 1031 passing; 59 -> 42 failing files.** Not finished.
`tsc` 0 errors and `lint` 0 errors / 2 pre-existing warnings, both unchanged.

**Rollback:** `<scratchpad>/snap-f5` (293 files, taken after F1+F3). Every pass is a
replayable script, and the sequence below reproduces the current tree exactly from
that snapshot:

```
applymap2.py -> applytpl.py -> applyrx.py -> applyruns.py -> (curated-only inline fixes)
```

### Method

Rather than hand-editing 59 files, the English replacements were **derived from the
app's own declarations**, so no test asserts a string the source does not render:

| Source of truth | Pairs |
|---|---:|
| `uiText.ts` zh/en, matched by key | 940 |
| `settingsHelp.ts` `settingsHelpZhCN` / `settingsHelpEnUS`, matched per entry | 1,185 |
| In-component `zh:`/`en:` label maps | - |
| The F3 replacement scripts, parsed statically with `ast` | 652 |
| Hand-added for JSX text edits made outside those scripts | 27 |
| **Total** | **3,057** (`<scratchpad>/zh2en.json`) |

Passes, each narrower than the last:

1. **`applymap2`** - replace only when an ENTIRE string literal equals a map key.
2. **`applytpl`** - parameterized i18n templates. `'查看 {stock} AI 建议详情'` ->
   `'View AI signal details for {stock}'`, matching the zh template against the
   literal, capturing `{stock}`, and rebuilding from the en template. This is what
   fixed the interpolated aria-labels while leaving `贵州茅台` intact as data.
3. **`applyrx`** - regex-literal bodies (`name: /保存配置/`). Earlier passes only saw
   quoted literals, so these were never retargeted even though the string was
   already mapped. Whole-body match only.
4. **`applyruns`** - composite literals (`'回避 35'`), rewritten **only if every
   Chinese run in the literal is a known key**. If any run is unknown the literal is
   left completely alone.

### Two mistakes made and corrected - read before continuing

1. **Plain substring replacement corrupts composites.** The first attempt replaced
   map keys anywhere they appeared. Short keys destroyed longer strings that were not
   themselves keys: `贵州茅台` -> `贵州茅Taiwan票...` (from `台`->`Taiwan`),
   `无效配置` -> `None效配置` (`无`->`None`), `中期` -> `Medium期`. It reported a better
   number (332) while producing garbage. Reverted from snapshot and redone under the
   whole-literal rule. **Never reintroduce unbounded substring replacement here.**
2. **Bounded-run replacement still produces hybrids.** A later attempt replaced each
   maximal Chinese run independently, turning `/实时行情、新闻、市场热点/` into
   `/实时行情、news、市场热点/` - matching neither old nor new. Reverted; the
   all-runs-or-nothing rule in `applyruns` replaced it.
3. **Case normalisation against source literals was net-negative.** Rewriting English
   test literals to match source casing fixed a few and broke nine other files
   (42 -> 51 failing files at flat failure count). Reverted; only the explicit
   `Channel name` / `Primary model` / `Full analysis report` fixes were kept.

### Deliberately reverted, not fixed

`tests/system_config_i18n.test.ts` and `src/locales/settingsHelp.test.ts` **test the
localization data itself** and assert the zh side on purpose. The map pass wrongly
flipped their expectations to English; both are restored to the snapshot version.
The zh maps still exist (F2 is not done), so their Chinese expectations are correct.
**Do not "fix" these two until F2 decides the fate of the zh data.**

### The remaining 174

| Class | Count | What it needs |
|---|---:|---|
| Expectation still Chinese | 114 | Regex **fragments** that are substrings of a longer source string (`/实时行情、新闻、市场热点/`, `/覆盖 8 股/`, `/说明: .../`). Not mechanically mappable - the English fragment has to be read off the source. |
| English expectation vs different English source | 53 | Two sources declared different English for the same Chinese (`uiText` title case vs component sentence case), so the map picked one and the component renders the other. Needs per-file precedence, e.g. `SettingsField` labels come from `systemConfigI18n.ts`, not `settingsHelp.ts`. |
| Ambiguous query | 7 | Translation made two previously distinct labels identical, so `getByText` now finds multiple. These need `getAllByText` or a more specific query - **a real assertion change, so treat each as a product decision, not a string swap.** |

Top remaining files: `ChatPage` (31), `LLMChannelEditor` (26), `StockScreeningPage`
(15), `SettingsField` (14), `HomePage` (12), `SettingsPage` (10), `PortfolioPage` (8).

**Recommended next step:** do the 53 "different English" cases first - they are
one-line precedence fixes and cluster in two files. The 114 fragment cases are
genuinely per-assertion work. The 7 ambiguous queries should be reviewed by hand.

## III.12 F5 - test retargeting DONE (2026-09-20, later session)

**174 -> 0 failures; 1,204 passing, 2 skipped (1,206 total).** `tsc -b` 0 errors, `eslint .`
0 errors / 2 pre-existing warnings, `npm run build` 34.74s (baseline 38.95s).

**Rollback:** `<scratchpad>/snap-f5-green` (dsa-web `src/` + `tests/`, taken green). The
replay chain from `snap-f5` is `f5b_settingsfield.py -> f5b_llmchannel.py -> f5c_pages.py ->
f5d_rest.py -> f5e_last.py -> f5f_final.py` plus the inline fixes recorded below. Scratchpad
for this session: `%LOCALAPPDATA%\Temp\claude\C--Ara-DSA\e47f964e-7d96-4cb9-99ba-91be8bd76f0a\scratchpad`.
Helper tools there: `summ.py` (per-file failure summary from `vitest --reporter=json`),
`uesc.py` (finds `\uXXXX`-escaped CJK in tests), `orphans.py` (assertions whose CJK matches
neither rendered source nor fixture data).

### Product fixes made while retargeting (not test-only)

These are the "different English" and "ambiguous query" classes from III.11 resolved at the
source, plus gaps the tests exposed:

- `SettingsField.tsx` + `settingsHelp.ts` - in English the field label fell back to the
  backend schema title or the raw env key, ignoring the 121 curated English titles that
  already exist in `settingsHelpEnUS`. New `getSettingsHelpFieldTitle()` gives English the
  same precedence the zh path always had: curated > schema title > key.
- `systemConfigI18n.ts` - English option labels for `AGENT_CONTEXT_COMPRESSION_PROFILE`; the
  backend ships those three option labels in Chinese only.
- `reportLanguage.ts` - `fullReport` was `'Full Analysis Report'` while the UI button is
  `home.fullReport` = `'Full analysis report'`. Aligned to sentence case.
- `ChatPage.tsx` - English alternatives added to `STRONG_COMPARE_STOCK_MESSAGE_RE` and
  `SWITCH_STOCK_MESSAGE_RE` (compare / switch intent now works for English input). The
  lowercase-ticker hint regex in `chatStockCode.ts` was **deliberately left Chinese-only**:
  in English prose every short lowercase word ("in", "depth") becomes a ticker candidate and
  the follow-up prompt "Analyze X in depth" produced `stock_code: "DEPTH"`. That heuristic
  only makes sense in a CJK context.
- `PortfolioPage.tsx:586` - display template `已提交 ${symbol} 分析任务：${taskId}` that F3
  missed, now English.
- `DesktopUpdateIndicator.tsx` - native `title=` on the trigger button (guarded against by
  `tests/ui_governance.test.ts`) replaced with the shared `Tooltip`; its test now hovers and
  reads `role="tooltip"`.

### Test-side decisions worth knowing

- **Mapping collisions.** Tests of the form "renders X in English mode" asserted the Chinese
  copy was *absent*; the bulk map turned the Chinese into the same English the test asserts
  *present*, making the test self-contradictory. Those `queryByText(...).not.toBeInTheDocument()`
  lines were deleted (ChatPage status copy, TokenUsage, Backtest, MarketReview, MarketStructure,
  Portfolio drawdown/Sell, AlertRuleForm/List drawdown, AgentBackend, Copy Markdown Source).
- **`\uXXXX` escapes hid Chinese from every earlier pass** (LLMChannelEditor, HomeStockWorkspace).
  `uesc.py` finds them; there are none left in `src/` or `tests/`.
- **ko is retired at the API surface.** `reportLanguage.test.ts` now asserts the en lock
  (`normalizeReportLanguage('ko') === 'en'`), `MarketStructureCard` "Korean labels" asserts
  English output for `language="ko"`.
- **Dropped one test:** AlertRuleForm "shows JP/KR options for market region in Chinese UI
  mode" - zh mode no longer exists and the en-mode behaviour (JP/KR hidden) is asserted by the
  sibling test.
- **Fixture data kept Chinese where the backend still sends Chinese** (stock names, news
  titles, server error messages, run-flow node labels). Only expectation text changed.
- **`SettingsPage.test.tsx` mocks `components/settings`** with literal stubs; the stubs were
  Chinese, so three "English" failures were the test's own mock, not the product.
- **`DecisionSignalsPage.test.tsx` had a time bomb**: fixture `createdAt: '2026-06-17'` fell
  outside the 90-day timeline window on 2026-09-20. Fixture dates are now relative to `Date.now()`.
- **Same-name buttons after translation** ("Log out" nav + dialog confirm, "Delete account",
  "History" mobile trigger, channel row named `primary` vs the "Primary model" select) are
  disambiguated with `getAllByRole(...).at(-1)`, an `aria-label` filter, or an anchored regex.
- The recovery-title comparison in `StockScreeningPage.tsx:145` is against the *frontend*
  mapper's title (`src/api/error.ts:359`), so translating it in F3 was correct; the test
  fixture had to follow.

### Still open after F5

- F2 (delete dormant zh/ko halves) and F4 (translate LLM system prompts) untouched; III.6
  risks R8/R14 unchanged. `tests/system_config_i18n.test.ts` and `settingsHelp.test.ts` still
  assert the zh data on purpose until F2.
- F6 minimal step (backend `REPORT_LANGUAGE` default -> `en`) not done; new reports still
  carry Chinese narrative.
- AGENTS.md screenshots for the PR not produced.
- Casing is still mixed between curated help titles (Title Case) and component labels
  (sentence case), e.g. button "View Runtime capability checks configuration help" opens a
  dialog titled "Runtime Capability Checks". Cosmetic; left as is.

## III.13 F6 minimal step - backend REPORT_LANGUAGE default is now `en` (2026-09-20)

**What changed (user-facing default only):**

- `src/report_language.py` - `normalize_report_language(value, default="en")`; unknown or
  empty values now resolve to `en`.
- `src/config.py` - `Config.report_language` dataclass default `"en"`; `_resolve_report_language_env_value`
  falls back to `"en"` when neither `.env` nor the process env sets `REPORT_LANGUAGE`;
  `_parse_report_language` falls back to `en` for invalid values (warning text updated).
- `src/core/config_registry.py` - `REPORT_LANGUAGE.default_value = "en"` (this is what the
  Settings UI shows as the schema default); examples list `en` first.
- `.env.example` - commented example is `REPORT_LANGUAGE=en`.

**What deliberately did not change:** the ~60 internal per-call fallbacks
(`getattr(result, "report_language", "zh")`, `report_language: str = "zh"` parameter defaults,
`ctx.meta["report_language"] = "zh"`). A first pass flipped them too and produced 83 new backend
failures, all unit tests that call renderers / prompt builders without a language and assert the
Chinese output. That is the backend half of F5 (III.4 phase 5) and was reverted here to keep F6
minimal. In production every path receives the language from `Config`, so new reports come out in
English; the fallbacks only matter for callers that pass nothing.

**Also unchanged:** an explicit `REPORT_LANGUAGE=zh|ko` in `.env` or a request body is still
honoured (D11 - dormant, not removed). The hard lock at the chokepoint (III.4 phase 1 "rejects
zh/ko") is still a separate decision.

**Validation:** backend suite `-m "not network"`: baseline 87 failed / 6,718 passed -> after F6
89 failed / 6,718 passed, and the set-difference is one flaky test in
`tests/test_local_cli_backend.py` (process-group kill) that flipped in both directions between
runs; the 87 baseline failures are pre-existing environment failures (Codex app-server gate,
local CLI backend, agent backend status, storage concurrency, packaging). `flake8 --select=E9,F63,F7,F82` 0.
Frontend untouched by this step.

**Tests retargeted (19):** `test_agent_pipeline.py`, `test_analysis_api_contract.py`,
`test_backtest_service.py`, `test_decision_signal_service.py`, `test_report_schema.py` - only
*derived* labels (`action_label`, `trend_prediction`, backfilled `analysis_summary` /
`stop_loss`) changed to English (`Watch/Buy/Hold/Avoid/Sell/Reduce`, `Bullish`, `TBD`); pass-through
`operation_advice` values that come straight from the fixture stay Chinese.
`test_market_strategy.py::test_cn_prompt_contains_strategy_plan_section` now pins
`report_language="zh"` exactly as its `us` sibling pins `en`. `test_report_language.py` asserts the
`en` fallback for unknown / None.

**Rollback:** `<scratchpad>/snap-f6` holds the *post-F6* copies of the 4 source files and 7 test
files listed above (a green reference, not a pre-change backup). To undo F6, change the four
`"en"` defaults in `report_language.py`, `config.py` (3 sites) and `config_registry.py` back to
`"zh"` and revert the 19 assertion lines; replay forward is `f6_default_en.py` then
`f6_revert_internal.py` plus the inline test fixes recorded here.

**Left open after F6:** existing stored reports keep their Chinese narrative (R-F3); the LLM base
prompts are still Chinese (F4) so English output relies on the "Output Language" override block;
`docs/CHANGELOG.md` `[Unreleased]` entry and AGENTS.md screenshots not produced.

*Update 2026-09-27: the ~60 internal `"zh"` fallbacks are resolved (III.14) and the
`[Unreleased]` changelog entries now exist for every step since.*

## III.14 Report-language fallbacks follow `REPORT_LANGUAGE` (2026-09-24, `8d7615d`)

Closes the III.13 gap: about 80 internal call sites fell back to a literal `"zh"` when no
language was passed, so any path that dropped the language produced Chinese in an English
deployment.

- **Helpers** in `src/report_language.py`: `get_default_report_language()` (the configured
  `REPORT_LANGUAGE`, `en` if config is unavailable; lazy import because `src.config` imports this
  module) and `resolve_report_language(value)` (keeps a valid explicit value, otherwise the
  configured default).
- **Rewritten:** `getattr(..., "report_language", "zh")` and `.get("report_language", "zh")`
  lookups; ~36 `language: str = "zh"` parameter defaults (now `Optional[str] = None`, resolved on
  the first line); the `AnalysisResult` and two `share_image` poster dataclass defaults
  (`default_factory`); the orchestrator meta fallback.
- **Deliberately unchanged:** the `lang="zh"` calls inside the Chinese-only prompt branches
  (`analysis_context_pack_prompt.py`, `market_phase_prompt.py`) and `Article(language='zh')` in
  `search_service.py` (newspaper3k tokenizer, not the report language).
- **`empty_news_disclosure` keeps raising on an unsupported language**; it only falls back when
  no language is given (`resolve` would have hidden that contract).
- **Tests:** ~100 tests asserted Chinese output without passing a language. They were not
  rewritten; they opt in to a new fixture, `zh_report_language_default` in `tests/conftest.py`,
  which sets `REPORT_LANGUAGE=zh` on the env and the config singleton.

## III.15 English API, progress, CLI and sender text (2026-09-24 to 2026-09-27)

Split into batches by risk. Every batch was validated by a full-suite set difference against a
`HEAD` worktree baseline; only assertions were retargeted, never test inputs.

| Batch | Commit | Scope | Coupling handled |
|---|---|---|---|
| A - OpenAPI docs | `cf0bcc9` | ~520 `description=` / `summary=` / response descriptions in 13 `api/` files; report-content schema examples now English | `docs/architecture/api_spec.json` is a **hand-maintained subset** of the runtime spec with pre-existing structural drift (14 paths / 24 schemas differ, 8 entries missing). The same translation map was applied to its text in place; every entry kept its previous match status. **Do not regenerate it wholesale from the runtime spec** - that would silently absorb the drift. |
| B - API runtime messages | `a6f9b87` | Error `message`/`detail` values, task/batch/watchlist/screening messages, admin-auth errors, Agent Chat tool labels, market-review task name (`Market Review`), Settings notification-test defaults, and `src/services/task_queue.py` status messages | Error codes and HTTP statuses unchanged. No frontend/bot/backend code matches these messages by text (checked). 10 assertions retargeted. |
| C - progress / run-flow / CLI / senders | `2aa77fb` | `run_flow.py`, `run_diagnostics.py`, pipeline SSE progress and logs, `main.py --help` and logs, `webui.py`, all 14 notification senders (logs, default report title / email subject `📈 AI Stock Analysis Report - <date>`, Discord username) | Frontend `RunFlowEventList` filters lowercase-match `fallback|retry|cancel`, so English still matches; the edge label `Invoke` now matches the existing Web i18n key. One source-window test (`test_count_set_to_zero_once_search_is_attempted`) was widened 600 -> 800 chars because the English log line is longer (R3). 33 assertions retargeted. |
| Analyzer progress | `98e6f9c` | The four `GeminiAnalyzer.analyze` progress messages | Two assertions retargeted. |

**Deliberately still Chinese after these batches** (not missed):

- Text sent to the LLM: base system prompts, `_format_prompt`, the agent task prompt, volume/trend
  descriptions and the local news evidence block in `pipeline.py` - this is F4, gated on III.16.
- Parser vocabulary: placeholder markers in `pipeline.py` (`未知`/`待补充`/`数据缺失`/`无`), the
  internal `股票{code}` placeholder name and its `startswith("股票")` check, the `"观望"`
  canonical inputs.
- Report headings written by `main.py` into merged notifications / Feishu docs (`# 📈 大盘复盘`,
  `# 🚀 个股决策仪表盘`) - report content, left for a language-aware change.
- The `EMAIL_SENDER_NAME` default (`daily_stock_analysis股票分析助手`) - quoted in docs; change with them.
- ~585 CJK lines remain in `src/analyzer.py` (prompts + logs), and there are still Chinese logs in
  `data_provider/` and other services; logs outside the files above were not in scope.

## III.16 Prompt-language eval (2026-09-27, `953a1fe`)

Implements option A of III.7 (R8). Code in `evals/prompt_language/`, doc in
`docs/prompt-language-eval.md`.

- `capture_fixtures.py` runs the real data pipeline for the 30 samples in `samples.json`
  (10 CN / 10 HK / 10 US) and records exactly what `GeminiAnalyzer.analyze` receives. No LLM call,
  no notifications, throwaway DB. A fixture is kept only if the prompt rebuilt from its JSON is
  byte-identical to the live prompt; the SHA-256 is stored and re-checked on replay.
- `run_eval.py` replays fixtures per prompt variant with `report_integrity_enabled=False` (so it
  scores the model's **first** answer), several repeats each. Without `--run` it only validates and
  prints the call plan; `--run` also needs `--max-calls N` covering the plan.
- `metrics.py` (pure): JSON / contract / integrity validity, decision distribution, advice vs
  `decision_type` consistency, English share (CJK share of text values, `stock_name` exempt),
  run-to-run noise floor, and per-sample agreement against the baseline.
- `variants.py`: `current` is the shipped prompt and the baseline. F4 must register its English
  prompt here as a context manager and compare it against `current`.
- Fixtures are git-ignored (market data and third-party news text).

**Status: built and tested offline (11 tests); never run against a model.** Two fixtures were
captured as a smoke test (600519, AAPL) and validate. This machine has no search keys, so
`news_context` was empty - capture must run where production's search keys are configured.

## III.17 Decisions taken 2026-09-24 to 2026-09-27

| Decision | Detail |
|---|---|
| **Git on** | Reverses D3. Tree imported as `16b0d47`; every later step committed and pushed only after the user confirmed. |
| **Python 3.11 for this project** | The copied `.venv` targeted 3.11 but the machine had only 3.14. On 3.14 every requirement installs and imports except `tiktoken>=0.8.0,<0.12.0` (the first 3.14 wheel is 0.12.0; the pin exists for issue #537). The user chose to install 3.11 rather than move the project to 3.14. |
| **F2 stays deferred** | The dormant zh/ko halves of the frontend i18n data are left as is (D11). Example: `ReportDiagnostics.tsx` `TEXT.zh.scope` looks untranslated but is unreachable because `normalizeReportLanguage()` always returns `'en'`. Do not delete zh entries piecemeal; if F2 is ever done, do the whole frontend at once and update `system_config_i18n.test.ts` / `settingsHelp.test.ts`. |
| **Prompt eval before F4** | III.7 option A adopted and built (III.16). Running it needs the user's production LLM key, search keys and a call budget (~90 calls for the baseline, ~180 for a current-vs-English comparison). |

## III.18 Windows test stabilisation (2026-09-27, `5dc71e6`)

Took the offline suite on Windows from **85-90 failures per run (varying)** to **0 failures, twice
in a row** (6,783 passed / 65 skipped). CI runs backend tests on `ubuntu-latest` only; the Windows
CI job only builds the package, so none of this was visible in CI.

**Product fix - `src/llm/local_cli_backend.py` (Windows only):**

- `_terminate_process_group` now force-kills the whole process tree with `taskkill /T /F`
  (`_taskkill_tree`) **before** CTRL_BREAK / terminate, while the root still exists. The old
  CTRL_BREAK-first order let the root exit and orphan descendants. This reverses the behaviour
  pinned by the old `test_windows_terminate_process_group_prefers_ctrl_break`, which was renamed
  and updated.
- The per-run working directory uses `_local_cli_workdir()`: removal is retried briefly and a
  failure is logged, not raised. Previously a `PermissionError` from cleanup replaced the run's
  real error and surfaced as `process_start_failed`.

**Test changes, by cause:**

| Cause | Tests | Fix |
|---|---:|---|
| Codex App Server / tool process need POSIX process groups; the product rejects native Windows (`is_native_windows()`) | 58 | `skipif(os.name == "nt")`: module-level in `test_codex_app_server_gate_a.py` / `test_codex_tool_process.py`, per test in `test_agent_backend_status_service.py` / `test_system_config_api.py` |
| `with sqlite3.connect()` does not close; engine not disposed before temp dir removal | 10 | New `tests/sqlite_helpers.py` (`sqlite_connection`, `temporary_database_dir`); one teardown reordered |
| Mock CLIs wrote locale-encoded, `\r\n` output | 8 | `_MOCK_CLI_PRELUDE` in `test_local_cli_backend.py` pins UTF-8 and `\n` |
| `os.kill(pid, 0)` terminates the process on Windows | 3 | `_process_exists()` (OpenProcess + WaitForSingleObject) |
| UTC values written into the local-time `AnalysisHistory.created_at` | 2 | Use local time (identical on UTC CI) |
| Windows monotonic clock ~15.6 ms > 5 ms sleep | 1 | 20 ms sleep |
| Test assumed `bash` = WSL (`/mnt/c`); here it is Git Bash (`/c`) | 2 | Detect the bash flavour via `uname -s` |
| Scheduler polling bounds too tight; a timeout test started a background AkShare lookup | 2 | `_PROCESS_WAIT_SECONDS = 20`; stub `_apply_timeout_partial_outcome` in that test |
| POSIX permission bits | 1 | `0o600` / `0o700` assertions only off Windows |

## III.19 Open items and next steps (updated 2026-09-29)

In priority order. Items 1-4 need no model key.

1. **Check CI.** Nothing pushed since 2026-09-24 has had its GitHub Actions result looked at (`gh` is not
   installed here). Open the Actions tab of `sayaara/dsa` and confirm `ai-governance` (fixed by `bccc96a`),
   `backend-gate`/`backend-tests`, and `web-gate` are green. The backend tests only run on Windows locally and
   on `ubuntu-latest` in CI; that gap is unverified.
2. ~~Bot replies~~ **Done** in `bac0b3a` (III.21). Still open around the bots: the Chinese log lines in
   `bot/`, and the LLM-facing intent prompt in `bot/dispatcher.py` and the agent message in `bot/commands/ask.py`
   (both belong with F4).
3. ~~Settings schema text~~ **Done** in `4c3978b` (III.22). Not done there: nobody opened a running Settings
   page, so the check was static (backend schema + frontend maps), not visual.
4. ~~Guard tests promised in III.7~~ **Done**: the strategy half (R13) in `c950088` (III.24) and the retired-language
   half (R14) in `83c02b0` (III.25). Both follow-ups are fixed: the two Korean labels with a Chinese character in
   `36eb462` (III.26) and the three strategy display names the report language map did not know in `22b778a` (III.27).
5. **Prompt eval baseline** (III.16) once the user adds production LLM and search keys to `.env`: capture 30
   fixtures, then `run_eval.py --run --repeats 3 --max-calls 90 --json-out prompt_eval.json`.
6. **F4 - translate the prompts** only after the baseline exists (register the English variant in
   `evals/prompt_language/variants.py`, compare against `current`, ship only within the measured noise floor).
   This covers `src/analyzer.py` (~6.7k string chars), `src/agent/executor.py` (~4.3k),
   `src/market_analyzer.py` (~2k), `src/core/market_strategy.py` (~1.3k) and `strategies/*.yaml`
   `instructions:` blocks.
7. **Smaller known gaps:**
   - Playwright e2e specs still force `locale: 'zh-CN'` and seed `dsa.uiLanguage='zh'` (`playwright.config.ts`,
     `e2e/*.spec.ts`); they are skipped without `DSA_WEB_SMOKE_PASSWORD`.
   - ~~`src/desktop/updateState.ts:70` full-width parentheses~~ fixed in `41d6d24` (III.23).
   - A background AkShare name lookup can still log at the end of `test_runtime_scheduler_service.py`; the
     offline HTTP block does not reach subprocesses.
   - Chinese **logs** remain in `data_provider/` and services not covered by III.15 (low value).
   - ~~Other frontend pages were not scanned for live Chinese~~ Scanned in III.23 with a source-level guard
     (`apps/dsa-web/tests/no_chinese_ui_source.test.ts`). It is a static ratchet, not a per-page render test:
     it cannot tell live text from dormant text, and it does not render anything. Rendering every page still needs
     per-page API mocks; the pattern is `PortfolioPage.test.tsx`.
   - Test isolation weakness: `get_default_report_language()` reads the shared config singleton, which some
     tests leave changed, so a test that relies on the default can pass alone and fail in the full suite.
     New tests should set the language explicitly (III.20).
8. **Assessment-report items still open** (`E2E_ASSESSMENT_REPORT.md`): `ErrorHandlerMiddleware` is dead code
   (`api/app.py` never registers it), the Discord platform is unregistered, `network-smoke` has
   `continue-on-error` on both steps, no Alembic, a narrow flake8 gate, stale `ci-test-durations.json`,
   duplicated helpers, giant modules. See III.20 for which of its findings are already closed.
9. `updated_product_overview.md`, `E2E_ASSESSMENT_REPORT.md` and `MIGRATION_REPORT.md` are dated reports
   (2026-09-19/20). Treat them as history, not current state.

## III.20 Session 2026-09-28 to 2026-09-29

### Fixes made (all committed and pushed; see the commit table at the top)

| Commit | Cause | Fix |
|---|---|---|
| `49df11a` | `LocalCliGenerationBackend` wrote `prompt.txt` in text mode, so on Windows every line reached the CLI as `\r\n` (the III.19 gap) | `write_text(..., newline="")` in `src/llm/local_cli_backend.py`; regression test in `tests/test_local_cli_backend.py`. Also joined a `[test]` changelog entry that a real line break had split in two. |
| `32e411d` | **Real product bug.** `get_conversation_history` and `get_conversation_messages` ordered by `created_at` only, so two messages saved in the same clock tick could return in reversed order. Showed up as a flaky `test_storage` failure (~1 in 4 alone). | Both queries now also order by `id`, matching `get_visible_conversation_messages` (`src/storage.py`). New test forces identical timestamps and covers all three fetch methods plus the `limit` case; it fails on the old code. |
| `b0addd7` | `test_bounded_topic_search_provider_receives_only_remaining_deadline` asserted `<= 0.2`, but the deadline is `start + 0.2` on a large monotonic value, so when the clock had not ticked the difference was `0.20000000000004547`. Failed every time on this machine, also on the previous commit. | Test-only: tolerance of `1e-6` and a comment. The product code was correct. |
| `c90cc1a` | `main.py` wrote hard-coded Chinese headings into the merged notification and the Feishu cloud document | `_MERGED_REPORT_HEADINGS` + `_merged_report_headings(config)` follow `REPORT_LANGUAGE`: English by default (`# 📈 Market Review`, `# 🚀 Stock Decision Dashboard`, doc title suffix `Market Review`); an explicit `zh` keeps the old headings; `ko` uses English. The reused market-review title no longer falls back to Chinese for `ko`. Tests set the language explicitly and one test pins en / zh / ko / both defaults. |
| `bccc96a` | Git stored `CLAUDE.md` as a plain 9-byte file (mode 100644) after the import. `scripts/check_ai_assets.py` requires a symlink, so the blocking `ai-governance` job on Ubuntu would fail and, since `backend-tests` lists it in `needs`, gate the backend jobs. | Index entry changed to mode `120000` on the existing blob (content `AGENTS.md`). The local check still errors on Windows because `core.symlinks=false`; that is expected. **Unverified in CI.** |
| `54cd586` | `PortfolioPage.tsx` still had ~100 lines of live Chinese (forms, warnings, CSV import, event log, delete confirmations). F3 missed it and later notes never mentioned it. | 91 phrases translated (whole-phrase, longest-first, with a residual-CJK scan as the safety net); the dormant `zh` label block at lines 86-96 was left alone (F2 policy). `formatBrokerLabel` now uses English names for `huatai`/`citic`/`cmb` because **the backend sends Chinese `display_name`s** ("华泰", "中信", "招商"); ASCII parentheses. New test `renders no Chinese UI chrome in the English page, including the entry forms` fails on the old page. |

### Review of the two dated reports against the current tree

`E2E_ASSESSMENT_REPORT.md` (2026-09-20) findings, re-checked:

- **Closed:** unmasked config secrets, open `/docs`, Docker `0.0.0.0` bind (compose now binds `127.0.0.1` via
  `API_BIND_HOST`), SSRF to private ranges (blocked unless `LLM_ALLOW_PRIVATE_BASE_URLS`; loopback stays
  allowed), no git, tests writing to the real DB and hitting the network (`tests/conftest.py`), the ~60
  internal `"zh"` fallbacks (the 28 remaining `"zh"` strings are real `language == "zh"` branches), the noisy
  Windows baseline, OpenAPI / API message / run-flow / progress / CLI / sender text, and G1 (Portfolio page).
- **Still open:** everything listed in III.19 items 2-8.
- **New, not in either report:** the `CLAUDE.md` mode problem, the bot replies, the storage ordering bug.

`MIGRATION_REPORT.md` (Part I): its claims hold (AST/token equivalence over 210 files, 396 preserved-literal
residual lines). Its "not a git repo" and "87 failed" notes are dated. Nothing in it needs redoing.

### Verification state at the end of the session

| Gate | Result |
|---|---|
| Backend `pytest -m "not network"` | 6,786 passed / 65 skipped / 0 failed (run after `c90cc1a`; `54cd586` is frontend-only) |
| Frontend `tsc` / `lint` / `build` | 0 errors / 0 errors + 2 baseline warnings / passes |
| Frontend `vitest` (full, parallel) | 1,201 passed / 4 timeouts in `HomePage` + `DecisionSignalsPage`; both pass alone |
| CI on GitHub | **not checked** |
| PR screenshots (`AGENTS.md`) | **not produced** for the Portfolio change or the F1/F3 UI changes |

### Things to keep in mind

- **Commit rules.** `AGENTS.md` forbids `Co-Authored-By` and requires explicit confirmation before commit and
  push. The tooling for this session also suggests a `Co-Authored-By` trailer; the repository rule wins and
  none was added. Every commit above was made only after the user said so.
- **Default-language tests.** Set `report_language` explicitly in the test config, or patch
  `src.report_language.get_default_report_language`. Relying on the default worked alone and failed in the full
  suite (an earlier test leaves the config singleton on `zh`).
- **Byte-level edits on Windows.** Detect CRLF before matching text in `docs/CHANGELOG.md` or source files, and
  build a literal backslash with `chr(92)`: a `\\n` typed in a shell heredoc did not survive the tool layer
  and produced real newlines twice.
- **The CHANGELOG `[Unreleased]` section** is still flat, one `- [type] description` per line, English types.

## III.21 Bot replies (2026-09-30, `bac0b3a`)

`bot/` carried ~2,300 CJK characters that no earlier batch covered (III.15 handled API, progress, CLI and
sender text, not the chat bots). The reply text a chat user reads is now English.

**Scope decisions**

- **Fixed English, not `REPORT_LANGUAGE`-dependent.** Bot replies are interface chrome, like the frontend, which
  is locked to English regardless of the report language.
- **Translated:** the output of `/help`, `/analyze`, `/ask`, `/batch`, `/market`, `/chat`, `/research`,
  `/history`, `/status`, `/strategies`; every command `description` and `usage` (shown by `/help`); the
  dispatcher's error replies (unknown command, rate limit, admin-only, greeting, command failure); the
  `BotResponse.error_response` prefix (`❌ Error: ...`); DingTalk card titles (`Stock Analysis Assistant`); the
  DingTalk / Feishu Stream startup errors; and `ReportType.display_name` in `src/enums.py`
  (`Simple report` / `Full report` / `Brief report`), which only `/analyze` used.
- **Deliberately unchanged:** command aliases and keywords (`分析`, `大盘`, `full`/`完整`/`详细`, `清除`,
  `激活`), the intent pre-filter and cleanup regexes in `bot/dispatcher.py`, the full-width comma handling in
  `/ask` argument parsing, the `理想买入点：` / `止损位：` prefixes that `/ask` strips from model output, the
  Chinese examples inside the intent-parsing prompt, the Chinese message `/ask` sends to the agent
  (`请分析股票 ...`), log lines, docstring examples, and stock / strategy names (data). `/help` still lists
  the Chinese aliases and the example `奕帆传动` on purpose.
- **Method:** whole-phrase replacement, longest first, applied only to reply lines (log lines, comments and
  bracket-tagged log arguments skipped), with every phrase required to match at least once. Replayable
  scripts were in the session scratchpad, which is temp storage and not kept.

**Tests**

- About 47 assertions retargeted in `test_bot_analyze_command.py`, `test_bot_status_command.py`,
  `test_bot_market_command.py`, `test_bot_dispatcher_async.py`, `test_ask_command.py` and one in
  `test_multi_agent.py`; assertion strings only, never fixtures or inputs.
- **Lesson:** a phrase grep for coupled tests missed `test_multi_agent.py` (it asserted `超时` on the `/research`
  timeout reply). Only the full suite found it. Run the full suite after any reply-text change.
- New `tests/test_bot_reply_language.py`: every command's description and usage, the unknown-command and rate-limit
  replies, and the `/help` overview and detail replies contain no Chinese apart from aliases and the data literal.
  It fails on the old code (checked by stashing `bot/` and `src/enums.py`).

**Not verified:** nothing was exercised against a live DingTalk, Feishu or Discord bot, so the platform-side
rendering of the new titles and errors is unchecked. CI was not looked at (no `gh` here).

**Still open in this area:** the Discord platform is implemented but not registered
(`bot/platforms/__init__.py`), and `bot/` log lines are still Chinese.

## III.22 Settings schema text and service messages (2026-09-30, `4c3978b`)

III.19 item 3 asked which Settings strings the English UI still showed in Chinese. The answer came from tracing
how `SettingsField.tsx` / `SettingsHelpButton.tsx` resolve text and from dumping the live schema
(`build_schema_response()`: 188 fields, 8 categories), not from a running page.

**Findings**

- **Already covered:** all 188 fields have an English help entry (122 help keys, one-to-one between the
  English and Chinese maps), so the English help text shadows the backend description. No category title or
  description had Chinese.
- **Leak 1 - related-docs chips (~237 labels, 33 distinct).** `SettingsHelpButton.tsx:110` prefers
  `schema.docs` from the backend over the English `help.docs`, so labels such as
  "完整指南：环境变量完整列表" showed in Chinese even though the linked docs are English now.
- **Leak 2 - option labels.** `fieldOptionLabelMapEn` had no entry for `FEISHU_RECEIVE_ID_TYPE` or
  `FEISHU_DOMAIN`.
- **Leak 3 - `SystemConfigService` messages (~130 lines).** These reach the Settings page after saving,
  testing a channel or importing a `.env`: save / restart notices, import errors, model / Agent / watchlist /
  database setup checks, notification test results, and the **default test-notification title and body, which
  are sent to real channels**. The frontend does not match on any of this text.

**Fix (all at the backend source, no frontend change)**

- `src/core/config_registry.py`: 33 doc labels, the Feishu and context-compression option labels (the
  compression labels use the same wording as the frontend English map), the Futu HK title and description, the
  three `ANTHROPIC_*` descriptions and `ServerChan3`.
- `src/services/system_config_service.py`: 108 phrases. Adjacent string fragments were given explicit
  trailing spaces so the concatenated messages read correctly. Setup-check titles are now `LLM primary channel`,
  `Agent channel`, `Watchlist`, `Notification channels`, `Database / local storage`; they are display text, and
  nothing in the code matches on them (checked). The check ids (`llm_primary`, ...) are unchanged.
- **Deliberately unchanged:** the two `FEISHU_WEBHOOK_KEYWORD=股票日报` examples (literal config values), and in
  the service the regexes with a full-width colon and the `请求被拦截` token, which recognise error output.
- Tests: 2 option-label assertions and about 44 assertion / filter lines in `test_system_config_api.py` and
  `test_system_config_service.py` (the `title="DSA 通知测试"` lines are test inputs and were left). New
  `tests/test_settings_schema_language.py` walks the live schema and parses the service source with `ast`;
  it fails on the old code.

**Not verified:** no running Settings page was opened; CI was not looked at. The frontend was not touched and its
tests were not re-run (they use their own fixtures).

**Still open in this area:** the dormant Chinese halves of `settingsHelp.ts`, `systemConfigI18n.ts` and `uiText.ts`
(F2, deferred), and `docs/CHANGELOG.md`, which stays frozen.

## III.23 Frontend source guard and full-width punctuation (2026-09-30, `41d6d24`)

III.19 asked for a check of the other frontend pages after the Portfolio leak. A scan of every non-test file under
`apps/dsa-web/src` found 27 files with Chinese (2,473 lines). Almost all of it is intentional; a few lines were live
leaks.

**What the scan showed**

- **Dormant zh/ko halves** of `Record<UiLanguage, ...>` maps: `uiText.ts`, `settingsHelp.ts`, `systemConfigI18n.ts`,
  `featureText.ts`, `reportLanguage.ts`, `AnalysisContextSummary.tsx`, `MarketStructureCard.tsx`,
  `ReportDiagnostics.tsx`, `ReportNews.tsx`, `marketPhase.ts`, `types/analysis.ts` and the `zh:` labels in
  `PortfolioPage.tsx`. Unreachable while the language is locked to `en` (F2, deferred).
- **Matchers** against backend or model text, which must stay: `decisionAction.ts`, hotspot names and the
  `DSA行情` markers in `StockScreeningPage.tsx`, chat intent regexes, `api/error.ts` token lists, the `市场阶段` prefix
  strippers, `MarketReviewReportView.tsx`, `ReportOverview.tsx`, `RunFlowEventList.tsx`, and example stock names in
  `ChatPage.tsx` (data).
- **Live leaks: full-width punctuation** in English UI text. Fixed: hotspot summaries and leader lists in
  `StockScreeningPage.tsx` (`，` `。` `：` `、` now `, ` `.` `: `), `api/error.ts` (`title: message`),
  `AlertTriggerHistory.tsx` (`'; '`), `agentChatStore.ts` (multi-skill names joined with `', '`) and
  `desktop/updateState.ts` (`（42%）` now ` (42%)`). Tests retargeted: 4 lines in `StockScreeningPage.test.tsx`
  and 2 in `agentChatStore.test.ts`.

**The guard** (`apps/dsa-web/tests/no_chinese_ui_source.test.ts`)

- Every non-test source file must contain no Chinese or full-width punctuation unless it is on an allowlist. Each
  allowlisted file has a maximum line count and a reason (`dormant`, `matcher` or `comment`).
- Three tests: no unlisted file has Chinese; no listed file exceeds its number; no listed file is below its number
  (so a cleaned-up file cannot regress silently, and the numbers must be lowered when a file shrinks).
- It fails on the pre-fix source (checked by stashing the five source files) and passes now.
- **Limits:** it counts lines, so new Chinese added to a file that already has an allowance is caught only if it
  pushes the count above the number. It does not render anything and cannot tell a live string from a dormant one.
  When a change legitimately adds a matcher or dormant entry, raise the number and say why in the review. When F2
  removes the dormant maps, lower the numbers to match.
- Gotcha: ESLint's `no-irregular-whitespace` also flags the ideographic space (U+3000) inside a regex literal, so
  the pattern in the test uses `\u` escapes. A tool round trip once turned them into literal characters; check
  the file if lint reports an irregular-whitespace error there.

**Not verified:** no running app was opened; CI was not looked at.

## III.24 Strategy alias guard tests (2026-09-30, `c950088`)

Implements the R13 mitigation from III.7: `strategies/*.yaml` is deliberately half-Chinese after the English
migration (English `instructions:` to come with F4, Chinese `aliases:` and `display_name:` forever), and that looks
like unfinished work to the next reader.

- **Why the aliases matter:** `bot/commands/ask.py` `_parse_skill` selects a strategy by finding a strategy's id,
  `display_name` or any alias as a substring of the user's message, longest first. Translating an alias silently
  stops Chinese input from selecting that strategy.
- **Header note** added to all 15 YAML files (a comment only; `yaml.safe_load` ignores it, nothing else reads the
  comments): "`aliases` and `display_name` are intentionally Chinese ... Do not translate them."
- **`tests/test_strategy_aliases_guard.py`** (6 tests):
  1. Every strategy file loads (guards against a strategy silently disappearing).
  2. Ids are ASCII identifiers; every `display_name` and at least one alias contains Chinese.
  3. With a neutral default skill, every id, display name and alias resolves to its own strategy in
     `AskCommand._parse_skill` (no cross-matches).
  4. Fifteen Chinese phrases users type (`请用缠论分析`, `均线金叉`, `一阳穿三阴`, ...) each select the expected
     strategy. This is the test that fails if an alias is translated; test 3 alone would pass, because a translated
     alias still matches itself (checked by translating `chan_theory` in a temp copy).
  5. Every strategy localizes to English by id through `report_language.localize_strategy_skill`.
  6. Every file carries the note.
- **Finding (fixed in III.27):** the older claim that `display_name` "keys into the `report_language.py` map" was true for
  12 of the 15 strategies; `缠论`, `龙头策略` and `一阳夹三阴` were not keys. The test first pinned them as a known gap
  (`DISPLAY_NAMES_NOT_IN_REPORT_MAP`); that set no longer exists.
- Backend suite after this: 6,797 passed / 65 skipped / 0 failed. CI was not looked at.

## III.25 Dormancy tests for the retired languages (2026-09-30, `83c02b0`)

Implements the R14 mitigation from III.7: the zh / ko code paths are dormant, not deleted (D11), and untested dormant
code rots. The retirement is **not uniform**, so each layer asserts what is actually true of it:

- **Frontend: unreachable.** The UI language is locked to `en` (`utils/uiLanguage.ts`,
  `contexts/UiLanguageContext.tsx`, `utils/reportLanguage.ts`).
- **Backend: reachable on request.** An explicit `REPORT_LANGUAGE=zh|ko` (or a request body value) is still honoured,
  so those tables must keep working. Only the *default* is English.
- **English by design, whatever the setting:** bot replies, `ReportType` names, Settings schema and service messages.

**`apps/dsa-web/tests/retired_ui_languages.test.tsx`** (6 tests)

1. `resolveInitialUiLanguage` returns `en` for every stored value (`zh`, `ko`, `en`, junk, none) and every browser
   language.
2. With `dsa.uiLanguage=zh` stored, `UiLanguageProvider` still reports `en`, sets `<html lang="en">`, and a
   `setLanguage('zh')` call changes nothing.
3. No `UiLanguageToggle` component exists or is referenced anywhere in `src`.
4. `normalizeReportLanguage` returns `en` for `zh`, `ko`, `en`, `zh-CN`, junk, empty and null.
5. `UI_TEXT.en` contains no Chinese or Korean, except the native short name `language.short.zh`, an unused key left
   from the removed toggle.
6. The `en` side of every `{zh, en}` table exported from `locales/featureText.ts` contains no Chinese or Korean.

**`tests/test_retired_languages_dormancy.py`** (4 tests)

1. All 15 localization tables in `src/report_language.py` (found by shape, not by name) keep all three languages in
   every entry, with no empty text, and `_REPORT_LABELS` has identical key sets in zh, en and ko (133 each).
2. Each language keeps to its own script: no Han or Hangul in `en`, no Hangul in `zh`, no Han in `ko`.
3. An explicit `zh` / `ko` still renders its language (`get_report_labels`, `localize_operation_advice`).
4. With `REPORT_LANGUAGE=zh` (the `zh_report_language_default` fixture), bot replies and `ReportType` names stay English.

**Finding, since fixed (III.26):** two Korean labels contained a Chinese character, `매출 전년比` and
`순이익 전년比`. The test first pinned them as known exceptions; `36eb462` fixed them and removed the exception
list, so every Korean label must now be free of Han characters.

**Checked to bite:** breaking the lock (`UI_LANGUAGE = 'zh'`) fails two frontend tests; removing a language from a
table and putting Hangul into an English label (and, while the exception list existed, fixing a listed Korean label without updating it) each fail a
backend test.

**Not covered:** the frontend dormant maps beyond `UI_TEXT.en` and the feature text (for example `settingsHelpEnUS`,
`systemConfigI18n.ts`, `reportLanguage.ts` REPORT_TEXT.en) are not walked, and nothing checks parity of the zh / en
frontend key sets beyond what TypeScript's `Record<UiTextKey, string>` enforces. CI was not looked at.

**Gotcha (third time):** the file-writing tool turned the `\u3000` escape inside a regex back into a literal
ideographic space, which ESLint's `no-irregular-whitespace` rejects. The frontend test now builds the escapes with
`chr(92)` in a Python step; run `npm run lint` after writing any such regex. Also: restoring a file after a PowerShell
mutation check with `Set-Content` rewrites its encoding and line endings; use `git checkout -- <file>` instead.

## III.26 Korean year-over-year labels (2026-09-30, `36eb462`)

`_REPORT_LABELS["ko"]` in `src/report_language.py` had `revenue_yoy_label` = `매출 전년比` and
`net_profit_yoy_label` = `순이익 전년比`, mixing a Chinese character (`比`) into Korean. They are now `매출 전년 대비`
and `순이익 전년 대비` ("versus the prior year", the Hangul-only standard phrasing), matching the English labels
`Revenue YoY` / `Net Profit YoY` in meaning.

- Nothing else referenced the old strings (checked across `src`, `tests` and the frontend).
- `tests/test_retired_languages_dormancy.py` lost its `KOREAN_LABELS_WITH_HAN` exception list; the "each language keeps
  to its own script" test now requires every Korean value to be free of Han characters.
- Only affects reports generated with `REPORT_LANGUAGE=ko`. The wording was chosen from standard usage, not checked
  by a native Korean speaker.
- Backend suite after this: 6,801 passed / 65 skipped / 0 failed. CI was not looked at.

## III.27 Strategy display names in the report language map (2026-09-30, `22b778a`)

III.24 found that three strategy display names were not keys of `_STRATEGY_SKILL_CANONICAL_MAP` in
`src/report_language.py` and left open whether that could ever matter. It can, rarely.

**How a display name reaches the localizer**

- `localize_strategy_skill(value, language)` is called from `src/notification.py` (two places: the strategy opinion list
  and conflict participants), `src/services/history_service.py` (opinion list) and the Jinja report renderer. All of
  them pass a `skill_id` taken from the strategy synthesis payload.
- That id normally is an id: `SkillAgent.system_prompt` gives the model the literal template
  `"skill_id": "{self.skill_id}"`, and `strategy_opinion_from_agent_opinion` falls back to the id parsed from the agent
  name. So a normal run never passes a display name.
- The exception is a model that echoes what it saw elsewhere in the same prompt, which says "applying the
  **{display_name}** skill" with the Chinese display name. Then `缠论`, `龙头策略` or `一阳夹三阴` would reach the
  localizer, miss the map, and show up in Chinese in an English report. Custom user strategies are not in the map at all
  and are shown as written; that is expected.

**Fix:** three entries added to `_STRATEGY_SKILL_CANONICAL_MAP` (`缠论` -> `chan_theory`, `龙头策略` -> `dragon_head`,
`一阳夹三阴` -> `one_yang_three_yin`), next to the older legacy names (`缠论结构`, `龙头战法`, `一阳三阴`), which stay. The
map is static on purpose: looking display names up from the loaded skills would make `report_language.py` depend on the
agent layer.

**Test:** `tests/test_strategy_aliases_guard.py` now requires, for every shipped strategy, that its display name
localizes to the same English name as its id (and to the same Chinese name), and it fails without the fix. A new
strategy shipped in `strategies/` without a map entry now fails this test, which is the intended contract.

- Backend suite after this: 6,801 passed / 65 skipped / 0 failed. CI was not looked at.
- Not checked: whether a real model ever echoes the display name; the fix is defensive.

## III.28 China-based notification and bot services removed (2026-09-30)

User decision: remove WeCom, Feishu, DingTalk and ServerChan3 (notification channels and bots); keep every other channel (Telegram, Discord, Slack, Email, Pushover, ntfy, Gotify, AstrBot, custom webhook). **PushPlus was removed in a follow-up commit the same day** (sender, config keys `PUSHPLUS_*`, registry, diagnostics, UI, workflow, docs, tests).

**Removed**
- Senders: `wechat_sender`, `feishu_sender`, `dingtalk_sender`, `serverchan3_sender`; `src/feishu_doc.py` (Feishu cloud docs); `src/notification_contracts.py` (only held Feishu helpers).
- Bots: `bot/platforms/{dingtalk,dingtalk_stream,feishu_stream}.py`; `Platform.FEISHU/DINGTALK/WECOM`; `handle_{feishu,dingtalk,wecom}_webhook`; `ALL_PLATFORMS` is now empty (Discord/Telegram still not registered, as before); `start_bot_stream_clients` in `main.py` (nothing left to start).
- `NotificationService`: channels, context-channel (DingTalk/Feishu conversation) replies, `generate_wechat_dashboard/summary`, `templates/report_wechat.j2`, `format_feishu_markdown`, `format_wechat_markdown`, the pipeline WeCom branch and Feishu file sending.
- Config/registry/settings/API: all `WECHAT_*`, `FEISHU_*`, `DINGTALK_*`, `WECOM_*`, `SERVERCHAN3_SENDKEY` keys; routable-channel and test-channel lists; diagnostics specs; setup checks; frontend types, help text, i18n labels, channel dropdown (default test channel is now `telegram`).
- Custom webhook no longer special-cases DingTalk URLs (`_send_dingtalk_chunked`).
- `requirements.txt`: `lark-oapi`, `dingtalk-stream`. `.env.example`, `00-daily-analysis.yml`, desktop `main.js`, `pr-review.yml`/`release.yml` labels, docs (`bot-command`, `notifications`, `full-guide`, `FAQ`, `DEPLOY`, `README`, ...), `docs/bot/{feishu,dingding}-bot-config.md`, `scripts/e2e_test_feishu_app.py`.

**Deliberately kept:** secret-redaction patterns for `open.feishu.cn`, `oapi.dingtalk.com`, `qyapi.weixin.qq.com`, `ftqq.com` and the `FEISHU`/`DINGTALK_APP_KEY`/`WECOM_*` env-name scrubbing (`src/utils/sanitize.py`, `src/llm/local_cli_backend.py`) and their tests: they only redact, and stay safe if such a URL is pasted into a custom webhook. Also kept: the Bocha docs link on feishu.cn, and historical reports (`MIGRATION_REPORT.md`, etc.).

**Notes**
- `.env.example` and the workflow keep the old "Option N" numbers (gaps where options were removed) to avoid renumbering docs/tests.
- The "no notification configured" config warning now points at `TELEGRAM_BOT_TOKEN`.
- `scripts/check_env.py` notification test uses `service.send` instead of WeCom.
- Frontend guard allowances lowered: `settingsHelp.ts` 810 -> 739, `systemConfigI18n.ts` 374 -> 345.
- Tests: Feishu/DingTalk/WeCom/ServerChan-specific tests deleted; generic ones retargeted to Discord/Slack/Telegram.
- Verified 2026-09-30: backend `pytest -m "not network"` 6,667 passed / 65 skipped / 0 failed (after fixing one renderer test); `tsc`/lint (0 errors, 2 pre-existing warnings)/build/vitest all green. Not verified: CI, any live channel.

**CI note (2026-09-30):** `ci.yml` only runs on pull requests to `main`, so the direct pushes since 2026-09-24 (including the III.28 removals) had no CI result. This branch's PR exists to run `ai-governance` and the Ubuntu `backend-tests` on current `main` (the changelog line below makes the backend path filter fire; `web-gate` does not run because no `apps/dsa-web` non-Markdown file changes). Record the result here after it finishes.

**CI result (PR #1, run on `c3ab836`, 2026-09-30): green** - `ai-governance` (so the `CLAUDE.md` symlink fix in `bccc96a` works), the three Ubuntu `backend-tests` shards, `docker-build`, both `desktop-futu-package` jobs and `backend-gate` passed. `web-gate` was skipped by the path filter (no frontend change in the PR), so the frontend is still only verified locally. Two real CI defects were found and fixed on the way (the first CI run since the import):
- `ci.yml` had no `permissions:`, so `dorny/paths-filter` failed with "Resource not accessible by integration" and every job was skipped; the `changes` job now has `contents: read` + `pull-requests: read` (`ba87f6e`).
- The import stored every `.sh` file as mode 100644, so `./scripts/ci_gate.sh` failed with exit 126 on Linux; all seven are now 100755 (`c3ab836`).
Direct pushes to `main` never run CI (`ci.yml` is `pull_request` only); use a PR to get a CI result.

**Settings page visual check (2026-09-30, after PR #1): passed.** The app was run with `main.py --serve-only` and the Settings page opened in the browser pane. The Notifications tab shows 45 fields and none belongs to WeCom, Feishu, DingTalk, ServerChan3 or PushPlus (checked in the rendered page and in `/api/v1/system/config/schema`); the channel dropdown lists only Telegram, Email, Pushover, ntfy, Gotify, Custom Webhook, Discord, Slack and AstrBot, and the test panel defaults to Telegram. The setup check hint reads "configure Telegram, email or another channel later". The rendered Settings main content had no Chinese characters. The Report language dropdown still offers Chinese / English / Korean, which is intended (D11: the backend keeps zh/ko as an explicit opt-in).
- Not checked: the other Settings tabs, the sidebar/header, any channel's "Send test" button.
- Environment note: the preview host (`preview_start`) cannot run the app on this machine because a Windows Application Control policy blocks a pandas DLL when Python is launched that way; the same `.venv` works from the shell (tests and `main.py --serve-only`). Start the server from a shell and navigate the browser pane to `http://127.0.0.1:8000`; allow ~30 s for startup.

**Next:** the prompt eval baseline (III.19 item 5) needs the user's production LLM and search keys in `.env`; F4 (prompt translation) follows only after it. Smaller open items: Chinese `bot/` log lines, `web-gate` never yet run in CI on the removal work (it needs a PR that touches `apps/dsa-web`), Playwright specs forcing `zh-CN`.

## III.29 Smaller gaps (III.19 item 7), 2026-09-30

**Playwright specs.** `playwright.config.ts` and the three `e2e/*.spec.ts` files now use `locale: 'en-US'`; the `dsa.uiLanguage='zh'` seed in `report-markdown.spec.ts` is gone (the UI language is locked to `en`, so it did nothing); `<html lang>` in the visual spec is `en`; screenshot names are `smoke-*-page-en`; the Chinese developer-facing evidence text in `market-structure-card-visual.spec.ts` is English (the Chinese stock/sector names in its fixtures are data and stay). `.github/PULL_REQUEST_TEMPLATE.md` suggests `smoke-settings-page-en`. **Not run:** Chromium is not installed here and the authenticated specs need `DSA_WEB_SMOKE_PASSWORD`, so the edited specs only passed lint.

**`data_provider/` logs.** 448 lines inside `logger.*(...)` calls (single-line and multi-line, found with `ast`) in 10 files were translated to English, keeping the bracket-tag style (`[API call]`, `[API returned]`, `[circuit breaker]`, `[data source attempt n/m]`, ...). Data literals inside log calls (DataFrame columns such as `df['日期']`, the efinance index names `['沪深系列指数']` / `['行业板块']`) were left. Also translated: the `error_summary` / `error_msg` strings that `base.py` writes into those logs. Tests that asserted the old Chinese log text were retargeted: `test_fetcher_logging.py`, `test_realtime_quote_fallback_logging.py`, `test_akshare_realtime_logging.py`, `test_a_share_index_data_routing.py`. **Still Chinese in `data_provider/` (out of scope):** `DataFetchError` / exception messages (for example `不支持港股日线`), `print()` in the `__main__` self-tests, comments' quoted literals, and Chinese in fetchers' data handling. The wording is machine-composed from a phrase table, then reviewed line by line; a few messages read slightly stiff.

**Frontend guard is now a line fingerprint ratchet, not a count.** `tests/no_chinese_ui_source.test.ts` no longer keeps a `max` per file. `tests/no_chinese_ui_source.baseline.json` records, per allowlisted file, a fingerprint (first 10 hex of SHA-1 of the trimmed line) and a count for every line with Chinese or full-width punctuation. A Chinese line that is not in the baseline fails the test (with the line text), so replacing one Chinese line by another in an allowed file is caught (the old count-only guard missed it; checked by mutation); a baseline line that disappears also fails, so the baseline must shrink. After a deliberate change: `UPDATE_CHINESE_BASELINE=1 npx vitest run tests/no_chinese_ui_source.test.ts`, review the JSON diff, and say in the review why a matcher/dormant line was added. `ALLOWED` keeps only the reason (`dormant` / `matcher` / `comment`). Gotcha: when rewriting this file, keep the `　` escapes in the `CHINESE` regex and the `?
` split as escapes (a tool round trip turns them into real characters).

**Verified:** backend `pytest -m "not network"` 6,659 passed / 0 failed; frontend `tsc`, lint (0 errors, 2 old warnings), build, vitest (`DecisionSignalsPage` timed out once under the parallel run and passes alone, the known flake). **Not verified:** CI (this went to `main` directly; CI only runs on PRs), the Playwright specs.

**web-gate in CI (PR #2, run on `224ff2f`, 2026-09-30): green.** `web-gate` (frontend lint + build) passed in 2m 2s with only the two existing `StockScreeningPage.tsx` `react-hooks/exhaustive-deps` warnings; `ai-governance`, `docker-build` and `backend-gate` passed too (`desktop-futu-package-*` were skipped by the path filter; `backend-tests` showed one job, the filter limits it). So the frontend work from the China-service removal and III.29 is now CI-verified, and the two CI defects fixed in PR #1 stay fixed. Still unverified in CI: the Playwright e2e specs (CI does not run them).


## III.30 US/HK focus, Phases 1 and 2 (2026-09-30, branch `feat/us-hk-focus`, merged as PR #3)

**Direction (user decision):** the product targets **US and Hong Kong** first, **Canada** later (priority 3), and Asia support (mainland China, Taiwan) is to be removed. Phases 1-2 are done on the branch; **Phase 3 (deleting the Asia code) and Phase 4 (Canada) are not started.**

**Decisions taken from the assistant's recommendations (user said "go with your recommendations"):** remove Taiwan in Phase 3; keep Futu as optional for HK and out of the defaults; remove the A-share screening module in Phase 3 and rebuild a US version later; drop the China-specific strategies (Chan theory, `dragon_head`, `one_yang_three_yin`, `emotion_cycle`) in Phase 3 unless asked to keep them; Chinese/English/Korean report languages stay.

**Phase 2 (commit `bb37203`):**
- New `data_provider/market_codes.py` holds `is_hk_stock_code` and `is_us_code`; `akshare_fetcher` delegates to it and `base.py` / `__init__.py` import from it.
- HK daily bars and HK stock-name lookups no longer use AkShare or Tushare (`_DAILY_MARKET_FETCHER_SUPPORT`); default `FUTU_HK_REALTIME_SOURCE_PRIORITY` is `futu,longbridge,yfinance` (AkShare still accepted as an opt-in value). `data_capability_service` was updated to match.
- Search providers now run Tavily, Brave, SerpAPI, SearXNG, then Bocha, Anspire, MiniMax (Anspire was previously inserted first).
- New `tests/test_us_hk_independent_of_cn_sources.py` proves US/HK daily, HK realtime and HK name lookups never call a China-only fetcher. Four existing tests that encoded the old HK-through-AkShare behaviour were updated.

**Phase 1 (config and docs, no code deleted):** `.env.example` defaults to `STOCK_LIST=AAPL,MSFT,NVDA,0700.HK`, lists Gemini / Claude / OpenAI / OpenRouter / Ollama as the LLM quick start, orders search as Tavily / Brave / SerpAPI ahead of the China-based ones, and labels Tushare, TickFlow, screening and `REALTIME_SOURCE_PRIORITY` as China-only. README, `docs/market-support.md` (new "Primary and planned markets" table), `docs/full-guide.md` and `docs/CHANGELOG.md` match.

**Known gaps (Phase 3 work):**
- `data_provider/__init__.py` still imports every fetcher eagerly, so importing the package loads akshare/efinance/tushare even for US/HK. The independence test therefore checks routing, not imports.
- The US chain already is Finnhub -> Alpha Vantage -> Yahoo -> Longbridge; no new US fetcher was added. Yahoo is unofficial, so consider Polygon or Twelve Data if it proves flaky.
- Code classification for mainland codes (BSE/SH/SZ), the pinyin name resolver, Tushare stock-list scripts, `src/services/screening/`, NewsNow and the China LLM channel templates are untouched.
- `.env.example` was not reordered for the multi-channel LLM templates (Anspire/DeepSeek templates still appear before the global ones in that section).

**Verified:** backend `pytest -m "not network"` 6,666 passed / 65 skipped / 0 failed. Not run: frontend gates (no frontend files changed), CI (the branch is pushed; check the Actions tab of `sayaara/dsa`), and any live data fetch (no keys or network checks on this machine).

## III.31 Japan, Korea and Taiwan removed (2026-09-30, branch `feat/remove-asia-markets`)

**PR #3 (Phases 1-2) merged; CI on it was green** (`backend-tests` 1-3/3, `backend-gate`, `ai-governance`, `docker-build`; `web-gate` and the desktop package jobs were skipped because no frontend files changed). Phase 3 is now in progress on a new branch; this section covers its first step.

**User decisions (2026-09-30):** remove JP/KR/TW **but keep the generic suffix-market mechanism** so Canada is one registry entry; **keep screening and make it US-only** (my earlier claim that screening was A-share only was wrong: its pipeline already accepts `market` = `cn` or `us` and has a US snapshot provider, so the plan changed from "remove" to "strip the China path").

**What changed**
- `src/services/market_symbol_utils.py`: `_SUFFIX_MARKET_SPECS` is now empty. The mechanism (`SuffixMarketSpec`, `get_suffix_market`, `normalize_suffix_market_symbol`, ...) is unchanged. `tests/test_market_symbol_utils.py` proves it by registering a temporary `ca` spec.
- `data_provider/base.py`, `yfinance_fetcher.py`, `stock_code_utils.py`, `stock_index_loader.py`, `pipeline.py`: hard-coded `{"jp","kr","tw"}` sets and predicates replaced by the generic `get_suffix_market` path or removed. The Yahoo entry in `_DAILY_MARKET_FETCHER_SUPPORT` is now `{"cn","hk","us"}`; a future market must be added there.
- Deleted: `data_provider/tw_institutional_fetcher.py` (and the `institution` prompt block in `analyzer.py`, `_append_institutional_flow` in `notification.py`, six `inst*` report labels), JP/KR/TW market-review profiles, blueprints, titles, prompts, calendars, `jp`/`kr` regions (`MARKET_REVIEW_REGION` is now `cn|hk|us|both`), schema/API enums, web UI options and labels, portfolio partial-valuation markets, `scripts/stock_index_seeds/stock_list_{jp,kr}.csv`, and 60 JP/KR rows from `static/stocks.index.json` and `apps/dsa-web/public/stocks.index.json`.
- **New behaviour:** `parse_analysis_target` rejects `\d{4,6}.(T|KS|KQ|TW|TWO)` as `unsupported` ("exchange suffix ... is no longer supported"). Without this, `7203.T` was parsed as a **US stock** and tagged `cn` by `_market_tag`. `_market_tag` still returns `cn` for any other unknown suffix (for example `RY.TO`); fix that when Canada is added.
- Tests: deleted 9 test files or test functions that were only about these markets (about 110 tests in total), adjusted the rest. `docs/architecture/api_spec.json` was synced for the changed paths and schemas only (other entries were already out of date before this change). `.github/ci-test-durations.json` dropped the deleted files and the floor in `test_ci_test_shard.py` went from 250 to 200. The frontend Chinese-source baseline was regenerated (8 lines removed, 3 re-fingerprinted dormant lines).

**Verified:** backend `pytest -m "not network"` 6,529 passed / 65 skipped / 0 failed; frontend `tsc` 0 errors, lint 0 errors (2 old warnings), build passes, vitest 1,201 passed in the full run plus `DecisionSignalsPage`, `HomePage` and `LLMChannelEditor` passing on their own (they time out under the parallel run, as noted before). **Not run:** live data fetches; CI (check the PR's Checks tab).

**Still to do for Phase 3 (mainland China), in this order**
1. `MARKET_REVIEW_REGION` default is still `cn`; change the default to `us` when the cn path goes.
2. Remove the China fetchers (`efinance`, `akshare`, `tushare`, `tickflow`, `pytdx`, `baostock`, `tencent`), the A-share routing in `data_provider/base.py`, and their dependencies in `requirements.txt` and Docker. `data_provider/__init__.py` still imports every fetcher eagerly.
3. Strip screening's `cn` market (snapshot, hotspot, industry, daily sources) and keep the US snapshot, ranker and web page.
4. Remove the pinyin name resolver, the Tushare stock-list scripts, NewsNow, the China LLM channel templates, and the China-specific strategies.
5. Stock-index data still has about 5,500 CN/BSE rows and 2,739 HK rows.

**Status and next action (2026-09-30):** `feat/remove-asia-markets` was opened as PR #4 and **merged** into `main` (merge commit `7790773`). Mainland China removal starts on a new branch, `feat/remove-cn-market`, cut from that merge (list above; nothing deleted yet). Known environment facts: `scripts/check_ai_assets.py` fails locally on the CLAUDE.md symlink (`core.symlinks=false`, not a regression); `static/stocks.index.json` is gitignored (a generated copy of `apps/dsa-web/public/stocks.index.json`); `git add` aborts if one path is ignored, so never pass `static` to it.

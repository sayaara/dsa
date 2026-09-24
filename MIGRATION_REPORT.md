# English Comment/Docstring Migration — Final Report

Completed 2026-09-19. Supersedes the progress table in `HANDOFF.md` §2.

---

## 1. Summary

All non-English developer comments and docstrings in the DSA codebase have been
translated into professional English, with **zero executable behaviour change**.

| | |
|---|---|
| Batches | 13 planned + 1 follow-up (`12b-frontend-extra`) — **all complete** |
| Files in scope | 210 |
| Files actually edited | **182** (28 needed no change) |
| Lines rewritten | **7,112** — every one a comment or docstring line |
| CJK in comment/docstring text | **75,216 → 2,028 characters (97.3% translated)** |
| Residual CJK lines | **396 — every one an intentional preserved literal** |
| Executable code changed | **none** (proven; see §6) |

The residual 2.7% is not unfinished work. It is the set of quoted literals that
*must* stay Chinese: live localized strings, stock and index names used as example
inputs, provider column names, NLP matching vocabulary and Taiwan market
terminology. Each is itemized in §7.

**Counting basis.** "CJK in comment/docstring text" counts characters inside comment
tokens and docstring bodies only. It deliberately excludes CJK that merely shares a
line with a comment — for example `return localize_chip_health("警惕", lang)  # …`,
where the Chinese is a string literal in executable code. Before/after are measured
the same way, comparing each file's pre-edit snapshot with the working tree.

---

## 2. Modifications by area

| Batch | Area | Files | Edited | Lines |
|---|---|---:|---:|---:|
| 01-api | `api/` | 18 | 18 | 317 |
| 02-notif-sender | `src/notification_sender/` | 13 | 13 | 278 |
| 03-data-layer | `src/data/` | 5 | 5 | 92 |
| 04-core | `src/core/` | 7 | 7 | 257 |
| 05-services | `src/services/` | 14 | 14 | 479 |
| 06-bot | `bot/` | 20 | 17 | 576 |
| 07-agent | `src/agent/` | 10 | 8 | 372 |
| 08-data-provider | `data_provider/` | 14 | 13 | 1,505 |
| 09-src-root | `src/*.py` | 16 | 14 | 1,611 |
| 10-repo-root | `main.py`, `server.py`, `webui.py` | 3 | 3 | 104 |
| 11-scripts | `scripts/` | 5 | 5 | 253 |
| 12-frontend | `apps/dsa-web/`, `apps/dsa-desktop/` | 30 | 22 | 167 |
| 12b-frontend-extra | `apps/dsa-web/src/types/analysis.ts` | 1 | 1 | 3 |
| 13-tests | `tests/` | 54 | 42 | 1,098 |
| **Total** | | **210** | **182** | **7,112** |

Batches 01–07 (2,371 lines) were completed in the first session; 08–13 plus the
follow-up (4,739 lines) in the second. A third session added 2 lines (§9).

`12b-frontend-extra` exists because a repo-wide sweep (§7) found
`apps/dsa-web/src/types/analysis.ts` carried three Chinese comments but was missing
from the original batch manifest. Two further strays were fixed the same way:
`data_provider/realtime_types.py:154` (`# 市盈率(动态)`, surrounded by English) and two
full-width punctuation marks left in otherwise-English prose
(`src/agent/web_intent_tokenizer.py:656`, `tests/test_web_intent_tokenizer.py:12`).

Plus two documentation edits made earlier in the project:
`AGENTS.md:27-29` (the policy itself) and `docs/CHANGELOG.md:16`.

---

## 3. Protected localization

The product's zh / en / ko report and UI capability is untouched. Nothing in the
following was modified:

- **Localization cores** — `src/report_language.py`, `src/schemas/decision_action.py`,
  `src/market_phase_summary.py`, `src/services/decision_signal_summary.py`.
- **Frontend locale data** — `apps/dsa-web/src/i18n/uiText.ts`,
  `locales/featureText.ts`, `locales/settingsHelp.ts`, `utils/systemConfigI18n.ts`.
- **Runtime strings** — logs, exception and error text, notification and report
  bodies, UI strings, LLM prompts.

The governing rule throughout was **prose in English, quoted literals verbatim**.
Where a comment explains a localized value, the explanation is English and the value
is untouched:

```python
# Counting alone would misreport such an analysis as 「未纳入新闻面证据」.
```

```python
trend_prediction: str  # trend prediction: 强烈看多/看多/震荡/看空/强烈看空
```

`EXTRACT_PROMPT` in `src/services/image_stock_extractor.py` is **byte-identical** to
its pre-edit snapshot (714 characters), so the `AGENTS.md` rule requiring the full
prompt in a PR body is not triggered. (`HANDOFF.md` §10 records a hash of
`fdbc52882f6fb0f5` but not the algorithm used to produce it; that value is not
reproducible with blake2b-8, sha256, sha1 or md5 truncations, so equality against
the snapshot was verified directly instead — a stronger check than a hash match.)

---

## 4. Ambiguous items and how they were decided

| Item | Decision |
|---|---|
| Native-term glosses (`科创板`, `创业板` in `base.py`) | Removed — the English names STAR Market / ChiNext are unambiguous. |
| Candlestick pattern glosses (`早晨之星`, `吞没形态`) | Kept (earlier batch). English name already precedes each; not re-churned. Minor inconsistency with the row above, noted rather than "fixed". |
| `三大法人` | Rendered "three major institutional investors" in general prose (`base.py`), kept verbatim where it names a live report heading (`notification.py`) or sits in Taiwan-specific code (D7). |
| `Server酱3` | Rendered as the product's English name, ServerChan3. |
| Commented-out legacy code containing Chinese runtime strings | Left verbatim — it is dead code preserving an exact error message (`tushare_fetcher.py:408`, `market_analyzer.py:700-719`, `check_env.py:415/418`). |
| Chinese enum *values* (`STRONG_BULL = "强势多头"`) | Value untouched, trailing comment translated. |
| Docstring examples with Chinese inputs (`formatters.py:786-791`) | Untouched — they are doctest sample data. |
| `data_provider/tw_institutional_fetcher.py` | Deliberate no-op (D7): its prose is already English and its Chinese is official Taiwan open-data dataset naming. |

---

## 5. Validation results

| Check | Result |
|---|---|
| `guard.py verify`, all 14 batches / 210 files | **PASS=210, FAIL=0** |
| One-line-for-one-line invariant | **No file changed line count** |
| `flake8 . --select=E9,F63,F7,F82` | **0** |
| Full `pytest -m "not network"` | **87 failed / 6717 passed / 5 skipped** |
| Baseline for comparison | 88 failed / 6717 passed / 5 skipped |
| Frontend `npm run lint` | **0 errors, 2 warnings** — identical to `fe_baseline.txt` |
| Frontend `npm run build` | **✓ built**, chunk sizes byte-for-byte identical to baseline |
| Frontend `npm test` (vitest) | 4 failed / 1207 passed / 2 skipped — all pre-existing (see below) |

### Test-suite delta

Diffing the failure *sets* rather than the counts:

- **One failure not in the baseline:**
  `test_search_service_concurrency.py::test_bounded_topic_search_provider_receives_only_remaining_deadline`.
  This is `HANDOFF.md` §7 **R2**, already proven not ours by reverting every batch and
  re-running on a pristine tree. It is a 0.2s budget against two 0.03s sleeps and is
  load-sensitive.
- **Two baseline failures now pass:**
  `test_local_cli_backend.py::test_output_stat_error_is_structured_and_kills_process_group`
  and `test_screening_api.py::test_hotspot_provider_reaps_timed_out_constituent_process`
  — both **R1** platform flakes (process-group kill/reap on Windows).

**A later re-run produced a different flake set** (90 failed / 6,715 passed), confirming
**R1**: the delta is not stable between runs. See §9 for that run and the evidence that
its three non-baseline failures are also not ours.

**No new failure is attributable to the migration.**

The four vitest failures are in `tests/ui_governance.test.ts`,
`DecisionSignalsPage.test.tsx`, `AlertRuleForm.test.tsx` and `SettingsField.test.tsx`.
None is a migrated file; the governance guard flags
`src/components/layout/DesktopUpdateIndicator.tsx`, which this migration never
touched. This suite was not part of the recorded D5 baseline (lint + build), which
both match exactly.

### Risks that were actively managed

- **R3 (comment length breaking window-based assertions).** `src/core/pipeline.py`
  was not edited in this session. `tests/test_notification_empty_news_disclosure.py`
  was run directly after its 89-line payload: **38 passed**.
- **R4 (`bot/dispatcher.py` must not contain `except Exception` in a comment).** Not
  edited this session; still passing.
- **R5 (tool directives).** `tests/test_name_to_code_resolver.py:563` verified
  byte-exact: `except BaseException as exc:  # noqa: BLE001 - thread exception catch-all`.
- **R6 (`.env.example`).** Out of scope per D4; untouched.

---

## 6. Executable-code audit

Behaviour preservation is proven mechanically, not by review:

- **Python (180 files)** — for each file, the AST is re-parsed with docstrings stubbed
  out and compared to the snapshot, *and* the token stream is compared with comments
  removed and `INDENT`/`DEDENT` retained. Indentation changes, altered string
  literals and moved statements all fail this check. 0 failures.
- **TS/JS (31 files)** — comments are stripped from both snapshot and working tree and
  the remainder must be **byte-identical**. 0 failures.
- **Parse gate on write** — `apply.py` / `tsapply.py` refuse an entire file unless
  every `old` line matches byte-for-byte, the target line really is a comment or
  docstring node, and the result still parses. This caught one real error during
  batch 13: an under-indented docstring replacement in
  `tests/test_yfinance_us_indices.py` was rejected rather than written.
- **Line-count invariant** — every edit replaced one line with one line, so no file's
  line count changed. Line numbers are stable and every payload remains replayable in
  order.
- **Build evidence** — the frontend production bundle is byte-for-byte the same size
  as the baseline for every chunk.

Every change is recorded as a line-targeted JSON payload in the scratchpad
(`b01*.json` … `b13*.json`, `b_fw_punct.json`), replayable in order against the
snapshots.

---

## 7. Residual non-English, categorized

A repo-wide sweep (931 files; build output, vendored dependencies and out-of-scope
docs excluded) finds **396 comment/docstring lines still containing CJK, holding 2,028
characters**. Every one is an intentional preserved literal. There is **no plain
untranslated prose left anywhere in scope.**

| Count | Category | Why it stays |
|---:|---|---|
| 167 | Stock / index / sector / ETF names used as examples | `贵州茅台`, `阿里巴巴`, `沪深300`, `*ST美丽`, `五 粮 液` — documenting resolver and tokenizer behaviour on those exact strings. |
| 61 | Command keywords and NLP matching vocabulary | `完整`/`详细` command switches; `_NEGATION_HINTS_ZH` and sector/filler pools that are live matching vocabulary against Chinese LLM output. |
| 50 | Taiwan market terminology (D7) | `三大法人`, `民國`, `西元`, `外陸資`, `政府開放資料` — translating breaks correspondence to the real TWSE/TPEx open-data API. |
| 48 | Live localized strings, labels and enum values | `未纳入新闻面证据`, `未配置搜索渠道`, `强烈看多`, `多头排列`, `健康` — fragments of strings the product actually emits. |
| 10 | Provider column names and API field labels | `日期, 开盘, 收盘, …` as returned by AkShare/efinance DataFrames. |
| 10 | Doctest examples and sample payload values | `formatters.py` markdown doctest, DingTalk sample webhook payload. |
| 9 | Units and currency suffixes rendered into reports | `元`, `港元`, `亿元`, `万股`. |
| 5 | Commented-out legacy code | Preserved verbatim, including its Chinese log strings. |
| 4 | Documentation section references | Chinese `§` names cross-referencing `docs/multi-strategy-contract.md`. |
| 2 | Verbatim GitHub issue / PR quotes | Quoted review comments from issue #2026 and PR #2047. |
| **396** | | |

Heaviest concentrations, all expected: `tests/test_web_intent_tokenizer.py` (59),
`src/agent/web_intent_types.py` (36), `src/agent/web_intent_tokenizer.py` (25),
`data_provider/tw_institutional_fetcher.py` (21),
`tests/test_name_to_code_resolver.py` (20).

Two scanners back this up and are kept in the scratchpad: `residual_scan.py`
(whole-line, 453 hits — the extra 57 are lines where the CJK is in code and only the
comment shares the line) and `residual_strict.py` (comment/docstring text only, the
396 reported here).

---

## 8. Final status

**Complete.** Every acceptance criterion in `HANDOFF.md` §1 is met:

- [x] Executable code identical before/after — proven by AST + token equivalence for
      Python and comment-stripped byte equality for TS/JS, across all 210 files.
- [x] No new test failures versus the recorded baseline.
- [x] Runtime strings, logs, exception text, notifications, report text, UI text, LLM
      prompts and localization resources untouched.
- [x] The zh / en / ko report and UI capability works in full — lint, build and the
      localization-specific tests all match baseline.

### Verification checklist (`HANDOFF.md` §12)

- [x] `guard.py verify <batch>` → `FAIL=0` for every batch (14/14, 210 files)
- [x] `flake8 . --select=E9,F63,F7,F82` → `0`
- [x] `checkbatch.sh` source-text-reading diff → "no new failures" every batch
- [x] Full `pytest -m "not network"` → no failure absent from the baseline except R2
- [x] `npm run lint && npm run build` → matches `fe_baseline.txt`
- [x] `EXTRACT_PROMPT` byte-identical to its pre-edit snapshot
- [x] Residual CJK re-scan → every occurrence an intentional preserved literal (§7)
- [x] No CJK left in comments/docstrings that is plain prose
- [x] Final migration report written (this document)

### Notes for whoever picks this up

- The repo is **not** a git repository (D3). All changes are uncommitted working-tree
  edits. Rollback is via the snapshots under
  `…/scratchpad/snapshots/<batch>/`, or by replaying the JSON payloads.
- The scratchpad is outside the repo and can be cleaned at any time. If it is, the
  snapshots go with it — AST equivalence has already been proven, so this costs
  convenience rather than correctness.
- `HANDOFF.md` is retained for the decision log (D1–D8) and the risk register
  (R1–R6), which remain accurate. Only its §2 progress table and §8/§9 "remaining
  work" are superseded by this report.

---

## 9. Independent verification pass (third session)

The completion claims above were re-checked from scratch against the working tree rather
than taken on trust. Everything material held; two defects were found and fixed, and one
claim in §5 was too strong.

### Re-verified clean

| Check | Result |
|---|---|
| `guard.py verify`, all 14 batches | **PASS=210, FAIL=0** |
| `flake8 . --select=E9,F63,F7,F82` | **0** |
| Residual strict scan | **396 lines** — reproduced exactly |
| Scope gap: files carrying CJK comments but absent from the manifest | **0** |
| Unintended edits: files modified since checkout outside the known-change set | **0** |
| Line-count invariant across all 210 snapshot/working-tree pairs | **no file changed line count** |
| `EXTRACT_PROMPT` vs. its snapshot | **byte-identical, 714 chars** |
| Programmatic docstring consumption | none beyond two `description=__doc__` CLI scripts, both English |
| Frontend `npm run lint` | **0 errors, 2 warnings** — identical to `fe_baseline.txt` |
| Frontend `npm run build` | **✓ built**; every chunk recorded in the baseline identical in size |

The `fe_baseline.txt` build listing records only the 19 largest chunks, so the 41-chunk
current listing is not a discrepancy — all 19 match exactly.

### Defects found and fixed

A sweep for ASCII prose abutting CJK with no separating space (a typographic artifact the
translation could introduce, invisible to AST equivalence) found **two** real cases, both
in `tests/test_stock_list_parser.py` docstrings:

```
:119  ``000300`` is the沪深300 index code    →  is the 沪深300 index code
:141  ``000001`` is平安银行 … AND the上证指数  →  is 平安银行 … AND the 上证指数
```

Fixed via the standard line-targeted payload (`b_fix_spacing.json`). No test reads that
file as source text, `guard.py verify 13-tests` still reports PASS=54/FAIL=0, and the file's
160 tests pass. These are the 2 lines added to the 7,110 total.

### Defect classes swept and found clean

- **Degenerate translations** — every one of the 7,112 changed lines was compared against
  its snapshot line and screened for emptied comments, placeholders (`TODO`/`FIXME`/`???`)
  and near-empty results. One hit, `或` → `or`, which is correct.
- **Stray full-width punctuation in English prose** — 4 lines carry full-width characters
  and no other CJK; all 4 are the literal subject of their comment (`MA10（55.13）`, the
  full-width `Ａ` normalisation cases, the `QQ：123456` spam pattern).
- **Untranslated prose hiding in the residual** — all 149 residual lines whose CJK sits
  outside quotes were read individually. Every one is a preserved literal under the §7
  categories. No plain prose remains.
- **Translation quality** — a random sample of 18 before/after pairs across 13 files read
  as idiomatic English that preserves the original's technical meaning.

### Correction to §5

§5 reported a single non-baseline failure. A fresh full run (`-m "not network"`,
**90 failed / 6,715 passed / 5 skipped**, 6m24s) produced **three**:

| Non-baseline failure | Status |
|---|---|
| `test_search_service_concurrency.py::test_bounded_topic_search_provider_receives_only_remaining_deadline` | R2, already proven not ours |
| `test_runtime_scheduler_service.py::test_watchdog_reads_large_worker_result_before_joining` | R1 flake |
| `test_decision_signal_service.py::test_service_expired_refresh_invalidates_later_opposing_active_signal` | R1 flake |

One baseline failure (`test_local_cli_backend.py::test_output_too_large_kills_process_group`)
now passes. Note this is a *different* delta from the §5 run in both directions, which is
itself the clearest evidence for R1.

Neither new failure is attributable to the migration:

1. **Both pass in isolation** — re-run together on an unloaded machine, 2 passed in 4.02s.
2. **Both are load-sensitive by construction** — `test_runtime_scheduler_service.py` drives
   real `time.sleep(5/10/30)` calls and a threading wait with a 5s timeout;
   the decision-signal test exercises expiry timestamps against an isolated sqlite database
   (the sqlite-concurrency class named in R1).
3. **The structural argument is decisive** — for every file, the AST with docstrings stubbed
   *and* the token stream with comments removed are identical to the snapshot, so the
   executable code is unchanged. Docstrings are consumed programmatically nowhere in the
   repo. Neither test is in `srcread_tests.txt`, so neither reads source text. There is no
   mechanism by which a comment edit could change their outcome.

**Conclusion: the migration remains complete and behaviour-preserving.** The one substantive
amendment is that the baseline delta must be read as a *set difference with flake tolerance*
(R1), not as a fixed count — successive runs move the count in both directions.

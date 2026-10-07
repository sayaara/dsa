# DSA (Daily Stock Analysis) — Updated Product Overview

> Source repository: [your-org/your-repo](https://github.com/your-org/your-repo)
>
> This document supersedes [PRODUCT_OVERVIEW.md](PRODUCT_OVERVIEW.md). It keeps that document's
> market-support and localization analysis, adds the architectural and technical detail that was
> missing from it, and records the **English comment/docstring migration** completed 2026-09-19
> (§7). It is a generated summary of repository state, not a substitute for
> [docs/full-guide.md](docs/full-guide.md).

---

## 1. What the application does

DSA is an AI-powered stock intelligence system. For a user-configured watchlist it runs a daily
(or on-demand) pipeline that:

1. **Fetches data** — quotes, K-line history, technical indicators, news, announcements and
   fundamentals from multiple providers with automatic failover.
2. **Enriches and analyses** — volume ratio, turnover, chip distribution, moving-average
   alignment, sector/concept membership, market structure.
3. **Asks an LLM** (any OpenAI-compatible / LiteLLM-routed model) for a structured verdict.
4. **Renders a report** — a "Decision Dashboard" with score, trend, buy/sell levels, risk
   alerts, catalysts and an action checklist.
5. **Pushes notifications** to one or more channels.

The project explicitly disclaims investment advice — output is AI-generated, for research only.

### Surfaces

| Surface | Entry point |
|---|---|
| **CLI** | [main.py](main.py) — `--debug`, `--dry-run`, `--stocks`, `--market-review`, `--schedule`, `--serve`, `--webui` |
| **REST API** | [server.py](server.py) / [api/app.py](api/app.py) — `uvicorn server:app` |
| **Web workspace** | [apps/dsa-web/](apps/dsa-web/) — React/TypeScript SPA |
| **Desktop app** | [apps/dsa-desktop/](apps/dsa-desktop/) — Electron shell around the Web workspace |
| **Chat / Agent** | Conversational "ask about a stock" agent, reachable from Web, bots and API |
| **Bots** | [bot/](bot/) — DingTalk, DingTalk Stream, Feishu Stream, Discord |
| **Automation** | GitHub Actions, Docker, local scheduling (`--schedule`) |

---

## 2. Scale

| Area | Files | Lines |
|---|---:|---:|
| `src/` (Python) | 238 | 140,515 |
| `tests/` | 283 | 153,832 |
| `apps/` (TS + TSX) | 296 | 87,720 |
| `data_provider/` | 20 | 17,369 |
| `api/` | 41 | 11,861 |
| `bot/` | 22 | 5,502 |
| `scripts/` | 14 | 4,516 |
| `docs/` | 50 | 16,504 |

Roughly **336,000 lines of Python** and **88,000 of TypeScript**. The test suite slightly
outweighs the source it covers: ~6,700 tests pass in the offline (`-m "not network"`) run.

---

## 3. Architecture

### 3.1 High-level flow

```
Watchlist (STOCK_LIST)
        │
        ▼
data_provider/*  ──► technical indicators + fundamentals + news/sentiment search
        │
        ▼
src/core/pipeline.py  (orchestration)
        │
        ▼
LLM analysis (LiteLLM-routed: OpenAI-compatible, Gemini, DeepSeek, Qwen, Claude, Ollama, ...)
        │
        ▼
src/reports/* + templates/  (Decision Dashboard / Market Review reports)
        │
        ▼
src/notification_sender/*  ──► WeCom / Feishu / Telegram / Discord / Slack / Email / DingTalk / ...
```

### 3.2 Backend layout

| Path | Responsibility |
|---|---|
| [main.py](main.py) | CLI entry point and task orchestration (1,882 lines) |
| [server.py](server.py) | FastAPI app entry |
| [src/core/](src/core/) | `pipeline.py`, `market_review.py`, `market_profile.py`, `market_strategy.py`, `trading_calendar.py`, `backtest_engine.py`, `config_manager.py` |
| [src/services/](src/services/) | Business/service layer — **61 modules** (analysis, history, decision signals, backtesting, screening, alerts, task queue) |
| [src/repositories/](src/repositories/) | **11 repositories** — analysis, portfolio, alerts, backtest, decision signals, skill-opinion samples/outcomes, intelligence, stock |
| [src/schemas/](src/schemas/) | Pydantic contracts shared across pipeline, API and Web |
| [src/agent/](src/agent/) | Agent/strategy orchestration (`orchestrator.py`, `executor.py`, `skills/`, `agents/`, `tools/`) |
| [data_provider/](data_provider/) | 13 provider adapters with priority ordering and failover |
| [api/](api/) | FastAPI routers, middleware, deps |
| [bot/](bot/) | Chat-platform integrations |
| [src/notification_sender/](src/notification_sender/) | One module per push channel |
| [templates/](templates/) | Jinja2 report templates |
| [strategies/](strategies/) | 15 YAML strategy definitions |

### 3.3 The analysis pipeline

`StockAnalysisPipeline` in [src/core/pipeline.py](src/core/pipeline.py) is the spine. Its own
docstring states its four responsibilities: manage the end-to-end flow, coordinate the data /
storage / search / analysis / notification modules, implement concurrency control and exception
handling, and provide the core analysis capability.

Per-stock sequence:

```
fetch_and_save_stock_data
  → _enhance_context                                (volume ratio, turnover, chip distribution, MA status)
  → _attach_belong_boards_to_fundamental_context    (A-share board membership)
  → _attach_concept_rankings_to_fundamental_context
  → _build_market_structure_context                 (non-blocking)
  → analyze_stock | _analyze_with_agent
  → _extract_decision_signal_after_history_save
  → _send_notifications
  → _save_local_report
```

Design characteristics worth knowing:

- **Fail-open throughout.** Supplementary context is best-effort;
  `_load_persisted_intelligence_context` explicitly treats stale locally-persisted intelligence
  as fail-open evidence rather than raising.
- **Checkpoint/resume** by trading date (`_resolve_resume_target_date`).
- **Graceful LLM degradation.** A family of `_trend_*_fallback` and
  `_backfill_agent_dashboard_fields` helpers reconstruct dashboard fields when the model returns
  placeholders or omits them.
- **Market-aware fallback.** `_get_analysis_context_with_market_fallback` fetches JP/KR/TW daily
  bars directly when the database has no stored context.

### 3.4 Multi-agent analysis

`AgentOrchestrator` ([src/agent/orchestrator.py](src/agent/orchestrator.py)) coordinates
specialised agents — **Technical → Intel → Risk → Specialist → Decision** — over a shared
`AgentContext`, collecting a `StageResult` per stage into a unified `OrchestratorResult`.

Four cost/depth tiers:

| Mode | Stages |
|---|---|
| `quick` | Technical → Decision (fastest, ~2 LLM calls) |
| `standard` | Technical → Intel → Decision (default) |
| `full` | Technical → Intel → Risk → Decision |
| `specialist` | Technical → Intel → Risk → specialist evaluation → Decision |

### 3.5 Strategy skills and consensus

15 YAML-declared strategies in [strategies/](strategies/): `bottom_volume`, `box_oscillation`,
`bull_trend`, `chan_theory`, `dragon_head`, `emotion_cycle`, `event_driven`,
`expectation_repricing`, `growth_quality`, `hot_theme`, `ma_golden_cross`, `one_yang_three_yin`,
`shrink_pullback`, `volume_breakout`, `wave_theory`.

`StrategyEngine` ([src/agent/skills/engine.py](src/agent/skills/engine.py)) describes itself as
the "authoritative multi-strategy pipeline facade". Because independent skills routinely
disagree, three dedicated modules resolve that:

- `synthesis.py` — dynamic bipartite grouping and consensus-level thresholds, per the
  multi-strategy contract in `docs/multi-strategy-contract.md`
- `deliberation.py` — cross-skill deliberation
- `disagreement.py` — conflict detection and severity

Skill opinions are persisted as samples with outcomes (`skill_opinion_sample_repo`,
`skill_opinion_outcome_repo`), so strategy performance can be scored over time.

### 3.6 Chinese intent tokenization

[src/agent/web_intent_tokenizer.py](src/agent/web_intent_tokenizer.py) is a hand-built entity
segmenter that resolves free-text Chinese queries against a stock-name library. It is unusually
subtle code: it must consume full names containing code-like or keyword substrings whole
(`TCL科技`, `恒生电子`), avoid substring collisions (`证券` inside `中信证券`, `农业` inside
`农业银行`), handle ST risk-warning prefixes in three spellings (`ST德豪` / `*ST美丽` / `ST*美丽`),
reach down to two characters for short HK names, and distinguish a sector word from a stock name.

This module and its test file hold the largest share of deliberately-preserved Chinese in the
repository (§7.4) — the keyword tables are live matching vocabulary, not prose.

### 3.7 Data layer

[data_provider/base.py](data_provider/base.py) documents itself as a **Strategy pattern**:
`BaseFetcher` defines the shared interface and `DataFetcherManager` is the strategy manager
implementing automatic failover, with each fetcher carrying its own flow-control logic as an
anti-ban measure.

13 providers: AkShare, Tushare, Baostock, Pytdx, efinance, YFinance, Longbridge, Futu, Finnhub,
AlphaVantage, Tencent, TickFlow, plus the TWSE/TPEx institutional feed.

Every aggregate accessor is failover-aware and fail-open — `get_daily_data`,
`get_realtime_quote`, `get_stock_name`, `get_main_indices`, `get_market_stats`,
`get_sector_rankings`, `get_concept_rankings`, `get_hot_stocks`, `get_limit_up_pool`.
`get_chip_distribution` additionally runs a circuit breaker with multi-source degradation.
Bulk prefetch paths (`prefetch_realtime_quotes`, `prefetch_daily_klines`, `prefetch_stock_names`)
exist to avoid per-stock round trips during parallel analysis.

### 3.8 API

~**129 endpoints** across 15 v1 routers:

| Router | Endpoints | Router | Endpoints |
|---|---:|---|---:|
| `portfolio` | 20 | `intelligence` | 9 |
| `system_config` | 17 | `stocks` | 8 |
| `decision_signals` | 12 | `analysis` | 6 |
| `agent` | 12 | `auth` | 5 |
| `history` | 11 | `backtest` | 4 |
| `screening` | 10 | `usage` | 2 |
| `alerts` | 10 | `data` | 2 |
| | | `health` | 1 |

### 3.9 Persistence

SQLAlchemy ORM over SQLite, with WAL mode, configurable busy timeout, and bounded write-retry
with backoff (`sqlite_wal_enabled`, `sqlite_busy_timeout_ms`, `sqlite_write_retry_max`,
`sqlite_write_retry_base_delay` in [src/storage.py](src/storage.py)). This concurrency tuning is
also the source of several load-sensitive tests on Windows (§7.5).

### 3.10 Frontend

React + TypeScript SPA under [apps/dsa-web/](apps/dsa-web/), organised into `api/`, `components/`,
`pages/`, `stores/`, `hooks/`, `contexts/`, `i18n/`, `locales/`, `types/`, `utils/`, `desktop/`.

11 pages: Home, Chat, Portfolio, Backtest, Stock Screening, Alerts, Decision Signals,
Token Usage, Settings, Login, NotFound.

Built with Vite into `static/` and served by the FastAPI backend, or run standalone in dev.
[apps/dsa-desktop/](apps/dsa-desktop/) wraps it in Electron with its own update/version-check flow.

### 3.11 Notification and bot channels

**13 push senders:** WeCom, Feishu, Telegram, Discord, Slack, Email, DingTalk, Gotify, ntfy,
Pushover, PushPlus, ServerChan3, custom webhook (plus AstrBot).

**4 interactive bot platforms:** DingTalk, DingTalk Stream, Feishu Stream, Discord — with 10
commands: `analyze`, `ask`, `batch`, `chat`, `help`, `history`, `market`, `research`, `status`,
`strategies`.

### 3.12 Deployment and CI

- **GitHub Actions** (recommended): fork, configure secrets (LLM key, notification webhook,
  `STOCK_LIST`, optional news-search keys), enable Actions. A scheduled workflow runs on weekday
  evenings (Beijing time) and skips non-trading days.
- **Docker**: [docker/](docker/) and [docs/DEPLOY.md](docs/DEPLOY.md); the build includes a smoke
  test importing key modules.
- **Local**: `pip install -r requirements.txt`, configure `.env` from
  [.env.example](.env.example), run `python main.py`.
- **CI gates** (see [AGENTS.md](AGENTS.md)): `ai-governance`, `backend-gate`
  (`./scripts/ci_gate.sh`), `docker-build`, `web-gate` on frontend changes. `network-smoke` and
  `pr-review` are non-blocking.

---

## 4. Markets supported

Market support is tiered. See [docs/market-support.md](docs/market-support.md) for the
authoritative boundary.

| Market | Code format | Status | Notes |
|---|---|---|---|
| **A-share** | 6-digit numeric (`600519`), registered indices (`sh000016`) | First-class | Full breadth: quotes, fundamentals, capital flow, dragon-tiger list, sector/board rankings, margin trading. Redundant sources (AkShare, Tushare, Baostock, Pytdx, efinance). |
| **Hong Kong** | `hk00700` | First-class | In market review and standard pipeline. |
| **US** | Ticker (`AAPL`) | First-class | In market review and standard pipeline; optional Reddit/X/Polymarket sentiment is US-only. |
| **Japan** | `.T` suffix (`7203.T`) | Suffix-only MVP | YFinance only; calendar `XTKS`/Asia-Tokyo; `^N225`, `^TOPX`. No full fundamentals or market breadth. |
| **South Korea** | `.KS` / `.KQ` (`005930.KS`) | Suffix-only MVP | Same constraints; calendar `XKRX`/Asia-Seoul; `^KS11`, `^KQ11`. |
| **Taiwan** | `.TW` / `.TWO` — strictly suffix-only; bare numeric is **not** Taiwan | Near first-class for single-stock | Calendar `XTAI`/Asia-Taipei; `^TWII`, `^TWOII`; TWD labelling; institutional flows (foreign / investment trust / dealer) via TWSE T86 and TPEx OpenAPI. Not in market review; no autocomplete seed; no Market Light alerts. |
| **ETFs** | Varies | Supported | Listed alongside equities. |

Cross-cutting:

- JP/KR/TW never fall back to A-share-specific sources; they route exclusively through YFinance.
- `MARKET_REVIEW_REGION` accepts `cn`, `hk`, `us`, `jp`, `kr` or `both`, comma-separable.
  Taiwan is not yet included.
- Market Light alerts support `cn` / `hk` / `us` only.
- Portfolio tracking accepts JP/KR/TW positions but marks them `data_quality=partial`.

---

## 5. Languages supported

Three report languages and two UI languages, applied at independent layers.

### 5.1 Report output — `REPORT_LANGUAGE`

```
REPORT_LANGUAGE=zh   # zh (default) / en / ko
```

Implemented in [src/report_language.py](src/report_language.py):

- `SUPPORTED_REPORT_LANGUAGES = ("zh", "en", "ko")`.
- `normalize_report_language()` accepts aliases (`zh-cn`, `zh_hans`, `cn`, `chinese`, `en-us`,
  `english`, `kr`, `korean`, `ko-kr`, …) and defaults to `zh`.
- `_REPORT_LABELS` dictionaries localize every report section in all three languages.
- `localize_*()` helpers normalize domain terms **regardless of which language the LLM emitted
  them in** — operation advice (买入 / Buy / 매수), trend prediction (看多 / Bullish / 상승),
  confidence level, strategy signal, consensus level, conflict severity, the 15 strategy skill
  names, chip-distribution health, price-bias status.
- Applies to both the LLM prompt's requested output language and the deterministic report
  scaffolding, so AI prose and templated fields stay consistent.

### 5.2 Web/Desktop UI — in-app toggle

`UiLanguage = 'zh' | 'en'` in [apps/dsa-web/src/i18n/uiText.ts](apps/dsa-web/src/i18n/uiText.ts),
toggled live, independent of `REPORT_LANGUAGE`. Korean is not offered at the UI-chrome level.
Locale resources live in `apps/dsa-web/src/locales/`, with helpers in
`apps/dsa-web/src/utils/systemConfigI18n.ts`.

### 5.3 Documentation

Parallel hand-maintained files: [README.md](README.md) (Simplified Chinese) /
[README.md](README.md), with `_EN`
counterparts for most major docs. Per [AGENTS.md](AGENTS.md) §1, changing one language version
requires evaluating whether the other needs a matching update.

---

## 6. Source-language policy (as of 2026-09-19)

[AGENTS.md](AGENTS.md) lines 27–29 now mandate English for source-code prose, with a precisely
scoped localization exception:

1. **Explanatory text in comments and docstrings must be English, and English only.** When
   translating an existing comment, replace it — do not keep a bilingual pair, and do not add
   new non-English explanatory text.
2. **Quoted literals inside comments and docstrings stay verbatim.** This covers localized labels
   and report copy (`未纳入新闻面证据`, `强烈买入`), language-map keys and values, example inputs
   (`沪深300`, `*ST美丽`, `五 粮 液`), stock and sector names, identifiers and field names. A
   docstring whose whole subject is the localized values themselves (e.g.
   `src/report_language.py`, `src/schemas/decision_action.py`) may keep them.
3. **Runtime copy is out of scope.** Logs, exceptions and error messages, notification bodies,
   report text, UI strings, LLM prompts and localization resources continue under their own
   localization contracts and must not be rewritten in the name of "englishing" the code. The
   existing zh / en / ko report and UI capability must be preserved in full.

The governing summary: **prose in English, quoted literals verbatim.**

---

## 7. What the migration changed

A three-session migration translated all non-English developer comments and docstrings into
professional English with **zero executable behaviour change**. Full detail, including the
decision log and residual itemization, is in [MIGRATION_REPORT.md](MIGRATION_REPORT.md); the
decision and risk registers are in [HANDOFF.md](HANDOFF.md).

| | |
|---|---|
| Files in scope | 210 |
| Files actually edited | 182 (28 needed no change) |
| Lines rewritten | 7,112 — every one a comment or docstring line |
| CJK in comment/docstring text | 75,216 → 2,028 characters (**97.3% translated**) |
| Residual CJK lines | 396 — every one an intentional preserved literal |
| Executable code changed | **none** (proven mechanically) |

### 7.1 Coverage by area

| Area | Files | Edited | Lines |
|---|---:|---:|---:|
| `api/` | 18 | 18 | 317 |
| `src/notification_sender/` | 13 | 13 | 278 |
| `src/data/` | 5 | 5 | 92 |
| `src/core/` | 7 | 7 | 257 |
| `src/services/` | 14 | 14 | 479 |
| `bot/` | 20 | 17 | 576 |
| `src/agent/` | 10 | 8 | 372 |
| `data_provider/` | 14 | 13 | 1,505 |
| `src/*.py` | 16 | 14 | 1,611 |
| `main.py`, `server.py`, `webui.py` | 3 | 3 | 104 |
| `scripts/` | 5 | 5 | 253 |
| Frontend (`apps/`) | 31 | 23 | 170 |
| `tests/` | 54 | 42 | 1,098 |
| **Total** | **210** | **182** | **7,112** |

### 7.2 How behaviour preservation was proven

The repository is deliberately **not** under git for this work, so equivalence was proven
mechanically rather than by diff review:

- **Python (180 files)** — for each file the AST is re-parsed with docstrings stubbed out and
  compared against a pre-edit snapshot, *and* the token stream is compared with comments removed
  and `INDENT`/`DEDENT` retained. Altered literals, moved statements and indentation changes all
  fail this check. **0 failures.**
- **TS/JS (31 files)** — comments stripped from both snapshot and working tree; the remainder
  must be byte-identical. **0 failures.**
- **Parse gate on write** — edits were applied only as line-targeted JSON payloads, refused
  unless every original line matched byte-for-byte, the target was genuinely a comment or
  docstring node, and the result still parsed.
- **Line-count invariant** — every edit replaced one line with one line, so no file's line count
  changed.
- **Prompt integrity** — `EXTRACT_PROMPT` in `src/services/image_stock_extractor.py` is
  byte-identical to its snapshot (714 chars), so the `AGENTS.md` rule requiring the full prompt
  in a PR body is not triggered.

### 7.3 What was deliberately *not* touched

- **Localization cores** — `src/report_language.py`, `src/schemas/decision_action.py`,
  `src/market_phase_summary.py`, `src/services/decision_signal_summary.py`.
- **Frontend locale data** — `i18n/uiText.ts`, `locales/featureText.ts`,
  `locales/settingsHelp.ts`, `utils/systemConfigI18n.ts`.
- **All runtime strings** — logs, exceptions, notification and report bodies, UI copy, LLM
  prompts.
- **`.env.example`, `AGENTS.md` body prose, `.github/instructions/*`, `docs/**`** — out of scope
  by decision; the code-only boundary was kept deliberately.
- **`data_provider/tw_institutional_fetcher.py`** — a deliberate no-op. Its prose is already
  English and its Chinese is official Taiwan open-data dataset naming; translating it would break
  correspondence with the real TWSE/TPEx API.

### 7.4 The 396 residual lines

Not unfinished work — every line is a quoted literal that must stay Chinese:

| Count | Category |
|---:|---|
| 167 | Stock / index / sector / ETF names used as examples (`贵州茅台`, `沪深300`, `*ST美丽`) |
| 61 | Command keywords and NLP matching vocabulary (`完整` / `详细`, `_NEGATION_HINTS_ZH`, sector pools) |
| 50 | Taiwan market terminology (`三大法人`, `民國`, `西元`, `外陸資`, `政府開放資料`) |
| 48 | Live localized strings, labels and enum values (`未纳入新闻面证据`, `强烈看多`, `多头排列`) |
| 10 | Provider column names as returned by AkShare/efinance DataFrames (`日期, 开盘, 收盘, …`) |
| 10 | Doctest examples and sample payload values |
| 9 | Units and currency suffixes (`元`, `港元`, `亿元`, `万股`) |
| 5 | Commented-out legacy code, preserved verbatim with its Chinese log strings |
| 4 | Chinese `§` names cross-referencing `docs/multi-strategy-contract.md` |
| 2 | Verbatim GitHub issue / PR quotes |

Heaviest concentrations are exactly where the design predicts:
`tests/test_web_intent_tokenizer.py` (59), `src/agent/web_intent_types.py` (36),
`src/agent/web_intent_tokenizer.py` (25), `data_provider/tw_institutional_fetcher.py` (21).

### 7.5 Validation

| Check | Result |
|---|---|
| AST + token equivalence, all 210 files | PASS=210, FAIL=0 |
| `flake8 . --select=E9,F63,F7,F82` | 0 |
| Full `pytest -m "not network"` | no failure attributable to the migration |
| Frontend `npm run lint` | 0 errors, 2 pre-existing warnings — identical to baseline |
| Frontend `npm run build` | ✓ built; every baseline-recorded chunk identical in size |
| Files modified outside the intended set | 0 |
| Files carrying Chinese comments but absent from the manifest | 0 |

**One caveat on reading the test gate.** The Windows baseline is noisy: 88 failures, mostly
platform-specific (process-group kill/reap, sqlite concurrency, macOS codesign tests, local-CLI
subprocesses), several of them load-sensitive and non-deterministic. Successive full runs move
the failure count in *both* directions. The gate is therefore a **set difference with flake
tolerance — "no new failures" — never an identical failure count.** CI on `ubuntu-latest` is
substantially greener.

### 7.6 Practical effect

The codebase is now readable end-to-end by a non-Chinese-reading developer without losing any
product capability. The self-documenting parts carry their weight again — `data_provider/base.py`
announces its Strategy pattern and anti-ban design, `AgentOrchestrator` documents its four
execution modes and their relative LLM cost, and `StockAnalysisPipeline` lists its four
responsibilities — while every localized value the product actually emits is byte-for-byte
unchanged.

---

## 8. Maintaining this going forward

- Write new comments and docstrings in English (§6). Replace, never append, when translating.
- Keep quoted literals verbatim — if a comment cites a string the product emits, a column a
  provider returns, or an input a test feeds the tokenizer, do not translate it.
- Treat `src/agent/web_intent_types.py` and `web_intent_tokenizer.py` keyword tables as **data,
  not prose**. They are live matching vocabulary against Chinese LLM output.
- Beware comment *length* near window-based assertions: some tests anchor on a string in a source
  file and assert another token appears within a fixed character window, and English runs longer
  than Chinese. `src/core/pipeline.py:690-700` currently has ~30 characters of headroom.
- `bot/dispatcher.py` must never contain the substring `except Exception` in a comment — a test
  asserts its absence from the function source.
- Keep tool directives byte-exact (`# pragma: no cover`, `# noqa: BLE001`); translate only the
  prose after the dash.

---

*Generated 2026-09-19 from repository state. Verify specifics against
[docs/market-support.md](docs/market-support.md) and [docs/full-guide.md](docs/full-guide.md)
before relying on them — see [AGENTS.md](AGENTS.md) on doc drift.*

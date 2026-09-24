# DSA — End-to-End Application Assessment

Assessment date: 2026-09-20. Working tree at `C:\Ara\DSA` (not a git repository).
Scope: the full application — CLI, backend services, REST API, Web SPA, Electron desktop, bots, data providers, notifications, CI/CD, tests, and the in-flight English-language migration.

Evidence basis: direct reads of `AGENTS.md`, `HANDOFF.md`, `MIGRATION_REPORT.md`, `PRODUCT_OVERVIEW.md`, `docs/CHANGELOG.md`; four parallel code explorations (backend core, API/auth/security, frontend/desktop, data/notifications/bots/CI); and fresh local runs of the backend test suite, frontend type-check/lint/unit tests, flake8 gate, governance check, and a residual-CJK scan.

---

## 1. Executive summary

DSA (Daily Stock Analysis) is a mature, feature-rich AI stock-analysis platform (~336k lines Python, ~88k lines TypeScript, 278 backend test files, 102 frontend test files) forked from `ZhuLinsen/daily_stock_analysis`. The local copy is mid-way through a three-part **English-language migration**:

| Part | Scope | Status |
|---|---|---|
| I | Source comments/docstrings → English | Complete, mechanically verified (AST/token equivalence, 210 files) |
| II | Developer resources (governance, `.env.example`, docs) → English | Complete |
| III | The product itself → English-only surface | **In progress**: frontend lock (F1), frontend strings (F3), frontend tests (F5) and backend default `REPORT_LANGUAGE=en` (F6-minimal) done; **F2** (delete dormant zh/ko data), **F4** (translate LLM base prompts), full backend F5/F6 **open** |

**Current health**: builds and gates pass (flake8 critical 0, `tsc` 0 errors, lint 0 errors, vitest 1,203/1,206 with one load-induced timeout, pytest 6,709 pass / 96 fail where the failures match the documented Windows-only baseline band). The product is usable and the English surface works for new reports.

**Top risks**, in priority order:

1. **Default-open API with cleartext secrets.** Auth is off by default, Docker binds `0.0.0.0`, and `GET /api/v1/system/config` returns most LLM/broker/webhook keys unmasked.
2. **No version control.** All migration work (thousands of edits) exists only as uncommitted files; rollback depends on snapshots in a temp directory that can be cleaned at any time.
3. **Language split-brain.** Config defaults to `en`, but ~60 internal call sites still default to `zh`; any path that drops the language key silently produces Chinese. The Portfolio page still renders ~97 lines of hard-coded Chinese.
4. **LLM prompts are still Chinese.** English output depends on an override block appended to Chinese base prompts; translating them (F4) has no test coverage and changes model behaviour.
5. **Test suite is noisy and not isolated.** ~90 baseline failures on Windows, and tests write to the real `data/stock_analysis.db` and hit the network under the "offline" marker.

---

## 2. Overall functionality

### 2.1 What the product does

For a watchlist of stocks it runs a pipeline: fetch market data (multi-source with fallback) → technical/chip/fundamental/news enrichment → LLM analysis (single-model or multi-agent) → structured "Decision Dashboard" report → notifications → persistence and history.

### 2.2 Surfaces

| Surface | Entry point | Notes |
|---|---|---|
| CLI | `main.py` | 24 flags: `--stocks`, `--market-review`, `--schedule`, `--serve`, `--webui`, `--backtest`, `--portfolio`, `--dry-run`, `--check-notify`, … |
| REST API | `server.py` → `api/app.py`, FastAPI | 129 routes across 15 routers under `/api/v1` (68 GET, 48 POST, 8 DELETE, 3 PUT, 2 PATCH) |
| Web SPA | `apps/dsa-web` (React 18 + TS + Vite + Tailwind + Zustand) | 11 lazy-loaded routes, served from `static/` by FastAPI |
| Desktop | `apps/dsa-desktop` (Electron) | Wraps the SPA; spawns a PyInstaller backend; GitHub-release update check |
| Bots | `bot/` | DingTalk (webhook + stream), Feishu (stream), Discord (implemented, **not registered**); 10 commands |
| Automation | `.github/workflows/00-daily-analysis.yml`, Docker, `--schedule` | Weekday 18:00 Beijing time by default |

### 2.3 Feature inventory

| Area | Capability | Key modules |
|---|---|---|
| Analysis | Per-stock AI report: score, trend, entry/exit, risks, catalysts, checklist | `src/core/pipeline.py`, `src/analyzer.py` |
| Multi-agent | quick / standard / full / specialist modes; 15 YAML strategies | `src/agent/orchestrator.py`, `strategies/*.yaml` |
| Agent chat | Multi-turn streaming chat, sessions, cancel, export, push to channels | `api/v1/endpoints/agent.py`, `ChatPage.tsx` |
| Deep research | Research artifacts with thesis/evidence/invalidation | `src/agent/research.py`, `research_artifact_service.py` |
| Market review | Indices, breadth, sectors, sentiment for cn/hk/us/jp/kr | `src/core/market_review.py`, `src/market_analyzer.py` |
| Screening | Hotspot discovery, strategy screens, history | `src/services/screening_service.py`, `screening/*` |
| Backtest | Signal backtesting and performance | `src/services/backtest_service.py`, `src/core/backtest_engine.py` |
| Portfolio | Accounts, trades, lots, cash ledger, corporate actions, FX, snapshots, broker CSV, Futu import | `src/services/portfolio_service.py`, `portfolio_repo.py` |
| Alerts | Price / % change / volume / technical / event rules; worker; cooldowns | `src/services/alert_service.py`, `alert_worker.py` |
| Decision signals | Signal extraction, outcome tracking, reassessment, feedback, profile calibration | `decision_signal_service.py`, `decision_signal_outcome_service.py` |
| Intelligence | Custom RSS/feeds, templates, fetch, items | `intelligence_service.py` |
| History | Browse, diagnostics, run-flow graph, news, Markdown, share image (PNG) | `history_service.py`, `run_flow.py`, `share_image.py` |
| Usage | LLM token/cost tracking with HMAC-integrity records | `src/llm/usage.py` |
| Settings | Full env-schema-driven config UI, LLM channel editor, provider discovery, notification tests, import/export | `config_registry.py` (5.2k lines), `system_config_service.py` (5.6k lines) |
| Smart import | Image (vision LLM), CSV/Excel, clipboard; pinyin/alias autocomplete | `image_stock_extractor.py`, `stock_list_parser.py` |
| Notifications | 14 channels + 3 conversational; dedup, cooldown, quiet hours, Markdown→image | `src/notification.py`, `src/notification_sender/*`, `src/md2img.py` |
| Scheduling | Multiple daily times, run-now, hard timeout, partial-completion notify | `runtime_scheduler.py` |

### 2.4 Data sources and markets

13 fetchers behind `DataFetcherManager` (`data_provider/base.py`) with per-source priority, circuit breakers (3 failures / 300 s), thread-pool timeouts, and last-good caching.

| Market | Tier | Sources |
|---|---|---|
| A-shares (CN) | First-class | Efinance, AkShare, Tushare, Pytdx, TickFlow, Baostock, Tencent, YFinance |
| Hong Kong | First-class | Futu, Longbridge, AkShare, YFinance |
| US | First-class | Longbridge, YFinance, Finnhub, AlphaVantage, Stooq |
| Taiwan | Near first-class single-stock | YFinance + TWSE/TPEx institutional open data |
| Japan / Korea | Suffix-only MVP | YFinance only |

### 2.5 LLM abstraction

Three backend types: `litellm` (Router with multi-channel, multi-key load balancing, fallback chain, prompt-cache caps), and generation-only local CLIs (`codex_cli`, `claude_code_cli`, `opencode_cli`) via hardened subprocess presets plus a JSON-RPC Codex app-server transport. Only `litellm` is agent-capable at runtime.

### 2.6 Persistence

SQLite via SQLAlchemy (WAL, busy timeout). 32 tables. **No Alembic**; schema is `create_all` plus hand-rolled `_ensure_*` ALTER routines that are SQLite-gated. `schema_migrations` holds one baseline row.

---

## 3. Changes made (local working tree vs upstream)

There is no git history, so this is reconstructed from `HANDOFF.md`, `MIGRATION_REPORT.md`, and `docs/CHANGELOG.md [Unreleased]`.

### 3.1 Part I — comments and docstrings (complete)

- 210 files in scope, 182 edited, 7,112 lines rewritten; CJK in comments 75,216 → 2,028 chars (97.3%). The residual 396 lines are itemised preserved literals (stock names, live localized strings, Taiwan terminology, NLP vocab).
- Zero executable change, proven per file by AST comparison (docstrings stubbed) + token stream (comments removed), and comment-stripped byte equality for TS/JS.
- Independent third-session re-verification fixed two spacing defects and corrected one over-strong test-delta claim.

### 3.2 Part II — developer resources (complete)

- `AGENTS.md`, `SKILL.md`, PR template, Copilot mirror → English.
- `.env.example`: 442 CJK lines → 5 (byte-identical `KEY=value` tokens enforced by a guard).
- All 7 `*_EN.md` docs promoted to primary; Chinese variants and `README_CHT` deleted. ~30 further docs translated, anchors re-mapped, 6 test files retargeted.
- Deliberately frozen: `docs/CHANGELOG.md` (parsed by `build_release_notes.py` for `### 发布亮点`), `strategies/*.yaml` bodies, `image-extract-prompt.md` fence, public-facing `stale.yml`/`pr-review.yml`.

### 3.3 Part III — English-only product (in progress)

| Step | Done | Detail |
|---|---|---|
| F1 language lock | ✅ | `UiLanguage` resolved to constant `'en'`; toggle component deleted with 4 mount sites; `document.lang='en'`; report chrome forced English |
| F3 hardcoded strings | ✅ (mostly) | ~500 replacements across 44 files; matchers against backend/model output intentionally kept Chinese; `formatAmount` switched 亿/万 → B/M/K |
| F5 frontend tests | ✅ | 601 → 0 failures via derived zh→en maps (3,057 pairs) and hand fixes; several product fixes made in passing (settings-field title precedence, English chat intent regexes, tooltip a11y, relative fixture dates) |
| F6 backend default | ✅ minimal | `REPORT_LANGUAGE` default → `en` in `report_language.py`, `config.py`, `config_registry.py`, `.env.example`; 19 tests retargeted |
| F2 delete dormant zh/ko | ❌ | ~38k CJK chars of unreachable dictionaries remain |
| F4 translate LLM prompts | ❌ | Base prompts still Chinese; English via override block |
| F5/F6 backend internals | ❌ | ~60 `"zh"` internal defaults untouched (first attempt caused 83 failures, reverted) |
| Docs | ❌ | `CHANGELOG [Unreleased]` has 2 entries but AGENTS.md-mandated screenshots not produced |

### 3.4 Other artefacts added locally

`HANDOFF.md`, `MIGRATION_REPORT.md`, `PRODUCT_OVERVIEW.md`, `updated_product_overview.md`, `.venv/`, `static/` rebuilt (fingerprint verified current with `apps/dsa-web/src`), `data/stock_analysis.db` created by runs/tests.

---

## 4. Current state (verified 2026-09-20)

| Gate | Result | Comment |
|---|---|---|
| `flake8 --select=E9,F63,F7,F82` | 0 | Only critical rules are enforced anywhere |
| `python scripts/check_ai_assets.py` | **ERROR** | `CLAUDE.md` is a 9-byte plain file, not a symlink (Windows checkout artefact; CI on Linux passes) |
| `pytest -m "not network"` | 96 failed / 6,709 passed / 5 skipped, 12m27s | Baseline documented as 87–90; all failures fall in known Windows clusters (see below) |
| `tsc -p tsconfig.app.json --noEmit` | 0 errors | |
| `eslint .` | 0 errors, 2 warnings | Both pre-existing `react-hooks/exhaustive-deps` in `StockScreeningPage.tsx` |
| `vitest run` | 1 failed / 1,203 passed / 2 skipped | Failure is a 5 s timeout in `ReportMarkdownDrawer.test.tsx` while pytest ran concurrently; suite was green in an isolated run |
| `static/build-info.json` | current | `sourceFingerprint` recomputed and matches; version `0.0.0`/`unknown` because no git |
| Playwright e2e | not run | Skipped unless `DSA_WEB_SMOKE_PASSWORD` is set |

**Backend failure clusters (96)**: Codex app-server gate (31), agent backend status (14), local CLI backend (13), Codex tool process (12), storage/LLM-usage SQLite migrations (11), runtime scheduler (5), decision-signal TTL (4), packaging/macOS signature (2), misc concurrency (4). These are process-group kill/reap, PID-file races, and SQLite concurrency tests that CI on Ubuntu passes. None reads translated text.

**Runtime environment**: no `.env` exists, `logs/` is empty, so the app has not been run locally beyond tests. The database has 1,393 `llm_usage` rows and 3 `intelligence_sources` with fetch timestamps during the test run — see Gap G5.

**Residual CJK in non-comment code** (excluding tests/docs): 248 files, ~121k chars, dominated by dormant frontend dictionaries (`settingsHelp.ts` 14k, `uiText.ts` 7k, `systemConfigI18n.ts` 4k), LLM prompts (`analyzer.py` 6.3k, `agent/executor.py` 4k, `market_analyzer.py` 1.7k, `core/market_strategy.py` 1.3k), localization tables (`report_language.py` 2.1k, intentional), and provider column names / parse maps (`akshare_fetcher.py` 2.1k, `share_image.py` 1.7k).

---

## 5. Gaps

### 5.1 Product / migration gaps

| # | Gap | Evidence |
|---|---|---|
| G1 | **Portfolio page body is still Chinese** — ~97 live lines: account creation, trade/cash/corporate-action forms, CSV import, event log, warnings | `apps/dsa-web/src/pages/PortfolioPage.tsx:320–1535` |
| G2 | **Backend internal `"zh"` defaults** (~60 sites) contradict the `en` config default; a dropped language key yields Chinese | `src/agent/executor.py:556,685,860`, `orchestrator.py:1159,1183`, `agents/base_agent.py:193`, `decision_agent.py:36`, `notification.py:114,414`, `analyzer.py:840,851` |
| G3 | **LLM base prompts are Chinese**; English relies on an appended "Output Language (highest priority)" block. `strategies/*.yaml` `instructions:` blocks are Chinese prompts | `src/analyzer.py:2392–2404, 2091, 2277`, `agent/executor.py:483–506` |
| G4 | **Chinese reaches API consumers**: OpenAPI schema descriptions, run-flow lane labels, SSE progress messages, CLI `--help`, startup prints, Feishu sender logs | `api/v1/schemas/history.py` (137 lines), `analysis.py` (108), `services/run_flow.py:22–27`, `pipeline.py:829,836`, `main.py:301+`, `webui.py:34–35` |
| G5 | **Tests are not isolated from the real DB or network** — `conftest.py` never overrides `DATABASE_PATH`; RSS sources were fetched and rows written to `data/stock_analysis.db` during an "offline" run | `tests/conftest.py`, `src/config.py:2135`, DB `intelligence_sources.last_fetched` |
| G6 | **Korean is half-implemented**: context-pack prompt collapses `ko` → `en`; frontend now asserts `ko` → `en` | `src/analysis_context_pack_prompt.py:106` |
| G7 | **Dormant zh/ko dictionaries** (~38k chars) still type-required via `Record<UiLanguage,…>`; ~14 components still index them; two tests (`settingsHelp.test.ts`, `system_config_i18n.test.ts`) pin the Chinese data | `i18n/uiText.ts:1`, `locales/settingsHelp.ts` |
| G8 | Old stored reports keep Chinese narrative forever; no re-render or migration path | HANDOFF III.13 |
| G9 | `CHANGELOG.md` frozen in Chinese because release tooling parses `### 发布亮点`; new entries are English → mixed-language file with mixed type tokens | `.github/scripts/build_release_notes.py` |
| G10 | Discord bot platform implemented and tested but never registered | `bot/platforms/__init__.py:18–20` vs `bot/platforms/discord.py:29` |
| G11 | Chat lowercase-ticker hint regex is Chinese-context-only; English "compare"/"switch" intents were added but ticker hinting is off for English | `utils/chatStockCode.ts` |
| G12 | Japan/Korea: no breadth/sector, no Market Light alerts, no autocomplete seed for TW; ambiguous bare 6-digit codes may fall to A-share semantics | `docs/market-support.md:15,128` |

### 5.2 Engineering / process gaps

| # | Gap | Evidence |
|---|---|---|
| E1 | **No git repository.** Rollback = snapshots in `%TEMP%` scratchpads from four different sessions | HANDOFF D3, R7, R12 |
| E2 | No Alembic; schema evolution via SQLite-only `_ensure_*` ALTERs that silently no-op on other engines | `src/storage.py:1435,1643,1859,1968` |
| E3 | flake8 enforces only E9/F63/F7/F82; `unit`/`integration` markers declared but unused; no mypy | `scripts/ci_gate.sh:15`, `setup.cfg` |
| E4 | `network-smoke` workflow has `continue-on-error` on both steps — can never fail; only 4 tests carry `@pytest.mark.network` | `.github/workflows/network-smoke.yml` |
| E5 | `ci-test-durations.json` stale: 258 entries vs 278 test files → shard imbalance | `.github/ci-test-durations.json` |
| E6 | `ErrorHandlerMiddleware` defined but never registered (dead code that would leak `str(e)` in DEBUG) | `api/middlewares/error_handler.py:24,65` |
| E7 | Playwright e2e skipped without a password env var; specs still force `locale: 'zh-CN'` and seed `dsa.uiLanguage='zh'` | `apps/dsa-web/playwright.config.ts:36`, `e2e/report-markdown.spec.ts:16` |
| E8 | Duplicated helpers: 4× `_safe_float`, 3× `_escape_md`; two parallel report renderers (hand-built Markdown vs Jinja, Jinja off by default) | `analyzer.py:586`, `notification.py:94`, `report_renderer.py` |
| E9 | 935 broad `except Exception`/bare `except` in backend; 22 end in `pass` | `pipeline.py` (49), `screening_service.py` (41), `storage.py` (31) |
| E10 | Giant modules: 10 files over 2,900 lines; `StockAnalysisPipeline` ~4,000 lines / 70+ methods; 6 frontend pages over 1,600 lines | see §4 |
| E11 | Documentation drift: `data_provider/__init__.py` priority comment omits TickFlow/Futu/Finnhub/AlphaVantage; `NotificationService` docstring says "concurrently" but sends sequentially; `updated_product_overview.md` describes deleted bilingual docs | `data_provider/__init__.py:12–33`, `notification.py:283` |
| E12 | Hidden dependency time bombs: `wkhtmltopdf` removed from Debian testing (Docker pinned to bookworm); `futu-api==10.8.6808` exact pin; Docker gets Longbridge 0.2.x while desktop CI gets 4.x; `newspaper3k` unmaintained; no `requires-python` | `requirements.txt`, `docker/Dockerfile:20` |

---

## 6. Risks

Severity scale: **Critical** (exploitable or unrecoverable now), **High** (likely to cause user-visible failure or wrong output), **Medium**, **Low**.

| # | Risk | Sev | Detail |
|---|---|---|---|
| R1 | **Unauthenticated secret exposure** | Critical | `ADMIN_AUTH_ENABLED=false` by default; Docker compose binds `0.0.0.0:8000`; `GET /api/v1/system/config` returns OpenAI/Anthropic/Gemini/broker/webhook keys in cleartext (only 4 Hermes/HMAC keys masked: `system_config_service.py:203–208`). `/docs` and `/openapi.json` are exempt even with auth on. `DSA_DESKTOP_MODE=true` bypasses the `.env` export/import gate entirely. |
| R2 | **Irrecoverable working tree** | Critical | No git. Thousands of behaviour-changing edits (Part III) with no diff, no revert, and rollback snapshots in temp folders that Windows may purge. A single bad bulk edit is unrecoverable. |
| R3 | **Prompt translation changes model behaviour with no detection** (F4) | High | The suite mocks the LLM; JSON adherence, decision distribution, and refusal rate can shift silently. `evals/agent_trajectory` exists but is a reporter, not a gate. |
| R4 | **Language split-brain produces Chinese output in an "English" product** | High | G2 + G4 + G1. Any bot/API/agent path that omits `report_language` renders Chinese; OpenAPI and run-flow already do. |
| R5 | **Confident reports built from heuristics** | High | Agent→result conversion has a large fallback ladder (`pipeline.py:2320–2662`) and `apply_placeholder_fill` on the legacy path; LLM failures can surface as complete-looking dashboards. |
| R6 | **SSRF / internal port scanning via config endpoints** | High | `_is_safe_base_url` is a metadata-IP blocklist only; `discover-models`, `test-channel`, and custom webhooks may target RFC1918/localhost. Combined with R1 this is anonymous. |
| R7 | **No CSRF protection** | Medium | SameSite=Lax cookie is the only defence; `secure` flag depends on scheme detection; auth middleware sits after CORS so 401s lack CORS headers. |
| R8 | **Flaky, environment-dependent test baseline** | Medium | ~90 Windows failures that move in both directions; gate is a manual set-difference. Real regressions can hide inside the noise. |
| R9 | **Tests mutate production data** | Medium | Real `data/stock_analysis.db` grows during test runs; RSS fetched under the offline marker (G5). |
| R10 | **Schema drift on non-SQLite deployments** | Medium | `_ensure_*` routines skip silently; missing `canonical_id`, `decision_profile`, telemetry columns with no error. |
| R11 | **Dormant-code rot (R14 in HANDOFF)** | Medium | 38k chars of unreachable zh/ko plus 60 `"zh"` defaults invite either accidental resurrection or "cleanup" that breaks bot alias matching (`strategies/*.yaml aliases`). |
| R12 | **Logout invalidates all sessions** | Low | Logout rotates the global session secret (`auth.py:475`). Single-user product, so low impact today. |
| R13 | **Release automation coupled to Chinese changelog** | Low | Any attempt to translate `CHANGELOG.md` breaks `build_release_notes.py` and 16+ tests. |
| R14 | **Supply chain / pins** | Low–Med | `wkhtmltopdf` availability, dual Longbridge SDK versions, unpinned `httpx[socks]`/`lxml_html_clean`, tag-pinned GitHub Actions (`anothrNick/github-tag-action@v1`), affiliate `?aff=` links baked into provider templates. |
| R15 | **Desktop main window not sandboxed; unsigned builds** | Low | `contextIsolation` and preload are correct, but `sandbox: true` is missing on the main window; macOS/Windows builds are unsigned by design. |

---

## 7. Recommendations

Ordered by leverage. Items 1–3 should happen before any further migration work.

### 7.1 Immediate (this week)

1. **`git init` and commit the current tree.** This is the single highest-value action. It converts an unrecoverable migration into a normal one, gives `static/build-info.json` a real revision, and costs nothing (upstream sync was already abandoned). Copy the four scratchpad snapshot folders into a `migration-snapshots/` branch or archive before they are purged.
2. **Close the secret-exposure hole.** Apply `is_sensitive` redaction on the read path of `GET /system/config` (the schema already knows which fields are sensitive); return a mask token, as the write path already accepts. Make the Docker compose default `ADMIN_AUTH_ENABLED=true` or bind `127.0.0.1`, and gate `/docs`/`/openapi.json` behind auth. Extend the SSRF check to block RFC1918/loopback unless an explicit `ALLOW_PRIVATE_LLM_HOSTS` flag is set (needed for Ollama).
3. **Isolate tests.** In `tests/conftest.py`, set `DATABASE_PATH` to a `tmp_path` SQLite file and default `LOG_DIR`/`DATA_DIR` similarly; mark the intelligence-fetch tests `network` or mock the RSS client. Delete or regenerate `data/stock_analysis.db` afterwards.

### 7.2 Finish the English migration safely (next 2–4 weeks)

4. **Fix the Portfolio page (G1)** — a straightforward F3 continuation; add a vitest assertion that no CJK renders in the default English tree for each page (a regex over `container.textContent`) so this class of leak cannot recur.
5. **Resolve the language split-brain (G2)** at a single chokepoint: make every `report_language` parameter/default read from `Config` (or a `get_default_report_language()` helper) instead of literal `"zh"`. Do this as one atomic change with its 83 test updates, on a branch, under git.
6. **Translate API-visible strings (G4)**: OpenAPI descriptions, run-flow lane labels, SSE progress messages, CLI help, startup prints. These are pure display strings with no parse coupling and are cheap wins.
7. **Defer F4 (prompt translation) until an eval exists.** Adopt HANDOFF option A: freeze ~30 symbols across CN/HK/US, run zh-prompt vs en-prompt through the real model, and diff JSON-validity rate, schema conformance, and decision-type distribution. Ship English prompts behind a flag (option C) only once A passes. Do not translate `strategies/*.yaml aliases`/`display_name`; add a test that asserts they remain Chinese (HANDOFF R13).
8. **Decide F2 explicitly.** Either delete the zh/ko halves and narrow `UiLanguage` to `'en'` (removing the two tests that pin Chinese data), or keep them and add the R14 "dormancy" tests. Do not leave it undecided; the dormant data is already 38k chars.
9. **Unfreeze the changelog** by teaching `build_release_notes.py` to accept both `### 发布亮点` and `### Release highlights` and by retargeting its tests; then translate historic entries or add an English-only cut-over marker.

### 7.3 Engineering hygiene (ongoing)

10. **Stabilise the test baseline**: quarantine the Windows-only process-group/SQLite-concurrency tests with `@pytest.mark.skipif(sys.platform == "win32")` or a `platform_posix` marker so the local gate is green and regressions are visible; regenerate `ci-test-durations.json`; make `network-smoke` fail on red (or at least open an issue).
11. **Add real static gates**: broaden flake8 (or switch to ruff) beyond E9/F7; add `mypy` to the touched-files set; enforce `requires-python >=3.10` in `pyproject.toml`; SHA-pin third-party GitHub Actions.
12. **Adopt Alembic** (or at least version the `_ensure_*` routines in `schema_migrations`) and make non-SQLite engines fail loudly rather than skip.
13. **Wire or delete dead code**: register `ErrorHandlerMiddleware` intentionally or remove it; register `DiscordPlatform` or remove it from the tree; decide the fate of the Jinja `report_renderer` path.
14. **Reduce blast radius in the giants**: split `StockAnalysisPipeline` (fetch / enrich / LLM / persist / notify) and the six 1,600+-line pages; consolidate `_safe_float`/`_escape_md`; compare `errorCode` instead of a rendered title in `isUnrecoverableScreenTaskError`.
15. **Security follow-ups**: CSRF token or `SameSite=Strict` for state-changing routes; per-session tokens instead of a global secret so logout is per-device; `sandbox: true` on the Electron main window; move auth middleware before CORS so 401s carry CORS headers.
16. **Documentation**: produce the AGENTS.md-required screenshots for the F1/F3 UI change; regenerate `updated_product_overview.md` or mark it historical; fix the `data_provider/__init__.py` priority comment and the "concurrently" docstring; add the R9 product statement ("interface and analysis are English; instrument names and headlines appear as the exchange publishes them") to the README.

---

## 8. What was and was not verified

**Verified locally**: flake8 gate, governance check, full offline pytest (96/6,709), `tsc`, `eslint`, `vitest`, `static/` fingerprint, SQLite table inventory, CJK residual scan, file-level reads of every finding cited above.

**Not verified**: Playwright e2e (needs a password env var and a running backend), Docker build, GitHub Actions workflows, desktop packaging, any live LLM or data-provider call, and the claim that all 96 pytest failures pass on Ubuntu (taken from HANDOFF and CI configuration, not re-run here).

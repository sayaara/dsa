# DSA (Daily Stock Analysis) — Product Overview

> Source repository: [ZhuLinsen/daily_stock_analysis](https://github.com/ZhuLinsen/daily_stock_analysis)
> This document is a generated summary based on the current state of [README.md](README.md), [AGENTS.md](AGENTS.md), [docs/market-support.md](docs/market-support.md), and the source tree. It is not a substitute for [docs/full-guide.md](docs/full-guide.md).

## 1. Application Overview

DSA is an AI-powered stock intelligence system. For a user-configured watchlist, it runs a daily (or on-demand) pipeline that:

1. **Fetches data** — quotes, K-line/history, technical indicators, news, announcements, and fundamentals from multiple data providers with automatic fallback.
2. **Runs technical + news/sentiment analysis** on top of that data.
3. **Sends the analysis to an LLM** (any OpenAI-compatible / LiteLLM-routed model) to produce a structured decision report.
4. **Renders a report** — a "Decision Dashboard" with score, trend, buy/sell levels, risk alerts, catalysts, and an action checklist.
5. **Pushes notifications** to one or more channels (Telegram, Discord, Slack, Email, and others).

Key surfaces:

- **CLI** — [main.py](main.py) is the primary entry point (`python main.py`, `--debug`, `--dry-run`, `--stocks`, `--market-review`, `--schedule`, `--serve`, `--webui`, etc.).
- **API** — [server.py](server.py) / [api/app.py](api/app.py) exposes a FastAPI service (`uvicorn server:app`).
- **Web workspace** — [apps/dsa-web/](apps/dsa-web/), a React/TypeScript SPA for manual analysis, task monitoring, history reports, backtesting, portfolio tracking, screening, alerts, and settings.
- **Desktop app** — [apps/dsa-desktop/](apps/dsa-desktop/), an Electron wrapper around the Web workspace.
- **Chat/Agent** — a conversational "ask about a stock" agent (`/chat`) backed by 15+ built-in strategy skills (moving-average golden cross, Chan theory, wave theory, bull trend, hot themes, event-driven, growth quality, expectation repricing, etc.), reachable from Web, bot platforms, and API.
- **Bots** — [bot/](bot/) integrates with chat platforms (Discord) for interactive querying, in addition to one-way push notifications.
- **Automation** — GitHub Actions workflows, Docker deployment, and local scheduling (`--schedule`) for unattended daily runs.

The project explicitly disclaims investment advice — output is AI-generated and for research/reference only.

## 2. Architecture

### 2.1 High-level flow

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
src/notification_sender/*  ──► Telegram / Discord / Slack / Email / ...
```

### 2.2 Backend layout (Python)

| Path | Responsibility |
|---|---|
| [main.py](main.py) | CLI entry point and task orchestration (analysis run, market review, scheduling, serving) |
| [server.py](server.py) | FastAPI app entry (`uvicorn server:app`) |
| [src/core/](src/core/) | Core orchestration: `pipeline.py` (main run pipeline), `market_review.py`, `market_profile.py`, `market_strategy.py`, `trading_calendar.py`, `backtest_engine.py`, `config_manager.py` |
| [src/services/](src/services/) | Business/service layer (62 modules) — analysis, history, decision signals, backtesting, screening, alerts, task queue, etc. |
| [src/repositories/](src/repositories/) | Data access layer (persistence for history, portfolio, config, etc.) |
| [src/schemas/](src/schemas/) | Pydantic/data-structure contracts shared across pipeline, API, and Web |
| [src/agent/](src/agent/) | Agent/strategy orchestration for the chat "ask about a stock" feature (`orchestrator.py`, `executor.py`, `agents/`) |
| [src/report_language.py](src/report_language.py), [src/reports (rendering helpers)](src/) | Report localization and rendering |
| [data_provider/](data_provider/) | Adapters for market data/news sources with source-priority and fallback logic (AkShare, Tushare, Baostock, Pytdx, Efinance, YFinance, Longbridge, Futu, Finnhub, AlphaVantage, Tencent, TickFlow) |
| [api/](api/) | FastAPI routers/middleware (`app.py`, `deps.py`, `middlewares/`, `v1/`) |
| [bot/](bot/) | Chat-platform integrations (`dispatcher.py`, `handler.py`, `platforms/`: Discord) |
| [src/notification_sender/](src/notification_sender/) | One sender module per push channel (Telegram, Discord, Slack, Email, Gotify, ntfy, Pushover, PushPlus, custom webhook, AstrBot) |
| [templates/](templates/) | Jinja2 report templates |
| [scripts/](scripts/) | Local operational scripts (incl. `ci_gate.sh`, stock index seed builders) |
| [tests/](tests/) | Pytest suite |

### 2.3 Frontend

- **Web** ([apps/dsa-web/](apps/dsa-web/)): React + TypeScript SPA with `api/` (backend client), `components/`, `pages/`, `stores/`, `hooks/`, `contexts/`, `i18n/`, `locales/`. Built with `npm run build`; served by the FastAPI backend or run standalone in dev.
- **Desktop** ([apps/dsa-desktop/](apps/dsa-desktop/)): Electron shell (`main.js`, `preload.js`, `renderer/`) that packages the Web workspace as a native app, with its own update/version-check flow.

### 2.4 Deployment / automation

- **GitHub Actions** (recommended path): fork the repo, configure secrets (LLM key, notification webhook, `STOCK_LIST`, optional news-search keys), enable Actions; a scheduled workflow runs on weekday evenings (Beijing time) and skips non-trading days.
- **Docker**: see [docker/](docker/) and [docs/DEPLOY.md](docs/DEPLOY.md) — build includes a smoke test that imports key modules.
- **Local**: `pip install -r requirements.txt`, configure `.env` from [.env.example](.env.example), run `python main.py` (optionally `--schedule`, `--webui`, `--serve`).
- **CI gates** (see [AGENTS.md](AGENTS.md)): `ai-governance`, `backend-gate` (`./scripts/ci_gate.sh`), `docker-build`, `web-gate` (on frontend changes); `network-smoke` and `pr-review` are non-blocking.

## 3. Share Markets Supported

Market support is tiered — some markets have full first-class support, others are suffix-only MVPs with explicit, documented limitations. See [docs/market-support.md](docs/market-support.md) for the authoritative, up-to-date boundary.

| Market | Code format | Status | Notes |
|---|---|---|---|
| **A-share (China Mainland)** | 6-digit numeric (e.g. `600519`), plus registered indices (e.g. `sh000016`) | First-class | Full data breadth: quotes, fundamentals, capital flow, dragon-tiger list (龙虎榜), sector/board rankings, margin trading, etc. Multiple redundant data sources (AkShare, Tushare, Baostock, Pytdx, Efinance). |
| **Hong Kong (HK)** | e.g. `hk00700` | First-class | Included in market review and standard analysis pipeline. |
| **US** | Ticker (e.g. `AAPL`) | First-class | Included in market review and standard analysis pipeline; optional social sentiment (Reddit/X/Polymarket via Stock Sentiment API) is US-only. |
| **Japan (JP)** | Yahoo Finance suffix `.T` (e.g. `7203.T`, `6758.T`) | Suffix-only MVP | Quotes via `YfinanceFetcher` only (no A-share-specific sources); trading calendar `XTKS`/Asia-Tokyo; main indices `^N225` (Nikkei 225), `^TOPX` (TOPIX); included in `MARKET_REVIEW_REGION`. No full fundamentals/sector breadth/market breadth; limited stock-index seed list for autocomplete. |
| **South Korea (KR)** | Yahoo Finance suffix `.KS` (KOSPI, e.g. `005930.KS`) / `.KQ` (KOSDAQ, e.g. `035720.KQ`) | Suffix-only MVP | Same constraints as JP; trading calendar `XKRX`/Asia-Seoul; main indices `^KS11` (KOSPI), `^KQ11` (KOSDAQ). |
| **Taiwan (TW)** | `.TW` for TWSE-listed (e.g. `2330.TW`, `0050.TW`), `.TWO` for TPEx/OTC (e.g. `6488.TWO`) — strictly suffix-only, bare numeric codes are **not** treated as Taiwan | Near first-class for single-stock analysis | Trading calendar `XTAI`/Asia-Taipei; main indices `^TWII` (weighted index), `^TWOII` (OTC index); TWD currency labeling; institutional flow data (foreign/investment trust/dealer) via TWSE T86 / TPEx OpenAPI. Not yet in `MARKET_REVIEW_REGION`, no stock-index seed/autocomplete, no Market Light alerts. |
| **ETFs** | Varies by market | Supported | Listed alongside equities in feature coverage. |

Cross-cutting notes:
- JP/KR/TW never fall back to A-share-specific data sources (AkShare/Tushare/Efinance/Pytdx/Baostock); they route exclusively through `YfinanceFetcher`.
- `MARKET_REVIEW_REGION` (daily "market review") currently accepts `cn`, `hk`, `us`, `jp`, `kr`, or `both` (all five), configurable as a comma-separated subset (e.g. `cn,us,jp`). Taiwan is not yet part of market review.
- Market Light alerts (real-time alert monitoring) currently only support `cn` / `hk` / `us`.
- Portfolio tracking accepts JP/KR/TW positions but marks them `data_quality=partial` (no FX/cost-basis/sector-risk completeness guarantee).

## 4. Non-English Languages Supported (and How)

DSA supports **Chinese (zh), English (en), and Korean (ko)**, applied at two independent layers:

### 4.1 Report / analysis output language — `REPORT_LANGUAGE`

Controlled by the `REPORT_LANGUAGE` environment variable (`.env`, see [.env.example](.env.example) line ~748):

```
REPORT_LANGUAGE=zh   # zh (default) / en / ko
```

Implementation: [src/report_language.py](src/report_language.py)

- `SUPPORTED_REPORT_LANGUAGES = ("zh", "en", "ko")`.
- `normalize_report_language()` accepts many aliases (`zh-cn`, `zh_hans`, `cn`, `chinese`, `en-us`, `english`, `kr`, `korean`, `ko-kr`, ...) and normalizes them to one of the three supported short codes, defaulting to `zh`.
- A full set of `_REPORT_LABELS` dictionaries provide localized UI copy for every report section (dashboard title, risk alerts, financial summary, institutional flow, signal attribution, strategy synthesis, etc.) in all three languages.
- Dedicated translation maps + `localize_*()` helper functions normalize and translate domain-specific terms regardless of what language the LLM happened to emit them in — e.g. operation advice (买入/Buy/매수), trend prediction (看多/Bullish/상승), confidence level, strategy signal, consensus level, conflict severity, strategy skill names (15 built-in strategies), chip-distribution health, and price-bias status.
- This affects the LLM prompt's requested output language as well as the deterministic (non-LLM) report scaffolding, so both AI-generated prose and templated fields are localized consistently.
- This is a runtime/report setting — it determines the language of generated analysis reports and push notifications, independent of who is running the tool.

### 4.2 Web/Desktop UI language — English-only

Implementation: [apps/dsa-web/src/i18n/uiText.ts](apps/dsa-web/src/i18n/uiText.ts) and [apps/dsa-web/src/utils/uiLanguage.ts](apps/dsa-web/src/utils/uiLanguage.ts)

- The Web/Desktop interface renders in **English only**; the resolved `UiLanguage` is locked to `'en'` and the former in-app language toggle has been removed. This is independent of the analysis `REPORT_LANGUAGE` setting (which defaults to `en`).
- All UI strings (navigation, buttons, settings labels, etc.) are keyed dictionaries (`common.*`, `layout.*`, `language.*`, `theme.*`, ...) with parallel `zh`/`en` entries, plus locale-aware helpers in `apps/dsa-web/src/utils/systemConfigI18n.ts` (tested by `apps/dsa-web/tests/system_config_i18n.test.ts`).
- Additional locale resources live under `apps/dsa-web/src/locales/`.

### 4.3 Documentation localization

The repository itself ships bilingual/trilingual docs, maintained as separate parallel files (not auto-generated):

- [README.md](README.md) (Simplified Chinese, default) / [README.md](README.md) (English).
- Most major docs have an `_EN` counterpart, e.g. [docs/full-guide.md](docs/full-guide.md) / [docs/full-guide.md](docs/full-guide.md), [docs/DEPLOY.md](docs/DEPLOY.md) / [docs/DEPLOY.md](docs/DEPLOY.md), [docs/FAQ.md](docs/FAQ.md) / [docs/FAQ.md](docs/FAQ.md), [docs/INDEX.md](docs/INDEX.md) / [docs/INDEX.md](docs/INDEX.md), [docs/bot-command.md](docs/bot-command.md) / [docs/bot-command.md](docs/bot-command.md), [docs/LLM_CONFIG_GUIDE.md](docs/LLM_CONFIG_GUIDE.md) / [docs/LLM_CONFIG_GUIDE.md](docs/LLM_CONFIG_GUIDE.md), [docs/CONTRIBUTING.md](docs/CONTRIBUTING.md).
- Per [AGENTS.md](AGENTS.md) §1: whenever one language version of a bilingual doc changes, contributors must evaluate whether the other needs a matching update (and state the reason if not synced).

---
*Generated on 2026-09-19 from repository state; verify against [docs/market-support.md](docs/market-support.md) and [docs/full-guide.md](docs/full-guide.md) before relying on specifics, as these evolve quickly (see AGENTS.md guidance on doc drift).*

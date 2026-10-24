# Web smoke tests (Playwright)

The Playwright specs in `apps/dsa-web/e2e/` drive the Web UI in Chromium against a real backend:

| Spec | What it checks | Needs the backend |
| --- | --- | --- |
| `smoke.spec.ts` | Login page, home page, Ask (chat) page, mobile navigation, settings, backtest | Yes, with a login |
| `report-markdown.spec.ts` | The "Full analysis report" drawer: copy Markdown, copy plain text, mobile layout | Yes, with a login and one stored analysis |
| `market-structure-card-visual.spec.ts` | Renders `MarketStructureCard` from US sample data and saves a screenshot | No (builds its own fixture page) |

The two backend specs skip themselves unless `DSA_WEB_SMOKE_PASSWORD` is set. When it is set, `playwright.config.ts` starts the backend (`main.py --webui-only` on port 8000) and the Vite dev server (port 4173, which proxies `/api` to the backend).

## In CI

The `web-e2e` job in `.github/workflows/ci.yml` runs all three specs when `apps/dsa-web/`, `api/`, `src/auth.py`, `scripts/seed_web_smoke_data.py` or the workflow changes. It installs Chromium with its system packages, points `ENV_FILE` and `DATABASE_PATH` at a throwaway directory, prepares it with `scripts/seed_web_smoke_data.py`, starts the backend without `GITHUB_ACTIONS` (`main.py` never serves when it is `true`, to protect the daily analysis workflow), and uploads `apps/dsa-web/test-results/` (screenshots, traces, videos of failures) as the `web-e2e-results` artifact.

## Locally

`scripts/seed_web_smoke_data.py` prepares the backend:

- writes `ENV_FILE` when it does not exist: admin login on, `WEBUI_AUTO_BUILD=false` (the specs use the Vite dev server, so the backend must not build the frontend or reinstall `node_modules` at startup), and a placeholder OpenAI-compatible model (`openai/web-smoke-model`) whose base URL is a closed local port, so the Ask page accepts a question while any model request fails at once and nothing leaves the machine;
- sets the admin password to `DSA_WEB_SMOKE_PASSWORD` when none is set yet;
- saves one AAPL analysis, so the history list and the full report drawer have content.

Use throwaway paths; never point it at a real deployment's `.env` or data. The backend reads only `ENV_FILE` when it is set (the repository `.env` is ignored).

```bash
cd apps/dsa-web
npx playwright install chromium
sudo npx playwright install-deps chromium   # once per machine (Linux/WSL system libraries)
cd ../..
```

```bash
export SMOKE_DIR="$(mktemp -d)"
export ENV_FILE="$SMOKE_DIR/smoke.env" DATABASE_PATH="$SMOKE_DIR/data/stock_analysis.db"
export DSA_WEB_SMOKE_PASSWORD=web-smoke-password
python scripts/seed_web_smoke_data.py
cd apps/dsa-web && npx playwright test
```

Run the commands from the repository root (the `cd` is part of the last line). Outside CI, Playwright reuses a backend or dev server that is already listening on port 8000 or 4173; stop them first, or they must use the same `ENV_FILE` and `DATABASE_PATH`. Right after a run, the backend may refuse port 8000 for about a minute (`FastAPI port is not available`) while the old connections close; wait and run again.

Screenshots of the pages go to `apps/dsa-web/test-results/`. Attach them to a PR description or comment when a Web UI change needs visual evidence; do not commit them.

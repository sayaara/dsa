#!/usr/bin/env python3
"""Prepare an isolated backend for the Playwright web smoke specs.

Writes ``ENV_FILE`` when it does not exist yet (admin login on, no frontend
build at backend startup, and a placeholder OpenAI-compatible model whose base URL is a closed local port, so
the Ask page accepts a question but no request leaves the machine), sets the
admin password to ``DSA_WEB_SMOKE_PASSWORD`` (only when none is set yet) and
saves one AAPL analysis so the history list and the full report drawer have
content. Run it with ``ENV_FILE`` and ``DATABASE_PATH`` pointing at throwaway
files, never at a real deployment's. See ``docs/web-smoke-tests.md``.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

SEED_QUERY_ID = "web-smoke-seed-aapl"
SMOKE_ENV_LINES = (
    "ADMIN_AUTH_ENABLED=true",
    # The specs reach the UI through the Vite dev server, so the backend
    # must not build the frontend (or reinstall node_modules) at startup.
    "WEBUI_AUTO_BUILD=false",
    "DATABASE_PATH={database_path}",
    "LITELLM_MODEL=openai/web-smoke-model",
    "OPENAI_API_KEY=web-smoke-placeholder-key",
    "OPENAI_BASE_URL=http://127.0.0.1:9/v1",
)


def main() -> int:
    password = os.getenv("DSA_WEB_SMOKE_PASSWORD", "").strip()
    if not password:
        print("DSA_WEB_SMOKE_PASSWORD is not set", file=sys.stderr)
        return 1
    env_file = os.getenv("ENV_FILE", "").strip()
    database_path = os.getenv("DATABASE_PATH", "").strip()
    if not env_file or not database_path:
        print("Set ENV_FILE and DATABASE_PATH to throwaway paths before seeding", file=sys.stderr)
        return 1
    env_path = Path(env_file)
    if not env_path.exists():
        env_path.parent.mkdir(parents=True, exist_ok=True)
        env_path.write_text(
            "\n".join(SMOKE_ENV_LINES).format(database_path=database_path) + "\n",
            encoding="utf-8",
        )
    Path(database_path).parent.mkdir(parents=True, exist_ok=True)

    from src import auth
    from src.analyzer import AnalysisResult
    from src.storage import AnalysisHistory, DatabaseManager

    if not auth.is_auth_enabled():
        print("ADMIN_AUTH_ENABLED=true is missing from ENV_FILE", file=sys.stderr)
        return 1
    if not auth.is_password_set():
        error = auth.set_initial_password(password)
        if error:
            print(f"Could not set the smoke password: {error}", file=sys.stderr)
            return 1

    db = DatabaseManager.get_instance()
    with db.get_session() as session:
        exists = (
            session.query(AnalysisHistory)
            .filter(AnalysisHistory.query_id == SEED_QUERY_ID)
            .first()
            is not None
        )
    if not exists:
        result = AnalysisResult(
            code="AAPL",
            name="Apple Inc.",
            sentiment_score=62,
            trend_prediction="Bullish",
            operation_advice="Hold",
            analysis_summary="Seeded smoke-test analysis: trend intact, valuation full.",
        )
        record_id = db.save_analysis_history(
            result=result,
            query_id=SEED_QUERY_ID,
            report_type="simple",
            news_content="Seeded smoke-test news summary.",
            context_snapshot=None,
            save_snapshot=False,
        )
        if not record_id:
            print("Could not save the seeded analysis", file=sys.stderr)
            return 1

    print("Web smoke data ready")
    return 0


if __name__ == "__main__":
    sys.exit(main())

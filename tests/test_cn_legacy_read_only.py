# -*- coding: utf-8 -*-
"""Mainland China ("cn") is a legacy market: old rows keep working, but the API refuses to create new ones."""

from __future__ import annotations

import os
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

try:
    import litellm  # noqa: F401
except ModuleNotFoundError:
    sys.modules["litellm"] = MagicMock()

from fastapi.testclient import TestClient

import src.auth as auth
from api.app import create_app
from src.config import Config
from src.services.intelligence_service import IntelligenceService, IntelligenceServiceError
from src.services.portfolio_service import PortfolioService
from src.storage import DatabaseManager

SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"


class CnLegacyApiTestCase(unittest.TestCase):
    def setUp(self) -> None:
        auth._auth_enabled = None
        auth._session_secret = None
        auth._password_hash_salt = None
        auth._password_hash_stored = None
        auth._rate_limit = {}
        self.temp_dir = tempfile.TemporaryDirectory()
        data_dir = Path(self.temp_dir.name)
        db_path = data_dir / "cn_legacy_test.db"
        env_path = data_dir / ".env"
        env_path.write_text(
            "\n".join(["STOCK_LIST=AAPL", "GEMINI_API_KEY=test", "ADMIN_AUTH_ENABLED=false", f"DATABASE_PATH={db_path}"])
            + "\n",
            encoding="utf-8",
        )
        os.environ["ENV_FILE"] = str(env_path)
        os.environ["DATABASE_PATH"] = str(db_path)
        Config.reset_instance()
        DatabaseManager.reset_instance()
        self.client = TestClient(create_app(static_dir=data_dir / "empty-static"))

    def tearDown(self) -> None:
        DatabaseManager.reset_instance()
        Config.reset_instance()
        os.environ.pop("ENV_FILE", None)
        os.environ.pop("DATABASE_PATH", None)
        self.temp_dir.cleanup()

    def test_new_cn_portfolio_account_is_rejected(self) -> None:
        resp = self.client.post(
            "/api/v1/portfolio/accounts",
            json={"name": "New", "broker": "Demo", "market": "cn", "base_currency": "CNY"},
        )
        self.assertEqual(resp.status_code, 422)
        ok = self.client.post(
            "/api/v1/portfolio/accounts",
            json={"name": "Ok", "broker": "Demo", "market": "hk", "base_currency": "HKD"},
        )
        self.assertEqual(ok.status_code, 200, ok.text)

    def test_existing_cn_account_is_still_listed_edited_and_traded(self) -> None:
        legacy = PortfolioService().repo.create_account(
            name="Legacy", broker=None, market="cn", base_currency="CNY", owner_id=None
        )
        listed = self.client.get("/api/v1/portfolio/accounts")
        self.assertEqual(listed.status_code, 200, listed.text)
        self.assertIn("Legacy", [item["name"] for item in listed.json()["accounts"]])

        renamed = self.client.put(f"/api/v1/portfolio/accounts/{legacy.id}", json={"name": "Legacy renamed"})
        self.assertEqual(renamed.status_code, 200, renamed.text)

        trade = self.client.post(
            "/api/v1/portfolio/trades",
            json={
                "account_id": legacy.id,
                "symbol": "600519",
                "trade_date": "2026-01-02",
                "side": "buy",
                "quantity": 10,
                "price": 100,
            },
        )
        self.assertEqual(trade.status_code, 200, trade.text)

    def test_new_cn_intelligence_source_is_rejected_and_default_market_is_global(self) -> None:
        body = {"name": "feed", "url": "https://feeds.example.com/rss.xml", "source_type": "rss", "scope_type": "market"}
        rejected = self.client.post("/api/v1/intelligence/sources", json={**body, "market": "cn"})
        self.assertEqual(rejected.status_code, 422)

        schema = self.client.get("/openapi.json").json()["components"]["schemas"]["IntelligenceSourceCreateRequest"]
        self.assertEqual(schema["properties"]["market"]["default"], "global")


class AuditCnDataScriptTestCase(unittest.TestCase):
    def setUp(self) -> None:
        sys.path.insert(0, str(SCRIPTS_DIR))
        import audit_cn_data

        self.audit = audit_cn_data
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "audit.db"
        conn = sqlite3.connect(self.db_path)
        conn.execute("CREATE TABLE portfolio_accounts (id INTEGER PRIMARY KEY, market TEXT)")
        conn.execute("CREATE TABLE stock_daily (id INTEGER PRIMARY KEY, code TEXT)")
        conn.execute("INSERT INTO portfolio_accounts (market) VALUES ('us'), ('hk')")
        conn.execute("INSERT INTO stock_daily (code) VALUES ('AAPL'), ('00700')")
        conn.commit()
        conn.close()

    def tearDown(self) -> None:
        sys.path.remove(str(SCRIPTS_DIR))
        sys.modules.pop("audit_cn_data", None)
        self.temp_dir.cleanup()

    def test_clean_database_reports_nothing(self) -> None:
        self.assertEqual(self.audit.audit(self.db_path), {})
        self.assertEqual(self.audit.main(["--db", str(self.db_path)]), 0)

    def test_cn_rows_and_a_share_codes_are_counted_without_modifying_the_database(self) -> None:
        conn = sqlite3.connect(self.db_path)
        conn.execute("INSERT INTO portfolio_accounts (market) VALUES ('cn'), ('CN')")
        conn.execute("INSERT INTO stock_daily (code) VALUES ('600519'), ('000001.SZ'), ('600519')")
        conn.commit()
        conn.close()

        result = self.audit.audit(self.db_path)

        self.assertEqual(result["portfolio_accounts"], {"market = 'cn'": 2})
        self.assertEqual(result["stock_daily"], {"distinct six-digit code (A-share)": 2})
        self.assertEqual(self.audit.main(["--db", str(self.db_path)]), 1)
        conn = sqlite3.connect(self.db_path)
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM portfolio_accounts").fetchone()[0], 4)
        conn.close()

    def test_missing_database_is_an_error(self) -> None:
        self.assertEqual(self.audit.main(["--db", str(Path(self.temp_dir.name) / "nope.db")]), 2)


if __name__ == "__main__":
    unittest.main()

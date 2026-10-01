# -*- coding: utf-8 -*-
"""Portfolio totals, risk and defaults for non-CNY accounts (USD, CAD, HKD)."""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd

try:
    import litellm  # noqa: F401
except ModuleNotFoundError:
    sys.modules["litellm"] = MagicMock()

from api.v1.schemas.portfolio import PortfolioAccountCreateRequest
from src.config import Config
from src.services.portfolio_risk_service import PortfolioRiskService
from src.services.portfolio_service import DEFAULT_REPORTING_CURRENCY, PortfolioService
from src.storage import (
    DatabaseManager,
    PortfolioAccount,
    PortfolioCashLedger,
    PortfolioDailySnapshot,
    PortfolioPosition,
    PortfolioTrade,
)

DAY = date(2026, 1, 2)


class ReportingCurrencyTestCase(unittest.TestCase):
    def test_single_shared_base_currency_is_kept(self) -> None:
        self.assertEqual(PortfolioService.resolve_reporting_currency(["CAD"]), "CAD")
        self.assertEqual(PortfolioService.resolve_reporting_currency(["cad", " CAD ", None]), "CAD")
        self.assertEqual(PortfolioService.resolve_reporting_currency(["HKD", "HKD"]), "HKD")

    def test_mixed_or_missing_base_currencies_fall_back_to_usd(self) -> None:
        self.assertEqual(DEFAULT_REPORTING_CURRENCY, "USD")
        self.assertEqual(PortfolioService.resolve_reporting_currency(["CAD", "USD"]), "USD")
        self.assertEqual(PortfolioService.resolve_reporting_currency(["CAD", "HKD"]), "USD")
        self.assertEqual(PortfolioService.resolve_reporting_currency([]), "USD")
        self.assertEqual(PortfolioService.resolve_reporting_currency([None, ""]), "USD")

    def test_market_default_currencies(self) -> None:
        self.assertEqual(PortfolioService._default_currency_for_market("us"), "USD")
        self.assertEqual(PortfolioService._default_currency_for_market("ca"), "CAD")
        self.assertEqual(PortfolioService._default_currency_for_market("hk"), "HKD")

    def test_new_accounts_default_to_the_us_market_and_usd(self) -> None:
        request = PortfolioAccountCreateRequest(name="Main")
        self.assertEqual(request.market, "us")
        self.assertEqual(request.base_currency, "USD")
        self.assertEqual(PortfolioAccountCreateRequest(name="TFSA", market="ca", base_currency="CAD").market, "ca")

    def test_storage_defaults_are_usd_and_us(self) -> None:
        for model, column in (
            (PortfolioAccount, "base_currency"),
            (PortfolioTrade, "currency"),
            (PortfolioCashLedger, "currency"),
            (PortfolioPosition, "valuation_currency"),
            (PortfolioDailySnapshot, "base_currency"),
        ):
            self.assertEqual(getattr(model, column).default.arg, "USD", f"{model.__name__}.{column}")
        for model in (PortfolioAccount, PortfolioTrade, PortfolioPosition):
            self.assertEqual(model.market.default.arg, "us", model.__name__)


class PortfolioMultiCurrencyTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        data_dir = Path(self.temp_dir.name)
        db_path = data_dir / "portfolio_multi_currency.db"
        env_path = data_dir / ".env"
        env_path.write_text(
            "\n".join(["STOCK_LIST=AAPL", "GEMINI_API_KEY=test", "ADMIN_AUTH_ENABLED=false", f"DATABASE_PATH={db_path}"]) + "\n",
            encoding="utf-8",
        )
        os.environ["ENV_FILE"] = str(env_path)
        os.environ["DATABASE_PATH"] = str(db_path)
        Config.reset_instance()
        DatabaseManager.reset_instance()
        self.db = DatabaseManager.get_instance()
        self.service = PortfolioService()
        self.risk_service = PortfolioRiskService(portfolio_service=self.service)
        patcher = patch.object(PortfolioRiskService, "_fetch_belong_boards", return_value=[])
        patcher.start()
        self.addCleanup(patcher.stop)

    def tearDown(self) -> None:
        DatabaseManager.reset_instance()
        Config.reset_instance()
        os.environ.pop("ENV_FILE", None)
        os.environ.pop("DATABASE_PATH", None)
        self.temp_dir.cleanup()

    def _save_close(self, symbol: str, close: float) -> None:
        frame = pd.DataFrame(
            [{"date": DAY, "open": close, "high": close, "low": close, "close": close, "volume": 1.0, "amount": close, "pct_chg": 0.0}]
        )
        self.db.save_daily_data(frame, code=symbol, data_source="portfolio-multi-currency-test")

    def _account_with_position(self, name: str, market: str, currency: str, symbol: str, price: float, *, cash: float = 10000.0, qty: int = 10) -> int:
        account = self.service.create_account(name=name, broker="Demo", market=market, base_currency=currency)
        self.service.record_cash_ledger(account_id=account["id"], event_date=DAY, direction="in", amount=cash, currency=currency)
        self.service.record_trade(
            account_id=account["id"],
            symbol=symbol,
            trade_date=DAY,
            side="buy",
            quantity=qty,
            price=price,
            market=market,
            currency=currency,
        )
        self._save_close(symbol, price)
        return int(account["id"])

    def test_single_cad_account_snapshot_stays_in_cad(self) -> None:
        self._account_with_position("TFSA", "ca", "CAD", "RY.TO", 200.0)

        snapshot = self.service.get_portfolio_snapshot(as_of=DAY, cost_method="fifo", include_realtime=False)

        self.assertEqual(snapshot["currency"], "CAD")
        self.assertFalse(snapshot["fx_stale"])
        self.assertAlmostEqual(snapshot["total_market_value"], 2000.0, places=4)
        self.assertAlmostEqual(snapshot["total_equity"], 10000.0, places=4)
        position = snapshot["accounts"][0]["positions"][0]
        self.assertEqual(position["symbol"], "RY.TO")
        self.assertEqual(position["market"], "ca")

    def test_cad_and_usd_accounts_are_totalled_in_usd_with_the_stored_rate(self) -> None:
        self._account_with_position("TFSA", "ca", "CAD", "RY.TO", 200.0)
        self._account_with_position("Main", "us", "USD", "AAPL", 100.0)
        self.service.repo.save_fx_rate(
            from_currency="CAD", to_currency="USD", rate_date=DAY, rate=0.5, source="manual", is_stale=False
        )

        snapshot = self.service.get_portfolio_snapshot(as_of=DAY, cost_method="fifo", include_realtime=False)

        self.assertEqual(snapshot["currency"], "USD")
        self.assertFalse(snapshot["fx_stale"])
        # CAD: 2,000 market value * 0.5 = 1,000 USD; USD: 10 * 100 = 1,000 USD.
        self.assertAlmostEqual(snapshot["total_market_value"], 2000.0, places=4)
        self.assertAlmostEqual(snapshot["total_cash"], (10000.0 - 2000.0) * 0.5 + (10000.0 - 1000.0), places=4)

    def test_missing_fx_rate_marks_the_total_stale_instead_of_failing(self) -> None:
        self._account_with_position("TFSA", "ca", "CAD", "RY.TO", 200.0)
        self._account_with_position("Main", "us", "USD", "AAPL", 100.0)

        snapshot = self.service.get_portfolio_snapshot(as_of=DAY, cost_method="fifo", include_realtime=False)

        self.assertEqual(snapshot["currency"], "USD")
        self.assertTrue(snapshot["fx_stale"])

    def test_risk_report_concentration_is_expressed_in_the_snapshot_currency(self) -> None:
        self._account_with_position("TFSA", "ca", "CAD", "RY.TO", 200.0)

        report = self.risk_service.get_risk_report(as_of=DAY, cost_method="fifo")

        top = report["concentration"]["top_positions"]
        self.assertEqual(top[0]["symbol"], "RY.TO")
        self.assertAlmostEqual(top[0]["market_value_base"], 2000.0, places=4)

    def test_mixed_currency_concentration_uses_usd(self) -> None:
        self._account_with_position("TFSA", "ca", "CAD", "RY.TO", 200.0)
        self._account_with_position("Main", "us", "USD", "AAPL", 100.0)
        self.service.repo.save_fx_rate(
            from_currency="CAD", to_currency="USD", rate_date=DAY, rate=0.5, source="manual", is_stale=False
        )
        self.service.get_portfolio_snapshot(as_of=DAY, cost_method="fifo", include_realtime=False)

        report = self.risk_service.get_risk_report(as_of=DAY, cost_method="fifo")

        positions = {item["symbol"]: item for item in report["concentration"]["top_positions"]}
        self.assertAlmostEqual(positions["RY.TO"]["market_value_base"], 1000.0, places=4)
        self.assertAlmostEqual(positions["AAPL"]["market_value_base"], 1000.0, places=4)

    def test_drawdown_series_uses_the_shared_base_currency(self) -> None:
        self._account_with_position("TFSA", "ca", "CAD", "RY.TO", 200.0)
        self.service.get_portfolio_snapshot(as_of=DAY, cost_method="fifo", include_realtime=False)

        report = self.risk_service.get_risk_report(as_of=DAY, cost_method="fifo")

        self.assertFalse(report["drawdown"]["fx_stale"])


class SectorClassificationTestCase(unittest.TestCase):
    def _service(self, manager) -> PortfolioRiskService:
        service = PortfolioRiskService(portfolio_service=MagicMock())
        service._data_manager = manager
        return service

    def _classify(self, service: PortfolioRiskService, symbol: str, market: str):
        coverage = {"classified_count": 0, "unclassified_count": 0, "failed_count": 0}
        errors: list = []
        sector = service._resolve_primary_sector(
            symbol=symbol, market=market, board_cache={}, coverage=coverage, errors=errors
        )
        return sector, coverage, errors

    def test_us_hk_and_canadian_symbols_are_classified_from_the_fundamental_context(self) -> None:
        manager = MagicMock()
        manager.get_fundamental_context.return_value = {
            "belong_boards": [
                {"name": "Banks - Diversified", "type": "概念"},
                {"name": "Financial Services", "type": "行业"},
            ]
        }
        service = self._service(manager)
        for symbol, market in (("RY.TO", "ca"), ("AAPL", "us"), ("0700.HK", "hk")):
            sector, coverage, errors = self._classify(service, symbol, market)
            self.assertEqual(sector, "Financial Services", symbol)
            self.assertEqual(coverage["classified_count"], 1)
            self.assertEqual(errors, [])
        self.assertEqual(manager.get_fundamental_context.call_count, 3)

    def test_empty_boards_and_provider_errors_degrade_to_unclassified(self) -> None:
        manager = MagicMock()
        manager.get_fundamental_context.return_value = {"belong_boards": []}
        sector, coverage, _ = self._classify(self._service(manager), "RY.TO", "ca")
        self.assertEqual(sector, "UNCLASSIFIED")
        self.assertEqual(coverage["unclassified_count"], 1)

        manager.get_fundamental_context.side_effect = RuntimeError("boom")
        sector, coverage, errors = self._classify(self._service(manager), "SHOP.TO", "ca")
        self.assertEqual(sector, "UNCLASSIFIED")
        self.assertEqual(coverage["failed_count"], 1)
        self.assertIn("SHOP.TO", errors[0])

    def test_missing_data_manager_is_unclassified(self) -> None:
        service = PortfolioRiskService(portfolio_service=MagicMock())
        service._data_manager = None
        service._data_manager_init_error = "no manager"
        sector, coverage, _ = self._classify(service, "AAPL", "us")
        self.assertEqual(sector, "UNCLASSIFIED")
        self.assertEqual(coverage["unclassified_count"], 1)


if __name__ == "__main__":
    unittest.main()

# -*- coding: utf-8 -*-
"""Tests for LLM usage dashboard API."""

import tempfile
import unittest
from datetime import date, datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from zoneinfo import ZoneInfo

from fastapi.testclient import TestClient

from api.app import create_app
from api.deps import get_database_manager


class FakeUsageDbManager:
    def get_llm_usage_summary(self, from_dt, to_dt):
        return {
            "total_calls": 2,
            "total_prompt_tokens": 30,
            "total_completion_tokens": 70,
            "total_tokens": 100,
            "by_call_type": [
                {
                    "call_type": "analysis",
                    "calls": 2,
                    "prompt_tokens": 30,
                    "completion_tokens": 70,
                    "total_tokens": 100,
                }
            ],
            "by_model": [
                {
                    "model": "openai/gpt-test",
                    "calls": 2,
                    "prompt_tokens": 30,
                    "completion_tokens": 70,
                    "total_tokens": 100,
                    "max_total_tokens": 60,
                }
            ],
        }

    def get_llm_usage_records(self, from_dt, to_dt, limit=50):
        return [
            {
                "id": 7,
                "called_at": datetime(2026, 6, 11, 9, 30, 0),
                "call_type": "analysis",
                "model": "openai/gpt-test",
                "stock_code": "600519",
                "provider": "openai",
                "language": "zh",
                "market_group": "cn",
                "analysis_mode": "stock_analysis",
                "legacy_prompt_mode": "skill_aware",
                "skill_config_hmac": "a" * 64,
                "transport": "litellm",
                "message_count": 2,
                "estimated_total_prompt_tokens": 2000,
                "approx_common_prefix_chars": 120,
                "approx_common_prefix_tokens": 40,
                "known_dynamic_marker_positions": '[{"marker_name":"stock_code","message_role":"user","char_offset":12}]',
                "prompt_tokens": 10,
                "completion_tokens": 50,
                "total_tokens": 60,
            }
        ]


class UsageDashboardApiTestCase(unittest.TestCase):
    def test_dashboard_returns_token_summary_and_recent_calls(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            app = create_app(static_dir=Path(temp_dir))
            app.dependency_overrides[get_database_manager] = lambda: FakeUsageDbManager()
            client = TestClient(app)

            response = client.get("/api/v1/usage/dashboard?period=today&limit=10")

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["period"], "today")
        self.assertEqual(body["total_tokens"], 100)
        self.assertEqual(body["by_model"][0]["model"], "openai/gpt-test")
        self.assertEqual(body["by_model"][0]["max_total_tokens"], 60)
        self.assertNotIn("provider", body["by_model"][0])
        self.assertNotIn("context_window", body["by_model"][0])
        self.assertNotIn("context_usage_ratio", body["by_model"][0])
        self.assertEqual(body["recent_calls"][0]["stock_code"], "600519")
        p05a_internal_fields = {
            "provider",
            "language",
            "market_group",
            "analysis_mode",
            "legacy_prompt_mode",
            "skill_config_hmac",
            "transport",
            "message_count",
            "estimated_total_prompt_tokens",
            "approx_common_prefix_chars",
            "approx_common_prefix_tokens",
            "known_dynamic_marker_positions",
        }
        self.assertTrue(p05a_internal_fields.isdisjoint(body["recent_calls"][0]))
        self.assertNotIn("context_window", body["recent_calls"][0])
        self.assertNotIn("context_usage_ratio", body["recent_calls"][0])


if __name__ == "__main__":
    unittest.main()


class UsageWindowTestCase(unittest.TestCase):
    """Period bounds follow USAGE_TIMEZONE, whatever the server's own timezone is."""

    # 2026-10-10 03:30 UTC is 23:30 on 2026-10-09 in Toronto and 11:30 on 2026-10-10 in Shanghai.
    NOW = datetime(2026, 10, 10, 3, 30, tzinfo=timezone.utc)

    def _window(self, period, tz_name, now=None):
        from api.v1.endpoints import usage

        with patch("src.config.get_config", return_value=SimpleNamespace(usage_timezone=tz_name)):
            return usage._date_range(period, now or self.NOW)

    @staticmethod
    def _server_local(year, month, day, tz_name):
        # ``called_at`` is naive server-local time, so compare in that form on any machine.
        return datetime(year, month, day, tzinfo=ZoneInfo(tz_name)).astimezone().replace(tzinfo=None)

    def test_today_and_month_start_at_midnight_in_the_usage_timezone(self):
        now_local = self.NOW.astimezone().replace(tzinfo=None)
        for tz_name, day in (("America/Toronto", 9), ("Asia/Shanghai", 10)):
            today = self._window("today", tz_name)
            self.assertEqual(today.from_dt, self._server_local(2026, 10, day, tz_name), tz_name)
            self.assertEqual(today.to_dt, now_local)
            self.assertEqual((today.from_date, today.to_date), (date(2026, 10, day), date(2026, 10, day)))

            month = self._window("month", tz_name)
            self.assertEqual(month.from_dt, self._server_local(2026, 10, 1, tz_name), tz_name)
            self.assertEqual(month.from_date, date(2026, 10, 1))

    def test_default_is_toronto_and_unknown_names_fall_back(self):
        from api.v1.endpoints import usage

        self.assertEqual(usage.DEFAULT_USAGE_TIMEZONE, "America/Toronto")
        expected = self._window("today", "America/Toronto")
        self.assertEqual(self._window("today", ""), expected)
        with self.assertLogs("api.v1.endpoints.usage", level="WARNING"):
            self.assertEqual(self._window("today", "Mars/Olympus"), expected)

    def test_month_start_keeps_its_own_utc_offset_across_dst(self):
        # Toronto leaves daylight time on 2026-11-01; mid-November the month still starts at local midnight.
        window = self._window("month", "America/Toronto", datetime(2026, 11, 15, 12, tzinfo=timezone.utc))
        self.assertEqual(window.from_dt, self._server_local(2026, 11, 1, "America/Toronto"))
        self.assertEqual(window.from_date, date(2026, 11, 1))

    def test_all_period_has_a_fixed_start(self):
        window = self._window("all", "America/Toronto")
        self.assertEqual((window.from_dt, window.from_date), (datetime(2000, 1, 1), date(2000, 1, 1)))
        self.assertEqual(window.to_date, date(2026, 10, 9))

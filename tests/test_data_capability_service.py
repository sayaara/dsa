# -*- coding: utf-8 -*-
"""Tests for the data capability overview service."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from fastapi.testclient import TestClient

from api.app import create_app
from src.services.data_capability_service import DataCapabilityService


class _Fetcher:
    def __init__(
        self,
        name: str,
        priority: int,
        *,
        available=None,
        last_error: str = "",
        is_available=None,
        is_available_for_request=None,
    ) -> None:
        self.name = name
        self.priority = priority
        if available is not None:
            self._available = available
        if last_error:
            self.last_error = last_error
        if is_available is not None:
            self.is_available = lambda: is_available
        if is_available_for_request is not None:
            self.is_available_for_request = lambda _capability="": is_available_for_request


class _FetcherManager:
    def __init__(self, fetchers) -> None:
        self._fetchers = fetchers

    def _get_fetchers_snapshot(self):
        return list(self._fetchers)


class _RuntimeScheduler:
    def __init__(self, active: bool) -> None:
        self.active = active

    def is_background_task_active(self, name: str) -> bool:
        return self.active and name == "agent_event_monitor"


def _config(**overrides):
    values = {
        "tushare_token": None,
        "tickflow_api_key": None,
        "tickflow_priority": 2,
        "futu_opend_host": None,
        "longbridge_app_key": None,
        "longbridge_app_secret": None,
        "longbridge_access_token": None,
        "longbridge_oauth_client_id": None,
        "finnhub_api_key": None,
        "alphavantage_api_key": None,
        "enable_realtime_quote": True,
        "enable_fundamental_pipeline": True,
        "realtime_source_priority": "tencent,akshare_sina,efinance,akshare_em",
        "futu_hk_realtime_source_priority": "futu,longbridge,yfinance",
        "screening_enabled": False,
        "agent_event_monitor_enabled": False,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _dataset(overview, name: str):
    return next(item for item in overview["datasets"] if item["dataset"] == name)


def _provider(overview, name: str):
    return next(item for item in overview["providers"] if item["name"] == name)








def test_provider_runtime_probe_honors_request_time_unavailable_over_cached_available_flag() -> None:
    manager = _FetcherManager([
        _Fetcher("LongbridgeFetcher", 1, available=True, is_available_for_request=False),
    ])
    service = DataCapabilityService(
        config=_config(longbridge_app_key="key"),
        fetcher_manager=manager,
    )

    overview = service.get_overview()

    assert _provider(overview, "longbridge")["status"] == "unavailable"
    assert _provider(overview, "longbridge")["warnings"] == ["provider_marked_unavailable"]


def test_us_realtime_priority_skips_longbridge_during_request_cooldown() -> None:
    manager = _FetcherManager([
        _Fetcher("LongbridgeFetcher", 1, available=True, is_available_for_request=False),
        _Fetcher("YfinanceFetcher", 4, available=True),
    ])
    service = DataCapabilityService(
        config=_config(longbridge_app_key="key"),
        fetcher_manager=manager,
    )

    overview = service.get_overview()
    priorities = {item["scenario"]: item for item in overview["priorities"]}
    us_quality = _dataset(overview, "quote.realtime")["coverage"]["markets"]["us"]

    assert priorities["us.realtime"]["providers"] == ["yfinance", "longbridge"]
    assert us_quality["status"] == "ok"
    assert us_quality["source"] == "yfinance"
    assert us_quality["fallback_from"] == []




def test_hk_realtime_priority_skips_futu_when_opend_is_unconfigured() -> None:
    service = DataCapabilityService(
        config=_config(futu_opend_host=None),
        fetcher_manager=_FetcherManager([_Fetcher("YfinanceFetcher", 4, available=True)]),
    )

    overview = service.get_overview()
    priorities = {item["scenario"]: item for item in overview["priorities"]}
    hk_quality = _dataset(overview, "quote.realtime")["coverage"]["markets"]["hk"]

    assert priorities["hk.realtime"]["providers"] == ["longbridge", "yfinance"]
    assert "futu" not in hk_quality["fallback_from"]












def test_hk_realtime_falls_back_only_when_both_akshare_routes_are_open() -> None:
    from data_provider.realtime_types import get_realtime_circuit_breaker

    breaker = get_realtime_circuit_breaker()
    try:
        for key in ("akshare_hk_em", "akshare_hk_sina"):
            breaker.reset(key)
            for _ in range(3):
                breaker.record_failure(key, "test")
        service = DataCapabilityService(
            config=_config(futu_hk_realtime_source_priority="akshare,yfinance"),
            fetcher_manager=_FetcherManager([
                _Fetcher("AkshareFetcher", 1, available=True),
                _Fetcher("YfinanceFetcher", 4, available=True),
            ]),
        )

        hk_quality = _dataset(service.get_overview(), "quote.realtime")["coverage"]["markets"]["hk"]

        assert hk_quality["status"] == "degraded"
        assert hk_quality["source"] == "yfinance"
        assert hk_quality["fallback_from"] == ["akshare"]
    finally:
        breaker.reset("akshare_hk_em")
        breaker.reset("akshare_hk_sina")


def test_us_index_realtime_keeps_yfinance_ahead_of_healthy_longbridge() -> None:
    service = DataCapabilityService(
        config=_config(longbridge_app_key="key"),
        fetcher_manager=_FetcherManager([
            _Fetcher("LongbridgeFetcher", 1, available=True, is_available_for_request=True),
            _Fetcher("YfinanceFetcher", 4, available=True),
        ]),
    )

    markets = _dataset(service.get_overview(), "quote.realtime")["coverage"]["markets"]

    assert markets["us"]["source"] == "longbridge"
    assert markets["us.index"]["source"] == "yfinance"
    assert markets["us.index"]["fallback_from"] == []


def test_us_index_realtime_does_not_fallback_to_longbridge() -> None:
    service = DataCapabilityService(
        config=_config(longbridge_app_key="key"),
        fetcher_manager=_FetcherManager([
            _Fetcher("LongbridgeFetcher", 1, available=True, is_available_for_request=True),
            _Fetcher("YfinanceFetcher", 4, available=False),
        ]),
    )

    markets = _dataset(service.get_overview(), "quote.realtime")["coverage"]["markets"]

    assert markets["us"]["source"] == "longbridge"
    assert markets["us.index"]["status"] == "unavailable"
    assert markets["us.index"]["source"] is None
    assert markets["us.index"]["fallback_from"] == ["yfinance"]




def test_hk_realtime_rejects_configured_provider_without_runtime_handler() -> None:
    service = DataCapabilityService(
        config=_config(
            tushare_token="token",
            futu_hk_realtime_source_priority="tushare,yfinance",
        ),
        fetcher_manager=_FetcherManager([
            _Fetcher("TushareFetcher", 0, available=True),
            _Fetcher("YfinanceFetcher", 1, available=True),
        ]),
    )

    overview = service.get_overview()
    hk_quality = _dataset(overview, "quote.realtime")["coverage"]["markets"]["hk"]

    assert hk_quality["status"] == "degraded"
    assert hk_quality["source"] == "yfinance"
    assert hk_quality["fallback_from"] == ["tushare"]
    assert "source_status:tushare:unsupported" in hk_quality["warnings"]






def test_daily_dataset_quality_prefers_longbridge_for_us_when_available() -> None:
    manager = _FetcherManager([
        _Fetcher("LongbridgeFetcher", 5, available=True, is_available_for_request=True),
        _Fetcher("YfinanceFetcher", 4, available=True),
    ])
    service = DataCapabilityService(
        config=_config(longbridge_app_key="key"),
        fetcher_manager=manager,
    )

    overview = service.get_overview()
    daily_quality = _dataset(overview, "kline.daily")

    assert daily_quality["coverage"]["markets"]["us"]["status"] == "ok"
    assert daily_quality["coverage"]["markets"]["us"]["source"] == "longbridge"
    assert "us:finnhub" not in daily_quality["fallback_from"]


def test_us_daily_priority_omits_unregistered_configured_sources() -> None:
    manager = _FetcherManager([
        _Fetcher("YfinanceFetcher", 4, available=True),
    ])
    service = DataCapabilityService(config=_config(), fetcher_manager=manager)

    overview = service.get_overview()
    priorities = {item["scenario"]: item for item in overview["priorities"]}
    us_quality = _dataset(overview, "kline.daily")["coverage"]["markets"]["us"]

    assert priorities["daily.generic"]["providers"] == ["yfinance"]
    assert us_quality["status"] == "ok"
    assert us_quality["source"] == "yfinance"
    assert us_quality["fallback_from"] == []
















def test_screening_snapshot_priority_preserves_explicit_env_override() -> None:
    service = DataCapabilityService(
        config=_config(screening_enabled=True),
        fetcher_manager=_FetcherManager([]),
    )

    with patch.dict("os.environ", {"SNAPSHOT_SOURCE_PRIORITY": "tushare,em_datacenter"}, clear=False):
        overview = service.get_overview()

    priorities = {item["scenario"]: item for item in overview["priorities"]}
    screening = priorities["screening.snapshot"]

    assert screening["providers"] == ["tushare", "em_datacenter"]












def test_daily_capability_contract_includes_market_specific_daily_fetchers() -> None:
    service = DataCapabilityService(
        config=_config(
            futu_opend_host="127.0.0.1",
            finnhub_api_key="key",
            alphavantage_api_key="key",
        ),
        fetcher_manager=_FetcherManager([]),
    )

    overview = service.get_overview()

    assert "kline.daily" in _provider(overview, "futu")["datasets"]
    assert "kline.daily" in _provider(overview, "finnhub")["datasets"]
    assert "kline.daily" in _provider(overview, "alphavantage")["datasets"]


def test_disabled_runtime_features_surface_dataset_quality_warnings() -> None:
    manager = _FetcherManager([_Fetcher("AkshareFetcher", 1), _Fetcher("YfinanceFetcher", 4)])
    service = DataCapabilityService(
        config=_config(
            enable_realtime_quote=False,
            enable_fundamental_pipeline=False,
            screening_enabled=False,
        ),
        fetcher_manager=manager,
    )

    overview = service.get_overview()

    assert _dataset(overview, "quote.realtime")["status"] == "unavailable"
    assert _dataset(overview, "quote.realtime")["warnings"] == ["realtime_quote_disabled"]
    assert _dataset(overview, "financial.snapshot")["status"] == "unavailable"
    assert _dataset(overview, "financial.snapshot")["warnings"] == ["fundamental_pipeline_disabled"]
    assert _dataset(overview, "strategy.screening")["status"] == "unconfigured"
    assert _dataset(overview, "strategy.screening")["warnings"] == ["screening_disabled"]
    assert _dataset(overview, "alert.monitor")["status"] == "unavailable"
    assert _dataset(overview, "alert.monitor")["source"] is None
    assert _dataset(overview, "alert.monitor")["warnings"] == ["agent_event_monitor_disabled"]
    assert _dataset(overview, "news.events")["source"] is None


def test_enabled_alert_monitor_requires_a_registered_live_scheduler_task() -> None:
    service = DataCapabilityService(
        config=_config(agent_event_monitor_enabled=True),
        fetcher_manager=_FetcherManager([]),
        runtime_scheduler=_RuntimeScheduler(active=False),
    )

    quality = _dataset(service.get_overview(), "alert.monitor")

    assert quality["status"] == "unavailable"
    assert quality["source"] is None
    assert quality["warnings"] == ["agent_event_monitor_not_running"]


def test_running_alert_monitor_surfaces_local_dataset_as_available() -> None:
    service = DataCapabilityService(
        config=_config(agent_event_monitor_enabled=True),
        fetcher_manager=_FetcherManager([]),
        runtime_scheduler=_RuntimeScheduler(active=True),
    )

    quality = _dataset(service.get_overview(), "alert.monitor")

    assert quality["status"] == "ok"
    assert quality["source"] == "alerts"
    assert quality["warnings"] == []


def test_data_capability_api_paths_return_valid_contract() -> None:
    overview_payload = {
        "as_of": "2026-08-26T15:05:00+08:00",
        "providers": [
            {
                "name": "efinance",
                "label": "Efinance",
                "enabled": True,
                "configured": True,
                "status": "ok",
                "priority": 0,
                "markets": ["cn"],
                "datasets": ["quote.realtime"],
                "dataset_markets": {"quote.realtime": ["cn"]},
                "warnings": [],
                "last_error": None,
                "cooldown": None,
            }
        ],
        "datasets": [
            {
                "dataset": "quote.realtime",
                "status": "ok",
                "source": "efinance",
                "stale": False,
                "last_success": None,
                "last_error": None,
                "fallback_from": [],
                "coverage": None,
                "warnings": [],
            }
        ],
        "priorities": [
            {
                "scenario": "cn.realtime",
                "providers": ["efinance"],
                "source": "test",
                "warnings": [],
            }
        ],
        "warnings": [],
    }

    class _Service:
        def __init__(self, *, config, runtime_scheduler=None) -> None:
            self.config = config
            self.runtime_scheduler = runtime_scheduler

        def get_overview(self):
            return overview_payload

    with tempfile.TemporaryDirectory() as temp_dir:
        client = TestClient(create_app(static_dir=Path(temp_dir)))
        with patch("api.v1.endpoints.data.DataCapabilityService", _Service):
            overview_response = client.get("/api/v1/data/overview")
            capabilities_response = client.get("/api/v1/data/capabilities")

    assert overview_response.status_code == 200
    assert capabilities_response.status_code == 200
    assert overview_response.json() == overview_payload
    assert capabilities_response.json() == overview_payload

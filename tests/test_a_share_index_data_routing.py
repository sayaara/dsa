import logging
from typing import cast
from unittest.mock import patch

import pandas as pd
import pytest

from data_provider.base import (
    BaseFetcher,
    DataFetchError,
    DataFetcherManager,
    STANDARD_COLUMNS,
)
from src.services.stock_list_parser import (
    AnalysisTarget,
    IndexEntry,
    ParseStatus,
    parse_analysis_target,
)


def _daily_frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "date": [pd.Timestamp("2026-08-21")],
            "open": [100.0],
            "high": [102.0],
            "low": [99.0],
            "close": [101.0],
            "volume": [1000],
            "amount": [101000.0],
            "pct_chg": [1.0],
        }
    )


class _FakeFetcher(BaseFetcher):
    def __init__(
        self,
        name: str,
        *,
        priority: int,
        daily_result=None,
        name_result=None,
        available: bool = True,
    ) -> None:
        self.name = name
        self.priority = priority
        self.daily_result = daily_result
        self.name_result = name_result
        self.available = available
        self.daily_calls: list[str] = []
        self.name_calls: list[str] = []

    def _fetch_raw_data(self, stock_code, start_date, end_date):
        raise NotImplementedError

    def _normalize_data(self, df, stock_code):
        raise NotImplementedError

    def is_available_for_request(self, _capability: str) -> bool:
        return self.available

    def get_daily_data(self, stock_code, start_date=None, end_date=None, days=30):
        self.daily_calls.append(stock_code)
        if isinstance(self.daily_result, Exception):
            raise self.daily_result
        if self.daily_result is None:
            return pd.DataFrame()
        return self.daily_result.copy()

    def get_stock_name(self, stock_code):
        self.name_calls.append(stock_code)
        if isinstance(self.name_result, Exception):
            raise self.name_result
        return self.name_result


def _manager_without_fetchers() -> DataFetcherManager:
    manager = DataFetcherManager.__new__(DataFetcherManager)
    manager._fetchers = []
    manager._ensure_concurrency_guards()
    return manager




@pytest.mark.parametrize(
    "stock_code",
    ["csi930956", "CSI930956", "930956.CSI", "csi93095", "93095.CSI"],
)
def test_unregistered_csi_name_is_rejected_before_provider_calls(stock_code) -> None:
    fetcher = _FakeFetcher("YfinanceFetcher", priority=1, name_result="wrong")
    manager = DataFetcherManager(fetchers=[fetcher])

    assert manager.get_stock_name(stock_code) == ""
    assert fetcher.name_calls == []


def test_prefetch_stock_names_skips_unregistered_csi() -> None:
    fetcher = _FakeFetcher("YfinanceFetcher", priority=1, name_result="wrong")
    manager = DataFetcherManager(fetchers=[fetcher])

    manager.prefetch_stock_names(["csi930956", "930956.CSI"])

    assert fetcher.name_calls == []


@pytest.fixture(autouse=True)
def _reset_daily_source_health():
    DataFetcherManager.reset_daily_source_health()
    yield
    DataFetcherManager.reset_daily_source_health()
















def test_index_daily_skips_unsupported_provider_symbols_without_health_failure() -> None:
    entry = IndexEntry(
        bare_code="000016",
        exchange="HK",
        canonical_id="hk000016",
        display_name="",
    )
    target = AnalysisTarget(
        raw_input="hk000016",
        asset_type=ParseStatus.INDEX,
        canonical_id="hk000016",
        display_code="000016.HK",
        exchange="HK",
        matched_index=entry,
    )
    fetchers = [
        _FakeFetcher("TencentFetcher", priority=0, daily_result=_daily_frame()),
        _FakeFetcher("AkshareFetcher", priority=1, daily_result=_daily_frame()),
        _FakeFetcher("TickFlowFetcher", priority=2, daily_result=_daily_frame()),
        _FakeFetcher("YfinanceFetcher", priority=3, daily_result=_daily_frame()),
    ]
    manager = DataFetcherManager(fetchers=cast(list[BaseFetcher], fetchers))

    with patch("data_provider.base.parse_analysis_target", return_value=target), patch(
        "data_provider.base.record_provider_run"
    ) as record_run, patch.object(
        DataFetcherManager, "_record_daily_source_failure"
    ) as record_health_failure:
        df, source = manager.get_daily_data("hk000016")

    assert df.empty
    assert source == ""
    assert all(fetcher.daily_calls == [] for fetcher in fetchers)
    assert [item.kwargs["error_type"] for item in record_run.call_args_list] == [
        "unsupported",
        "unsupported",
        "unsupported",
        "unsupported",
    ]
    assert all(
        "unsupported index provider symbol" in item.kwargs["error_message"]
        for item in record_run.call_args_list
    )
    assert all(item.kwargs["record_count"] == 0 for item in record_run.call_args_list)
    record_health_failure.assert_not_called()












def test_index_name_fallback_uses_fixed_order_and_provider_symbols() -> None:
    entry = IndexEntry(
        bare_code="000016",
        exchange="SH",
        canonical_id="sh000016",
        display_name="",
    )
    target = AnalysisTarget(
        raw_input="sh000016",
        asset_type=ParseStatus.INDEX,
        canonical_id="sh000016",
        display_code="",
        exchange="SH",
        matched_index=entry,
    )
    tencent = _FakeFetcher("TencentFetcher", priority=9, name_result=None)
    akshare = _FakeFetcher("AkshareFetcher", priority=8, name_result="")
    tickflow = _FakeFetcher("TickFlowFetcher", priority=0, name_result="网络上证50")
    manager = DataFetcherManager(fetchers=[tickflow, akshare, tencent])

    with patch("data_provider.base.parse_analysis_target", return_value=target):
        name = manager.get_stock_name("sh000016", allow_realtime=False)

    assert name == "网络上证50"
    assert tencent.name_calls == ["sh000016"]
    assert akshare.name_calls == ["sh000016"]
    assert tickflow.name_calls == ["000016.SH"]
    assert manager._stock_name_cache == {"sh000016": "网络上证50"}






def test_index_name_rejects_code_aliases_from_registry_cache_network_and_static() -> None:
    entry = IndexEntry(
        bare_code="000016",
        exchange="SH",
        canonical_id="sh000016",
        display_name="000016.SH",
    )
    target = AnalysisTarget(
        raw_input="sh000016",
        asset_type=ParseStatus.INDEX,
        canonical_id="sh000016",
        display_code="SSE50",
        exchange="SH",
        matched_index=entry,
    )
    tencent = _FakeFetcher("TencentFetcher", priority=0, name_result="sh000016")
    akshare = _FakeFetcher("AkshareFetcher", priority=1, name_result="000016.SS")
    tickflow = _FakeFetcher("TickFlowFetcher", priority=2, name_result="SSE50")
    manager = DataFetcherManager(fetchers=[tencent, akshare, tickflow])
    manager._stock_name_cache["sh000016"] = "000016"

    with patch.dict(
        "data_provider.base.STOCK_NAME_MAP", {"sh000016": "000016"}, clear=True
    ), patch("data_provider.base.parse_analysis_target", return_value=target):
        name = manager.get_stock_name("sh000016", allow_realtime=False)

    assert name == "sh000016"
    assert manager._stock_name_cache == {}
    assert tencent.name_calls == ["sh000016"]
    assert akshare.name_calls == ["sh000016"]
    assert tickflow.name_calls == ["000016.SH"]


def test_index_name_returns_canonical_id_when_registry_and_network_fail() -> None:
    entry = IndexEntry(
        bare_code="399001",
        exchange="SZ",
        canonical_id="sz399001",
        display_name="",
    )
    target = AnalysisTarget(
        raw_input="sz399001",
        asset_type=ParseStatus.INDEX,
        canonical_id="sz399001",
        display_code="",
        exchange="SZ",
        matched_index=entry,
    )
    fetchers = [
        _FakeFetcher("TencentFetcher", priority=0, name_result=RuntimeError("failed")),
        _FakeFetcher("AkshareFetcher", priority=1, name_result=None),
        _FakeFetcher("TickFlowFetcher", priority=2, name_result=""),
    ]
    manager = DataFetcherManager(fetchers=cast(list[BaseFetcher], fetchers))

    with patch("data_provider.base.parse_analysis_target", return_value=target):
        name = manager.get_stock_name("sz399001", allow_realtime=False)

    assert name == "sz399001"
    assert manager._stock_name_cache == {}




# ---------------------------------------------------------------------------
# CSI provider symbol routing.
# ---------------------------------------------------------------------------





# -*- coding: utf-8 -*-
"""Tests for name_to_code_resolver.

Covers:
- Local mapping (STOCK_NAME_MAP reverse)
- Code format boundary (_is_code_like, _normalize_code)
- Pinyin match (when pypinyin available)
- AkShare fallback (mocked)
- Fuzzy match (difflib)
- Ambiguous names return None
- Stock dataclass / resolver_name_to_code_list / US_stock_code_match / extend_AkShare
"""

import threading
import time
from typing import Optional
from unittest.mock import patch

import pandas as pd
import pytest

from src.data.stock_mapping import STOCK_NAME_MAP
from src.services import name_to_code_resolver as ntc
from src.services.name_to_code_resolver import (
    Stock,
    resolve_name_to_code,
    resolver_name_to_code_list,
    US_stock_code_match,
    _is_code_like,
    _normalize_code,
    _build_reverse_map_no_duplicates,
)


@pytest.fixture()
def clean_db(request):
    """Isolate the global stockDB and its caches."""
    yield
    # Normalised local mapping used for restore (isomorphic to the module's initial value, see _normalize_stock_name)
    ntc.stockDB.clear()
    ntc.stockDB.update(
        {c: ntc._normalize_stock_name(n) for c, n in STOCK_NAME_MAP.items()}
    )
    ntc._names_cache[:] = [None, None, None]
    ntc._pinyin_cache[:] = [None, None]
    ntc.stockAliases.clear()


# ---------------------------------------------------------------------------
# _is_code_like
# ---------------------------------------------------------------------------

class TestIsCodeLike:
    def test_a_share_5_digits(self):
        assert _is_code_like("60051") is True
        assert _is_code_like("600519") is True

    def test_a_share_6_digits(self):
        assert _is_code_like("300750") is True

    def test_bse_with_exchange_hint(self):
        assert _is_code_like("920493.BJ") is True
        assert _is_code_like("BJ920493") is True

    def test_bj_exchange_hint_rejects_non_bse_code(self):
        assert _is_code_like("600519.BJ") is False
        assert _is_code_like("BJ600519") is False

    def test_hk_5_digits(self):
        assert _is_code_like("00700") is True

    def test_us_stock_letters(self):
        assert _is_code_like("AAPL") is True
        assert _is_code_like("TSLA") is True
        assert _is_code_like("BRK.B") is True

    def test_rejects_non_code(self):
        assert _is_code_like("贵州茅台") is False
        assert _is_code_like("1234") is False  # too short
        assert _is_code_like("1234567") is False  # too long
        assert _is_code_like("") is False
        assert _is_code_like("   ") is False


# ---------------------------------------------------------------------------
# _normalize_code
# ---------------------------------------------------------------------------

class TestNormalizeCode:
    def test_preserves_valid_a_share(self):
        assert _normalize_code("600519") == "600519"
        assert _normalize_code("  600519  ") == "600519"

    def test_strips_suffix(self):
        assert _normalize_code("600519.SH") == "600519"
        assert _normalize_code("000001.SZ") == "000001"
        assert _normalize_code("920493.BJ") == "920493"

    def test_strips_bse_prefix(self):
        assert _normalize_code("BJ920493") == "920493"

    def test_bj_exchange_hint_rejects_non_bse_code(self):
        assert _normalize_code("600519.BJ") is None
        assert _normalize_code("BJ600519") is None

    def test_preserves_us_stock(self):
        assert _normalize_code("AAPL") == "AAPL"
        assert _normalize_code("brk.b") == "BRK.B"

    def test_returns_none_for_invalid(self):
        assert _normalize_code("") is None
        assert _normalize_code("1234") is None
        assert _normalize_code("贵州茅台") is None


# ---------------------------------------------------------------------------
# _build_reverse_map_no_duplicates
# ---------------------------------------------------------------------------

class TestBuildReverseMapNoDuplicates:
    def test_excludes_ambiguous_names(self):
        # "阿里巴巴" maps to both BABA and 09988
        code_to_name = {"BABA": "阿里巴巴", "09988": "阿里巴巴", "600519": "贵州茅台"}
        result = _build_reverse_map_no_duplicates(code_to_name)
        assert "阿里巴巴" not in result
        assert result.get("贵州茅台") == "600519"

    def test_includes_unique_names(self):
        code_to_name = {"600519": "贵州茅台", "00700": "腾讯控股"}
        result = _build_reverse_map_no_duplicates(code_to_name)
        assert result["贵州茅台"] == "600519"
        assert result["腾讯控股"] == "00700"


# ---------------------------------------------------------------------------
# resolve_name_to_code
# ---------------------------------------------------------------------------

class TestResolveNameToCode:
    def test_code_like_input_returned_normalized(self):
        assert resolve_name_to_code("600519") == "600519"
        assert resolve_name_to_code("600519.SH") == "600519"
        assert resolve_name_to_code("920493.BJ") == "920493"
        assert resolve_name_to_code("  AAPL  ") == "AAPL"

    def test_local_map_exact_match(self):
        assert resolve_name_to_code("贵州茅台") == "600519"
        assert resolve_name_to_code("腾讯控股") == "00700"



    def test_returns_none_for_empty_or_invalid_input(self):
        assert resolve_name_to_code("") is None
        assert resolve_name_to_code("   ") is None
        assert resolve_name_to_code(None) is None  # type: ignore

    def test_ambiguous_name_returns_none(self):
        # "阿里巴巴" maps to both BABA and 09988 in STOCK_NAME_MAP
        assert resolve_name_to_code("阿里巴巴") is None







# ---------------------------------------------------------------------------
# Stock dataclass
# ---------------------------------------------------------------------------

class TestStock:
    def test_fields(self):
        s = Stock(code="600519", name="贵州茅台", market="a")
        assert (s.code, s.name, s.market) == ("600519", "贵州茅台", "a")

    def test_value_equality(self):
        assert Stock("600519", "贵州茅台", "a") == Stock("600519", "贵州茅台", "a")
        assert Stock("600519", "贵州茅台", "a") != Stock("00700", "腾讯控股", "hk")


# ---------------------------------------------------------------------------
# resolver_name_to_code_list
# ---------------------------------------------------------------------------

class TestResolverNameToCodeList:
    @pytest.mark.usefixtures("clean_db")
    def test_exact_match(self):
        assert resolver_name_to_code_list("贵州茅台") == [Stock("600519", "贵州茅台", "a")]

    @pytest.mark.usefixtures("clean_db")
    def test_exact_match_cross_market_sorted(self):
        # 阿里巴巴 in STOCK_NAME_MAP: BABA (us) + 09988 (hk) → hk before us
        assert resolver_name_to_code_list("阿里巴巴") == [
            Stock("09988", "阿里巴巴", "hk"),
            Stock("BABA", "阿里巴巴", "us"),
        ]

    @pytest.mark.usefixtures("clean_db")
    def test_substring_match(self):
        assert resolver_name_to_code_list("茅台") == [Stock("600519", "贵州茅台", "a")]

    @pytest.mark.usefixtures("clean_db")
    def test_pinyin_substring_match(self):
        # Non-CJK input: resolved locally via pinyin, without AkShare fetch
        assert resolver_name_to_code_list("maotai") == [Stock("600519", "贵州茅台", "a")]

    @pytest.mark.usefixtures("clean_db")
    def test_cjk_fragment_skips_pinyin_layer(self):
        # Regression: a CJK fragment must not reach the pinyin substring layer. "平果" pinyin pingguo collides
        # exactly with the full pinyin of 苹果, and before the fix strategy 3 would mismatch it; the pinyin
        # granularity of a CJK fragment is uncontrolled (content characters plus particles can collide with an
        # unrelated full name, e.g. "阿里的" -> "alide" subset of "zhongdalide" 中大力德), so only ASCII pinyin input takes that layer.
        assert resolver_name_to_code_list("平果") == []

    @pytest.mark.usefixtures("clean_db")
    def test_fuzzy_typo_match(self):
        assert resolver_name_to_code_list("贵州茅苔") == [Stock("600519", "贵州茅台", "a")]

    @pytest.mark.usefixtures("clean_db")
    def test_no_match_returns_empty(self):
        assert resolver_name_to_code_list("你好世界") == []

    @pytest.mark.usefixtures("clean_db")
    def test_invalid_input_returns_empty(self):
        assert resolver_name_to_code_list("") == []
        assert resolver_name_to_code_list(None) == []  # type: ignore
        assert resolver_name_to_code_list("茅") == []  # single char is never a name





class TestCompactLookupInputs:
    """Query-side flattening at source: an input in "source form" with embedded spaces (such as
    "五 粮 液" copied from AkShare data) resolves just like the usual unspaced spelling. Records are
    flattened on insert, so a query entry that only strips the ends would miss source-form input at the exact, substring and fuzzy layers."""



    def test_spaced_input_resolves_legacy(self):
        # The local mapping already holds the unspaced spelling: the legacy entry matches spaced input too
        assert resolve_name_to_code("五 粮 液") == "000858"


# ---------------------------------------------------------------------------
# US_stock_code_match
# ---------------------------------------------------------------------------

class TestUSStockCodeMatch:
    def test_known_ticker(self):
        assert US_stock_code_match("AAPL") == [Stock("AAPL", "苹果", "us")]
        assert US_stock_code_match("aapl") == [Stock("AAPL", "苹果", "us")]

    def test_unknown_word_returns_empty(self):
        assert US_stock_code_match("HELLO") == []  # ordinary English word
        assert US_stock_code_match("TOOLONGTICKER") == []
        assert US_stock_code_match("贵州茅台") == []


# ---------------------------------------------------------------------------
# extend_AkShare
# ---------------------------------------------------------------------------

class TestCompactStockNameMerge:
    """AkShare name whitespace flattening: stockDB only stores the unspaced spelling.

    A spaced name ("五 粮 液") and the local unspaced spelling ("五粮液") mean the same thing:
    once flattened they compare equal, so no spurious rename or alias is created, and the full-name exact match stays visible to ordinary input.
    """







# ---------------------------------------------------------------------------
# AkShare single-flight concurrency: the real _get_akshare_name_to_code + a fake _fetch_akshare_df
# ---------------------------------------------------------------------------


class _FakeAkShareFetch:
    """A deterministic stand-in for _fetch_akshare_df.

    Each call first sets fetch_started (proving the fetch has begun on the background thread), then blocks
    on release_fetch, so the test controls the fetch window precisely without relying on sleep timing.
    """

    def __init__(self, fail: bool = False, rows: Optional[dict] = None):
        self.fetch_started = threading.Event()
        self.release_fetch = threading.Event()
        self.fail = fail
        self.rows = rows or {"code": ["600000"], "name": ["浦发银行"]}
        self.calls = 0

    def fetch(self):
        self.calls += 1
        self.fetch_started.set()
        # 30s safety net: a correct case always sets it before tear-down, so a defect here cannot hang the thread
        self.release_fetch.wait(timeout=30)
        if self.fail:
            raise RuntimeError("simulated akshare failure")
        return pd.DataFrame(self.rows)


@pytest.fixture()
def real_akshare_path(monkeypatch, tmp_path):
    """Reset the AkShare fetch globals and take the real _get_akshare_name_to_code path.

    The disk cache points at a temporary path, isolating the real files under the repo's data/cache
    while letting the persist and lazy-load cases read and write safely.
    """
    saved = (
        ntc._akshare_cache,
        ntc._akshare_failure_cache,
        ntc._akshare_merged,
        ntc._akshare_inflight,
        ntc._akshare_disk_checked,
    )
    ntc._akshare_cache = None
    ntc._akshare_failure_cache = None
    ntc._akshare_merged = None
    ntc._akshare_inflight = None
    ntc._akshare_disk_checked = False
    monkeypatch.setattr(ntc, "_AKSHARE_DISK_CACHE_PATH", tmp_path / "akshare_name_map.json")
    yield monkeypatch
    # Wait for the in-flight refresh to finish (a correct case has already released it in finally, so this passes in milliseconds),
    # so a late worker cannot write its cache into the next case
    deadline = time.time() + 5
    while ntc._akshare_inflight is not None and time.time() < deadline:
        time.sleep(0.05)
    ntc._akshare_cache, ntc._akshare_failure_cache, ntc._akshare_merged = saved[:3]
    ntc._akshare_inflight, ntc._akshare_disk_checked = saved[3:]
    ntc.stockDB.clear()
    ntc.stockDB.update(
        {c: ntc._normalize_stock_name(n) for c, n in STOCK_NAME_MAP.items()}
    )
    ntc._names_cache[:] = [None, None, None]
    ntc._pinyin_cache[:] = [None, None]
    ntc.stockAliases.clear()


def _run_resolver_in_thread(query: str):
    """Resolve on a daemon thread, capturing the return value or exception."""
    outcome = {}

    def _worker():
        try:
            outcome["value"] = ntc.resolver_name_to_code_list(query)
        except BaseException as exc:  # noqa: BLE001 - thread exception catch-all
            outcome["error"] = exc

    t = threading.Thread(target=_worker, daemon=True)
    t.start()
    return t, outcome


def _wait_until(condition, timeout: float = 5.0) -> bool:
    """Bounded polling for a condition (the background refresh finishing is deterministic, only its duration is not)."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if condition():
            return True
        time.sleep(0.02)
    return condition()




# ---------------------------------------------------------------------------
# Stale-while-revalidate: an expired TTL must return the old value immediately (zero wait) while the refresh
# runs in the background; inside a network-failure backoff the old value keeps serving (availability), and only a cold start degrades.
# ---------------------------------------------------------------------------




# ---------------------------------------------------------------------------
# Disk cache: persisted atomically after a successful fetch; lazily loaded after a restart (globals reset), zero network.
# ---------------------------------------------------------------------------




# ---------------------------------------------------------------------------
# Warm-up is idempotent: concurrent or repeated calls share one in-flight handle and trigger a single network fetch.
# ---------------------------------------------------------------------------




# ---------------------------------------------------------------------------
# The hang (rather than failure) case: once the subprocess timeout wrapper raises TimeoutError, it must take
# the regular failure path and arm the backoff instead of holding the single-flight lock forever.
# ---------------------------------------------------------------------------



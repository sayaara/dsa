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
    """Isolate the global stockDB/caches; the AkShare fetch is mocked offline
    by default. Parametrize with ``indirect=True`` to inject a fake map."""
    fake_map = getattr(request, "param", None)
    with patch.object(ntc, "_get_akshare_name_to_code", return_value=fake_map):
        yield
    # Normalised local mapping used for restore (isomorphic to the module's initial value, see _normalize_stock_name)
    ntc.stockDB.clear()
    ntc.stockDB.update(
        {c: ntc._normalize_stock_name(n) for c, n in STOCK_NAME_MAP.items()}
    )
    ntc._names_cache[:] = [None, None, None]
    ntc._pinyin_cache[:] = [None, None]
    ntc._akshare_merged = None
    ntc._akshare_cache = None
    ntc._akshare_failure_cache = None
    ntc._akshare_inflight = None
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

    @patch("src.services.name_to_code_resolver._get_akshare_name_to_code")
    def test_local_hit_does_not_trigger_akshare(self, mock_akshare):
        # An exact local-table hit must involve zero network: existing callers (API/Bot/import) keep
        # the offline low-latency contract and are never blocked by an AkShare cold start.
        assert resolve_name_to_code("贵州茅台") == "600519"
        assert resolve_name_to_code("腾讯控股") == "00700"
        mock_akshare.assert_not_called()

    @patch("src.services.name_to_code_resolver._get_akshare_name_to_code")
    def test_local_hit_wins_over_akshare_same_name(self, mock_akshare):
        # Compatibility contract: a name uniquely matched in the local table returns the local code directly,
        # with no cross-market merge (中国移动: local holds only HK 00941, while AkShare has the same-named A-share 600941).
        # The full cross-market candidate list comes from resolver_name_to_code_list.
        mock_akshare.return_value = {"中国移动": "600941"}
        assert resolve_name_to_code("中国移动") == "00941"
        mock_akshare.assert_not_called()

    def test_returns_none_for_empty_or_invalid_input(self):
        assert resolve_name_to_code("") is None
        assert resolve_name_to_code("   ") is None
        assert resolve_name_to_code(None) is None  # type: ignore

    def test_ambiguous_name_returns_none(self):
        # "阿里巴巴" maps to both BABA and 09988 in STOCK_NAME_MAP
        assert resolve_name_to_code("阿里巴巴") is None

    @patch("src.services.name_to_code_resolver._get_akshare_name_to_code")
    def test_akshare_fallback_when_not_in_local(self, mock_akshare):
        mock_akshare.return_value = {"平安银行": "000001"}
        # 000001 is in local map as 平安银行, so we use a name that's only in akshare
        # Actually local has 000001 -> 平安银行. So "平安银行" would hit local first.
        # Use a name not in STOCK_NAME_MAP - e.g. some A-share only in AkShare
        mock_akshare.return_value = {"浦发银行": "600000"}
        result = resolve_name_to_code("浦发银行")
        assert result == "600000"
        mock_akshare.assert_called()

    @patch("src.services.name_to_code_resolver._get_akshare_name_to_code")
    def test_fuzzy_match_fallback(self, mock_akshare):
        mock_akshare.return_value = {"贵州茅台": "600519"}
        # Typo: 贵州茅苔 -> should fuzzy match 贵州茅台
        result = resolve_name_to_code("贵州茅苔")
        assert result == "600519"

    @patch("src.services.name_to_code_resolver._get_akshare_name_to_code")
    def test_returns_none_when_no_match(self, mock_akshare):
        mock_akshare.return_value = {}
        result = resolve_name_to_code("不存在的股票名称xyz")
        assert result is None

    @patch("src.services.name_to_code_resolver._get_akshare_name_to_code")
    def test_skips_akshare_for_non_cjk_garbage_input(self, mock_akshare):
        result = resolve_name_to_code("aaaaaaa")
        assert result is None
        mock_akshare.assert_not_called()

    @pytest.mark.parametrize("clean_db", [{"三一重能": "688349"}], indirect=True)
    def test_akshare_exact_fallback_beats_fuzzy_for_non_local_name(self, clean_db):
        # A CJK name absent from the local table: the exact AkShare hit (step 4) wins over fuzzy
        # matching (step 5), so "三一重能" is never mismatched onto the similar 三一重工.
        assert resolve_name_to_code("三一重能") == "688349"


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

    @pytest.mark.parametrize("clean_db", [{"浦发银行": "600000"}], indirect=True)
    def test_akshare_extension_visible_after_retry(self, clean_db):
        # Exact match against the AkShare-extended database
        assert resolver_name_to_code_list("浦发银行") == [Stock("600000", "浦发银行", "a")]


    @pytest.mark.parametrize("clean_db", [{"阿里巴巴": "600000"}], indirect=True)
    def test_local_exact_hit_still_merges_akshare_same_name_a_share(self, clean_db):
        # When the local table already holds a same-named HK or US stock, the same-named A-share from AkShare must be merged in too.
        ntc.stockDB.clear()
        ntc.stockDB.update({"09988": "阿里巴巴", "BABA": "阿里巴巴"})
        ntc._names_cache[:] = [None, None, None]
        ntc._pinyin_cache[:] = [None, None]
        ntc._akshare_merged = None
        ntc.stockAliases.clear()
        assert resolver_name_to_code_list("阿里巴巴") == [
            Stock("600000", "阿里巴巴", "a"),
            Stock("09988", "阿里巴巴", "hk"),
            Stock("BABA", "阿里巴巴", "us"),
        ]

    @pytest.mark.parametrize("clean_db", [{"阿里巴巴": "600000"}], indirect=True)
    def test_local_single_candidate_gets_a_share_candidate_after_akshare_merge(self, clean_db):
        # When the local table holds only one market, the candidate set becomes complete once AkShare adds the same-named A-share.
        ntc.stockDB.clear()
        ntc.stockDB.update({"09988": "阿里巴巴"})
        ntc._names_cache[:] = [None, None, None]
        ntc._pinyin_cache[:] = [None, None]
        ntc._akshare_merged = None
        ntc.stockAliases.clear()
        assert resolver_name_to_code_list("阿里巴巴") == [
            Stock("600000", "阿里巴巴", "a"),
            Stock("09988", "阿里巴巴", "hk"),
        ]

class TestCompactLookupInputs:
    """Query-side flattening at source: an input in "source form" with embedded spaces (such as
    "五 粮 液" copied from AkShare data) resolves just like the usual unspaced spelling. Records are
    flattened on insert, so a query entry that only strips the ends would miss source-form input at the exact, substring and fuzzy layers."""

    @pytest.mark.parametrize("clean_db", [{"五 粮 液": "000858"}], indirect=True)
    def test_spaced_input_resolves_via_list(self, clean_db):
        ntc.extend_AkShare()
        assert resolver_name_to_code_list("五 粮 液") == [
            Stock("000858", "五粮液", "a")
        ]

    @pytest.mark.parametrize("clean_db", [{"五 粮 液": "000858"}], indirect=True)
    def test_spaced_input_is_known_name(self, clean_db):
        ntc.extend_AkShare()
        assert ntc.is_known_stock_name("五 粮 液") is True

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

class TestExtendAkShare:
    @pytest.mark.parametrize("clean_db", [{"浦发银行": "600000"}], indirect=True)
    def test_merges_new_entries_idempotently(self, clean_db):
        assert ntc.extend_AkShare() is True
        assert ntc.stockDB["600000"] == "浦发银行"
        # Same cached map object is not merged twice
        assert ntc.extend_AkShare() is False

    @pytest.mark.parametrize("clean_db", [{"贵州茅台": "600519"}], indirect=True)
    def test_no_new_entries_returns_false(self, clean_db):
        # All entries already in the local database
        assert ntc.extend_AkShare() is False

    @pytest.mark.usefixtures("clean_db")
    def test_fetch_failure_returns_false(self):
        assert ntc.extend_AkShare() is False


    @pytest.mark.parametrize("clean_db", [{"新名称": "600000"}], indirect=True)
    def test_rename_existing_code_updates_canonical_name_and_keeps_alias(self, clean_db):
        ntc.stockDB.clear()
        ntc.stockDB.update({"600000": "旧名称"})
        ntc._names_cache[:] = [None, None, None]
        ntc._pinyin_cache[:] = [None, None]
        ntc._akshare_merged = None
        ntc.stockAliases.clear()
        assert ntc.extend_AkShare() is True
        assert ntc.stockDB["600000"] == "新名称"
        assert ntc.stockAliases["600000"] == {"旧名称"}
        # The new name resolves as the current official name
        assert resolver_name_to_code_list("新名称") == [Stock("600000", "新名称", "a")]
        # The old name still resolves as an alias, while the current official name is displayed
        assert resolver_name_to_code_list("旧名称") == [Stock("600000", "新名称", "a")]


class TestCompactStockNameMerge:
    """AkShare name whitespace flattening: stockDB only stores the unspaced spelling.

    A spaced name ("五 粮 液") and the local unspaced spelling ("五粮液") mean the same thing:
    once flattened they compare equal, so no spurious rename or alias is created, and the full-name exact match stays visible to ordinary input.
    """

    @pytest.mark.parametrize("clean_db", [{"五 粮 液": "600000"}], indirect=True)
    def test_spaced_akshare_name_compacted(self, clean_db):
        # 600000 is absent from the local mapping, so the new entry is written with the flattened spelling
        # (000858 already exists locally, and being equal after flattening it takes the "no change" path, see the next case)
        assert ntc.extend_AkShare() is True
        assert ntc.stockDB["600000"] == "五粮液"

    @pytest.mark.parametrize("clean_db", [{"五 粮 液": "000858"}], indirect=True)
    def test_spaced_name_vs_local_no_spurious_alias(self, clean_db):
        # The local table already holds the unspaced spelling: equal after flattening, so no spurious alias or rename
        ntc.stockDB.clear()
        ntc.stockDB.update({"000858": "五粮液"})
        ntc._names_cache[:] = [None, None, None]
        ntc._akshare_merged = None
        ntc.stockAliases.clear()
        assert ntc.extend_AkShare() is False
        assert ntc.stockDB["000858"] == "五粮液"
        assert "000858" not in ntc.stockAliases

    @pytest.mark.parametrize("clean_db", [{"五 粮 液": "000858"}], indirect=True)
    def test_spaced_name_exact_match_after_merge(self, clean_db):
        # The flattened canonical name is visible to ordinary unspaced input as a whole name (the step 3 exact-match basis included)
        ntc.extend_AkShare()
        assert ntc.is_known_stock_name("五粮液") is True
        assert resolver_name_to_code_list("五粮液") == [Stock("000858", "五粮液", "a")]

    @pytest.mark.parametrize(
        "clean_db", [{"   ": "600000", "万  科Ａ": "000002"}], indirect=True
    )
    def test_whitespace_only_name_skipped(self, clean_db):
        # Name entries that flatten to empty are skipped rather than written as an empty string; "万  科Ａ" normalises to
        # "万科A" (NFKC width normalisation plus whitespace removal)
        assert ntc.extend_AkShare() is True
        assert ntc.stockDB["000002"] == "万科A"
        assert "600000" not in ntc.stockDB or ntc.stockDB["600000"] != ""


class TestStockNameWidthNormalization:
    """Stored-name width normalisation (_normalize_stock_name = NFKC + whitespace removal): the source
    data's full-width spelling (AkShare "京东方Ａ", historical disk cache) and NFKC-normalised user
    input ("京东方A") must go through the same transform - otherwise the full-name exact match misses
    and a shorter stored name ("京东") captures it instead."""

    @pytest.mark.parametrize("clean_db", [{"京东方Ａ": "000725"}], indirect=True)
    def test_akshare_fullwidth_name_normalized_on_merge(self, clean_db):
        # Merge-entry normalisation: a full-width Ａ name is written into stockDB in the half-width spelling
        assert ntc.extend_AkShare() is True
        assert ntc.stockDB["000725"] == "京东方A"

    @pytest.mark.parametrize("clean_db", [{"京东方Ａ": "000725"}], indirect=True)
    def test_fullwidth_and_halfwidth_queries_both_resolve(self, clean_db):
        ntc.extend_AkShare()
        # Query-entry normalisation at source: full-width and half-width input both resolve, and the display name is the normalised spelling
        assert ntc.resolver_name_to_code_list("京东方A") == [
            Stock("000725", "京东方A", "a")
        ]
        assert ntc.resolver_name_to_code_list("京东方Ａ") == [
            Stock("000725", "京东方A", "a")
        ]
        assert ntc.is_known_stock_name("京东方Ａ") is True

    @pytest.mark.parametrize("clean_db", [{"京东方A": "000725"}], indirect=True)
    def test_legacy_fullwidth_input_resolves(self, clean_db):
        # legacy-entry query normalisation (production cache-side names are already normalised by
        # _build_name_map_from_df, so the mock supplies half-width keys as production would)
        assert ntc.resolve_name_to_code("京东方Ａ") == "000725"

    def test_local_name_indexes_normalized(self):
        # Builder-internal normalisation: full-width input indexes under the half-width key
        unique, ambiguous = ntc._build_local_name_indexes({"000725": "京东方Ａ"})
        assert unique == {"京东方A": "000725"}
        assert ambiguous == set()

    @pytest.mark.usefixtures("real_akshare_path")
    def test_disk_cache_names_normalized_on_load(self):
        # Historical unnormalised names in the disk cache are normalised on load (zero network, fresh timestamp)
        import json
        import time as time_mod

        ntc._akshare_disk_checked = False
        ntc._AKSHARE_DISK_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        ntc._AKSHARE_DISK_CACHE_PATH.write_text(
            json.dumps(
                {"ts": time_mod.time(), "map": {"京东方Ａ": "000725"}},
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        assert ntc._get_akshare_name_to_code() == {"京东方A": "000725"}

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


class TestAkShareSingleFlightConcurrency:
    @pytest.mark.usefixtures("real_akshare_path")
    def test_waiter_resolves_after_inflight_fetch_completes(self, monkeypatch):
        fake = _FakeAkShareFetch()
        monkeypatch.setattr(ntc, "_fetch_akshare_df", fake.fetch)

        t1, r1 = _run_resolver_in_thread("浦发银行")
        t2 = None
        try:
            assert fake.fetch_started.wait(timeout=5)
            t2, r2 = _run_resolver_in_thread("浦发银行")
            # The old implementation (non-blocking give-up) returned an empty result inside this window; the new one keeps waiting
            t2.join(timeout=2)
            # Before the release, the first two threads must still be waiting (not already returned empty) - the heart of the missed-resolution bug
            assert t1.is_alive() and t2.is_alive()
        finally:
            fake.release_fetch.set()
            t1.join(timeout=10)
            if t2 is not None:
                t2.join(timeout=10)
        assert not t1.is_alive() and not t2.is_alive()
        # The waiters get the in-flight fetch's result (this bug's core assertion), and the whole process fetches only once
        assert r1.get("value") == [Stock("600000", "浦发银行", "a")]
        assert r2.get("value") == [Stock("600000", "浦发银行", "a")]
        assert fake.calls == 1

    @pytest.mark.usefixtures("real_akshare_path")
    def test_waiter_returns_empty_after_inflight_failure_and_no_refetch(self, monkeypatch):
        fake = _FakeAkShareFetch(fail=True)
        monkeypatch.setattr(ntc, "_fetch_akshare_df", fake.fetch)

        t1, r1 = _run_resolver_in_thread("浦发银行")
        t2 = None
        try:
            assert fake.fetch_started.wait(timeout=5)
            t2, r2 = _run_resolver_in_thread("浦发银行")
            t2.join(timeout=2)
        finally:
            fake.release_fetch.set()
            t1.join(timeout=10)
            if t2 is not None:
                t2.join(timeout=10)
        assert not t1.is_alive() and not t2.is_alive()
        # In-flight fetch failed: the waiters wake into the failure backoff (rather than a retry storm), and the empty local table returns []
        assert r1.get("value") == []
        assert r2.get("value") == []
        assert fake.calls == 1
        assert ntc._akshare_failure_cache is not None

    @pytest.mark.usefixtures("real_akshare_path")
    def test_cold_waiters_degrade_after_timeout_but_fetch_lands(self, monkeypatch):
        # The safety-net path for a worker that breaks its contract (never resolving despite ample budget): waiters degrade
        # on their own deadline, while the background fetch is unaffected and still completes exactly once
        monkeypatch.setattr(ntc, "_AKSHARE_WAIT_COLD_START", 0.2)
        fake = _FakeAkShareFetch()
        monkeypatch.setattr(ntc, "_fetch_akshare_df", fake.fetch)

        t1, r1 = _run_resolver_in_thread("浦发银行")
        t2 = None
        try:
            assert fake.fetch_started.wait(timeout=5)
            t2, r2 = _run_resolver_in_thread("浦发银行")
            # While the fetch hangs, every cold-start waiter (including the one that triggered it) must
            # return within the timeout bound rather than wait forever
            t1.join(timeout=10)
            t2.join(timeout=10)
            # Both waiters must be confirmed degraded before the fetch is released; waiting on t2 alone
            # does not prove t1 returned, and after the finally release t1 could still get a success
            assert not t1.is_alive() and not t2.is_alive()
            assert r1.get("value") == []
            assert r2.get("value") == []
        finally:
            fake.release_fetch.set()
            t1.join(timeout=10)
            if t2 is not None:
                t2.join(timeout=10)
        assert not t1.is_alive() and not t2.is_alive()
        # The background fetch is unaffected by waiter timeouts and still completes exactly once
        assert fake.calls == 1
        assert _wait_until(
            lambda: ntc._akshare_cache is not None
            and ntc._akshare_cache[1] == {"浦发银行": "600000"}
        )
        # Once the fetch lands, later requests hit the new cache immediately
        assert ntc.resolver_name_to_code_list("浦发银行") == [Stock("600000", "浦发银行", "a")]

    @pytest.mark.usefixtures("real_akshare_path")
    def test_slow_persist_does_not_delay_waiter_wakeup(self, monkeypatch):
        # Wake before persisting: a slow disk must not hold up a waiter's result (a ready cache with a
        # timed-out waiter was a real regression)
        fake = _FakeAkShareFetch()
        monkeypatch.setattr(ntc, "_fetch_akshare_df", fake.fetch)
        release_persist = threading.Event()
        monkeypatch.setattr(
            ntc, "_persist_akshare_map", lambda map_: release_persist.wait(timeout=30)
        )

        t1, r1 = _run_resolver_in_thread("浦发银行")
        try:
            assert fake.fetch_started.wait(timeout=5)
            fake.release_fetch.set()
            # Wake and return as soon as the fetch completes, without waiting for the persist
            t1.join(timeout=5)
            assert not t1.is_alive()
            assert r1.get("value") == [Stock("600000", "浦发银行", "a")]
            assert not release_persist.is_set()  # the persist is still blocked, yet the waiter has returned
        finally:
            release_persist.set()
            t1.join(timeout=10)

    @pytest.mark.usefixtures("real_akshare_path")
    def test_base_exception_still_clears_inflight_and_arms_backoff(self, monkeypatch):
        # finally safety net: even when a BaseException (KeyboardInterrupt/SystemExit, say) escapes,
        # the in-flight handle must be cleared, the backoff armed and the waiters woken, leaving no dead handle
        class _Bomb(BaseException):
            pass

        def bomb():
            raise _Bomb

        # Take over excepthook: this silences the unhandled-exception output when the worker dies and gives a
        # deterministic signal that "the worker died carrying _Bomb" (independent of global thread state,
        # so a background refresh thread leaked by another case cannot interfere)
        hook_calls: list = []
        monkeypatch.setattr(threading, "excepthook", lambda args: hook_calls.append(args))
        monkeypatch.setattr(ntc, "_fetch_akshare_df", bomb)
        t1, r1 = _run_resolver_in_thread("浦发银行")
        t1.join(timeout=10)
        assert not t1.is_alive()
        assert _wait_until(lambda: hook_calls)  # the worker has fired excepthook
        assert r1.get("value") == []  # the waiter, woken by finally, received None
        assert ntc._akshare_inflight is None  # no dead handle
        assert ntc._akshare_failure_cache is not None  # the backoff is armed
        assert ntc._get_akshare_name_to_code() is None  # no network inside the backoff window


# ---------------------------------------------------------------------------
# Stale-while-revalidate: an expired TTL must return the old value immediately (zero wait) while the refresh
# runs in the background; inside a network-failure backoff the old value keeps serving (availability), and only a cold start degrades.
# ---------------------------------------------------------------------------


class TestAkShareStaleWhileRevalidate:
    @pytest.mark.usefixtures("real_akshare_path")
    def test_stale_served_immediately_while_refresh_inflight(self, monkeypatch):
        # Prime the cache to v1 with an immediately returning fake fetch
        primed = {"浦发银行": "600000"}

        def fetch_v1():
            return pd.DataFrame({"code": ["600000"], "name": ["浦发银行"]})

        monkeypatch.setattr(ntc, "_fetch_akshare_df", fetch_v1)
        assert ntc._get_akshare_name_to_code() == primed
        # Force expiry: wind the timestamp back past the TTL
        ntc._akshare_cache = (time.time() - ntc._AKSHARE_CACHE_TTL - 10, primed)

        # Swap in the blocking fetch (v2: 600000 renamed to 新名称银行)
        fake = _FakeAkShareFetch(rows={"code": ["600000"], "name": ["新名称银行"]})
        monkeypatch.setattr(ntc, "_fetch_akshare_df", fake.fetch)

        started = time.monotonic()
        result = ntc._get_akshare_name_to_code()
        elapsed = time.monotonic() - started
        try:
            # Core assertion: the stale value returns immediately, with no wait on the in-flight fetch
            assert result == primed
            assert elapsed < 2
            # The background refresh really did start and has not finished (the fake is still blocked)
            assert fake.fetch_started.wait(timeout=5)
            assert not fake.release_fetch.is_set()
        finally:
            fake.release_fetch.set()
        # After the refresh finishes the new cache is visible, and the whole process fetched only once
        v2 = {"新名称银行": "600000"}
        assert _wait_until(lambda: ntc._akshare_cache is not None and ntc._akshare_cache[1] == v2)
        assert fake.calls == 1
        assert ntc._get_akshare_name_to_code() == v2

    @pytest.mark.usefixtures("real_akshare_path")
    def test_backoff_window_serves_stale_during_outage(self, monkeypatch):
        # Prime the cache to v1 and force expiry
        primed = {"浦发银行": "600000"}

        def fetch_ok():
            return pd.DataFrame({"code": ["600000"], "name": ["浦发银行"]})

        monkeypatch.setattr(ntc, "_fetch_akshare_df", fetch_ok)
        assert ntc._get_akshare_name_to_code() == primed
        ntc._akshare_cache = (time.time() - ntc._AKSHARE_CACHE_TTL - 10, primed)

        # Swap in an immediately failing fetch: the first stale call starts a background refresh and fails
        calls = {"n": 0}

        def fetch_fail():
            calls["n"] += 1
            raise RuntimeError("simulated outage")

        monkeypatch.setattr(ntc, "_fetch_akshare_df", fetch_fail)
        assert ntc._get_akshare_name_to_code() == primed  # the old value still serves during the outage
        assert _wait_until(lambda: ntc._akshare_failure_cache is not None)
        # Called again inside the backoff window: it keeps serving stale and starts no new fetch
        assert ntc._get_akshare_name_to_code() == primed
        assert calls["n"] == 1


# ---------------------------------------------------------------------------
# Disk cache: persisted atomically after a successful fetch; lazily loaded after a restart (globals reset), zero network.
# ---------------------------------------------------------------------------


class TestAkShareDiskCache:
    @pytest.mark.usefixtures("real_akshare_path")
    def test_persist_and_reload_without_network(self, monkeypatch):
        def fetch_ok():
            return pd.DataFrame({"code": ["600000"], "name": ["浦发银行"]})

        monkeypatch.setattr(ntc, "_fetch_akshare_df", fetch_ok)
        assert ntc._get_akshare_name_to_code() == {"浦发银行": "600000"}
        assert _wait_until(lambda: ntc._AKSHARE_DISK_CACHE_PATH.is_file())

        # Simulate a restart: the in-memory state is fully reset while the disk keeps its copy
        ntc._akshare_cache = None
        ntc._akshare_failure_cache = None
        ntc._akshare_disk_checked = False

        never = _FakeAkShareFetch()
        monkeypatch.setattr(ntc, "_fetch_akshare_df", never.fetch)
        # The lazy load hits directly (the persisted timestamp is fresh), with zero network throughout
        assert ntc._get_akshare_name_to_code() == {"浦发银行": "600000"}
        assert never.calls == 0

    @pytest.mark.usefixtures("real_akshare_path")
    def test_corrupt_disk_cache_ignored(self, monkeypatch):
        ntc._AKSHARE_DISK_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        ntc._AKSHARE_DISK_CACHE_PATH.write_text("not-a-json{", encoding="utf-8")

        calls = {"n": 0}

        def fetch_ok():
            calls["n"] += 1
            return pd.DataFrame({"code": ["600000"], "name": ["浦发银行"]})

        monkeypatch.setattr(ntc, "_fetch_akshare_df", fetch_ok)
        # A corrupt disk cache is ignored and the normal cold-start fetch runs
        assert ntc._get_akshare_name_to_code() == {"浦发银行": "600000"}
        assert calls["n"] == 1


# ---------------------------------------------------------------------------
# Warm-up is idempotent: concurrent or repeated calls share one in-flight handle and trigger a single network fetch.
# ---------------------------------------------------------------------------


class TestWarmupIdempotent:
    @pytest.mark.usefixtures("real_akshare_path")
    def test_double_warmup_shares_single_fetch(self, monkeypatch):
        fake = _FakeAkShareFetch()
        monkeypatch.setattr(ntc, "_fetch_akshare_df", fake.fetch)

        ntc.warmup_akshare_cache()
        assert fake.fetch_started.wait(timeout=5)  # the in-flight handle is registered
        ntc.warmup_akshare_cache()  # second call: shares the Future, no second fetch
        fake.release_fetch.set()

        assert _wait_until(
            lambda: ntc._akshare_cache is not None
            and ntc._akshare_cache[1] == {"浦发银行": "600000"}
        )
        assert fake.calls == 1


# ---------------------------------------------------------------------------
# The hang (rather than failure) case: once the subprocess timeout wrapper raises TimeoutError, it must take
# the regular failure path and arm the backoff instead of holding the single-flight lock forever.
# ---------------------------------------------------------------------------


class TestAkShareHangBackoff:
    @pytest.mark.usefixtures("real_akshare_path")
    def test_timeout_error_arms_failure_backoff(self, monkeypatch):
        calls = []

        def hang():
            calls.append(1)
            # The same exception type _akshare_call_with_timeout raises on timeout
            raise TimeoutError("stock_info_a_code_name 调用超过 25s，已放弃等待")

        monkeypatch.setattr(ntc, "_fetch_akshare_df", hang)
        assert ntc._get_akshare_name_to_code() is None
        assert ntc._akshare_failure_cache is not None  # the backoff is armed
        # Resolving again inside the backoff window: it takes the failure-cache fast path and never touches the network
        assert ntc._get_akshare_name_to_code() is None
        assert len(calls) == 1


# ---------------------------------------------------------------------------
# _fetch_akshare_df wiring: the worker must be called through the subprocess timeout wrapper (capping a hang).
# ---------------------------------------------------------------------------


class TestFetchAkshareDfWiring:
    def test_delegates_to_subprocess_timeout_wrapper(self, monkeypatch):
        import data_provider.akshare_fetcher as af

        captured = {}

        def fake_wrapper(func, *args, **kwargs):
            captured["func"] = func
            captured["timeout"] = kwargs.get("timeout")
            captured["call_name"] = kwargs.get("call_name")
            return pd.DataFrame({"code": ["600000"], "name": ["浦发银行"]})

        monkeypatch.setattr(af, "_akshare_call_with_timeout", fake_wrapper)
        df = ntc._fetch_akshare_df()
        assert captured["func"] is ntc._akshare_stock_info_worker
        assert captured["timeout"] == ntc._AKSHARE_FETCH_TIMEOUT
        assert captured["call_name"] == "stock_info_a_code_name"
        assert list(df["name"]) == ["浦发银行"]


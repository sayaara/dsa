# -*- coding: utf-8 -*-
"""Unit tests for the six-step web_intent_tokenizer pipeline.

Tokenisation and entity extraction only (WebIntentResolver intent decisions are out of scope):
  Step 1   exact full-name stock scan (_split_by_stock_entities, the first stage, with entry-point expansion)
  Step 2   special punctuation split (applied only to the gaps Step 1 left)
  Step 3   code-form extraction (_split_by_codes: a bare number -> unknown_number)
  Step 4   market-word extraction (_split_market_tokens, disambiguating "股" + "份")
  Step 5   unambiguous keywords (_tokenize_by_clean_keywords)
  Step 6   multi-strategy DFS matching (_multi_match; sector words come before the whole-DFS sector)
  code recognition _identify_stock_codes (unknown_code -> stock_code with a triple attached /
  wrong_{market}_code / unknown_{market}_code)

The AkShare expansion fires at the Step 1 pipeline entry (idempotently); the test mocks a minimal
full A-share data set (_MOCK_AKSHARE_A_SHARES) for offline determinism, and names outside both the
mock and the library still do not resolve.
"""

from unittest.mock import patch

import pytest

from src.agent.web_intent_tokenizer import (
    Token,
    _extract_markets_from_tokens,
    _identify_stock_codes,
    _is_identified_token,
    _market_of_code,
    _multi_match,
    _preprocess_text,
    _split_by_codes,
    _split_by_stock_entities,
    _split_market_tokens,
    _tokenize_by_clean_keywords,
)
from src.services.name_to_code_resolver import Stock, resolver_name_to_code_list
from src.agent.web_intent_types import (
    Market,
    TAG_CORP_SUFFIX,
    TAG_FILLER,
    TAG_QUESTION,
    TAG_REQUEST,
    TAG_SECTOR,
    TAG_SECTOR_NAME,
    TAG_SECTOR_N_STOCK,
    TAG_STOCK_CODE,
    TAG_STOCK_NAME,
    TAG_SUBJECT_MARKET,
    TAG_SUBJECT_MARKET_BROAD,
    TAG_SUBJECT_INDEX,
    TAG_SUBJECT_RESEARCH,
    TAG_UNKNOWN_CODE,
    TAG_UNKNOWN_NUMBER,
    unknown_code_tag,
    wrong_code_tag,
)

@pytest.fixture(autouse=True)
def _restore_resolver_state():
    """Snapshot and restore the module-level mutable state of name_to_code_resolver, so cases cannot leak into each other."""
    from src.services import name_to_code_resolver as resolver_mod

    db = dict(resolver_mod.stockDB)
    aliases = {code: set(names) for code, names in resolver_mod.stockAliases.items()}
    yield
    resolver_mod.stockDB.clear()
    resolver_mod.stockDB.update(db)
    resolver_mod.stockAliases.clear()
    resolver_mod.stockAliases.update(aliases)
    # stockDB is mutated in place, so name and pinyin lists cached by object identity may be stale - force a rebuild
    resolver_mod._names_cache[:] = [None, None, None]
    resolver_mod._pinyin_cache[:] = [None, None]


# =========================================================================
# Step 3 - code-form extraction
# =========================================================================

class TestSplitByCodes:
    """A bare number of any length is tagged unknown_number right in _split_by_codes;
    exchange-prefixed/suffixed forms and US ticker forms are tagged unknown_code."""

    def test_year_tag(self):
        assert _split_by_codes("2024") == [Token("2024", TAG_UNKNOWN_NUMBER)]

    def test_month_tag(self):
        assert _split_by_codes("12") == [Token("12", TAG_UNKNOWN_NUMBER)]

    def test_bare_4digit_tag(self):
        assert _split_by_codes("0070") == [Token("0070", TAG_UNKNOWN_NUMBER)]

    def test_bare_5digit_tag(self):
        assert _split_by_codes("00700") == [Token("00700", TAG_UNKNOWN_NUMBER)]

    def test_bare_6digit_tag(self):
        assert _split_by_codes("600519") == [Token("600519", TAG_UNKNOWN_NUMBER)]

    def test_bare_7digit_tag(self):
        assert _split_by_codes("6005199") == [Token("6005199", TAG_UNKNOWN_NUMBER)]

    def test_hk_suffix_still_unknown_code(self):
        assert _split_by_codes("1234.HK") == [Token("1234.HK", TAG_UNKNOWN_CODE)]

    def test_sz_suffix_still_unknown_code(self):
        assert _split_by_codes("0070.SZ") == [Token("0070.SZ", TAG_UNKNOWN_CODE)]

    def test_hk_prefix_still_unknown_code(self):
        assert _split_by_codes("HK12") == [Token("HK12", TAG_UNKNOWN_CODE)]

    def test_sh_prefix_form(self):
        assert _split_by_codes("SH600519") == [Token("SH600519", TAG_UNKNOWN_CODE)]

    def test_us_ticker_form(self):
        assert _split_by_codes("BABA") == [Token("BABA", TAG_UNKNOWN_CODE)]

    def test_us_suffix_case_insensitive(self):
        assert _split_by_codes("aapl.us") == [Token("aapl.us", TAG_UNKNOWN_CODE)]

    def test_date_splits_into_three_number_tokens(self):
        tokens = _split_by_codes("2024-08-12")
        assert [t.tag for t in tokens if t.tag] == [TAG_UNKNOWN_NUMBER] * 3
        # "-" is not in the punctuation split set (it can appear inside codes and names), so it survives as a gap token
        assert [t.text for t in tokens if not t.tag] == ["-", "-"]

    def test_overlapping_spans_merge_to_longest(self):
        # "HK3294384923": the prefix regex (0,12) and the bare-number regex (2,12) merge into the longest span
        assert _split_by_codes("HK3294384923") == [
            Token("HK3294384923", TAG_UNKNOWN_CODE),
        ]

    def test_gap_text_preserved_as_untagged_token(self):
        tokens = _split_by_codes("分析一下600519.SH")
        assert tokens == [
            Token("分析一下"),
            Token("600519.SH", TAG_UNKNOWN_CODE),
        ]

    def test_lowercase_words_not_code_candidates(self):
        # An ordinary lowercase English word is not a code-form candidate (a US ticker must be uppercase or carry .us)
        assert _split_by_codes("tell us about") == [Token("tell us about")]

    def test_empty_text_returns_no_tokens(self):
        assert _split_by_codes("") == []


# =========================================================================
# Step 2 - index words containing digits pass through (a CJK+digit compound is not broken by bare-number extraction)
# =========================================================================

class TestDigitKeywordRelease:
    """Enumerated index words containing digits, such as "沪深300" and "中证1000": the digit run is
    protected by _DIGIT_KEYWORDS_RE and passes through, the whole word reaches Step 4/5 as subject_index, and bare-number behaviour is unchanged."""

    @pytest.mark.parametrize("keyword", [
        "沪深300", "科创50",                       # the existing word pool
        "中证A500", "中证1000", "中证2000",        # added here (including the user-specified ones)
        "中证500", "中证800", "中证100",
        "上证50", "北证50", "深证100", "创业板50",
    ])
    def test_digit_index_keyword_kept_whole(self, keyword):
        _, tokens = _preprocess_text(f"{keyword}怎么样")
        pairs = [(t.text, t.tag) for t in tokens]
        assert (keyword, TAG_SUBJECT_INDEX) in pairs
        # A keyword's digit run must not leak out as a standalone bare-number token
        assert all(
            t.tag != TAG_UNKNOWN_NUMBER or keyword.find(t.text) < 0
            for t in tokens
        )

    def test_hushen_300_pipeline_exact(self):
        _, tokens = _preprocess_text("沪深300怎么样")
        assert [(t.text, t.tag) for t in tokens] == [
            ("沪深300", TAG_SUBJECT_INDEX),
            ("怎么样", TAG_QUESTION),
        ]

    def test_zhengzheng_1000_pipeline_exact(self):
        _, tokens = _preprocess_text("中证1000走势")
        assert [(t.text, t.tag) for t in tokens] == [
            ("中证1000", TAG_SUBJECT_INDEX),
            ("走势", TAG_SUBJECT_RESEARCH),
        ]

    def test_bare_numbers_untouched(self):
        # The pass-through applies only to a digit run fully contained in a keyword span; bare-number behaviour is unchanged
        assert _split_by_codes("300") == [Token("300", TAG_UNKNOWN_NUMBER)]
        assert _split_by_codes("1000") == [Token("1000", TAG_UNKNOWN_NUMBER)]
        assert _split_by_codes("50") == [Token("50", TAG_UNKNOWN_NUMBER)]

    def test_number_adjacent_to_digit_keyword(self):
        # "2024年沪深300": the year stays a bare number while the whole index word matches, without interfering
        _, tokens = _preprocess_text("2024年沪深300")
        pairs = [(t.text, t.tag) for t in tokens]
        assert ("2024", TAG_UNKNOWN_NUMBER) in pairs
        assert ("沪深300", TAG_SUBJECT_INDEX) in pairs

    def test_code_after_digit_keyword(self):
        _, tokens = _preprocess_text("中证1000和600519")
        pairs = [(t.text, t.tag) for t in tokens]
        assert ("中证1000", TAG_SUBJECT_INDEX) in pairs
        assert ("600519", TAG_UNKNOWN_NUMBER) in pairs

    def test_partial_overlap_not_released(self):
        # A digit run that only partly overlaps a keyword ("沪深3000" != "沪深300" + 0) is not protected:
        # bare-number extraction stands and the prefix goes downstream
        tokens = _split_by_codes("沪深3000")
        pairs = [(t.text, t.tag) for t in tokens]
        assert ("3000", TAG_UNKNOWN_NUMBER) in pairs


# =========================================================================
# Code recognition - unknown_code -> stock_code / wrong_{market}_code / unknown_{market}_code
# =========================================================================

class TestIdentifyStockCodes:
    """A library hit attaches the full triple and the canonical spelling; a miss is split into wrong/unknown by whether the market library is complete."""

    @staticmethod
    def _identify(token_text, tag=TAG_UNKNOWN_CODE):
        return _identify_stock_codes([Token(token_text, tag)])



    def test_hk_suffix_canonicalized(self):
        assert self._identify("00700.HK") == [
            Token("HK00700", TAG_STOCK_CODE, stocks=(Stock("HK00700", "腾讯控股", "hk"),))
        ]

    def test_hk_prefixed_bare_key_canonicalized(self):
        assert self._identify("HK00700") == [
            Token("HK00700", TAG_STOCK_CODE, stocks=(Stock("HK00700", "腾讯控股", "hk"),))
        ]

    def test_hk_short_suffix_padded_before_validation(self):
        # A 4-digit short suffix code (1810.HK = Xiaomi): the canonical is zero-padded before the 5-digit
        # gate, and the token text uses the canonical spelling HK01810 (matching stock_code_utils zfill(5))
        assert self._identify("1810.HK") == [
            Token("HK01810", TAG_STOCK_CODE, stocks=(Stock("HK01810", "小米集团", "hk"),))
        ]

    def test_hk_short_suffix_with_leading_zero_padded(self):
        assert self._identify("0700.HK") == [
            Token("HK00700", TAG_STOCK_CODE, stocks=(Stock("HK00700", "腾讯控股", "hk"),))
        ]

    def test_hk_short_prefix_padded(self):
        # A prefixed short code is padded the same way: HK700 -> HK00700 Tencent
        assert self._identify("HK700") == [
            Token("HK00700", TAG_STOCK_CODE, stocks=(Stock("HK00700", "腾讯控股", "hk"),))
        ]

    def test_hk_one_digit_suffix_padded(self):
        # The extreme case: 700.HK -> HK00700 (the same basis as the stock_scope regex \d{1,5}\.HK)
        assert self._identify("700.HK") == [
            Token("HK00700", TAG_STOCK_CODE, stocks=(Stock("HK00700", "腾讯控股", "hk"),))
        ]

    def test_us_ticker_in_db(self):
        assert self._identify("TSLA") == [
            Token("TSLA", TAG_STOCK_CODE, stocks=(Stock("TSLA", "特斯拉", "us"),))
        ]

    def test_us_ticker_lowercase_suffix_canonicalized(self):
        # aapl.us -> the canonical uppercase AAPL (the US extract regex only accepts uppercase, so it falls back to the uppercase spelling)
        assert self._identify("aapl.us") == [
            Token("AAPL", TAG_STOCK_CODE, stocks=(Stock("AAPL", "苹果", "us"),))
        ]

    def test_prefixed_illegal_code_is_wrong_a(self):
        # A prefixed invalid code (SH777777) enters wrong_a_code exactly like the bare 777777,
        # and the prefix form must not let it through (invalid form is decided by static exchange rules, independent of library state)
        assert self._identify("SH777777") == [Token("SH777777", wrong_code_tag("a"))]

    def test_hk_bad_digit_count_is_wrong_hk(self):
        # HK plus 11 digits: the digit count makes the form invalid -> wrong_hk_code
        assert self._identify("HK3294384923") == [
            Token("HK3294384923", wrong_code_tag("hk"))
        ]

    def test_hk_prefix_with_ashare_digits_is_wrong_hk(self):
        # HK prefix plus 6 digits (the A-share length) contradicts the label, so wrong_hk,
        # and it must not silently resolve to the A-share 600519 贵州茅台
        assert self._identify("HK600519") == [
            Token("HK600519", wrong_code_tag("hk"))
        ]

    def test_sh_prefix_with_hk_digits_is_wrong_a(self):
        # SH prefix plus 5 digits (the HK length) -> wrong_a, and it must not silently become HK00700 Tencent
        assert self._identify("SH00700") == [
            Token("SH00700", wrong_code_tag("a"))
        ]

    def test_sz_suffix_with_hk_digits_is_wrong_a(self):
        assert self._identify("00700.SZ") == [
            Token("00700.SZ", wrong_code_tag("a"))
        ]

    def test_hk_suffix_with_ashare_digits_is_wrong_hk(self):
        # .HK suffix plus 6 digits -> wrong_hk: a fragment must not be cut from the middle of the digits and
        # joined to the suffix to resolve (and taking the first of several candidates is equally forbidden)
        assert self._identify("600519.HK") == [
            Token("600519.HK", wrong_code_tag("hk"))
        ]

    def test_sh_marker_with_sz_digits_is_wrong_a(self):
        # SH prefix plus a Shenzhen code (000001 = 平安银行): the exchange label contradicts the digit form
        # -> wrong_a, and it must not silently resolve to 平安银行 (SH000001 means the SSE Composite)
        assert self._identify("SH000001") == [
            Token("SH000001", wrong_code_tag("a"))
        ]

    def test_bj_marker_with_sh_digits_is_wrong_a(self):
        # BJ prefix plus a Shanghai code (600519 = 贵州茅台) -> wrong_a, never silently resolved to Moutai
        assert self._identify("BJ600519") == [
            Token("BJ600519", wrong_code_tag("a"))
        ]

    def test_sz_marker_with_sh_digits_is_wrong_a(self):
        # SZ suffix plus a Shanghai code -> wrong_a (a suffix label is bound by the same consistency gate)
        assert self._identify("600519.SZ") == [
            Token("600519.SZ", wrong_code_tag("a"))
        ]



    def test_contradictory_double_marker_is_wrong(self):
        # A prefix and suffix labelling different markets: judged wrong by the suffix market, never silently resolved from the digits
        assert self._identify("HK600519.SH") == [
            Token("HK600519.SH", wrong_code_tag("a"))
        ]


    def test_out_of_db_ticker_kept_unknown_us(self):
        # SOFI is absent from the local library: the US library is never treated as complete, so unknown_us_code goes downstream to the LLM
        assert self._identify("SOFI") == [Token("SOFI", unknown_code_tag("us"))]

    def test_plain_english_word_kept_unknown_us(self):
        assert self._identify("OK") == [Token("OK", unknown_code_tag("us"))]



    def test_hk_absent_code_always_unknown(self):
        # The local HK library is never treated as complete: valid format but no library hit (HK39999) -> uncertain
        assert self._identify("HK39999") == [Token("HK39999", unknown_code_tag("hk"))]


    def test_untagged_tokens_pass_through(self):
        tokens = [Token("分析", TAG_REQUEST), Token("600519", TAG_UNKNOWN_NUMBER)]
        assert _identify_stock_codes(tokens) == tokens


# =========================================================================
# Step 1 - exact full-name stock scan (the first pipeline stage)
# =========================================================================

class TestFullNameScan:
    """The window must equal a full stock name in the library (4 to 3 characters); abbreviations and partial names are left to Step 6."""


    def test_cross_market_same_name_carries_candidates(self):
        # 阿里巴巴 -> hk 09988 / us BABA, several stocks share the name, so the token carries multiple candidates
        tokens = _split_by_stock_entities("阿里巴巴")
        assert len(tokens) == 1
        assert tokens[0].tag == TAG_STOCK_NAME
        assert {s.code for s in tokens[0].stocks} == {"HK09988", "BABA"}

    def test_abbreviation_not_matched_here(self):
        # A one-to-one abbreviation (茅台) is not a full name, so Step 1 skips it and Step 6 picks it up
        assert _split_by_stock_entities("茅台") == [Token("茅台")]

    def test_non_name_text_untouched(self):
        assert _split_by_stock_entities("大港股份怎么样") == [Token("大港股份怎么样")]



    def test_pure_ascii_short_circuit(self):
        # A pure-English segment is returned untouched (Step 6 pinyin / US code handles it)
        assert _split_by_stock_entities("TSLA") == [Token("TSLA")]

    def test_two_char_full_name_matched(self):
        # The 8-to-2 window contract (the old "do not scan 2-character names" rule is reversed): a 2-character
        # full name (美团 = 03690) matches exactly and no longer depends on the Step 6 fuzzy path
        tokens = _split_by_stock_entities("美团")
        assert [(t.text, t.tag) for t in tokens] == [("美团", TAG_STOCK_NAME)]
        assert [s.code for s in tokens[0].stocks] == ["HK03690"]

    def test_six_char_full_name_matched_whole(self):
        # A 6-character full name (中国海洋石油 = 00883) matches whole, instead of falling to DFS and splitting into
        # "中国海洋" + "石油" at the wrong boundary (the "石油" substring once dragged in an unmentioned 中国石油)
        tokens = _split_by_stock_entities("中国海洋石油怎么样")
        assert [(t.text, t.tag) for t in tokens] == [
            ("中国海洋石油", TAG_STOCK_NAME),
            ("怎么样", ""),
        ]
        assert [s.code for s in tokens[0].stocks] == ["HK00883"]

    def test_spaced_six_char_name_matched_whole(self):
        # A 6-character full name written with single spaces (11 raw characters, over the compressed length cap of 8):
        # whitespace collapsing plus the span upper bound (2*max_len-1) still match the whole name, and the token text is the flattened spelling
        tokens = _split_by_stock_entities("中 国 海 洋 石 油怎么样")
        assert [(t.text, t.tag) for t in tokens] == [
            ("中国海洋石油", TAG_STOCK_NAME),
            ("怎么样", ""),
        ]
        assert [s.code for s in tokens[0].stocks] == ["HK00883"]

    def test_spaced_long_name_pipeline_resolves(self):
        # Full pipeline: a spaced 6-character full name matches whole - Step 2's whitespace split would tear it into
        # single characters with no way for Step 6 to recover it, so Step 1 must consume it here
        _, tokens = _preprocess_text("中 国 海 洋 石 油怎么样")
        assert [(t.text, t.tag) for t in tokens] == [
            ("中国海洋石油", TAG_STOCK_NAME),
            ("怎么样", TAG_QUESTION),
        ]
        assert [s.code for s in tokens[0].stocks] == ["HK00883"]



# =========================================================================
# HK code identity invariant - the name path and the code path share one spelling
# =========================================================================

class TestHkCodeIdentityInvariant:
    """The token-layer code identity contract: a = 6 bare digits, hk = HK plus 5 digits, us = an uppercase
    ticker (defined in exactly one place, _canonical_stock_code). The name path (Step 1 entity/alias scan,
    Step 6 substring/pinyin matching) and the code path (_identify_stock_codes) must agree, or the same
    stock takes several identities across turns (breaking recent_stocks dedup and event comparison).
    The stockDB HK key stays bare 5 digits; normalisation happens only at the token layer and the resolver contract is unchanged."""

    @pytest.mark.parametrize("name, code", [
        ("腾讯控股", "HK00700"),
        ("美团", "HK03690"),
    ])
    def test_name_path_matches_code_path(self, name, code):
        # P1-1 regression: a name reference and a code reference in one message must resolve to the same code spelling
        _, tokens = _preprocess_text(f"{name}怎么样")
        name_codes = {s.code for t in tokens if t.tag == TAG_STOCK_NAME
                      for s in (t.stocks or ())}
        out = _identify_stock_codes([Token(code.lower(), TAG_UNKNOWN_CODE)])
        code_codes = {s.code for t in out for s in (t.stocks or ())}
        assert name_codes == code_codes == {code}

    def test_step1_alias_hit_canonical(self):
        # The Step 1 alias branch: a hit shows the current canonical name plus the canonical spelling
        from src.services import name_to_code_resolver as resolver_mod

        resolver_mod.stockAliases.setdefault("00700", set()).add("老腾讯名")
        resolver_mod._names_cache[:] = [None, None, None]
        try:
            tokens = _split_by_stock_entities("老腾讯名怎么样")
            assert [(t.text, t.tag) for t in tokens] == [
                ("老腾讯名", TAG_STOCK_NAME), ("怎么样", "")
            ]
            assert [s.code for s in tokens[0].stocks] == ["HK00700"]
            assert tokens[0].stocks[0].name == "腾讯控股"
        finally:
            resolver_mod.stockAliases["00700"].discard("老腾讯名")
            if not resolver_mod.stockAliases["00700"]:
                del resolver_mod.stockAliases["00700"]
            resolver_mod._names_cache[:] = [None, None, None]

    def test_dfs_cjk_substring_path_canonical(self):
        # The Step 6 CJK loop matches the HK stock through a resolver substring (腾讯 within 腾讯控股)
        _, tokens = _preprocess_text("腾讯怎么样")
        assert [s.code for t in tokens if t.tag == TAG_STOCK_NAME
                for s in (t.stocks or ())] == ["HK00700"]

    def test_dfs_alpha_pinyin_path_canonical(self):
        # The Step 6 alpha path matches the HK stock by pinyin (tengxun within tengxunkonggu)
        _, tokens = _preprocess_text("tengxun怎么样")
        assert [s.code for t in tokens if t.tag == TAG_STOCK_NAME
                for s in (t.stocks or ())] == ["HK00700"]

    def test_no_bare_hk_code_in_any_token(self):
        # Invariant sweep: no token's stocks may hold market == "hk" together with an all-digit code
        # (a cross-market name such as 理想汽车 = LI + 02015 is normalised per candidate inside one token)
        for msg in ["腾讯控股和美团对比", "阿里巴巴vs贵州茅台", "港股腾讯控股",
                    "分析hk00700和腾讯控股", "理想汽车怎么样"]:
            _, tokens = _preprocess_text(msg)
            for t in tokens:
                for s in (t.stocks or ()):
                    assert not (s.market == "hk" and s.code.isdigit()), (msg, s)


# =========================================================================
# Step 1 entity scan runs first - a library full name containing an uppercase ASCII substring is not torn apart by code-form extraction
# =========================================================================

class TestAsciiContainedFullName:
    """P1-1 regression: when a library full name contains an uppercase ASCII substring shaped like a US ticker
    ("TCL" inside "TCL科技"), the Step 1 entity scan (the first stage, expanding at the entry) must consume the whole name.
    The old order (code-form extraction before the entity scan) tore "TCL" into an unknown_code and
    mislabelled "科技" as a sector_name - losing the entity and emitting a bogus industry/market signal,
    equally broken on a cold and a warm library."""

    _TCL_MOCK = {"TCL科技": "000100"}

    def _run(self, msg):
        """Cold-start precondition: reset the expansion state, so the first message meets the expansion at the Step 1 entry."""
        from src.services import name_to_code_resolver as resolver_mod

        with patch(
            "src.services.name_to_code_resolver._get_akshare_name_to_code",
            return_value=self._TCL_MOCK,
        ):
            resolver_mod._akshare_merged = None
            resolver_mod._names_cache[:] = [None, None, None]
            _, tokens = _preprocess_text(msg)
        return _identify_stock_codes(tokens)







# =========================================================================
# Keyword case insensitivity - the lowercase form of an uppercase stored word matches identically
# =========================================================================

class TestCaseInsensitiveKeywordClassification:
    """P1-2 regression: keyword case insensitivity matches the (?i:) compile declaration - the lowercase forms
    ("ai赛道" / "中证a500") of uppercase stored keywords ("AI" / "中证A500") must produce exactly what the
    uppercase originals do, never failing outright or being torn apart by bare-number extraction."""

    def test_lowercase_ai_sector_pair(self):
        _, tokens = _preprocess_text("ai赛道")
        assert [(t.text, t.tag) for t in tokens] == [
            ("ai", TAG_SECTOR_NAME),
            ("赛道", TAG_SECTOR),
        ]

    def test_lowercase_digit_index_keyword_kept_whole(self):
        # The digit run in "中证a500" is protected and passes through (case-insensitively), so the whole word
        # matches subject_index rather than splitting into "中证a" + "500"
        _, tokens = _preprocess_text("中证a500走势")
        assert [(t.text, t.tag) for t in tokens] == [
            ("中证a500", TAG_SUBJECT_INDEX),
            ("走势", TAG_SUBJECT_RESEARCH),
        ]

    def test_digit_keyword_release_case_insensitive(self):
        assert _split_by_codes("中证a500") == [Token("中证a500")]

    def test_uppercase_pool_keyword_original_form_unchanged(self):
        # Matching the original form of an uppercase stored word is unaffected by the normalisation table
        assert _preprocess_text("AI赛道")[1][0].tag == TAG_SECTOR_NAME


# =========================================================================
# Letter-dot-exchange suffix codes - the suffix and the body form one span
# =========================================================================

class TestSuffixedUsTicker:
    """The BRK.B / AAPL.N / TSLA.N forms (matching the extract_stock_codes US regex): the suffix and the body
    must form one span and must not split into "BRK" + ".B" - the old regex left the text of an out-of-library
    code mutilated (unknown_us_code holding only "BRK")."""

    def test_step3_keeps_suffix_whole(self):
        assert _split_by_codes("BRK.B") == [Token("BRK.B", TAG_UNKNOWN_CODE)]
        assert _split_by_codes("AAPL.N") == [Token("AAPL.N", TAG_UNKNOWN_CODE)]
        assert _split_by_codes("TSLA.N怎么样") == [
            Token("TSLA.N", TAG_UNKNOWN_CODE),
            Token("怎么样"),
        ]

    def test_identify_in_db_ticker_with_suffix(self):
        # An in-library ticker: take the canonical uppercase spelling of the body (AAPL.N -> AAPL)
        assert _identify_stock_codes([Token("AAPL.N", TAG_UNKNOWN_CODE)]) == [
            Token("AAPL", TAG_STOCK_CODE, stocks=(Stock("AAPL", "苹果", "us"),))
        ]

    def test_identify_out_of_db_keeps_text_intact(self):
        # An out-of-library suffixed code: the text stays whole for downstream confirmation (no more "BRK" + ".B")
        assert _identify_stock_codes([Token("BRK.B", TAG_UNKNOWN_CODE)]) == [
            Token("BRK.B", unknown_code_tag("us"))
        ]

    def test_us_suffix_pattern_unaffected(self):
        # The .us suffix (case-insensitive) behaves as before
        assert _split_by_codes("aapl.us") == [Token("aapl.us", TAG_UNKNOWN_CODE)]
        assert _split_by_codes("BABA.US") == [Token("BABA.US", TAG_UNKNOWN_CODE)]


# =========================================================================
# Step 4 - market-word extraction
# =========================================================================

class TestMarketTokenSplit:
    """"股" followed by "份" (a stock-name suffix) is skipped, so the "港股" inside "大港股份" is not extracted."""

    def test_market_word_tagged(self):
        tokens = _split_market_tokens("港股")
        assert [(t.text, t.tag) for t in tokens] == [("港股", TAG_SUBJECT_MARKET)]

    def test_ascii_market_case_insensitive(self):
        tokens = _split_market_tokens("A股")
        assert [(t.text, t.tag) for t in tokens] == [("A股", TAG_SUBJECT_MARKET)]

    def test_market_suffix_company_name_not_split(self):
        # The "港股" substring inside "大港股份" is followed by "份" -> skipped, and the run is preserved
        assert _split_market_tokens("大港股份") == [Token("大港股份")]

    def test_broad_market_keyword(self):
        tokens = _split_market_tokens("行情怎么样")
        assert ("行情", TAG_SUBJECT_MARKET_BROAD) in [(t.text, t.tag) for t in tokens]

    def test_gap_untagged(self):
        tokens = _split_market_tokens("看看港股走势")
        assert [t.text for t in tokens] == ["看看", "港股", "走势"]
        assert tokens[1].tag == TAG_SUBJECT_MARKET


# =========================================================================
# Step 5 - unambiguous keywords
# =========================================================================

class TestCleanKeywordTokenize:
    def test_request_and_filler(self):
        tokens = _tokenize_by_clean_keywords("帮我分析一下")
        assert [(t.text, t.tag) for t in tokens] == [
            ("帮我", TAG_FILLER),
            ("分析", TAG_REQUEST),
            ("一下", TAG_FILLER),
        ]

    def test_research_subject(self):
        tokens = _tokenize_by_clean_keywords("走势")
        assert tokens == [Token("走势", TAG_SUBJECT_RESEARCH)]

    def test_ambiguous_keyword_not_in_clean_pool(self):
        # "对比" is in the extend pool (it can be confused with a stock name), so clean tokenisation does not extract it
        assert _tokenize_by_clean_keywords("对比") == [Token("对比")]


# =========================================================================
# Step 6 sector-word contract - sector words never match individual stock names (no fuzzy matching before Step 6)
# =========================================================================

class TestSectorWordNotStockMatched:
    """Sector words never match individual stock names. "XX板块/行业/赛道/概念/题材" has no dedicated regex:
    the Step 6 DFS splits an in-pool industry name and the generic term into an adjacent
    [sector_name/sector_n_stock] + [sector] token pair, and that adjacency is the high-confidence sector
    signal the downstream consumes. Steps 1-5 stay purely exact-match."""

    def test_suffix_decomposes_to_adjacent_pair(self):
        # Step 5 clean keywords come before Step 6; "建筑板块" -> [sector_name] + [sector], adjacent
        _, tokens = _preprocess_text("看看建筑板块")
        assert [(t.text, t.tag) for t in tokens] == [
            ("看看", TAG_REQUEST),
            ("建筑", TAG_SECTOR_NAME),
            ("板块", TAG_SECTOR),
        ]

    def test_industry_prefix_never_stock_matched(self):
        # "建筑" must not resolve through the name library substring into the 中国建筑 stock
        _, tokens = _preprocess_text("看看建筑板块")
        assert all(t.tag != TAG_STOCK_NAME for t in tokens)

    def test_multi_match_adjacent_pair_direct(self):
        assert _multi_match("建筑板块") == [
            Token("建筑", TAG_SECTOR_NAME),
            Token("板块", TAG_SECTOR),
        ]

    def test_adjacent_pair_then_dfs_recursion(self):
        # Once the adjacent pair matches, the remaining text keeps matching inside the same recursion chain
        tokens = _multi_match("建筑板块怎么样")
        assert [(t.text, t.tag) for t in tokens] == [
            ("建筑", TAG_SECTOR_NAME),
            ("板块", TAG_SECTOR),
            ("怎么样", TAG_QUESTION),
        ]

    def test_ascii_industry_word_pair(self):
        # An ASCII industry name (AI is in the TAG_SECTOR_NAME pool) takes the adjacent pair path too
        assert _multi_match("AI赛道") == [
            Token("AI", TAG_SECTOR_NAME),
            Token("赛道", TAG_SECTOR),
        ]

    def test_bare_suffix_still_keyword_matched(self):
        # The bare suffix "板块" with no prefix is matched by the DFS extend exact keywords
        assert _multi_match("板块") == [Token("板块", TAG_SECTOR)]

    def test_unenumerated_industry_word_left_for_llm(self):
        # An unenumerated industry word (预制菜) is not in the pool: the run cannot match fully -> left as-is with an empty tag for the LLM
        assert _multi_match("预制菜板块") == [Token("预制菜板块")]

    def test_enumerated_industry_word_sector_first(self):
        # "建筑" is enumerated in the TAG_SECTOR_NAME pool (proven by the full library to be a substring of 中国建筑):
        # the industry sense wins for the bare word, tagged sector_name rather than resolved to the 中国建筑 stock
        assert _multi_match("建筑") == [Token("建筑", TAG_SECTOR_NAME)]

    def test_enumerated_word_beats_name_library_substring(self):
        # A real collision in the base library: "农业" within 农业银行, "证券" within 中信证券 - Step 6 keyword
        # classification wins over a name-library substring hit, so the bare word is tagged sector_name
        assert _multi_match("农业") == [Token("农业", TAG_SECTOR_NAME)]
        assert _multi_match("证券") == [Token("证券", TAG_SECTOR_NAME)]

    def test_sector_n_stock_word_ambiguous_tag(self):
        # An industry name that is also a full stock name (机器人 = 300024): bare use gets the ambiguous tag sector_n_stock,
        # neither stock_name nor an arbitrary sector_name, leaving the LLM or a confirmation to disambiguate
        assert _multi_match("机器人") == [Token("机器人", TAG_SECTOR_N_STOCK)]

    def test_full_name_scan_releases_enumerated_word(self):
        # "机器人" is the full name of 300024 in the production library: after injection Step 1 must let it through
        # and must not tag it stock_name before Step 6, leaving Step 6 keywords to apply the ambiguous tag
        from src.services import name_to_code_resolver as resolver_mod

        resolver_mod.stockDB["300024"] = "机器人"
        assert _split_by_stock_entities("机器人板块") == [Token("机器人板块")]
        # DFS regression: the 4-character window "机器人板" is fuzzy-matched to "机器人" first
        # (ratio about 0.86), but the remaining "块" cannot match fully -> it backtracks to the 3-character keyword path
        # and produces the high-confidence adjacent pair [sector_n_stock] + [sector]
        _, tokens = _preprocess_text("机器人板块")
        assert [(t.text, t.tag) for t in tokens] == [
            ("机器人", TAG_SECTOR_N_STOCK),
            ("板块", TAG_SECTOR),
        ]
        _, tokens = _preprocess_text("机器人怎么样")
        assert [(t.text, t.tag) for t in tokens] == [
            ("机器人", TAG_SECTOR_N_STOCK),
            ("怎么样", TAG_QUESTION),
        ]


# =========================================================================
# Step 6 - multi-strategy DFS matching
# =========================================================================

class TestMultiMatch:
    def test_filler_run_split_to_single_chars(self):
        tokens = _multi_match("的的")
        assert [t.text for t in tokens] == ["的", "的"]
        assert all(t.tag == TAG_FILLER for t in tokens)

    def test_overlong_token_returned_unchanged(self):
        text = "的" * 250
        assert _multi_match(text) == [Token(text)]

    def test_length_cap_boundary_50_processed(self):
        # Exactly 50 characters (at the cap) still enters DFS: the filler covers every character (the filler-only
        # path skips the full-library scan, so there is no performance risk)
        tokens = _multi_match("的" * 50)
        assert [t.text for t in tokens] == ["的"] * 50
        assert all(t.tag == TAG_FILLER for t in tokens)

    def test_length_cap_boundary_51_abandoned(self):
        # 51 characters (over the cap): 50+ characters with no punctuation and none of the signals Steps 2-5
        # already extracted is assumed not to be normal dialogue, so the whole run goes downstream to the LLM
        text = "的" * 51
        assert _multi_match(text) == [Token(text)]

    def test_length_cap_leaves_earlier_steps_intact(self):
        # The cap applies only to Step 6: the codes, full names and keywords Steps 2-5 extracted are unaffected
        _, tokens = _preprocess_text("分析600519.SH，" + "的" * 60)
        pairs = [(t.text, t.tag) for t in tokens]
        assert ("分析", TAG_REQUEST) in pairs
        assert ("600519.SH", TAG_UNKNOWN_CODE) in pairs
        assert ("的" * 60, "") in pairs


    def test_generic_corp_suffix_not_fabricated(self):
        # "苹果公司" must not split into two stock_names, 苹果 + 公司: "公司" is a zero-discrimination generic
        # suffix (the extend pool's corp_suffix), and a substring hit on 中微公司 is noise, not signal -
        # 苹果 matches exactly while "公司" is tagged corp_suffix and joins the DFS full coverage
        tokens = _multi_match("苹果公司")
        assert [(t.text, t.tag) for t in tokens] == [
            ("苹果", TAG_STOCK_NAME), ("公司", TAG_CORP_SUFFIX)
        ]
        assert [s.code for s in tokens[0].stocks] == ["AAPL"]

    def test_suffix_tag_enables_full_coverage(self):
        # The corp_suffix makes DFS full coverage possible: "腾讯公司" -> 腾讯 (腾讯控股) +
        # 公司 (corp_suffix), rather than abandoning the run downstream (which the empty-tag design could not cover)
        tokens = _multi_match("腾讯公司")
        assert [(t.text, t.tag) for t in tokens] == [
            ("腾讯", TAG_STOCK_NAME), ("公司", TAG_CORP_SUFFIX)
        ]
        assert [s.code for s in tokens[0].stocks] == ["HK00700"]

    def test_bare_generic_suffix_tagged_corp_suffix(self):
        # A purely generic suffix standing alone: no full-library scan, tagged corp_suffix (the original implementation
        # resolved it into the 5 stock_name candidates 上汽/豪威/小米/京东/百度)
        assert _multi_match("集团") == [Token("集团", TAG_CORP_SUFFIX)]

    def test_generic_suffix_pipeline_not_injected(self):
        # Full-pipeline regression: 分析 苹果公司 走势 -> only 苹果 (AAPL) is produced, with no 688012 injected
        _, tokens = _preprocess_text("分析 苹果公司 走势")
        assert [(t.text, t.tag) for t in tokens] == [
            ("分析", TAG_REQUEST),
            ("苹果", TAG_STOCK_NAME),
            ("公司", TAG_CORP_SUFFIX),
            ("走势", TAG_SUBJECT_RESEARCH),
        ]
        assert [s.code for t in tokens if t.tag == TAG_STOCK_NAME
                for s in (t.stocks or ())] == ["AAPL"]


    def test_space_separated_ascii_words_resolved(self):
        # Whitespace is a word boundary and Step 1 splits on it - space-separated lowercase words behave like comma-separated ones
        # (the whole run used to fail to the LLM; the accidental edge where a remaining word of 4 characters or fewer
        # scraped through on a "spaced fuzzy hit" leaving a leading space in the token text is gone too)
        _, tokens = _preprocess_text("tsla aapl")
        assert [(t.text, t.tag) for t in tokens] == [
            ("tsla", TAG_STOCK_NAME), ("aapl", TAG_STOCK_NAME)
        ]
        assert [s.code for t in tokens for s in (t.stocks or ())] == ["TSLA", "AAPL"]

    def test_space_equivalent_to_comma(self):
        # Spaces and commas produce the same structure: independent tokens, no leading-space residue
        _, spaced = _preprocess_text("tsla amd")
        _, commaed = _preprocess_text("tsla,amd")
        assert [(t.text, t.tag) for t in spaced] == [(t.text, t.tag) for t in commaed]

    def test_space_separated_word_failure_not_contagious(self):
        # Words are independent: a junk word gets an empty tag for the LLM without dragging down its resolved neighbours
        _, tokens = _preprocess_text("tsla jkl")
        assert [(t.text, t.tag) for t in tokens] == [
            ("tsla", TAG_STOCK_NAME), ("jkl", "")
        ]


    def test_alpha_path_ascii_name_dedup(self):
        # A US stock whose ASCII name equals its ticker (AMD): the resolver exact-name match and the
        # US ticker match each contribute one entry, so the concatenation must dedup by (code, market),
        # or duplicate stocks would be misread downstream as an ambiguous name
        tokens = _multi_match("amd")
        assert len(tokens) == 1
        assert tokens[0].tag == TAG_STOCK_NAME
        assert [(s.code, s.market) for s in tokens[0].stocks] == [("AMD", "us")]


    @pytest.mark.parametrize("message", ["O", "K", "hi", "ai", "ma", "no", "you", "long", "open"])
    def test_common_latin_noise_not_stock(self, message):
        # A pinyin fragment that is too short must not match a stock-name pinyin substring (hi/long/open and the like)
        tokens = _multi_match(message)
        assert all(t.tag != TAG_STOCK_NAME for t in tokens)

    def test_unresolvable_text_returned_unchanged(self):
        assert _multi_match("你好股份") == [Token("你好股份")]

    def test_cjk_with_particle_not_pinyin_matched(self):
        # Regression: after 中大力德 (pinyin zhongdalide) is merged in from the expanded library, "阿里的" (pinyin
        # alide, a substring of zhongdalide) must not be mismatched through the pinyin substring layer; once the
        # longest-first 3-character DFS path fails it must fall back to the correct 2-character "阿里" substring + "的" filler
        resolver_name_to_code_list("酒鬼酒")  # a CJK query triggers the mocked AkShare merge
        tokens = _multi_match("阿里的")
        assert [(t.text, t.tag) for t in tokens] == [
            ("阿里", "stock_name"),
            ("的", "filler"),
        ]
        assert [s.code for s in tokens[0].stocks] == ["HK09988", "BABA"]


# =========================================================================
# Step 6 - cold-start DFS backtracking budget sentinel
# =========================================================================

# Three ingredients trigger it:
#   1. A 4-character library name (长城汽车): at the same alignment, len4 exact / len3 fuzzy ("长城汽"
#      vs "长城汽车" ratio = 0.75 fails, though "长城汽" can match a truncated name) / len2 substring
#      branches coexist, so the backtracking tree has a branching factor above 1;
#   2. A trailing character that fuzzy matching cannot absorb ("咣": "汽车咣" vs "长城汽车" ratio about 0.67
#      < 0.8) blocks a quick win on the first path and forces a full-tree backtrack;
#   3. Cold start: the name is absent from the local library and merged in mid-flight after the Step 1 entry
#      expansion - if whole-name consumption degrades (the expansion point moves later, the window narrows,
#      the alias index is dropped), the name falls to the Step 6 DFS first-CJK-resolver path and the exponential backtracking surface returns.
_BACKTRACK_NAME = "长城汽车"
_BACKTRACK_TAIL = "咣"


class TestDfsBacktrackingColdStart:
    """DFS backtracking budget sentinel: when the Step 6 length loop keeps several branches alive (len4 exact /
    len3 fuzzy / len2 substring), a "repeated full name plus an unabsorbable trailing character" construction
    backtracks exponentially. Once an exact full name is consumed whole by Step 1 (first-stage entry expansion,
    the 8-to-2 window, the entity/alias index), only an anonymous gap reaches DFS and the call count is constant.
    A low-confidence path with no exact anchor is at worst linear times a full-library scan, capped by the
    50-character limit. This budget assertion stops an exponential-backtracking regression after any link in the
    whole-name-consumption chain (expansion point, window width, alias index, exact-confirmation boundary) degrades."""

    @staticmethod
    def _cold_start_run(text):
        """The mocked expansion holds only the trigger name: it is absent from the library before the call
        (the cold-start precondition) and merged in after the Step 3 entry expansion. Returns (tokens, resolver call count)."""
        import src.agent.web_intent_tokenizer as tokenizer_mod

        calls = {"n": 0}
        orig = tokenizer_mod.resolver_name_to_code_list

        def _counting(fragment):
            calls["n"] += 1
            return orig(fragment)

        with patch(
            "src.agent.web_intent_tokenizer.resolver_name_to_code_list",
            _counting,
        ), patch(
            "src.services.name_to_code_resolver._get_akshare_name_to_code",
            return_value={_BACKTRACK_NAME: "601633"},
        ):
            _, tokens = _preprocess_text(text)
        return tokens, calls["n"]




# =========================================================================
# DFS duration-ratio sentinel - guards against an exponential backtracking regression
# =========================================================================

class TestDfsRescanBudgetSentinel:
    """The upper bound on how much longer a keyword-chain message (no exact anchor) may take than a zero-hit text
    of the same length: linear times a full-library scan is the normal cost, and going over suggests an
    exponential-backtracking regression (the ratio explodes to a thousandfold when Step 3 whole-name consumption
    breaks) or a badly degraded linear coefficient. The ratio is independent of both machine speed and library size (same library, same machine on both sides)."""

    def test_keyword_chain_bounded_time(self):
        import itertools
        import time
        from src.services import name_to_code_resolver as resolver_mod

        db = dict(resolver_mod.stockDB)
        try:
            # A controlled synthetic library of about 4913 names (roughly the size of the full AkShare A-share set),
            # whose character pool is disjoint from both measured texts, keeping the zero-hit baseline clean
            pool = "金木水火土天地人和风云雷电山海川湖林石田"
            i = 600000
            for combo in itertools.product(pool[:17], repeat=3):
                resolver_mod.stockDB[str(i)] = "".join(combo)
                i += 1
            resolver_mod._names_cache[:] = [None, None, None]

            chain_text = "白酒板块" * 11 + "好"       # 45 characters, under the 50 cap
            gib_text = "狐猬獾貂蚨鹉鹦鹋鹌" * 2        # 18 characters, zero hits, also inside the cap

            t0 = time.perf_counter()
            _multi_match(chain_text)
            chain = time.perf_counter() - t0
            t0 = time.perf_counter()
            _multi_match(gib_text)
            gib = time.perf_counter() - t0

            ratio = chain / max(gib, 1e-9)
            assert ratio < 60, (
                f"哨兵: 关键词链消息耗时 {chain*1000:.0f}ms，"
                f"为同长零命中文本({gib*1000:.0f}ms)的 {ratio:.0f} 倍（阈值 60）——"
                f"疑似指数回溯回归或线性系数显著劣化"
            )
        finally:
            resolver_mod.stockDB.clear()
            resolver_mod.stockDB.update(db)
            resolver_mod._names_cache[:] = [None, None, None]


# =========================================================================
# Step 3 pass-through + Step 1 asterisk-equivalent exact matching + Step 6 fuzzy ban
# =========================================================================

class TestStPrefixNames:
    """An ST full name = prefix (ST / *ST / ST*, all three mutually recognised) + the AB characters: Step 3 does not
    treat "ST" as a code candidate (all three arrangements pass), and Step 1 does exact whole-name matching across the
    three forms - the tolerance covers only the prefix form (whether the * is omitted or placed differently), while the AB characters must equal a library full name exactly."""

    def test_step3_releases_st_prefix(self):
        # "ST" in all three arrangements is not a code candidate and the whole name survives (an out-of-library name
        # falls to Step 6; an in-library name is already consumed whole by Step 1)
        assert _split_by_codes("*ST美丽怎么样") == [Token("*ST美丽怎么样")]
        assert _split_by_codes("ST德豪怎么样") == [Token("ST德豪怎么样")]
        assert _split_by_codes("ST*美丽怎么样") == [Token("ST*美丽怎么样")]

    def test_step1_exact_match_with_star(self):
        from src.services import name_to_code_resolver as resolver_mod

        resolver_mod.stockDB["000010"] = "*ST美丽"
        try:
            tokens = _split_by_stock_entities("*ST美丽怎么样")
            assert [(t.text, t.tag) for t in tokens] == [
                ("*ST美丽", TAG_STOCK_NAME), ("怎么样", "")
            ]
            assert tokens[0].stocks == (Stock("000010", "*ST美丽", "a"),)
        finally:
            del resolver_mod.stockDB["000010"]

    def test_step1_star_equivalent_omitted_star(self):
        # The user omits the *: the window "ST美丽" matches the library's "*ST美丽" and the token keeps the input spelling
        from src.services import name_to_code_resolver as resolver_mod

        resolver_mod.stockDB["000010"] = "*ST美丽"
        try:
            tokens = _split_by_stock_entities("ST美丽怎么样")
            assert [(t.text, t.tag) for t in tokens] == [
                ("ST美丽", TAG_STOCK_NAME), ("怎么样", "")
            ]
            assert tokens[0].stocks == (Stock("000010", "*ST美丽", "a"),)
        finally:
            del resolver_mod.stockDB["000010"]

    def test_step1_three_prefix_forms_interchangeable(self):
        # Three-form recognition: the library holds "*ST美丽" and the input "ST*美丽" also matches whole,
        # with the token keeping the input spelling while stocks shows the library's canonical name
        from src.services import name_to_code_resolver as resolver_mod

        resolver_mod.stockDB["000010"] = "*ST美丽"
        try:
            tokens = _split_by_stock_entities("ST*美丽怎么样")
            assert [(t.text, t.tag) for t in tokens] == [
                ("ST*美丽", TAG_STOCK_NAME), ("怎么样", "")
            ]
            assert tokens[0].stocks == (Stock("000010", "*ST美丽", "a"),)
        finally:
            del resolver_mod.stockDB["000010"]

    def test_step1_star_equivalent_reverse(self):
        # The library name has no asterisk and the user typed one: equivalent in reverse
        from src.services import name_to_code_resolver as resolver_mod

        resolver_mod.stockDB["002174"] = "ST德豪"
        try:
            tokens = _split_by_stock_entities("*ST德豪走势")
            assert [(t.text, t.tag) for t in tokens] == [
                ("*ST德豪", TAG_STOCK_NAME), ("走势", "")
            ]
            assert tokens[0].stocks == (Stock("002174", "ST德豪", "a"),)
        finally:
            del resolver_mod.stockDB["002174"]

    def test_library_external_st_name_left_for_llm(self):
        # An out-of-library ST name: the three Step 3 forms miss and no Step 6 strategy hits in this environment
        # -> the whole run gets an empty tag for the LLM (Step 6 has no special ST branch)
        _, tokens = _preprocess_text("ST德豪怎么样")
        assert [(t.text, t.tag) for t in tokens] == [
            ("ST德豪", ""), ("怎么样", TAG_QUESTION)
        ]



# =========================================================================
# Step 6 cross-validation - better to do nothing than to do it wrong
# =========================================================================

class TestCrossValidation:
    """The Step 6 cross-validation contract: output happens only when several low-confidence hits together cover the
    whole run with tags; if any fragment has no tag the whole thing is abandoned (better nothing than wrong)."""


    def test_partial_coverage_abandoned(self):
        # "茅台你好": the "茅台" substring hit is low-confidence and the remaining "你好" cannot be covered ->
        # abandon the lot and emit no tag at all (better nothing)
        _, tokens = _preprocess_text("茅台你好")
        assert [(t.text, t.tag) for t in tokens] == [("茅台你好", "")]

    def test_step3_releases_ascii_keywords_case_insensitive(self):
        # An ASCII fragment in keyword form is not a code candidate (case-insensitively) -
        # letting the ticker regex take the uppercase form would lose the keyword sense and misroute it into US recognition
        assert _split_by_codes("茅台PK五粮液") == [Token("茅台PK五粮液")]
        assert _split_by_codes("BUY") == [Token("BUY")]
        # An uppercase word that is not a keyword is still a code candidate (the wide net is unchanged)
        assert _split_by_codes("ROE") == [Token("ROE", TAG_UNKNOWN_CODE)]


    def test_step3_releases_sector_pool_ascii_word(self):
        # Step 3 does not disturb sector entity recognition: "AI" is in the sector word pool, so it is not intercepted
        # as a code candidate and the pipeline layer can emit the high-confidence adjacent pair
        _, tokens = _preprocess_text("AI赛道")
        assert [(t.text, t.tag) for t in tokens] == [
            ("AI", TAG_SECTOR_NAME),
            ("赛道", TAG_SECTOR),
        ]


# =========================================================================
# Market enumeration extraction / recognition decision / code market inference
# =========================================================================

class TestExtractMarketsFromTokens:
    def test_market_tag_mapped(self):
        assert _extract_markets_from_tokens(
            [Token("港股", TAG_SUBJECT_MARKET)]
        ) == [Market.HK]
        assert _extract_markets_from_tokens(
            [Token("A股", TAG_SUBJECT_MARKET)]
        ) == [Market.A]

    def test_ascii_market_shorthand(self):
        # "HK" is tagged unknown_code by Step 3, but the text form is still a market hint
        assert _extract_markets_from_tokens([Token("HK", TAG_UNKNOWN_CODE)]) == [Market.HK]
        # A lowercase abbreviation needs CJK context: a standalone "us" in a Chinese message is a market hint
        assert _extract_markets_from_tokens([Token("看看"), Token("us")]) == [Market.US]

    def test_english_pronoun_us_not_market(self):
        # In a pure-English message the lowercase "us" is a pronoun ("tell us about..."), not a market hint
        assert _extract_markets_from_tokens([
            Token("tell"), Token("us"), Token("about"),
        ]) == []
        # An uppercase abbreviation is deliberate and is not constrained by context
        assert _extract_markets_from_tokens([Token("US")]) == [Market.US]

    def test_dedup(self):
        markets = _extract_markets_from_tokens([
            Token("港股", TAG_SUBJECT_MARKET),
            Token("香港", TAG_SUBJECT_MARKET),
        ])
        assert markets == [Market.HK]


class TestIsIdentifiedToken:
    def test_tagged_token_identified(self):
        assert _is_identified_token(Token("分析", TAG_REQUEST)) is True


    def test_code_like_text_not_identified_as_name(self):
        # A code key is not a name hit: a bare number must still go on to the code-extraction step
        assert _is_identified_token(Token("600519")) is False

    def test_abbreviation_not_identified_as_name(self):
        # "茅台" is an abbreviation, not a full name: it is absent from the name table and goes to Step 6 multi-strategy matching
        assert _is_identified_token(Token("茅台")) is False


class TestMarketOfCode:
    @pytest.mark.parametrize("code,expected", [
        ("600519", "a"),
        ("000799", "a"),
        ("00700", "hk"),
        ("09988", "hk"),
        ("AAPL", "us"),
        ("AAPL.N", "us"),   # a single-letter exchange suffix (the NYSE/NASDAQ shorthand)
        ("AAPL.US", ""),    # a two-letter suffix is outside the single-letter inference contract
        ("77", ""),
        ("", ""),
    ])
    def test_inference(self, code, expected):
        assert _market_of_code(code) == expected


# =========================================================================
# _preprocess_text - end-to-end pipeline
# =========================================================================

class TestPreprocessPipeline:



    def test_punctuation_tokens_filtered(self):
        # Pure punctuation and whitespace tokens are filtered out at the end of the pipeline
        _, tokens = _preprocess_text("你好，在吗？？")
        assert all(t.text.strip() for t in tokens)
        assert all(t.text not in ("，", "？") for t in tokens)

    def test_nfkc_width_normalization(self):
        # NFKC width normalisation at the entry (on a working copy): full-width digits and letters take part in every
        # step just like half-width ones - full-width digits were once silently dropped by the final filter and a
        # full-width Ａ missed the market keyword; the returned original text keeps the user's input verbatim
        _, tokens = _preprocess_text("Ａ股分析６００５１９")
        pairs = [(t.text, t.tag) for t in tokens]
        assert ("A股", TAG_SUBJECT_MARKET) in pairs
        assert ("分析", TAG_REQUEST) in pairs
        assert ("600519", TAG_UNKNOWN_NUMBER) in pairs
        text, _ = _preprocess_text("Ａ股分析６００５１９")
        assert text == "Ａ股分析６００５１９"


    def test_returns_original_text(self):
        text, _ = _preprocess_text("分析一下600519.SH")
        assert text == "分析一下600519.SH"

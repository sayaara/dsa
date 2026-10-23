# -*- coding: utf-8 -*-
"""Tests for :mod:`src.services.stock_list_parser`.

Phase 1 (issue #2063): covers the three core contracts —
* Allow-listed prefixed index: prefixed ``sh``/``sz`` + registry-known code -> ``index``
* Bare code defaults to a stock: bare numeric code -> ``stock`` even if it's an index code
* Unknown prefix degrades to a stock: prefixed unknown code -> ``stock`` (never ``unsupported``)

Also keeps the legacy ``split_stock_list`` / ``serialize_stock_list`` tests
so PR1 is a strict superset of pre-PR coverage rather than a replacement.
"""

from __future__ import annotations


import pytest

from src.services.stock_list_parser import (
    IndexEntry,
    IndexRegistry,
    ParseStatus,
    default_index_registry,
    parse_analysis_target,
    serialize_stock_list,
    split_stock_list,
)


# ---------------------------------------------------------------------------
# Legacy helpers — unchanged behaviour.
# ---------------------------------------------------------------------------
def test_split_stock_list_accepts_common_copy_paste_separators() -> None:
    value = "600519，300750  hk00700;AAPL、7203.T\n005930.KS；002594"

    assert split_stock_list(value) == [
        "600519",
        "300750",
        "hk00700",
        "AAPL",
        "7203.T",
        "005930.KS",
        "002594",
    ]


def test_serialize_stock_list_uses_canonical_commas() -> None:
    assert serialize_stock_list("600519，300750\nAAPL") == "600519,300750,AAPL"


# ---------------------------------------------------------------------------
# Contract #1 — prefixed index white-list.
# ---------------------------------------------------------------------------
class TestContract1PrefixedIndex:
    """Allow-listed prefixed index - prefixed ``sh``/``sz`` + registry-known code -> index."""

    def test_alias_resolution_sh000300_dot_sh(self) -> None:
        """Alias-style ``sh000300.SH`` — prefix ``sh`` carries, bare becomes
        ``000300.SH`` which matches the canonical entry's alias.
        """
        # ``sh`` prefix + bare ``000300.SH`` — the registry stores ``000300.SH``
        # as an alias, so this still resolves to index. Test the alias path
        # without having to teach the prefix splitter about dots.
        registry = IndexRegistry([
            IndexEntry(
                bare_code="000300",
                exchange="SH",
                canonical_id="sh000300",
                display_name="沪深300",
                aliases=("000300.SH",),
            )
        ])
        target = parse_analysis_target("sh000300.SH", registry=registry)
        # Contract #1 — alias matches even when bare carries a dot suffix.
        assert target.asset_type == ParseStatus.INDEX
        assert target.canonical_id == "sh000300"


# ---------------------------------------------------------------------------
# Contract #2 — bare code defaults to stock.
# ---------------------------------------------------------------------------
class TestContract2BareCodeDefaultsToStock:
    """Bare code defaults to a stock - a bare numeric code always resolves to a stock."""

    def test_bare_us_ticker_is_stock(self) -> None:
        target = parse_analysis_target("AAPL")
        assert target.asset_type == ParseStatus.STOCK
        assert target.exchange == "US"
        # US tickers preserve case so the canonical ID doubles as the
        # display code that fetchers accept directly.
        assert target.canonical_id == "AAPL"
        assert target.display_code == "AAPL"
        assert target.matched_index is None

    def test_bare_4_or_5_digit_codes_are_unsupported_hong_kong(self) -> None:
        # Bare 4-5 digit codes were Hong Kong short codes; Hong Kong is not currently supported.
        for raw in ("00700", "0941"):
            target = parse_analysis_target(raw)
            assert target.asset_type == ParseStatus.UNSUPPORTED
            assert target.exchange == "HK"


# ---------------------------------------------------------------------------
# Contract #3 — prefixed unknown degrades to stock.
# ---------------------------------------------------------------------------
class TestContract3PrefixedUnknownDegradesToStock:
    """Unknown prefix degrades to a stock - prefixed unknown -> stock (never unsupported)."""

    def test_hk_prefixed_code_is_unsupported(self) -> None:
        target = parse_analysis_target("hk00700")
        assert target.asset_type == ParseStatus.UNSUPPORTED
        assert target.exchange == "HK"

    def test_us_prefixed_ticker_is_stock(self) -> None:
        target = parse_analysis_target("usAAPL")
        assert target.asset_type == ParseStatus.STOCK
        assert target.exchange == "US"
        # ``us`` prefix is recognised, but US canonical IDs are the bare
        # ticker (fetchers don't accept ``usAAPL``) — the prefix only biases
        # the exchange detection; it doesn't enter the canonical ID.
        assert target.canonical_id == "AAPL"
        assert target.normalized_prefix == "us"
        assert target.normalized_code == "AAPL"

    @pytest.mark.parametrize(
        "ticker,expected_canonical_id",
        [
            # Phase 1 contract (issue #2063, maintainer clarification
            # 2026-08-01): the ``us`` exchange prefix is case-insensitive
            # on the prefix itself, but the ticker base must arrive in the
            # canonical uppercase US symbol shape (regex
            # ``^[A-Z]{1,5}(\.[A-Z]{1,2})?$``). ``us``-prefixed tokens
            # whose base does NOT match that shape are surfaced as
            # ``unsupported`` so callers can prompt the user to retype in
            # mixed/upper case. This uniformly rejects:
            #   - bare-US collisions (``usfd``/``usm``, previously
            #     OR-COR-9c3d2c44)
            #   - explicit-prefix collisions (``usibm``/``usamd``/``usge``
            #     /``usbk``/``usaapl``/``usshop``, previously OR-COR-2f0d1a7e)
            #   - mixed-case prefix with lowercase base (``Usfd``/``USibm``/
            #     ``Usaapl``/``uSfd``/``USaapl``, previously OR-COR-7b45f5c1)
            #   - lowercase/non-alphabetic base bypassing the earlier
            #     ``raw.isalpha()``-gated guard (``usbrk.b``/``usshop.us``/
            #     ``us1``, previously OR-COR-us-prefix-nonalpha-guard-gap)
            # under one consistent contract rule — no US ticker whitelist
            # or length-dependent heuristic needed. ``canonical_id`` carries
            # the raw token verbatim so the caller can echo it back to the
            # user as the offending input; ``normalized_prefix`` is None
            # because the input was NOT accepted as an explicit prefix form.
            ("usfd", "usfd"),
            ("usm", "usm"),
            ("usibm", "usibm"),
            ("usamd", "usamd"),
            ("usge", "usge"),
            ("usbk", "usbk"),
            ("usaapl", "usaapl"),
            ("usshop", "usshop"),
            # Mixed-case prefix + lowercase base (OR-COR-7b45f5c1): the
            # prefix alone being uppercase (or partially uppercase) is not
            # sufficient — the base must be all uppercase for the explicit
            # ``us``-prefix contract to apply.
            ("Usfd", "Usfd"),
            ("USibm", "USibm"),
            ("Usaapl", "Usaapl"),
            ("uSfd", "uSfd"),
            ("USaapl", "USaapl"),
            # Lowercase base with punctuation/digits (OR-COR-us-prefix-
            # nonalpha-guard-gap): the earlier ``raw.isalpha()``-gated
            # guard let ``usbrk.b`` / ``usshop.us`` / ``us1`` slip through
            # to the normalizer, which silently rewrote them to ``BRK.B``
            # / ``SHOP.US`` / ``1``. The new regex-based guard catches
            # these regardless of character class — digit-only bases,
            # lowercase+dotted bases, lowercase+digit bases alike.
            ("usbrk.b", "usbrk.b"),
            ("usshop.us", "usshop.us"),
            ("us1", "us1"),
            ("us1a", "us1a"),
            ("us12a", "us12a"),
            # All-uppercase but invalid US shape (digits in base): ``US1``
            # contains a digit so it doesn't match ``^[A-Z]{1,5}(\.[A-Z]{1,2})?$``.
            # Previously ``_split_prefix`` would strip ``US`` and the
            # normalizer would accept ``1`` as the canonical_id — surfacing
            # an invalid US symbol to callers. The regex-based guard
            # rejects it up-front.
            ("US1", "US1"),
            ("US12345", "US12345"),
        ],
    )
    def test_lowercase_us_prefix_is_unsupported(
        self,
        ticker: str,
        expected_canonical_id: str,
    ) -> None:
        r"""Regression for PR #2129 review blockers OR-COR-9c3d2c44 (closed),
        OR-COR-2f0d1a7e (closed), OR-COR-7b45f5c1 (closed), and
        OR-COR-us-prefix-nonalpha-guard-gap: ``us``-prefixed tokens whose
        ticker base does NOT match the canonical US symbol shape regex
        ``^[A-Z]{1,5}(\.[A-Z]{1,2})?$`` — whether the prefix itself is
        lowercase, mixed-case, or uppercase, and whether the base
        contains lowercase letters, digits, or punctuation — are neither
        bare US tickers nor explicit-prefix stock symbols under the Phase
        1 contract from issue #2063 (maintainer clarification 2026-08-01).
        They are surfaced as ``unsupported`` so callers can prompt the
        user to retype the ticker base in canonical uppercase form
        (``usAAPL``/``usBRK.B``/``USFD``). The contract closes four
        prior blockers under one uniform rule — no US ticker whitelist
        required:
            * OR-COR-9c3d2c44: ``usfd``/``usm`` silent bare-rewrite bloom
            * OR-COR-2f0d1a7e: ``usibm``/``usge``/``usbk``/``usaapl``
              length-dependent explicit-prefix split bifurcation
            * OR-COR-7b45f5c1: ``Usfd``/``USibm``/``Usaapl`` mixed-case
              prefix with lowercase base bypassing the lowercase-only guard
            * OR-COR-us-prefix-nonalpha-guard-gap: ``usbrk.b``/``usshop.us``/
              ``us1`` lowercase base with punctuation/digits bypassing the
              earlier ``raw.isalpha()``-gated guard
        """
        target = parse_analysis_target(ticker)
        assert target.asset_type == ParseStatus.UNSUPPORTED
        assert target.exchange == "US"
        assert target.canonical_id == expected_canonical_id
        assert target.normalized_prefix is None
        assert target.unsupported_reason is not None
        assert "uppercase" in target.unsupported_reason


# ---------------------------------------------------------------------------
# Edge cases — empty input + unsupported shapes.
# ---------------------------------------------------------------------------
class TestEdgeCases:
    def test_empty_string_is_unsupported(self) -> None:
        target = parse_analysis_target("")
        assert target.asset_type == ParseStatus.UNSUPPORTED
        assert target.canonical_id == ""
        assert target.unsupported_reason == "empty input"

    def test_whitespace_only_is_unsupported(self) -> None:
        target = parse_analysis_target("   ")
        assert target.asset_type == ParseStatus.UNSUPPORTED
        assert target.unsupported_reason == "empty input"

    def test_three_digit_bare_code_is_unsupported(self) -> None:
        """Three-digit bare codes don't map to any known market shape — the
        parser surfaces ``unsupported`` with a reason rather than guessing.
        """
        target = parse_analysis_target("007")
        assert target.asset_type == ParseStatus.UNSUPPORTED
        assert target.unsupported_reason == "unrecognized code shape"

    def test_seven_digit_bare_code_is_unsupported(self) -> None:
        target = parse_analysis_target("1234567")
        assert target.asset_type == ParseStatus.UNSUPPORTED
        assert target.unsupported_reason == "unrecognized code shape"

    @pytest.mark.parametrize(
        "text",
        ["沪深300", "腾讯", "hello world", "Apple Inc.", "APPLE!", "$AAPL", "AAPL123456", "MICROSOFT", "ＡＡＰＬ"],
    )
    def test_text_that_is_not_a_symbol_is_not_guessed_as_us(self, text: str) -> None:
        target = parse_analysis_target(text)
        assert target.asset_type == ParseStatus.UNSUPPORTED
        assert target.unsupported_reason.startswith(f"unrecognized symbol {text!r}")

    @pytest.mark.parametrize(
        "text, canonical",
        [
            ("aapl", "AAPL"),
            ("SPX", "SPX"),
            ("brk.b", "BRK.B"),
            ("brk-b", "BRK-B"),
            ("^gspc", "^GSPC"),
            ("AAICPRC", "AAICPRC"),  # 7-letter preferred share code from the bundled index
            ("AEONWS", "AEONWS"),  # warrant code from the bundled index
        ],
    )
    def test_us_symbol_shapes_still_fall_back_to_us(self, text: str, canonical: str) -> None:
        target = parse_analysis_target(text)
        assert target.asset_type == ParseStatus.STOCK
        assert target.exchange == "US"
        assert target.canonical_id == canonical


# ---------------------------------------------------------------------------
# Default registry — public API surface.
# ---------------------------------------------------------------------------
class TestDefaultIndexRegistry:

    def test_default_registry_is_empty(self) -> None:
        # No supported market ships index rows, so nothing is loaded.
        assert len(default_index_registry()) == 0

    def test_default_registry_find_by_prefixed_code_rejects_non_sh_sz(self) -> None:
        registry = default_index_registry()
        # Even if a code looks like a known index, hk/us/bj prefixes don't
        # elevate to index status — they degrade to stock (contract #3).
        assert registry.find_by_prefixed_code("hk", "000300") is None
        assert registry.find_by_prefixed_code("us", "000300") is None

    def test_ambiguous_display_name_is_reported(self) -> None:
        """PR2: two entries with NFKC/casefold-equivalent display names make
        the name lookup ambiguous — no guessing, no single winner."""
        registry = IndexRegistry((
            IndexEntry(
                bare_code="000300",
                exchange="SH",
                canonical_id="sh000300",
                display_name="沪深300",
            ),
            IndexEntry(
                bare_code="000999",
                exchange="SH",
                canonical_id="sh000999",
                display_name="沪深300",
            ),
        ))
        assert registry.is_ambiguous_display_name("沪深300") is True
        assert registry.find_by_display_name("沪深300") is None
        # Explicit identity still resolves deterministically.
        assert registry.find_by_explicit_key("sh000300") is not None
        assert registry.find_by_explicit_key("sh000999") is not None

    def test_custom_registry_rejects_text_identity_alias(self) -> None:
        with pytest.raises(ValueError, match="explicit code form"):
            IndexRegistry((
                IndexEntry(
                    bare_code="000300",
                    exchange="SH",
                    canonical_id="sh000300",
                    display_name="沪深300",
                    aliases=("CSI300",),
                ),
            ))

    def test_code_shaped_display_names_stay_distinct_under_exact_name_lookup(
        self,
    ) -> None:
        """PR2 review fix: display-name equality is exactly NFKC + trim +
        casefold. Code-shaped names (``000016.SH`` vs ``sh000016``) that
        identity normalization would falsely collapse (``_normalize_index_key``
        treats them as the same resolver key ``sh000016``) must stay distinct
        for the name lookup, so each exact query resolves its own entry and
        neither is reported ambiguous."""
        registry = IndexRegistry((
            IndexEntry(
                bare_code="000016",
                exchange="SH",
                canonical_id="sh000016",
                display_name="000016.SH",
            ),
            IndexEntry(
                bare_code="000999",
                exchange="SH",
                canonical_id="sh000999",
                display_name="sh000016",
            ),
        ))
        # Identity normalization collapses both names to ``sh000016``, but the
        # name lookup must NOT reuse it — each display name resolves exactly.
        entry = registry.find_by_display_name("000016.SH")
        assert entry is not None
        assert entry.display_name == "000016.SH"
        entry = registry.find_by_display_name("sh000016")
        assert entry is not None
        assert entry.display_name == "sh000016"
        assert registry.is_ambiguous_display_name("000016.SH") is False
        assert registry.is_ambiguous_display_name("sh000016") is False


# ---------------------------------------------------------------------------
# Regression — exact maintainer spec samples from issue #2063.
# ---------------------------------------------------------------------------
class TestMaintainerSpecSamples:
    """Six samples the upstream maintainer called out as minimum coverage."""


# ---------------------------------------------------------------------------
# Dataclass serialization sanity — keeps the contract JSON-friendly.
# ---------------------------------------------------------------------------
def test_analysis_target_is_immutable_and_hashable() -> None:
    target = parse_analysis_target("sh000300")
    with pytest.raises(Exception):

        target.asset_type = "mutated"  # type: ignore[misc]
    hash(target)  # should not raise


# ---------------------------------------------------------------------------
# Review-blocker regressions — covers the three correctness blockers raised
# by maintainer on PR #2094 (issue #2063 phase 1):
#   OR-COR-d24a4e9a: 1-5 letter US tickers colliding with sh/sz/bj/hk/us
#                    prefixes were mis-split (SHOP -> shOP, HKD -> hkD, ...)
#   OR-COR-1b643ee6: bare A-share ETF codes (510300 etc.) were canonicalised
#                    to ``cn510300`` which no upstream fetcher accepts.
#   OR-COR-403bd018: passing ``IndexRegistry([])`` was silently replaced by
#                    the default registry, hiding the empty-white-list config.
# These tests pin the fixes so the same regressions can't land unnoticed.
# ---------------------------------------------------------------------------
class TestReviewBlockerRegressions:
    """Maintainer-specified regression inputs (issue #2063 phase 1 review)."""

    # ---- OR-COR-d24a4e9a: US ticker prefix collisions ---------------------

    @pytest.mark.parametrize(
        "ticker",
        ["SHOP", "HKD", "BJRI", "USM", "SHAK", "USFD", "BJDX", "SZKMY",
         "AAPL", "TSLA", "BRK", "A", "Z"],
    )
    def test_us_ticker_prefix_collision_is_not_split(self, ticker: str) -> None:
        """1-5 letter US tickers must round-trip as US stock, not be split
        into ``(sh, OP)`` / ``(hk, D)`` / ... by the prefix scanner.
        """
        target = parse_analysis_target(ticker)
        assert target.asset_type == ParseStatus.STOCK
        assert target.exchange == "US"
        assert target.canonical_id == ticker
        assert target.display_code == ticker
        assert target.normalized_prefix is None
        assert target.normalized_code == ticker
        assert target.matched_index is None

    # ---- OR-COR-bare-us-suffix-prefix-collision ----------------------------

    @pytest.mark.parametrize(
        "ticker",
        # Bare ``.US`` suffix US tickers (round-4 blocker
        # OR-COR-bare-us-suffix-prefix-collision): a token like ``SHOP.US`` /
        # ``HKD.US`` / ``BJRI.US`` / ``USFD.US`` has the same canonical US
        # symbol shape ``^[A-Z]{1,5}\.[A-Z]{1,2}$`` as ``BRK.B`` / ``AAPL.US``.
        # Previously ``_split_prefix`` only short-circuited bare uppercase
        # letters (``USFD``-form), so dotted ``.US`` codes whose first 2
        # letters happened to collide with a known exchange prefix
        # (``sh``/``hk``/``bj``/``us``) were mis-split into
        # ``(sh, OP.US)`` / ``(hk, D.US)`` / ``(bj, RI.US)`` / ``(us, FD.US)``,
        # producing wrong market and non-canonical stock id.
        ["SHOP.US", "HKD.US", "BJRI.US", "USFD.US", "AAPL.US", "BRK.B"],
    )
    def test_bare_dotted_us_suffix_collision_is_not_split(self, ticker: str) -> None:
        r"""Bare ``.US`` / ``.B`` dotted US tickers whose first 1-2 letters
        collide with a known exchange prefix (``sh`` / ``hk`` / ``bj`` /
        ``us``) must round-trip as US stock, not be split by the prefix
        scanner into ``(sh, OP.US)`` / ``(hk, D.US)`` / ``(us, FD.US)`` etc.

        Regression for PR #2129 round-4 review blocker
        ``OR-COR-bare-us-suffix-prefix-collision``.

        Both bare form (``USFD``) and dotted form (``SHOP.US`` / ``BRK.B``)
        share the canonical ``_US_TICKER_SHAPE_RE`` regex
        ``^[A-Z]{1,5}(\.[A-Z]{1,2})?$``, so ``_split_prefix`` now applies
        the same short-circuit to both families.
        """
        target = parse_analysis_target(ticker)
        assert target.asset_type == ParseStatus.STOCK
        assert target.exchange == "US"
        assert target.canonical_id == ticker
        assert target.display_code == ticker
        assert target.normalized_prefix is None
        assert target.normalized_code == ticker
        assert target.matched_index is None

    # ---- OR-COR-0e285b84: us-prefixed dotted uppercase US base accepted-path
    # regression (PR #2129 round-5 review) -----------------------------

    @pytest.mark.parametrize(
        "ticker,expected_canonical,expected_prefix,expected_bare",
        [
            # mixed-case us-prefix + bare US base: usAAPL / usBRK — the
            # explicit ``us`` prefix is recorded in ``normalized_prefix``
            # and the bare US ticker form is the canonical id.
            ("usAAPL", "AAPL", "us", "AAPL"),
            ("usBRK", "BRK", "us", "BRK"),
            # mixed-case us-prefix + dotted uppercase US base (the new
            # contract): usBRK.B and usABC.US must preserve the explicit
            # ``us`` prefix and pass the bare US short-circuit in
            # ``_split_prefix`` intact — they are valid US-ticker shapes
            # that carry the user's intent of a ``us`` prefix.
            ("usBRK.B", "BRK.B", "us", "BRK.B"),
            ("usABC.US", "ABC.US", "us", "ABC.US"),
        ],
    )
    def test_us_prefixed_dotted_uppercase_us_base_preserves_prefix(
        self, ticker: str, expected_canonical: str, expected_prefix: str, expected_bare: str
    ) -> None:
        """Explicit ``us`` prefix paired with a dotted uppercase US base
        must not be silently rewritten to a bare ticker shape.

        Regression for PR #2129 round-5 review blocker
        ``OR-COR-0e285b84``: previously ``usBRK.B`` / ``usABC.US`` were
        uppercased to ``USBRK.B`` / ``USABC.US`` and then short-circuited
        by ``_split_prefix`` as bare US tickers, swallowing the user's
        explicit ``us`` prefix and producing a different canonical id
        (e.g. canonical ``USBRK.B`` instead of bare ``BRK.B`` with
        ``normalized_prefix='us'``).

        The fix extends the ``us``-prefix recovery gate at
        ``stock_list_parser.py:~825`` to match the same
        ``_US_TICKER_SHAPE_RE`` shape the upfront guard at
        ``~566-585`` already accepts, while keeping the bare all-uppercase
        short-circuit exclusion (``bare USFD.US`` / ``BRK.B``) intact.
        """
        target = parse_analysis_target(ticker)
        assert target.asset_type == ParseStatus.STOCK
        assert target.exchange == "US"
        assert target.canonical_id == expected_canonical
        assert target.normalized_prefix == expected_prefix
        assert target.normalized_code == expected_bare

    # ---- OR-COR-1b643ee6: bare A-share ETF routing ------------------------

    # ---- OR-COR-403bd018: explicit empty IndexRegistry -------------------


# ---------------------------------------------------------------------------
# Explicit-exchange-suffix review-blocker regressions (issue #2063 phase 1
# review): when a user types ``600519.BJ`` / ``00700.HK`` / ``abc.SH`` /
# ``1234567.SH`` they must see ``unsupported`` rather than be silently
# rewritten to a ``sh600519.bj`` / ``hk00700`` / ``sh1234567`` / ``shabc``
# token that no fetcher accepts.
# ---------------------------------------------------------------------------
class TestExplicitExchangeSuffixRejections:
    """Maintainer-specified explicit-suffix rejection inputs."""

    # ---- OR-COR-4b91e5a0: ``sz399001.SZ`` / ``sz399006.SZ`` mixed
    #      prefix+suffix forms must resolve through the same index-alias
    #      rebuild path as ``sh000300.SH``. The default registry already
    #      lists both as SZ indices, so the parser must rebuild them into
    #      ``sz399001`` / ``sz399006`` instead of rejecting with
    #      "explicit exchange suffix 'SZ' rejects base 'SZ399001'".

    # ---- OR-COR-d83a3580: malformed explicit-suffix with embedded hex-like
    #      digits must NOT be silently rebuilt into a valid index alias.
    @pytest.mark.parametrize(
        "code,expected_exchange",
        [
            ("sh0x00300.SH", "SH"),       # hex-like garbage before digits
            ("SZ0x000300.SZ", "SZ"),      # leading 0x-style hex in base
            ("HK0x000700.HK", "HK"),      # hex-like garbage in HK context
        ],
    )
    def test_malformed_explicit_suffix_with_embedded_hex_is_unsupported(
        self, code: str, expected_exchange: str
    ) -> None:
        target = parse_analysis_target(code)
        assert target.asset_type == ParseStatus.UNSUPPORTED
        assert target.exchange == expected_exchange
        assert target.canonical_id == code
        assert target.unsupported_reason is not None
        assert expected_exchange in target.unsupported_reason

    # ---- OR-COR-b3e32200 / OR-COR-6f4d6b12: dotted-prefix form
    #      (``SH.000999`` / ``BJ.600519`` / ``HK.600519`` / ``SS.000999``)
    #      with a base the normalizer rejected must reject as ``unsupported``
    #      rather than degrade to a malformed canonical stock (``sh.000999``)
    #      or — worse — silently flip to US (``SS.000999`` → exchange='US').
    #      Contract #3 (``sh + unknown → degrade to stock``) only applies when
    #      the bare base is a passable code shape; an explicit dotted-prefix
    #      reject is a typo, not a stock.
    #
    #      NOTE: ``SZ.000001`` is intentionally NOT included here — ``SZ`` is
    #      in the alias-rebuild whitelist, so the dotted-prefix form is
    #      equivalent to the strict-suffix form ``000001.SZ`` (alias for SZ
    #      stock 000001) and must resolve to a real STOCK, not reject.

    # Removed Japan/Korea/Taiwan suffix forms must reject explicitly — not silently
    # flip to a US or mainland stock.
    @pytest.mark.parametrize(
        "code,expected_exchange",
        [
            ("7203.T", "T"),
            ("005930.KS", "KS"),
            ("2330.TW", "TW"),
            ("6505.TWO", "TWO"),
            ("035720.KQ", "KQ"),
        ],
    )
    def test_foreign_exchange_suffix_with_invalid_base_is_unsupported(
        self, code: str, expected_exchange: str
    ) -> None:
        target = parse_analysis_target(code)
        assert target.asset_type == ParseStatus.UNSUPPORTED
        assert target.exchange == expected_exchange
        assert target.canonical_id == code
        assert target.unsupported_reason is not None
        assert expected_exchange in target.unsupported_reason


# ---------------------------------------------------------------------------
# Index registry & CSI provider symbol governance.
# ---------------------------------------------------------------------------
class TestIndexAliasMatrix:
    """Canonical/display/alias converge; CSI explicit; bare stays stock."""

    def test_us_ticker_starting_with_csi_remains_stock(self) -> None:
        target = parse_analysis_target("CSIQ")
        assert target.asset_type == ParseStatus.STOCK
        assert target.canonical_id == "CSIQ"

    def test_old_text_aliases_do_not_resolve_to_index(self) -> None:
        # CSI300 / HS300 / SSE50 / STAR50 are not in the manifest aliases.
        for code in ("CSI300", "HS300", "SSE50", "STAR50", "SZSE", "ChiNext"):
            target = parse_analysis_target(code)
            assert target.asset_type != ParseStatus.INDEX

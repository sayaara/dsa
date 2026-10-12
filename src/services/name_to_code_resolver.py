# -*- coding: utf-8 -*-
"""
===================================
Name-to-code resolution engine
===================================

Resolves stock names to codes: exact matching against the global ``stockDB``, plus
hybrid matching (substring / pinyin / fuzzy).
"""

from __future__ import annotations

import difflib
import logging
import re
import threading
import unicodedata
from dataclasses import dataclass
from typing import Dict, List, Optional, Set, Tuple

from src.data.stock_mapping import STOCK_NAME_MAP
from src.services.english_stock_names import (
    english_name_for_ticker_shaped_word,
    find_interlisted_listings,
    resolve_english_stock_name,
)
from src.services.stock_code_utils import is_code_like, normalize_code

logger = logging.getLogger(__name__)

# stockDB read/write lock: intent resolution runs concurrently in asyncio.to_thread workers, so
# in-place merges and read paths iterating stockDB would otherwise raise
# "dictionary changed size during iteration". An RLock allows nested acquisition.
_db_lock = threading.RLock()


def _contains_cjk(text: str) -> bool:
    """Return True when the text contains CJK characters."""
    return any("\u3400" <= ch <= "\u9fff" for ch in text)


def _normalize_stock_name(name: str) -> str:
    """Unified normalization of stock names: NFKC width normalization (full-width letters and
    digits to half-width) plus removal of all whitespace.

    The tokenizer pipeline applies the same NFKC to user input (the working copy in
    web_intent_tokenizer._preprocess_text). If database names kept their source spelling (a source's
    full-width A in "京东方Ａ", the embedded spaces in "五 粮 液"), windows and fragments could never
    equal the normalized input: full-name exact matching would miss, and a shorter database name
    would mis-segment the wrong entity (after "京东方Ａ" misses, a two-character window hits "京东").
    Input side and database side must share the same transform: all three ingestion points - the
    initial local mapping, merging, and disk cache loading - share this
    function with every query path (historical un-normalized disk-cache data is normalized here too). Display names follow the normalized spelling, consistent with the token layer's single-code-identity principle.
    """
    return "".join(unicodedata.normalize("NFKC", name).split())


def _is_code_like(s: str) -> bool:
    """Backward-compatible wrapper around the shared code-like check."""
    return is_code_like(s)


def _normalize_code(raw: str) -> Optional[str]:
    """Backward-compatible wrapper around the shared code normalization."""
    return normalize_code(raw)


def _build_reverse_map_no_duplicates(
    code_to_name: Dict[str, str],
) -> Dict[str, str]:
    """
    Build the name -> code mapping. A name mapping to multiple codes is ambiguous and is excluded.
    """
    name_to_codes: Dict[str, Set[str]] = {}
    for code, name in code_to_name.items():
        if not name or not code:
            continue
        name = name.strip()
        if name not in name_to_codes:
            name_to_codes[name] = set()
        name_to_codes[name].add(code)
    # Only include names with exactly one code
    return {name: next(iter(codes)) for name, codes in name_to_codes.items() if len(codes) == 1}


def _build_local_name_indexes(code_to_name: Dict[str, str]) -> Tuple[Dict[str, str], Set[str]]:
    """
    Build cached local lookup structures:
    - unique name -> code
    - ambiguous names that should fail fast
    """
    name_to_codes: Dict[str, Set[str]] = {}
    for code, name in code_to_name.items():
        if not name or not code:
            continue
        normalized_name = _normalize_stock_name(name)
        if not normalized_name:
            continue
        name_to_codes.setdefault(normalized_name, set()).add(code)

    unique_names = {
        name: next(iter(codes))
        for name, codes in name_to_codes.items()
        if len(codes) == 1
    }
    ambiguous_names = {
        name
        for name, codes in name_to_codes.items()
        if len(codes) > 1
    }
    return unique_names, ambiguous_names


_LOCAL_REVERSE_MAP, _LOCAL_AMBIGUOUS_NAMES = _build_local_name_indexes(STOCK_NAME_MAP)


# =========================================================================
# Stock — immutable code/name/market value object
# =========================================================================


@dataclass(frozen=True)
class Stock:
    """A stock entry: code / name / market ("a" | "hk" | "us")."""

    code: str
    name: str = ""
    market: str = ""


# =========================================================================
# stockDB - the global code->name database, built from the local name map
# =========================================================================


stockDB: Dict[str, str] = {
    # Normalize the initial values too (the same NFKC transform as the input side), so full-width
    # spellings and embedded whitespace from the source never enter the in-database view
    code: _normalize_stock_name(name) for code, name in STOCK_NAME_MAP.items()
}

# When a merge updates an existing code to its current official name, the old name is kept as an
# alias, so a renamed security does not become completely unresolvable by its old name.
stockAliases: Dict[str, Set[str]] = {}

_MARKET_ORDER: Dict[str, int] = {"a": 0, "hk": 1, "us": 2}

# =========================================================================
# Name and pinyin caches, keyed by (database object, len): any insertion into or deletion from the
# database invalidates them automatically, with no manual reset required.
# =========================================================================


_names_cache: List = [None, None, None]  # [database, len(database), names]
_pinyin_cache: List = [None, None]  # [names, pinyins]


def _database_names(database: Dict[str, str]) -> List[str]:
    """A de-duplicated, order-preserving list of names in *database* (cached).

    Alongside the canonical names it also includes stockDB's old-name aliases, so old names can
    take part in exact, substring, pinyin and fuzzy matching as well.
    """
    with _db_lock:
        if _names_cache[0] is database and _names_cache[1] == len(database):
            return _names_cache[2]
        names = list(dict.fromkeys(database.values()))
        if database is stockDB:
            for aliases in stockAliases.values():
                for alias in aliases:
                    if alias not in names:
                        names.append(alias)
        _names_cache[:] = [database, len(database), names]
        return names


def _database_pinyins(
    database: Dict[str, str], names: Optional[List[str]] = None
) -> List[str]:
    """A lowercase full-pinyin list aligned with *names* (cached).

    When an outer snapshot is passed in it is built from that snapshot, guaranteeing the same source
    and ordering as the caller's local names, so fetching the list twice during a concurrent merge cannot misalign the zip pairing.
    """
    if names is None:
        names = _database_names(database)
    with _db_lock:
        if _pinyin_cache[0] is not names:
            try:
                from pypinyin import lazy_pinyin

                pinyins = ["".join(lazy_pinyin(name)).lower() for name in names]
            except Exception:
                pinyins = [""] * len(names)
            _pinyin_cache[:] = [names, pinyins]
        return _pinyin_cache[1]


# =========================================================================
# Name matching helpers
# =========================================================================


def _exact_names(fragment: str, database: Dict[str, str]) -> List[str]:
    """Return the database names that match *fragment* exactly, ignoring case."""
    fragment_lower = fragment.lower()
    return [name for name in _database_names(database) if name.lower() == fragment_lower]


def _is_single_char_typo(input_name: str, candidate_name: str) -> bool:
    """Return True when two names differ in exactly one character position."""
    if not input_name or not candidate_name:
        return False
    if len(input_name) != len(candidate_name):
        return False
    # Keep typo fallback conservative: only for names with enough signal.
    if len(input_name) < 3:
        return False
    diff = sum(1 for a, b in zip(input_name, candidate_name) if a != b)
    return diff == 1


# Minimum length for pinyin substring matching: pinyin letters are high-frequency per-syllable
# particles, so very short fragments (o/k/ai/ma) match the pinyin of many unrelated names and would resolve ordinary English input into stocks.
_MIN_PINYIN_FRAGMENT_LEN = 5


def _fix_name(fragment: str, database: Dict[str, str]) -> List[str]:
    """Resolve a name fragment into a full stock name through hybrid matching.

    Strategy chain, in order:
    1. Exact match (case-insensitive)
    2. Substring match (case-insensitive; the fragment holds >= 2 CJK characters, e.g. 茅台 -> 贵州茅台)
    3. Pinyin substring match (e.g. "maotai" is contained in "guizhoumaotai")
    4. difflib fuzzy match (cutoff 0.8, plus a conservative 0.7 single-character typo fallback,
       e.g. 贵州茅苔 -> 贵州茅台)
    """
    if not fragment:
        return []
    fragment_lower = fragment.lower()
    names = _database_names(database)

    # 1. Exact match
    exact = [name for name in names if name.lower() == fragment_lower]
    if exact:
        return exact

    # 2. Substring match
    if sum(1 for ch in fragment if "\u3400" <= ch <= "\u9fff") >= 2:
        matches = [name for name in names if fragment_lower in name.lower()]
        if matches:
            return matches

    # 3. Pinyin substring match - only applies to pure-ASCII fragments
    # (the intended case is romanized input: "maotai" inside "guizhoumaotai"). Converting a CJK
    # fragment to pinyin loses granularity: a content word plus a particle ("阿里的" -> "alide") is
    # exactly 5 letters, passes the minimum-length gate, and collides as a substring with an
    # unrelated full name ("alide" inside "zhongdalide", 中大力德). Legitimate CJK cases are already covered by the other three layers (exact, substring, difflib).
    if _contains_cjk(fragment):
        fragment_pinyin = ""
    else:
        try:
            from pypinyin import lazy_pinyin

            fragment_pinyin = "".join(lazy_pinyin(fragment)).lower()
        except Exception:
            fragment_pinyin = ""
    if len(fragment_pinyin) >= _MIN_PINYIN_FRAGMENT_LEN:
        matches = [
            name
            for name, pinyin in zip(names, _database_pinyins(database, names))
            if fragment_pinyin in pinyin
        ]
        if matches:
            return matches

    # 4. Fuzzy match
    if len(fragment) > 2:
        matches = difflib.get_close_matches(fragment, names, n=5, cutoff=0.8)
        if matches:
            return matches
        typo_matches = difflib.get_close_matches(fragment, names, n=5, cutoff=0.7)
        matches = [m for m in typo_matches if _is_single_char_typo(fragment, m)]
        if matches:
            return matches

    return []


def _infer_code_market(code: str) -> Optional[str]:
    """Infer the market from the code format: 6 digits -> "a", 5 digits -> "hk", letters -> "us"."""
    c = code.strip()
    if c.isdigit():
        return {5: "hk", 6: "a"}.get(len(c))
    return "us" if re.fullmatch(r"[A-Z]{1,5}(\.[A-Z])?", c) else None


def _find_codes_for_name(name: str, database: Dict[str, str]) -> List[Tuple[str, str]]:
    """Find every (code, market) pair in *database* that maps to *name*."""
    results: List[Tuple[str, str]] = []
    # Iterate under the lock: serializes against concurrent in-place merges
    with _db_lock:
        for code, mapped_name in database.items():
            if mapped_name == name or (
                database is stockDB and name in stockAliases.get(code, set())
            ):
                market = _infer_code_market(code)
                if market:
                    results.append((code, market))
    return results


# =========================================================================
# Public API
# =========================================================================


def resolver_name_to_code_list(name: str) -> List[Stock]:
    """Resolve a stock name into matching ``Stock`` entries (at most 5). Stock codes are not resolved here.

    1. Exact-match against ``stockDB``.
    2. Hybrid-match against the database (exact / substring / pinyin / fuzzy).

    Results are ordered A-shares -> HK -> US.

    Examples:
        "阿里巴巴" → [Stock("09988", "阿里巴巴", "hk"), Stock("BABA", "阿里巴巴", "us")]
        "茅台"     → [Stock("600519", "贵州茅台", "a")]
        "你好世界"  → []
    """
    if not name or not isinstance(name, str):
        return []
    # Query input is normalized the same way as ingestion, so source forms (full-width spelling or
    # embedded spaces, such as "京东方Ａ"/"五 粮 液" copied from a data source) resolve just like normal spelling
    s = _normalize_stock_name(name)
    # A single character cannot be a stock name (the shortest is 2), so short-circuit to avoid a full name-table scan
    if len(s) < 2:
        return []

    full_names = _exact_names(s, stockDB)
    if not full_names:
        full_names = _fix_name(s, stockDB)
    if not full_names:
        return []

    stocks: List[Stock] = []
    seen: Set[str] = set()
    for full_name in full_names:
        for code, market in _find_codes_for_name(full_name, stockDB):
            if code not in seen:
                seen.add(code)
                stocks.append(Stock(code=code, name=stockDB.get(code, full_name), market=market))

    stocks.sort(key=lambda r: _MARKET_ORDER.get(r.market, 99))
    return stocks[:5]


def US_stock_code_match(segment: str) -> List[Stock]:
    """Match US stock codes: a 1-5 letter ticker, returned only when the code exists in the local database.

    This avoids mistaking ordinary English words (hello/open/...) for stock codes.
    """
    if not isinstance(segment, str) or not segment.isascii() or not segment.isalpha():
        return []
    if not 1 <= len(segment) <= 5:
        return []
    upper = segment.upper()
    name = stockDB.get(upper, "")
    return [Stock(code=upper, name=name, market="us")] if name else []


def lookup_stock_by_code(code: str) -> Optional[Stock]:
    """Look the normalized code up in the database and return the full (code/name/market) triple, or None when absent.

    A valid format does not imply existence: a stockDB miss returns None and nothing is ever invented
    (LLM hallucinations and stale codes must not be injected into stocks). HK keys in the local
    database are bare 5-digit ("00700"), so the HK-prefixed form ("HK00700") also retries the de-prefixed bare key.
    """
    c = (code or "").strip().upper()
    if not c:
        return None
    with _db_lock:
        name = stockDB.get(c)
        if not name and c.startswith("HK"):
            name = stockDB.get(c[2:])
        if not name:
            return None
    if c.startswith("HK"):
        market = "hk"
    else:
        market = _infer_code_market(c) or ""
    return Stock(code=c, name=name, market=market)


def is_market_db_complete(market: str) -> bool:
    """Whether this market's name database has been enriched to full coverage (so a miss proves the code does not exist).

    Every market uses a curated local database that is never treated as complete, so a miss stays
    uncertain and is left for downstream to judge.
    """
    return False


def is_known_stock_name(name: str) -> bool:
    """Decide whether *name* is a full stock name known to stockDB (including rename aliases).

    This is a local name-table membership check only. A code key (such as "600519") does not count as a name hit: the tokenizer pipeline
    (web_intent_tokenizer) uses this function to protect already-recognized name tokens, and
    code-shaped text must continue into the code-extraction step to be re-labelled rather than skipped as a name.
    """
    if not isinstance(name, str):
        return False
    s = _normalize_stock_name(name)
    if not s:
        return False
    return s in _database_names(stockDB)


def resolve_name_to_code(name: str) -> Optional[str]:
    """
    Resolve stock name to code.

    Strategy (in order):
    0. A name of an interlisted company returns None (see ``find_interlisted_listings``).
    1. If input looks like a code (5-6 digits or 1-5 letters), return it normalized.
    2. Local STOCK_NAME_MAP reverse (exclude ambiguous names).
    3. Pinyin match against local names.
    4. English company name (src/services/english_stock_names.py).
    5. Fuzzy match (difflib, CJK input only).
    6. Return None.

    Args:
        name: Stock name or code string.

    Returns:
        Resolved stock code, or None if ambiguous/failed.
    """
    if not name or not isinstance(name, str):
        return None
    s = _normalize_stock_name(name)
    if not s:
        return None

    # A name of an interlisted company (``Telus``: ``TU`` and ``T.TO``) never picks a listing
    # and is not read as a ticker either; callers ask for the symbol.
    if find_interlisted_listings(name) is not None:
        return None

    # 1. Input looks like code. A ticker-shaped word that is really a company name
    #    (``Apple`` -> AAPL, not the nonexistent ticker APPLE) resolves as a name first.
    if _is_code_like(s):
        return english_name_for_ticker_shaped_word(name) or _normalize_code(s)

    # 2. Local reverse map (no duplicates)
    local_reverse = _LOCAL_REVERSE_MAP
    if s in local_reverse:
        return local_reverse[s]
    if s in _LOCAL_AMBIGUOUS_NAMES:
        logger.debug(f"[NameResolver] Matched a known ambiguous name, returning None early: {s}")
        return None

    # 3. Pinyin match (exact)
    try:
        from pypinyin import lazy_pinyin

        input_pinyin = "".join(lazy_pinyin(s)).lower()
        for local_name, code in local_reverse.items():
            local_pinyin = "".join(lazy_pinyin(local_name)).lower()
            if input_pinyin == local_pinyin:
                return code
    except ImportError:
        pass
    except Exception as e:
        logger.debug(f"[NameResolver] Pinyin match failed: {e}")

    # 4. English company name (US/CA): curated names, then the stock index. Uses the original
    #    text, because the normalization above removes the spaces between words.
    english_code = resolve_english_stock_name(name)
    if english_code:
        return english_code

    # Skip the fuzzy fallback for non-CJK free text such as random Latin noise.
    if not _contains_cjk(s):
        logger.debug(f"[NameResolver] Skip CJK-only fallbacks for non-CJK input: {s}")
        return None

    all_name_to_code = dict(local_reverse)
    # Skip fuzzy matching for very short inputs (<=2 chars) to avoid false positives,
    # e.g. '中国' matching arbitrary company names in a pool of 5000+ stocks.
    # Use a higher cutoff (0.8) to reduce mis-hits on longer inputs as well.
    if len(s) > 2:
        names = list(all_name_to_code.keys())
        matches = difflib.get_close_matches(s, names, n=1, cutoff=0.8)
        if matches:
            logger.debug(f"[NameResolver] Fuzzy match: input={s}, matched={matches[0]}")
            return all_name_to_code[matches[0]]

        # Conservative fallback for one-character typo in medium/long names.
        # This keeps the strict default threshold while fixing obvious misspellings
        # such as "贵州茅苔" -> "贵州茅台".
        typo_matches = difflib.get_close_matches(s, names, n=1, cutoff=0.7)
        if typo_matches and _is_single_char_typo(s, typo_matches[0]):
            logger.debug(f"[NameResolver] Single-character typo fallback match: input={s}, matched={typo_matches[0]}")
            return all_name_to_code[typo_matches[0]]

    logger.debug(f"[NameResolver] Resolution failed: {s}")
    return None

# -*- coding: utf-8 -*-
"""
===================================
Name-to-code resolution engine
===================================

Resolves stock names to codes: exact matching against the global ``stockDB``, plus
AkShare enrichment and hybrid matching (substring / pinyin / fuzzy).
"""

from __future__ import annotations

import concurrent.futures
import difflib
import json
import logging
import os
import re
import threading
import time
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

from src.data.stock_mapping import STOCK_NAME_MAP
from src.services.stock_code_utils import is_code_like, normalize_code

logger = logging.getLogger(__name__)

# AkShare result cache: (timestamp, name_to_code dict). Once the TTL expires it keeps
# serving as stale data (stale-while-revalidate), with a background thread doing the refresh.
_akshare_cache: Optional[tuple[float, Dict[str, str]]] = None
_AKSHARE_CACHE_TTL = 1800  # 30 MIN

# Failure backoff: timestamp of the most recent failed fetch. Without a negative cache, every
# resolution would re-issue a network request during an outage, turning slow timeouts into user-visible latency on every message.
# When a stale cache exists it is still served inside the backoff window (staying available during
# a network failure); only a cold start with no cache at all falls back to the local database.
_akshare_failure_cache: Optional[float] = None
_AKSHARE_FAILURE_TTL = 300  # 5 MIN

# Fetch timeout: some akshare exchange requests have no timeout (the SSE GET and the BSE POST,
# for example), so a hang - as opposed to a failure - means the fetch thread never returns: the
# error path never fires and the failure backoff is never armed. With the fetch wrapped in a
# subprocess and capped in duration, a hung child is terminated/killed at the timeout and raises TimeoutError, taking the normal failure path and arming the backoff.
_AKSHARE_FETCH_TIMEOUT = 25.0

# Cold-start wait ceiling: the fetch is capped by the subprocess within _AKSHARE_FETCH_TIMEOUT,
# and the worker resolves the Future within a bounded number of cleanup steps after that. Deriving
# the wait bound from that same constant, rather than an independent magic number, structurally
# guarantees that any request overlapping an in-flight fetch receives its result. A previous
# independent constant of 8s sat in the same distribution as the measured 6.6-8.2s fetch time, so
# cold-start requests deterministically failed to resolve. The margin covers DataFrame parsing and cleanup; disk writes and logging happen after wake-up and do not count. TTL expiry uses stale-while-revalidate with zero wait, so this value only affects cold starts.
_AKSHARE_WAIT_COLD_START = _AKSHARE_FETCH_TIMEOUT + 5.0

# State lock: guarantees atomicity only for reads and writes of the cache, backoff and in-flight
# handle. The single IO exception under the lock is the first lazy load in
# _try_load_disk_cache_locked (once per process, a small local file, milliseconds). Network fetches
# and disk writes both happen outside the lock in the background refresh thread. It never nests with _db_lock, so there is no lock-ordering cycle.
_state_lock = threading.Lock()

# In-flight fetch handle: non-None means a background thread is already refreshing. Concurrent
# waiters wait on the Future's completion signal (both success and failure wake them precisely)
# rather than queuing for the lock and double-checking, so waiting is decoupled from fetch duration with no implicit constant-to-constant contract such as 25 < 30.
_akshare_inflight: Optional[concurrent.futures.Future] = None

# Disk cache: written atomically after a successful fetch and lazily loaded as stale data on
# restart. The stock name table changes very rarely, so reusing it across restarts narrows the
# cold-start wait to the case where even the disk has no data. The path follows the data/cache convention (that directory is gitignored).
_AKSHARE_DISK_CACHE_PATH = (
    Path(__file__).resolve().parents[2] / "data" / "cache" / "akshare_name_map.json"
)
_akshare_disk_checked = False

# stockDB read/write lock: intent resolution runs concurrently in asyncio.to_thread workers, so
# the in-place merge in extend_AkShare and read paths iterating stockDB would otherwise raise
# "dictionary changed size during iteration". An RLock allows nested acquisition.
_db_lock = threading.RLock()


def _contains_cjk(text: str) -> bool:
    """Return True when the text contains CJK characters."""
    return any("\u3400" <= ch <= "\u9fff" for ch in text)


def _normalize_stock_name(name: str) -> str:
    """Unified normalization of stock names: NFKC width normalization (full-width letters and
    digits to half-width) plus removal of all whitespace.

    The tokenizer pipeline applies the same NFKC to user input (the working copy in
    web_intent_tokenizer._preprocess_text). If database names kept their source spelling (AkShare's
    full-width A in "京东方Ａ", the embedded spaces in "五 粮 液"), windows and fragments could never
    equal the normalized input: full-name exact matching would miss, and a shorter database name
    would mis-segment the wrong entity (after "京东方Ａ" misses, a two-character window hits "京东").
    Input side and database side must share the same transform: all three ingestion points - the
    initial local mapping, AkShare construction and merging, and disk cache loading - share this
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


def _akshare_stock_info_worker():
    """Runs inside the subprocess: import akshare and fetch the full A-share code table.

    Must stay a module-level function (spawn passes it by qualified name through pickle); akshare
    and heavy dependencies such as pandas load only in the subprocess, never in the parent.
    """
    import akshare as ak

    return ak.stock_info_a_code_name()


def _fetch_akshare_df():
    """The single network egress for the full AkShare fetch (a test seam).

    Executed through the data_provider subprocess timeout wrapper (spawn): a hung network request
    is killed within _AKSHARE_FETCH_TIMEOUT and surfaces as TimeoutError in the parent.
    akshare's internal @lru_cache exists only in the subprocess, so a refresh after the 30-minute
    TTL always returns fresh data on the parent side.
    """
    from data_provider.akshare_fetcher import _akshare_call_with_timeout

    return _akshare_call_with_timeout(
        _akshare_stock_info_worker,
        timeout=_AKSHARE_FETCH_TIMEOUT,
        call_name="stock_info_a_code_name",
    )


def _build_name_map_from_df(df) -> Dict[str, str]:
    """Convert the AkShare code/name DataFrame into a disambiguated name->code mapping."""
    code_to_name = {}
    for _, row in df.iterrows():
        code = row.get("code")
        name = row.get("name")
        if code is None or name is None:
            continue
        code_str = str(code).strip()
        # Strip .SH/.SZ suffix
        if "." in code_str:
            base, suffix = code_str.rsplit(".", 1)
            if suffix.upper() in ("SH", "SZ", "SS") and base.isdigit():
                code_str = base
        code_to_name[code_str] = _normalize_stock_name(str(name))
    return _build_reverse_map_no_duplicates(code_to_name)


def _try_load_disk_cache_locked() -> None:
    """Lazily load the disk cache into memory (attempted at most once per process). The caller must hold _state_lock."""
    global _akshare_cache, _akshare_disk_checked
    if _akshare_disk_checked:
        return
    _akshare_disk_checked = True
    try:
        payload = json.loads(_AKSHARE_DISK_CACHE_PATH.read_text(encoding="utf-8"))
        ts = payload.get("ts")
        raw_map = payload.get("map")
        if isinstance(ts, (int, float)) and isinstance(raw_map, dict):
            # Historical disk writes may hold un-normalized names (full-width spelling, embedded spaces): normalize on load
            name_map = {
                _normalize_stock_name(str(k)): str(v)
                for k, v in raw_map.items()
                if k and v
            }
            if name_map:
                _akshare_cache = (float(ts), name_map)
                logger.info(
                    "[NameResolver] AkShare 磁盘缓存已加载: "
                    f"{len(name_map)} 条, age={time.time() - float(ts):.0f}s"
                )
    except FileNotFoundError:
        pass
    except Exception as e:
        logger.debug(f"[NameResolver] AkShare 磁盘缓存不可用，忽略: {e}")


def _persist_akshare_map(name_map: Dict[str, str]) -> None:
    """Atomic disk write (a per-process unique tmp name plus os.replace). Failure is non-fatal and only logged.

    The tmp name embeds the PID: web and CLI may be two processes, and sharing one tmp name would
    let them overwrite each other's partially written file before os.replace.
    """
    try:
        path = _AKSHARE_DISK_CACHE_PATH
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
        tmp.write_text(
            json.dumps({"ts": time.time(), "map": name_map}, ensure_ascii=False),
            encoding="utf-8",
        )
        os.replace(tmp, path)
    except Exception as e:
        logger.debug(f"[NameResolver] AkShare 磁盘缓存写入失败（非致命）: {e}")


def _spawn_refresh_locked() -> concurrent.futures.Future:
    """Start the background refresh thread and register the in-flight handle. The caller must hold _state_lock.

    The network fetch, DataFrame parsing and disk write all happen in this daemon thread; the
    request path only reads state or waits on the Future and never performs network IO.
    """
    global _akshare_inflight
    fut: concurrent.futures.Future = concurrent.futures.Future()
    # Register before starting: in theory the worker can finish before start() returns, and its
    # cleanup branch `is fut` must be able to see the registered handle
    _akshare_inflight = fut

    def _worker():
        global _akshare_cache, _akshare_failure_cache, _akshare_inflight
        result: Optional[Dict[str, str]] = None
        try:
            try:
                df = _fetch_akshare_df()
                if df is not None and not df.empty:
                    # Treat empty data as a failure for backoff purposes: retrying soon would only return the same empty result
                    result = _build_name_map_from_df(df)
            except Exception as e:
                logger.warning(f"[NameResolver] AkShare fallback failed: {e}")
        finally:
            # Clean up and wake every waiter first, then do best-effort side effects such as logging
            # and the disk write: a slow log handler or slow disk must not delay waiters from getting
            # the result (the disk write once preceded set_result, so on a slow disk the cache was ready
            # while waiters still timed out). The finally block is the catch-all: even if a BaseException
            # escapes, the handle, backoff and Future are cleaned up and no dead handle is left behind (otherwise every later cold-start request would wait out the full timeout for nothing).
            with _state_lock:
                now = time.time()
                if result:
                    _akshare_cache = (now, result)
                    _akshare_failure_cache = None
                else:
                    _akshare_failure_cache = now
                    result = None
                if _akshare_inflight is fut:
                    _akshare_inflight = None
            # Wake every waiter precisely on both success and failure; failure is expressed as result=None
            fut.set_result(result)
            if result:
                logger.info(
                    f"[NameResolver] AkShare cache loaded: {len(result)} name->code mappings"
                )
                _persist_akshare_map(result)

    try:
        threading.Thread(
            target=_worker, name="akshare-name-refresh", daemon=True
        ).start()
    except RuntimeError as e:
        # Thread start failed (for example the process ran out of threads): release the handle and wake the waiters
        _akshare_inflight = None
        fut.set_result(None)
        logger.warning(f"[NameResolver] AkShare 刷新线程启动失败: {e}")
    return fut


def _get_akshare_name_to_code() -> Optional[Dict[str, str]]:
    """Get the AkShare name->code mapping: a fresh cache is read directly; an expired one uses
    stale-while-revalidate (return the old value immediately and refresh in the background); a cold start waits on the in-flight Future for a bounded time; failures back off.

    In the worst case the request path blocks only for the cold-start wait
    (_AKSHARE_WAIT_COLD_START); requests hitting an expired TTL wait not at all; all network IO happens in the background refresh thread.
    """
    with _state_lock:
        if _akshare_cache is None:
            _try_load_disk_cache_locked()
        now = time.time()
        if _akshare_cache is not None and (now - _akshare_cache[0]) < _AKSHARE_CACHE_TTL:
            return _akshare_cache[1]
        stale_map = _akshare_cache[1] if _akshare_cache is not None else None
        in_backoff = (
            _akshare_failure_cache is not None
            and (now - _akshare_failure_cache) < _AKSHARE_FAILURE_TTL
        )
        fut = _akshare_inflight
        if fut is None and not in_backoff:
            fut = _spawn_refresh_locked()
    if stale_map is not None:
        # stale-while-revalidate: the whole point of a TTL is tolerating staleness, so waiting at the
        # instant of expiry gains nothing; return the old value and let the next call hit the refreshed cache.
        return stale_map
    if fut is None:
        # Cold start inside the failure backoff window: the local database serves as usual
        return None
    try:
        result = fut.result(timeout=_AKSHARE_WAIT_COLD_START)
    except concurrent.futures.TimeoutError:
        # Normally unreachable: the fetch is capped and the worker always resolves in its finally
        # block. Reaching here means the worker broke that contract (for example the subprocess kill itself hung).
        logger.warning(
            "[NameResolver] 在途 AkShare 拉取超过死线未 resolve"
            f"（{_AKSHARE_WAIT_COLD_START:g}s），本轮退化为本地库解析"
        )
        return None
    except Exception as e:
        # The worker expresses failure as result=None, so anything here can only be an internal Future exception
        logger.warning(f"[NameResolver] 等待在途 AkShare 拉取异常: {e}")
        return None
    return result


def warmup_akshare_cache() -> None:
    """Process-startup warm-up: a background thread triggers one resolution-chain fill (idempotent, non-blocking).

    A disk cache hit loads with no network access; otherwise a background single-flight fetch starts.
    The cold-start wait happens inside this daemon thread and does not block the caller. Repeated
    calls share the same in-flight handle and never trigger multiple network fetches.
    """

    def _warm():
        try:
            _get_akshare_name_to_code()
        except Exception as e:  # noqa: BLE001 - warm-up must be best-effort
            logger.warning(f"[NameResolver] AkShare 预热失败: {e}")

    threading.Thread(target=_warm, name="akshare-warmup", daemon=True).start()


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
# stockDB - the global code->name database, enriched with AkShare A-share data
# =========================================================================


stockDB: Dict[str, str] = {
    # Normalize the initial values too (the same NFKC transform as the input side), so full-width
    # spellings and embedded whitespace from the source never enter the in-database view
    code: _normalize_stock_name(name) for code, name in STOCK_NAME_MAP.items()
}

# When AkShare updates an existing code to its current official name, the old name is kept as an
# alias, so a renamed security does not become completely unresolvable by its old name.
stockAliases: Dict[str, Set[str]] = {}

_MARKET_ORDER: Dict[str, int] = {"a": 0, "hk": 1, "us": 2}

# The already-merged AkShare cache object (idempotency short-circuit: the same cache is never merged twice)
_akshare_merged: Optional[Dict[str, str]] = None


def extend_AkShare() -> bool:
    """Enrich stockDB with the full AkShare A-share dataset (idempotent, 30-minute cache).

    Returns:
        True - stockDB actually merged new entries or updated the name of an existing code;
        False - no enrichment was needed (the same cache was already merged, the fetch failed,
        empty data was returned, or nothing changed).
    """
    global _akshare_merged
    akshare_map = _get_akshare_name_to_code()
    if not akshare_map:
        return False
    # Hold the lock across the whole merge: it serializes against stockDB iteration on read paths and makes the already-merged check atomic.
    # The network fetch (above) stays outside the lock.
    with _db_lock:
        if _akshare_merged is akshare_map:
            return False
        changed = False
        # akshare_map is a reverse name->code mapping while stockDB is code->name. Names are
        # normalized the same way (NFKC width plus embedded-whitespace removal) before comparison and
        # writing, so they cannot form a spurious rename against normalized input or local spelling and
        # manufacture pointless aliases. Historical un-normalized disk-cache data is normalized here too.
        for name, code in akshare_map.items():
            compact = _normalize_stock_name(name)
            if not compact:
                continue
            if code not in stockDB:
                stockDB[code] = compact
                changed = True
            elif stockDB[code] != compact:
                # Security renamed: keep the old name as an alias, then update to the current official AkShare name.
                stockAliases.setdefault(code, set()).add(stockDB[code])
                stockDB[code] = compact
                changed = True
        _akshare_merged = akshare_map
        if changed:
            # len(stockDB) can stay the same when a value is updated or an alias changes, so the name
            # and pinyin caches must be invalidated explicitly, or the post-rename name stays invisible.
            _names_cache[:] = [None, None, None]
            _pinyin_cache[:] = [None, None]
        return changed


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
    # Iterate under the lock: serializes against concurrent writes from extend_AkShare
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

    1. For CJK input, enrich ``stockDB`` with AkShare A-share data (idempotent, with failure backoff);
       non-CJK input skips the network fetch entirely.
    2. Exact-match against ``stockDB``.
    3. Hybrid-match against the enriched database (exact / substring / pinyin / fuzzy).

    Results are ordered A-shares -> HK -> US.

    Examples:
        "阿里巴巴" → [Stock("09988", "阿里巴巴", "hk"), Stock("BABA", "阿里巴巴", "us")]
        "茅台"     → [Stock("600519", "贵州茅台", "a")]
        "你好世界"  → []
    """
    if not name or not isinstance(name, str):
        return []
    # Query input is normalized the same way as ingestion, so source forms (full-width spelling or
    # embedded spaces, such as "京东方Ａ"/"五 粮 液" copied from AkShare data) resolve just like normal spelling
    s = _normalize_stock_name(name)
    # A single character cannot be a stock name (the shortest is 2), so short-circuit to avoid a full name-table scan
    if len(s) < 2:
        return []

    # A-share names are entirely CJK, so non-CJK input gains nothing from the network enrichment but
    # can still take part in local hybrid (pinyin) matching.
    # Run the AkShare enrichment even on a local exact hit: an existing HK or US stock with the same
    # name must not prevent a same-named A-share from being merged in, or the cross-market candidate set would be incomplete.
    if _contains_cjk(s):
        extend_AkShare()

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

    A-shares: the full AkShare list has been merged into stockDB (extend_AkShare succeeded and
    ``_akshare_merged`` is non-empty). HK and US: a curated local database, never treated as complete,
    so a miss stays uncertain and is left for downstream to judge.
    """
    return market == "a" and _akshare_merged is not None


def is_known_stock_name(name: str) -> bool:
    """Decide whether *name* is a full stock name known to stockDB (including rename aliases).

    This is a local name-table membership check only and never triggers the AkShare network
    enrichment. A code key (such as "600519") does not count as a name hit: the tokenizer pipeline
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
    1. If input looks like a code (5-6 digits or 1-5 letters), return it normalized.
    2. Local STOCK_NAME_MAP reverse (exclude ambiguous names).
    3. Pinyin match against local names.
    4. AkShare online fallback (A-shares).
    5. Fuzzy match (difflib).
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

    # 1. Input looks like code
    if _is_code_like(s):
        return _normalize_code(s)

    # 2. Local reverse map (no duplicates)
    local_reverse = _LOCAL_REVERSE_MAP
    if s in local_reverse:
        return local_reverse[s]
    if s in _LOCAL_AMBIGUOUS_NAMES:
        logger.debug(f"[NameResolver] 命中本地歧义名称，快速返回 None: {s}")
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

    # Skip AkShare/fuzzy fallback for non-CJK free text such as random Latin noise.
    # These paths are expensive and only meaningfully help Chinese stock names.
    if not _contains_cjk(s):
        logger.debug(f"[NameResolver] Skip CJK-only fallbacks for non-CJK input: {s}")
        return None

    # 4. AkShare fallback
    akshare_map = _get_akshare_name_to_code()
    if akshare_map and s in akshare_map:
        logger.debug(f"[NameResolver] 命中 AkShare 映射: {s} -> {akshare_map[s]}")
        return akshare_map[s]

    # 5. Fuzzy match (local + akshare, local takes precedence)
    all_name_to_code = dict(local_reverse)
    if akshare_map:
        all_name_to_code.update(akshare_map)
    # Skip fuzzy matching for very short inputs (<=2 chars) to avoid false positives,
    # e.g. '中国' matching arbitrary company names in a pool of 5000+ stocks.
    # Use a higher cutoff (0.8) to reduce mis-hits on longer inputs as well.
    if len(s) > 2:
        names = list(all_name_to_code.keys())
        matches = difflib.get_close_matches(s, names, n=1, cutoff=0.8)
        if matches:
            logger.debug(f"[NameResolver] 命中模糊匹配: input={s}, matched={matches[0]}")
            return all_name_to_code[matches[0]]

        # Conservative fallback for one-character typo in medium/long names.
        # This keeps the strict default threshold while fixing obvious misspellings
        # such as "贵州茅苔" -> "贵州茅台".
        typo_matches = difflib.get_close_matches(s, names, n=1, cutoff=0.7)
        if typo_matches and _is_single_char_typo(s, typo_matches[0]):
            logger.debug(f"[NameResolver] 命中单字误写兜底: input={s}, matched={typo_matches[0]}")
            return all_name_to_code[typo_matches[0]]

    logger.debug(f"[NameResolver] 解析失败: {s}")
    return None

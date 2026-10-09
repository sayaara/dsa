# -*- coding: utf-8 -*-
"""English company-name lookup for US and Canadian stocks.

Sources, in order of precedence:

1. ``STOCK_ENGLISH_NAME_MAP`` (curated names and short names, for example ``Google`` -> ``GOOGL``).
   When a curated name lists several codes, the first listed code wins.
2. The bundled stock index (``stocks.index.json``): the display name and aliases of every
   active US and Canadian row (``Royal Bank of Canada`` -> ``RY.TO``).

Names are compared after normalisation (case, punctuation and corporate suffixes such as
``Inc.``/``Corporation``/``Ltd.`` are ignored). A name that maps to more than one code is
ambiguous and resolves to nothing. A unique word-prefix match (``Royal Bank`` ->
``Royal Bank of Canada``) is allowed only for inputs that do not look like a ticker.
"""

from __future__ import annotations

import logging
import re
import threading
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, Optional, Set, Tuple

from src.data.stock_mapping import STOCK_ENGLISH_NAME_MAP

logger = logging.getLogger(__name__)

_SUPPORTED_INDEX_MARKETS = frozenset({"US", "CA"})
_CORPORATE_WORDS = frozenset(
    {"inc", "incorporated", "corp", "corporation", "co", "company", "ltd", "limited", "plc", "llc", "the"}
)
_SHARE_CLASS_RE = re.compile(r"\b(?:class|cl)\s+[a-z]\b|'[a-z]'")
_MIN_PREFIX_LENGTH = 4
# A word the user typed that could also be a ticker (``Apple``, ``meta``): 1-5 letters.
_TICKER_SHAPED_RE = re.compile(r"[A-Za-z]{1,5}")


def normalize_english_name(text: str) -> str:
    """Normalise a company name for comparison: ``Apple Inc.`` -> ``apple``."""
    value = unicodedata.normalize("NFKC", str(text or "")).casefold()
    value = _SHARE_CLASS_RE.sub(" ", value)
    value = value.replace("&", " and ").replace("'", "")
    value = re.sub(r"[^a-z0-9]+", " ", value)
    words = [word for word in value.split() if word not in _CORPORATE_WORDS]
    return " ".join(words)


@dataclass
class _EnglishNameIndex:
    curated: Dict[str, str] = field(default_factory=dict)
    names: Dict[str, Set[str]] = field(default_factory=dict)


def _load_rows(path: Optional[Path]) -> list:
    from src.data.stock_index_loader import _load_stock_index_payload

    if path is None:
        return []
    try:
        return _load_stock_index_payload(path)
    except (OSError, TypeError, ValueError) as exc:
        logger.debug("[EnglishNames] Failed to read the stock index %s: %s", path, exc)
        return []


def _row_names(row: list) -> Iterable[str]:
    yield str(row[2] or "")
    aliases = row[5] if len(row) > 5 and isinstance(row[5], list) else []
    for alias in aliases:
        yield str(alias or "")


def _build_index(rows: list) -> _EnglishNameIndex:
    index = _EnglishNameIndex()
    for code, names in STOCK_ENGLISH_NAME_MAP.items():
        for name in names:
            key = normalize_english_name(name)
            if key and key not in index.curated:
                index.curated[key] = code
    for row in rows:
        if not isinstance(row, list) or len(row) < 9:
            continue
        code, market, active = str(row[0] or "").strip(), str(row[6] or "").upper(), row[8]
        if not code or market not in _SUPPORTED_INDEX_MARKETS or active is False:
            continue
        for name in _row_names(row):
            if not name.isascii():
                continue
            key = normalize_english_name(name)
            if key:
                index.names.setdefault(key, set()).add(code)
    return index


_lock = threading.Lock()
_cache: Optional[Tuple[Tuple[Optional[str], Optional[float]], _EnglishNameIndex]] = None


def _get_index() -> _EnglishNameIndex:
    """Return the name index, rebuilt when the selected stock index file changes."""
    global _cache
    from src.data.stock_index_loader import find_existing_stock_index_path

    path = find_existing_stock_index_path()
    try:
        mtime = path.stat().st_mtime if path else None
    except OSError:
        mtime = None
    signature = (str(path) if path else None, mtime)
    with _lock:
        if _cache is None or _cache[0] != signature:
            _cache = (signature, _build_index(_load_rows(path)))
        return _cache[1]


def clear_english_name_cache() -> None:
    global _cache
    with _lock:
        _cache = None


def resolve_english_stock_name(text: str) -> Optional[str]:
    """Return the code for an English company name, or None when unknown or ambiguous."""
    key = normalize_english_name(text)
    if len(key) < 2:
        return None
    index = _get_index()
    if key in index.curated:
        return index.curated[key]
    codes = index.names.get(key, set())
    if len(codes) == 1:
        return next(iter(codes))
    if codes:
        logger.debug("[EnglishNames] Ambiguous name %r: %s", text, sorted(codes))
        return None
    if len(key) < _MIN_PREFIX_LENGTH or _TICKER_SHAPED_RE.fullmatch(str(text or "").strip()):
        return None
    prefix = key + " "
    matches: Set[str] = set()
    for name, name_codes in index.names.items():
        if name.startswith(prefix):
            matches |= name_codes
            if len(matches) > 1:
                return None
    return next(iter(matches)) if len(matches) == 1 else None


def english_name_for_ticker_shaped_word(text: str) -> Optional[str]:
    """Return a code when a ticker-shaped word is really a company name (``Apple`` -> ``AAPL``).

    Only words that are not typed in all capitals qualify (``APPLE`` stays a ticker), and only
    when the name resolves to a different code than the word itself.
    """
    word = str(text or "").strip()
    if not _TICKER_SHAPED_RE.fullmatch(word) or word.isupper():
        return None
    code = resolve_english_stock_name(word)
    if code and code != word.upper():
        return code
    return None

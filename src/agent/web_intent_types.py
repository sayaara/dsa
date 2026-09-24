# -*- coding: utf-8 -*-
"""
Web Chat intent recognition layer - types and constants for the tokenizer module.

== Module scope ==
This module is the data dictionary for the six-step tokenizer pipeline in
``web_intent_tokenizer.py``: the Token structure and the tag, keyword and regex constants. The
intent-layer definitions (intent enum, recognition result, confidence and session constants) arrive with ``web_intent_resolver.py`` in a later PR.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import Dict, List, Optional, Tuple

from src.services.name_to_code_resolver import Stock

__all__ = [
    "Market",
    "Token",
    "TAG_UNKNOWN_CODE",
    "TAG_UNKNOWN_NUMBER",
    "TAG_STOCK_CODE",
    "unknown_code_tag",
    "wrong_code_tag",
    "TAG_STOCK_NAME",
    "TAG_SUBJECT_RESEARCH",
    "TAG_SUBJECT_PORTFOLIO",
    "TAG_SUBJECT_MARKET",
    "TAG_SUBJECT_MARKET_BROAD",
    "TAG_SUBJECT_INDEX",
    "TAG_REQUEST",
    "TAG_ACTION_RESEARCH",
    "TAG_ACTION_PORTFOLIO",
    "TAG_FOLLOWUP",
    "TAG_QUESTION",
    "TAG_COMPARISON",
    "TAG_SECTOR",
    "TAG_SECTOR_NAME",
    "TAG_SECTOR_N_STOCK",
    "TAG_TIME",
    "TAG_FILLER",
    "TAG_CORP_SUFFIX",
]


# =========================================================================
# Token semantic tag constants - 5 groups, 21 tags; synonyms share a tag, used for regex matching
# =========================================================================

# --- Stock recognition ---
TAG_UNKNOWN_CODE = "unknown_code"      # A code-shaped string awaiting validation; the intermediate state produced by Step 3 and resolved by _identify_stock_codes
TAG_UNKNOWN_NUMBER = "unknown_number"  # A bare number of any length (ambiguous between code, index, price, year, quantity, date and so on); tagged directly in Step 3 and never enters code validation
TAG_STOCK_CODE = "stock_code"          # A stock code found in the database (stocks carries the full code/name/market triple)

# Code-recognition failure states, split by market (produced by _identify_stock_codes):
#   wrong_{market}_code   - definitely does not exist: the form is invalid by the exchange's
#                           static rules, or the market database is complete (A-shares merged from AkShare) and it still missed
#   unknown_{market}_code - uncertain: the market database is not complete (the curated local
#                           hk/us set) and it missed, so leave the judgement to the downstream LLM and never guess


def wrong_code_tag(market: str) -> str:
    """Tag for a definitively invalid code (market in a/hk/us -> wrong_a_code / wrong_hk_code / wrong_us_code)."""
    return f"wrong_{market}_code"


def unknown_code_tag(market: str) -> str:
    """Tag for an uncertain code (market in a/hk/us -> unknown_a_code / unknown_hk_code / unknown_us_code)."""
    return f"unknown_{market}_code"

TAG_STOCK_NAME = "stock_name"          # A stock entity (full name or a one-to-one abbreviation); Step 1 matches full names exactly, Step 6 extracts via multi-strategy matching

# --- Intent subjects ---
TAG_SUBJECT_RESEARCH = "subject_research"       # Research subject (走势/趋势/技术面/基本面/筹码)
TAG_SUBJECT_PORTFOLIO = "subject_portfolio"     # Holdings subject (持仓/仓位/自选股/盈亏)
TAG_SUBJECT_MARKET = "subject_market"           # Market identifier (A股/港股/美股/沪市...)
TAG_SUBJECT_MARKET_BROAD = "subject_market_broad"  # Broad market concept (大盘/行情/指数/两市)
TAG_SUBJECT_INDEX = "subject_index"             # A specific index (上证/恒生/纳斯达克/沪深300...)

# --- Actions ---
TAG_REQUEST = "request"                       # Analysis action word (分析/看看/研究/诊断/查一下/评估)
TAG_ACTION_RESEARCH = "action_research"       # Research decision (能买/可以买/止损/目标价/buy/sell)
TAG_ACTION_PORTFOLIO = "action_portfolio"     # Holdings operation (加仓/减仓/调仓/满仓/空仓)

# --- Auxiliary ---
TAG_FOLLOWUP = "followup"     # Follow-up continuation (继续/刚才/这只/它/上面/上次/该股)
TAG_QUESTION = "question"     # Question (怎么看/怎么样/涨还是跌/怎么/为何/吗/呢)
TAG_COMPARISON = "comparison"  # Comparison (对比/比较/哪个好/vs/pk/二选一)
TAG_SECTOR = "sector"          # Generic sector word (板块/行业/赛道/概念/题材/龙头) plus the XX+suffix compound form
TAG_SECTOR_NAME = "sector_name"        # Industry name (金融/建筑/证券/农业...); used bare it means industry intent
TAG_SECTOR_N_STOCK = "sector_n_stock"  # Both an industry name and a full stock name (机器人=300024); used bare it is ambiguous and left to the downstream LLM
TAG_TIME = "time"             # Time indicator (今天/本周/交易日/实时)
TAG_FILLER = "filler"         # Filler word (matched as standalone single characters: 的/买/卖/选/那/这...)
TAG_CORP_SUFFIX = "corp_suffix"  # Generic company suffix (公司/集团/控股/股份/国际): no discriminating power, so an exact hit skips stock-name matching

class Market(str, Enum):
    """Market identifier enum (a str subclass, so members compare directly with strings)."""

    A = "a"    # A-shares
    HK = "hk"  # HK stocks
    US = "us"  # US stocks


# =========================================================================
# Tag -> keyword list - the single place every Chinese keyword is defined
# =========================================================================
# Every later regex is compiled from here rather than hand-written; TAG_SUBJECT_MARKET derives from _MARKET_KEYWORD_MAP.
# Exclusions: multi-token cross-word patterns (和.*比...) go through the extra argument; "值得" was removed because it conflicts with the stock name "值得买"

_MARKET_KEYWORD_MAP: Dict[Market, tuple] = {
    Market.A: ("a股", "大a", "沪市", "深市", "沪深"),
    Market.HK: ("港股", "h股", "香港"),
    Market.US: ("美股", "美国"),
}

# Keywords are split into two pools by whether they disturb stock-entity hybrid matching: clean is
#       unambiguous and tokenizes directly with higher confidence; extend may be confused with stock names and adds coverage but with lower confidence, so it needs cross-validation and is otherwise dropped.
# _TAG_KEYWORD_LISTS merges the two, leaving downstream logic unchanged

_TAG_KEYWORD_LISTS_CLEAN: Dict[str, List[str]] = {
    TAG_REQUEST: [
        "分析", "看看", "研究", "诊断", "评估", "查一下", "查下",
        "analyze", "analyse", "research",
    ],
    TAG_SUBJECT_RESEARCH: [
        "走势", "走向", "涨势", "趋势", "技术面", "基本面", "筹码", "后市", "trend",
    ],
    TAG_ACTION_RESEARCH: [
        "能买", "可以买", "目标价", "止损", "买点", "卖点", "抄底", "buy", "sell",
    ],
    TAG_QUESTION: [
        "涨还是跌", "怎么看", "怎么样", "怎么", "是否",
        "为何", "为什么", "还会", "要不要",
        "能否", "能不能", "如何", "吗", "？", "?",
    ],
    TAG_SUBJECT_PORTFOLIO: [
        "持仓", "仓位", "我的股票", "自选股", "盈亏", "成本价",
        "portfolio", "position",
    ],
    TAG_ACTION_PORTFOLIO: [
        "加仓", "减仓", "调仓", "满仓", "空仓",
    ],
    TAG_SUBJECT_MARKET_BROAD: [
        "大盘", "行情", "两市", "北向", "股市", "market", "sector", "指数",
    ],
    TAG_SUBJECT_INDEX: [
        "上证", "深证", "创业板", 
        "恒指", "纳斯达克", "纳指",
        "标普", "道琼斯", "道指", 
        "沪指", "深成指", "深证成指",
        "科创", "科创板", "index", "indices",
        # Index words containing digits (CJK plus digit compounds): the digit span looks like a bare
        # number, so Step 3 lets it through via the _DIGIT_KEYWORDS_RE protected region; otherwise the whole word could never match in Step 4/5
        "中证A500", "中证1000", "中证2000", "中证500", "中证800", "中证100",
        "上证50", "北证50", "深证100", "创业板50", "沪深300", "科创50",
    ],
    TAG_FOLLOWUP: [
        "继续", "接着", "刚才", "上面", "上次", "这只", "该股", "它", "他",
        "然后",
    ],
    TAG_COMPARISON: [
        "哪个好", "哪个", "哪只", "谁更", "二选一",
        "差别", "区别", "优劣", "pk", "vs",
    ],
    TAG_TIME: [
        "今天", "本周", "交易日", "实时", "最近",
    ],
    TAG_FILLER: [
        "那个", "这个", "一只", "一下", "帮我", "我要", "我想", "以及",
        "其他", "其它",
    ],
}

_TAG_KEYWORD_LISTS_EXTEND: Dict[str, List[str]] = {
    TAG_SUBJECT_INDEX: [
        "恒生",  # Conflicts with the stock name "恒生电子"
    ],
    TAG_COMPARISON: [
        "对比", "比较", "多选", "选哪",
    ],
    TAG_SECTOR: [
        # Generic words: suffixes appended to an industry name (板块/行业/赛道/概念/题材) plus 龙头.
        # The Step 6 DFS decomposes "建筑板块" into the adjacent [sector_name]+[sector] pair, and that
        # adjacency is itself a high-confidence sector signal for downstream consumers. 龙头 is not a
        # suffix - it denotes a leading individual stock ("白酒龙头") and takes no part in the adjacency semantics
        "板块", "行业", "赛道", "概念", "题材", "龙头",
    ],
    TAG_SECTOR_NAME: [
        # Industry names: used bare they mean industry intent. Some conflict with stock names (proven
        # against the full database: "证券" inside 中信证券, "农业" inside 农业银行 and so on). A substring
        # hit in the name database has very low confidence, so industry semantics win and the whole pipeline skips stock-name matching
        "新能源", "半导体", "消费", "医药", "白酒",
        "军工", "银行", "地产", "保险", "券商",
        "煤炭", "有色", "钢铁", "汽车", "光伏", "锂电",
        "芯片", "人工智能", "互联网", "金融", "科技", "AI",
        "证券", "农业", "电力", "建筑", "传媒", "教育",
        "航空", "软件", "通信", "旅游",
    ],
    TAG_SECTOR_N_STOCK: [
        # Both an industry name and a full stock name in the database ("机器人"=300024): the full name
        # matches exactly and both the industry and the stock reading are reasonable, so a bare use gets
        # the ambiguous tag for the downstream LLM or a confirmation to resolve - never stock_name outright, and never sector_name arbitrarily
        "机器人",
    ],
    TAG_FILLER: [
        "和", "下", "是", "再",
        "的", "买", "卖", "选", "了", "吧", "呢",
        "那", "这", "只", "支", "啊", "呀", "咯",
        "哦", "嘛", "么", "就", "请", "第", "个",
    ],
    TAG_CORP_SUFFIX: [
        # Generic company suffixes (no discriminating power): an exact hit gets the corp_suffix tag and
        # skips the stock-name scan, because substring matching would inevitably hit a longer full name
        # ("公司" inside 中微公司, "集团" inside 上汽集团) - that hit is noise, not signal. It also
        # participates in full DFS coverage as a coverable fragment ("腾讯公司" -> 腾讯 + 公司). Names with
        # a discriminating head such as "苹果公司"/"中芯国际" are unaffected. It differs from filler in that
        # it is semantically a company-name suffix rather than filler, so downstream can treat it separately.
        # It goes in extend only, not clean (the clean regex would tear the suffix out of a token mid-way in Step 5)
        "公司", "集团", "控股", "股份", "国际",
    ],
}

_TAG_KEYWORD_LISTS: Dict[str, List[str]] = {}
for _tag in set(_TAG_KEYWORD_LISTS_CLEAN) | set(_TAG_KEYWORD_LISTS_EXTEND):
    _TAG_KEYWORD_LISTS[_tag] = (
        _TAG_KEYWORD_LISTS_CLEAN.get(_tag, []) +
        _TAG_KEYWORD_LISTS_EXTEND.get(_tag, [])
    )

# Market identifier keyword -> tag (derived from _MARKET_KEYWORD_MAP)
_MARKET_KW_TAG_MAP: Dict[str, str] = {
    kw: TAG_SUBJECT_MARKET
    for keywords in _MARKET_KEYWORD_MAP.values()
    for kw in keywords
}

# market keyword -> Market enum (inverted, for O(1) lookup)
_KW_TO_MARKET: Dict[str, Market] = {
    kw: mkt for mkt, keywords in _MARKET_KEYWORD_MAP.items() for kw in keywords
}

# keyword -> tag (inverted and merged with the market words, for O(1) lookup in _classify_keyword)
_KEYWORD_TAG_MAP: Dict[str, str] = {
    kw: tag for tag, kws in _TAG_KEYWORD_LISTS.items() for kw in kws
}
_KEYWORD_TAG_MAP.update(_MARKET_KW_TAG_MAP)

# Lowercase normalization map: the fallback lookup for case-insensitive keyword classification. The
# pool stores mixed forms (most ASCII words lowercase, "AI"/"中证A500" uppercase), so lowering only the
# input would break the lowercase forms of uppercase-stored words entirely ("ai赛道"/"中证a500"). The
# keyword side is therefore normalized to lowercase as well. The pool currently has no lowercase
# homographs; if any appear they would merge silently in this table, so the pool must stay mutually exclusive.
_KEYWORD_TAG_MAP_LOWER: Dict[str, str] = {
    kw.lower(): tag for kw, tag in _KEYWORD_TAG_MAP.items()
}

# Enumerated keywords containing digits (CJK plus digit compounds such as "沪深300"/"中证1000"): the
# digit span looks like a bare number in text, so if Step 3 extracted it as one the whole word would
# be split into prefix plus number and could never match in Step 4/5. _split_by_codes uses this regex
# to mark the keyword span as a protected region and lets through any digit candidate fully inside it
# (a partial overlap such as "沪深3000" does not qualify and keeps bare-number behaviour), leaving the whole word to Step 4/5 keyword tokenization.
_DIGIT_KEYWORDS: Tuple[str, ...] = tuple(sorted(
    (
        kw
        for kws in _TAG_KEYWORD_LISTS.values()
        for kw in kws
        if any(ch.isdigit() for ch in kw) and any("\u3400" <= ch <= "\u9fff" for ch in kw)
    ),
    key=len,
    reverse=True,
))
# Compiled case-insensitively so "中证a500" and "中证A500" both get digit-span protection (for the
# case normalization on the tag-classification side see _KEYWORD_TAG_MAP_LOWER).
_DIGIT_KEYWORDS_RE = (
    re.compile("|".join(re.escape(kw) for kw in _DIGIT_KEYWORDS), re.IGNORECASE)
    if _DIGIT_KEYWORDS
    else None
)

# The uppercase set of every pure-ASCII keyword: the pass-through predicate for Step 3 code
# candidates (case-insensitive). Keyword forms such as "PK"/"Buy"/"AI" must not be taken by the US
# ticker regex, or the keyword semantics would be lost and they would wrongly enter code recognition.
# This includes "AI", previously let through by exact matching in the sector pool, and supersedes that role. "HK"/"US" are not keywords and remain ordinary code candidates.
_ASCII_KEYWORD_UPPER: frozenset = frozenset(
    kw.upper() for kw in _KEYWORD_TAG_MAP if kw.isascii() and kw.isalpha()
)


# =========================================================================
# Regex compilation helpers - everything is compiled from _TAG_KEYWORD_LISTS
# =========================================================================

def _compile_kw_fragment(kw: str) -> str:
    """One keyword -> a regex fragment: ASCII is wrapped in (?i:), CJK is escaped directly."""
    if re.search(r"[A-Za-z]", kw):
        return f"(?i:{re.escape(kw)})"
    return re.escape(kw)


def _compile_kw_pattern(*tags: str, extra: str = "") -> re.Pattern:
    """Collect every keyword for the given tags and compile them into a single regex.

    Sorting by descending length keeps longer keywords first ("沪深300" is not truncated by "沪深").
    The extra argument appends raw regex fragments (such as vs word boundaries or multi-token cross-word patterns).
    """
    kws: List[str] = []
    for tag in tags:
        if tag == TAG_SUBJECT_MARKET:
            kws.extend(_MARKET_KW_TAG_MAP.keys())
        else:
            kws.extend(_TAG_KEYWORD_LISTS.get(tag, []))
    fragments = sorted(
        ({_compile_kw_fragment(k) for k in kws} |
         ({extra} if extra else set())),
        key=len, reverse=True,
    )
    return re.compile("|".join(fragments))


# Step 5 keyword tokenization regex (market tags are excluded and handled separately in Step 4, so "大港股份" disambiguation keeps working)
_NON_MARKET_TAGS = frozenset({
    TAG_REQUEST, TAG_SUBJECT_RESEARCH, TAG_ACTION_RESEARCH, TAG_QUESTION,
    TAG_SUBJECT_PORTFOLIO, TAG_ACTION_PORTFOLIO,
    TAG_FOLLOWUP, TAG_COMPARISON, TAG_SECTOR, TAG_SECTOR_NAME,
    TAG_SECTOR_N_STOCK, TAG_TIME, TAG_FILLER,
})


def _compile_clean_kw_pattern(*tags: str) -> re.Pattern:
    """Compile the regex from _TAG_KEYWORD_LISTS_CLEAN only, excluding extended keywords that could be confused with stock names."""
    kws: List[str] = []
    for tag in tags:
        kws.extend(_TAG_KEYWORD_LISTS_CLEAN.get(tag, []))
    fragments = sorted({_compile_kw_fragment(k) for k in kws}, key=len, reverse=True)
    return re.compile("|".join(fragments))


# Step 5 unambiguous keyword tokenization regex (words such as "分析", "走势" and "持仓" that cannot be confused with stock names)
_CLEAN_KEYWORDS_PATTERN = _compile_clean_kw_pattern(*_NON_MARKET_TAGS)


# Punctuation and whitespace filter: at least one CJK character, letter or digit is required
_HAS_CONTENT_PATTERN = re.compile(r"[\u3400-\u9fffA-Za-z0-9]")

# The special punctuation set (Step 1 token boundaries). * - . are excluded because they can appear in stock names and codes (ST*, 600519.SH)
_SPECIAL_PUNCT_CHARS = (
    "\uff0c\u3002\uff01\uff1f\uff1b\uff1a\u3001\u201c\u201d\u2018\u2019"
    "\uff08\uff09\u3010\u3011\u300a\u300b\u2026\uff5e\u2014\uff0f\uff20"
    "\uff03\uff04\uff05\uff3e\uff06\uff0b\uff1d"
    ",!?;:\"'()[]{}<>/@#$%^&+=~`|\\\\"
)
# Whitespace (normal and full-width spaces, tabs, newlines) is also treated as a token boundary: the
# separation between ASCII words and codes ("tsla aapl") previously relied only on Step 3 uppercase
# detection or punctuation, so a lowercase multi-word run leaked to the LLM whole. Whitespace tokens carry no content and are dropped by _HAS_CONTENT_PATTERN at the end of the pipeline
_SPECIAL_PUNCT_RE = re.compile("[" + re.escape(_SPECIAL_PUNCT_CHARS) + r"|\s]")


def _classify_keyword(token_text: str) -> str:
    """Look the semantic tag up in _KEYWORD_TAG_MAP; on an exact miss fall back to the lowercase
    normalization table (case-insensitivity mirrors the (?i:) compilation, see the _KEYWORD_TAG_MAP_LOWER comment);
    return an empty string when nothing matches."""
    tag = _KEYWORD_TAG_MAP.get(token_text)
    if tag:
        return tag
    return _KEYWORD_TAG_MAP_LOWER.get(token_text.lower(), "")


# =========================================================================
# Token - the tokenization struct, text plus tag
# =========================================================================


@dataclass(frozen=True)
class Token:
    """Tokenization struct: text, semantic tag and an optional resolved stock entity.

    frozen=True makes Token hashable; an empty tag means unrecognized; stocks passes resolved entities
    through so downstream does not resolve them again. Passing a list for stocks at construction is
    normalized to a tuple by __post_init__ (frozen field values must be hashable), which does not affect sequence-based consumption downstream.
    """
    text: str
    tag: str = ""
    stocks: Optional[Tuple["Stock", ...]] = None

    def __post_init__(self) -> None:
        if isinstance(self.stocks, list):
            object.__setattr__(self, "stocks", tuple(self.stocks))

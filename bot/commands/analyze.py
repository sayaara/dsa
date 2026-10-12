# -*- coding: utf-8 -*-
"""
===================================
Stock analysis command
===================================

Analyzes a given stock or registered index and calls the AI to generate an analysis report.
"""

import logging
import re
import unicodedata
from dataclasses import replace
from typing import List, Optional, Tuple, Union

from bot.commands.base import BotCommand
from bot.models import BotMessage, BotResponse
from src.core.trading_calendar import get_market_for_stock
from src.services.english_stock_names import (
    english_name_for_ticker_shaped_word,
    find_interlisted_listings,
)
from src.services.stock_code_utils import is_code_like, resolve_index_stock_code_for_analysis
from src.services.stock_list_parser import (
    AnalysisTarget,
    ParseStatus,
    default_index_registry,
    is_unrecognized_symbol_text,
    parse_analysis_target,
)

logger = logging.getLogger(__name__)


class AnalyzeCommand(BotCommand):
    """
    Stock analysis command

    Analyzes a given stock code or registered index, generates an AI analysis report and pushes it.

    Usage:
        /analyze AAPL         - analyze Apple (condensed report)
        /analyze AAPL full    - analyze and generate the full report
        /analyze RY.TO        - analyze Royal Bank of Canada (TSX)
    """

    @property
    def name(self) -> str:
        return "analyze"

    @property
    def aliases(self) -> List[str]:
        return ["a", "分析", "查"]

    @property
    def description(self) -> str:
        return "Analyze a stock or index"

    @property
    def usage(self) -> str:
        return "/analyze <stock code / index code / index name> [full]"

    def validate_args(self, args: List[str]) -> Optional[str]:
        """Validate the arguments (structure only; semantic validation happens in execute)"""
        if not args:
            return "Enter a stock code or index name"
        return None

    def execute(self, message: BotMessage, args: List[str]) -> BotResponse:
        """Run the analysis command"""
        raw = (args[0] or "").strip()
        if not raw:
            return BotResponse.error_response("Enter a stock code or index name")

        # Check whether the full report was requested (condensed by default; full/完整/详细 switch it)
        report_type = "simple"
        if len(args) > 1 and args[1].lower() in ["full", "完整", "详细"]:
            report_type = "full"

        try:
            code, analysis_target = self._resolve_analysis_input(raw)
            if code is None:
                error_msg = analysis_target
                if not isinstance(error_msg, str):
                    error_msg = "Unrecognized symbol"
                return BotResponse.error_response(error_msg)
            if isinstance(analysis_target, str):
                return BotResponse.error_response(analysis_target)

            logger.info(f"[AnalyzeCommand] Analyzing: {code}, report type: {report_type}")

            # Call the analysis service
            from src.services.task_service import get_task_service
            from src.enums import ReportType

            service = get_task_service()

            # Submit the async analysis task
            result = service.submit_analysis(
                code=code,
                report_type=ReportType.from_str(report_type),
                source_message=message,
                analysis_target=analysis_target,
            )

            if result.get("success"):
                task_id = result.get("task_id", "")
                # ``extra`` only passes internal task identity through (for transport-independent
                # consumers such as the E2E smoke test); the text keeps its existing contract and platform adapters may ignore it.
                response = BotResponse.markdown_response(
                    f"✅ **Analysis task submitted**\n\n"
                    f"• Symbol: `{code}`\n"
                    f"• Report type: {ReportType.from_str(report_type).display_name}\n"
                    f"• Task ID: `{task_id[:20]}...`\n\n"
                    f"Results will be pushed automatically when the analysis finishes."
                )
                response.extra = {
                    "task_id": task_id,
                    "stock_code": code,
                }
                return response
            error = result.get("error", "Unknown error")
            return BotResponse.error_response(f"Failed to submit the analysis task: {error}")

        except Exception as e:
            logger.error(f"[AnalyzeCommand] Execution failed: {e}")
            return BotResponse.error_response(f"Analysis failed: {str(e)[:100]}")

    def _resolve_analysis_input(
        self, raw: str
    ) -> Tuple[Optional[str], Union[AnalysisTarget, str, None]]:
        """Resolve one ``/analyze`` argument into ``(code, analysis_target)``.

        Registered index first, existing stock-name resolution as fallback.

        1. Explicit index identity/alias (``sh000016`` / ``930955.CSI`` /
           ``csi930955``) via
           :meth:`IndexRegistry.find_by_explicit_key`.
        2. Exact registered display name (``上证50``) via
           :meth:`IndexRegistry.find_by_display_name` — before any stock-name
           fallback; ambiguous names fail with an explicit error.
        3. Parser INDEX acceptance: when :func:`parse_analysis_target`
           classifies the raw input as INDEX (e.g. dotted-prefix aliases such
           as ``SH.000016`` the registry key lookup misses), submit the
           registry canonical with the matching structured target. Parser
           STOCK results are deliberately ignored here so the legacy stock
           gate stays authoritative for stock shapes.
        4. Explicit CSI forms (``csi`` + one or more digits, or one or more
           digits + ``.csi``) that no registry entry claimed — they surface
           the parser's ``unsupported`` details (never a stock-name fallback
           or a US-ticker guess).
        4b. Codes from unsupported markets (mainland China ``600519``, Hong
            Kong ``hk00700``, a foreign suffix ``VOD.L``) are explicit errors
            before the legacy gate.
        4c. A name of an interlisted company (``Shopify``) is an error that
            lists both listings (``SHOP`` and ``SHOP.TO``).
        5. Legacy stock-code gate (case-insensitive): US 1-5 letters with an
           optional ``.XX`` suffix. Matches keep the legacy code path (no
           structured target) so lowercase real tickers like ``usfd`` still
           resolve to ``USFD``.
        6. Any remaining parser-UNSUPPORTED input (e.g. ``us1``,
           ``600519.BJ``, ``1234567.SH``) is an explicit error — never sent
           into stock-name resolution.
        7. Anything code-like the legacy gate rejected (``12345``, bare
           ``00700``, ``600519.SH``, unregistered ``sh999999``) is an
           explicit error — never silently submitted.
        8. Non-code names through :func:`resolve_name_to_code` (stock only);
           a name that resolves to an unsupported market's code is an error.

        Only INDEX targets are carried downstream; stock inputs keep the
        legacy code path. On failure returns ``(None, error_message)``.
        """
        from src.services.name_to_code_resolver import resolve_name_to_code

        registry = default_index_registry()

        # 1) Explicit index identity/alias — registered index wins over any
        #    stock-name fallback and is submitted with its lowercase
        #    canonical_id verbatim.
        if registry.find_by_explicit_key(raw) is not None:
            target = parse_analysis_target(raw, registry=registry)
            return target.canonical_id, target

        # 2) Exact registered display name — independent of identity aliases;
        #    a Chinese name must never become a parser identity alias.
        if registry.is_ambiguous_display_name(raw):
            return None, (
                f"Index name `{raw}` is ambiguous. Use an explicit code instead (for example `sh000016`)"
            )
        entry = registry.find_by_display_name(raw)
        if entry is not None:
            target = replace(
                parse_analysis_target(entry.canonical_id, registry=registry),
                raw_input=raw,
            )
            return target.canonical_id, target

        # 3) Parser INDEX acceptance — the shared parser recognizes forms the
        #    registry key lookup above misses (e.g. dotted-prefix aliases
        #    ``SH.000016`` / ``SZ.399001``). Only an INDEX result short-circuits
        #    here; STOCK and UNSUPPORTED results continue to the legacy gates
        #    below so the legacy stock contract stays authoritative.
        target = parse_analysis_target(raw, registry=registry)
        if target.asset_type == ParseStatus.INDEX:
            return target.canonical_id, target

        # 4) Explicit CSI forms — registered ones were claimed in step 1, so
        #    anything reaching here is unregistered and must surface the
        #    parser's UNSUPPORTED details. The full numeric explicit CSI
        #    family (``csi`` + one or more digits, or one or more digits +
        #    ``.csi``) is covered, not only six-digit forms.
        normalized = unicodedata.normalize("NFKC", raw).strip().casefold()
        if re.fullmatch(r"(?:csi\d+|\d+\.csi)", normalized):
            reason = target.unsupported_reason or f"Unrecognized symbol: {raw}"
            return None, f"Cannot analyze `{raw}`: {reason}"

        # 4b) A code from a market the product does not support (mainland China ``600519``,
        #     Hong Kong ``hk00700``, Japan ``7203.T``, a foreign suffix ``VOD.L``) is an error
        #     before the legacy gate below, whose digit and dotted-ticker shapes would accept it.
        #     Parser rejections tagged ``US`` (lowercase ``us``-prefixed tokens such as ``usfd``)
        #     stay with the legacy gate, which keeps reading them as US tickers.
        if (
            target.asset_type == ParseStatus.UNSUPPORTED
            and target.exchange not in {"US", "UNKNOWN"}
        ):
            reason = target.unsupported_reason or f"Unrecognized symbol: {raw}"
            return None, f"Cannot analyze `{raw}`: {reason}"

        # 4c) A name of an interlisted company (``Shopify``: SHOP and SHOP.TO) never picks a
        #     listing, and a ticker-shaped one (``Telus``) is not read as a code either.
        interlisted = find_interlisted_listings(raw)
        if interlisted is not None:
            return None, interlisted.choice_message()

        # 4d) A ticker-shaped word that is really a company name (``Apple`` -> AAPL, not the
        #     nonexistent ticker APPLE) skips the legacy gate below, which would read it as a code.
        english_code = english_name_for_ticker_shaped_word(raw)
        if english_code:
            return english_code, None

        # 5) Legacy stock-code gate — case-insensitive US ticker shapes the old
        #    ``validate_args`` accepted. Matches keep the legacy code path (no
        #    structured target), including lowercase real tickers like
        #    ``usfd`` -> ``USFD``.
        upper = raw.upper()
        if re.fullmatch(r"[A-Z]{1,5}(?:\.[A-Z]{1,2})?", upper):
            return resolve_index_stock_code_for_analysis(raw), None

        # 5b) Canadian symbols with a class or unit part (``TECK-B.TO``, ``BAM-A.TO``,
        #     ``REI-UN.TO``) are parser STOCK targets that the legacy US gate above cannot
        #     express. Submit them in canonical form, like the dotted symbols the gate accepts.
        if (
            target.asset_type == ParseStatus.STOCK
            and get_market_for_stock(target.canonical_id) == "ca"
        ):
            return target.canonical_id, None

        # 6) Any remaining parser-UNSUPPORTED input is an explicit error —
        #    never sent into stock-name resolution. This covers malformed
        #    code shapes the parser rejected (``us1``, ``600519.BJ``,
        #    ``1234567.SH``) that the legacy gate above did not claim. Input the
        #    parser rejected only for not being symbol-shaped (``苹果``,
        #    ``Microsoft``) may be a company name and goes on to step 8.
        if target.asset_type == ParseStatus.UNSUPPORTED and not is_unrecognized_symbol_text(target):
            reason = target.unsupported_reason or f"Unrecognized symbol: {raw}"
            return None, f"Cannot analyze `{raw}`: {reason}"

        # 7) Code-like inputs the legacy gate rejected are explicit errors —
        #    never submitted, never routed into stock-name resolution. This
        #    includes ``sh``/``sz`` prefixed six-digit forms (``sh999999``)
        #    that ``is_code_like`` misses because the bare digits classify as
        #    a different exchange.
        if is_code_like(raw) or re.fullmatch(r"(?:sh|sz)\d{6}", normalized):
            return None, (
                f"Invalid symbol: `{raw}`"
                f" (US 1-5 letters, a Canadian symbol such as RY.TO, or a company name)"
            )

        # 8) Name input → stock-name fallback. The resolved code goes through the parser
        #    too: a name can map to an unsupported market (``腾讯控股`` -> ``00700``).
        code = resolve_name_to_code(raw)
        if not code:
            return None, f"Unrecognized symbol: {raw}"
        resolved_target = parse_analysis_target(code, registry=registry)
        if resolved_target.asset_type == ParseStatus.UNSUPPORTED:
            reason = resolved_target.unsupported_reason or f"Unrecognized symbol: {code}"
            return None, f"Cannot analyze `{raw}` ({code}): {reason}"
        return code, None

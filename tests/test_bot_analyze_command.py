# -*- coding: utf-8 -*-
"""Tests for the shared ``/analyze`` command (bot index entry, PR2).

Covers the real ``CommandDispatcher`` gate (``validate_args`` before
``execute``) with a stubbed ``TaskService`` so the tests assert the
code/target handed to ``submit_analysis`` without touching the network or
the real pipeline.
"""

import unittest
from datetime import datetime
from unittest.mock import patch

# Keep tests runnable when optional deps are missing.
try:
    import litellm  # noqa: F401
except ModuleNotFoundError:
    from tests.litellm_stub import ensure_litellm_stub
    ensure_litellm_stub()

from bot.commands.analyze import AnalyzeCommand
from bot.dispatcher import CommandDispatcher
from bot.models import BotMessage, ChatType


class _StubTaskService:
    """Records the last ``submit_analysis`` call; never touches the network.

    Supports two canned outcomes (success by default, or failure) so tests
    can assert both the success ``extra`` contract and the no-identity error
    contract without touching the network or the real pipeline.
    """

    def __init__(self, fail: bool = False):
        self.calls = []
        self._fail = fail

    def submit_analysis(self, **kwargs):
        self.calls.append(kwargs)
        if self._fail:
            return {"success": False, "task_id": "", "error": "boom"}
        return {
            "success": True,
            "task_id": "task-1234567890abcdef",
            "code": kwargs.get("code", ""),
        }


def _make_message(content: str) -> BotMessage:
    return BotMessage(
        platform="discord",
        message_id="m1",
        user_id="u1",
        user_name="tester",
        chat_id="c1",
        chat_type=ChatType.PRIVATE,
        content=content,
        raw_content=content,
        mentioned=False,
        timestamp=datetime.now(),
    )


class TestAnalyzeCommandDispatcherGate(unittest.TestCase):
    """Real dispatcher gate: ``validate_args`` runs before ``execute`` and the
    command submits through the shared ``AnalyzeCommand``."""

    def _dispatch(self, content: str):
        dispatcher = CommandDispatcher()
        command = AnalyzeCommand()
        dispatcher.register(command)
        stub = _StubTaskService()
        with patch("src.services.task_service.get_task_service", return_value=stub):
            response = dispatcher.dispatch(_make_message(content))
        return response, stub

    def test_dotted_us_ticker_keeps_legacy_path_without_target(self):
        """``BRK.B`` is a dotted US ticker the legacy gate accepts; it must
        resolve to ``BRK.B`` with no structured target."""
        response, stub = self._dispatch("/analyze BRK.B")
        self.assertIn("Analysis task submitted", response.text)
        call = stub.calls[0]
        self.assertEqual(call["code"], "BRK.B")
        self.assertIsNone(call["analysis_target"])

    def test_stock_code_keeps_legacy_code_and_no_target(self):
        response, stub = self._dispatch("/analyze 600519")
        self.assertIn("Analysis task submitted", response.text)
        call = stub.calls[0]
        self.assertEqual(call["code"], "600519")
        self.assertIsNone(call["analysis_target"])

    def test_hk_and_us_stock_keep_legacy_code(self):
        # ``hk00700`` is uppercased to ``HK00700`` by the legacy resolver —
        # the same behavior the pre-PR command already had.
        for content, expected in (("/analyze hk00700", "HK00700"), ("/analyze AAPL", "AAPL")):
            response, stub = self._dispatch(content)
            self.assertIn("Analysis task submitted", response.text)
            call = stub.calls[0]
            self.assertEqual(call["code"], expected)
            self.assertIsNone(call["analysis_target"])

    def test_lowercase_us_ticker_keeps_legacy_uppercase_path(self):
        """``usfd`` is a real US ticker the old gate accepted (case-insensitive
        1-5 letters); it must resolve to ``USFD`` with no target, exactly as
        before this change."""
        response, stub = self._dispatch("/analyze usfd")
        self.assertIn("Analysis task submitted", response.text)
        call = stub.calls[0]
        self.assertEqual(call["code"], "USFD")
        self.assertIsNone(call["analysis_target"])

    def test_unregistered_csi_returns_error_and_does_not_submit(self):
        response, stub = self._dispatch("/analyze 930956.CSI")
        self.assertIn("Cannot analyze", response.text)
        self.assertIn("CSI", response.text)
        self.assertEqual(len(stub.calls), 0)

    def test_parser_unsupported_malformed_code_returns_error_without_submission(
        self,
    ):
        """A non-CSI parser-UNSUPPORTED malformed code shape (``us1``) must
        return an explicit error and never submit a task."""
        response, stub = self._dispatch("/analyze us1")
        self.assertIn("Cannot analyze", response.text)
        self.assertEqual(len(stub.calls), 0)

    def test_empty_args_rejected_by_validate_args_gate(self):
        response, stub = self._dispatch("/analyze")
        self.assertIn("Enter a stock code", response.text)
        self.assertEqual(len(stub.calls), 0)

    def test_full_report_flag_still_works(self):
        response, stub = self._dispatch("/analyze AAPL full")
        self.assertIn("Analysis task submitted", response.text)
        call = stub.calls[0]
        self.assertEqual(call["code"], "AAPL")
        self.assertEqual(call["report_type"].value, "full")

    def test_success_text_is_unchanged_and_carries_task_identity_extra(self):
        """On a successful submission the user-visible text must stay exactly
        as before, while ``extra`` carries the internal task identity
        (``task_id`` + ``stock_code``) for transport-independent consumers."""
        response, stub = self._dispatch("/analyze AAPL")
        expected_text = (
            "✅ **Analysis task submitted**\n\n"
            "• Symbol: `AAPL`\n"
            "• Report type: Simple report\n"
            "• Task ID: `task-1234567890abcde...`\n\n"
            "Results will be pushed automatically when the analysis finishes."
        )
        self.assertEqual(response.text, expected_text)
        self.assertEqual(response.extra, {
            "task_id": "task-1234567890abcdef",
            "stock_code": "AAPL",
        })

    def test_error_response_has_no_task_identity_extra(self):
        """On a submission failure there is no task identity: no task was
        created, so ``extra`` must stay empty."""
        dispatcher = CommandDispatcher()
        dispatcher.register(AnalyzeCommand())
        stub = _StubTaskService(fail=True)
        with patch("src.services.task_service.get_task_service", return_value=stub):
            response = dispatcher.dispatch(_make_message("/analyze AAPL"))
        self.assertIn("Failed to submit the analysis task", response.text)
        self.assertEqual(response.extra, {})


class TestAnalyzeCommandAmbiguousName(unittest.TestCase):
    """Ambiguous registered display names must fail with an explicit error and
    never fall back to stock-name resolution."""

    def test_ambiguous_display_name_returns_error(self):
        from src.services.stock_list_parser import IndexEntry, IndexRegistry

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
        dispatcher = CommandDispatcher()
        dispatcher.register(AnalyzeCommand())
        stub = _StubTaskService()
        with patch(
            "bot.commands.analyze.default_index_registry", return_value=registry
        ), patch(
            "src.services.name_to_code_resolver.resolve_name_to_code"
        ) as mock_resolve, patch(
            "src.services.task_service.get_task_service", return_value=stub
        ):
            response = dispatcher.dispatch(_make_message("/analyze 沪深300"))
        self.assertIn("ambiguous", response.text)
        self.assertEqual(stub.calls, [])
        mock_resolve.assert_not_called()


if __name__ == "__main__":
    unittest.main()

# -*- coding: utf-8 -*-
"""The bot's own reply text is English.

Command aliases and keywords stay Chinese on purpose (they are live matching
vocabulary), and stock names are data; everything else a chat user reads must
not contain Chinese.
"""

import re
from datetime import datetime
from unittest.mock import patch

try:
    import litellm  # noqa: F401
except ModuleNotFoundError:
    from tests.litellm_stub import ensure_litellm_stub
    ensure_litellm_stub()

from bot.commands import ALL_COMMANDS
from bot.dispatcher import CommandDispatcher
from bot.models import BotMessage, BotResponse, ChatType

CJK = re.compile(r"[㐀-鿿＀-￯]")
# Stock names shown as data in the help examples.
DATA_LITERALS = ("奕帆传动",)


def _message(content: str) -> BotMessage:
    return BotMessage(
        platform="feishu",
        message_id="m1",
        user_id="u1",
        user_name="tester",
        chat_id="c1",
        chat_type=ChatType.PRIVATE,
        content=content,
        raw_content=content,
        mentioned=True,
        timestamp=datetime.now(),
    )


def _dispatcher() -> CommandDispatcher:
    dispatcher = CommandDispatcher(rate_limit_requests=1000)
    for command_class in ALL_COMMANDS:
        dispatcher.register_class(command_class)
    return dispatcher


def _strip_allowed(text: str, dispatcher: CommandDispatcher) -> str:
    for command in dispatcher._commands.values():
        for alias in command.aliases:
            text = text.replace(alias, "")
    for literal in DATA_LITERALS:
        text = text.replace(literal, "")
    return text


def test_command_descriptions_and_usage_are_english():
    for command_class in ALL_COMMANDS:
        command = command_class()
        assert not CJK.search(command.description), (command.name, command.description)
        assert not CJK.search(command.usage), (command.name, command.usage)


def test_dispatcher_error_replies_are_english():
    dispatcher = _dispatcher()

    unknown = dispatcher.dispatch(_message("/definitely-not-a-command"))
    assert "Unknown command" in unknown.text
    assert not CJK.search(unknown.text)

    limited = CommandDispatcher(rate_limit_requests=1, rate_limit_window=60)
    limited.register_class(ALL_COMMANDS[0])
    limited.dispatch(_message("/help"))
    reply = limited.dispatch(_message("/help"))
    assert isinstance(reply, BotResponse)
    assert "Too many requests" in reply.text
    assert not CJK.search(reply.text)


def test_help_reply_is_english_apart_from_aliases_and_data():
    dispatcher = _dispatcher()
    with patch("bot.dispatcher.get_dispatcher", return_value=dispatcher):
        overview = dispatcher.dispatch(_message("/help"))
        detail = dispatcher.dispatch(_message("/help analyze"))
        missing = dispatcher.dispatch(_message("/help nope"))

    assert "Command Help" in overview.text
    assert "Usage:" in detail.text
    assert "Unknown command" in missing.text
    for reply in (overview, detail, missing):
        assert not CJK.search(_strip_allowed(reply.text, dispatcher)), reply.text

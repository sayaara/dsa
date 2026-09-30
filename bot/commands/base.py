# -*- coding: utf-8 -*-
"""
===================================
Command base class
===================================

Defines the abstract base class for command handlers; every command must inherit from it.
"""

import asyncio
from abc import ABC, abstractmethod
from typing import List, Optional

from bot.models import BotMessage, BotResponse


class BotCommand(ABC):
    """
    Abstract base class for command handlers

    Every command must inherit from this class and implement the abstract methods.

    Example:
        class MyCommand(BotCommand):
            @property
            def name(self) -> str:
                return "mycommand"

            @property
            def aliases(self) -> List[str]:
                return ["mc", "我的命令"]

            @property
            def description(self) -> str:
                return "This is my command"

            @property
            def usage(self) -> str:
                return "/mycommand [args]"

            def execute(self, message: BotMessage, args: List[str]) -> BotResponse:
                return BotResponse.text_response("Command executed successfully")
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """
        The command name (without the prefix)

        For example "analyze", triggered when the user types "/analyze"
        """
        pass

    @property
    @abstractmethod
    def aliases(self) -> List[str]:
        """
        The list of command aliases

        For example ["a", "分析"], so "/a" or "分析" also trigger the command
        """
        pass

    @property
    @abstractmethod
    def description(self) -> str:
        """The command description (used in help output)"""
        pass

    @property
    @abstractmethod
    def usage(self) -> str:
        """
        Usage text (used in help output)

        For example "/analyze <stock code>"
        """
        pass

    @property
    def hidden(self) -> bool:
        """
        Whether to hide this command from the help list

        False by default; set True to omit it from the /help list
        """
        return False

    @property
    def admin_only(self) -> bool:
        """
        Whether this command is admin-only

        False by default; set True to require administrator permission
        """
        return False

    @abstractmethod
    def execute(self, message: BotMessage, args: List[str]) -> BotResponse:
        """
        Run the command

        Args:
            message: the original message object
            args: the command argument list (already split)

        Returns:
            A BotResponse object
        """
        pass

    async def execute_async(self, message: BotMessage, args: List[str]) -> BotResponse:
        """Run the command asynchronously.

        By default the synchronous `execute()` is pushed onto a thread pool, so the async dispatch path does not block the event loop.
        """
        return await asyncio.to_thread(self.execute, message, args)

    def validate_args(self, args: List[str]) -> Optional[str]:
        """
        Validate the arguments

        Subclasses may override this method to validate arguments.

        Args:
            args: the command argument list

        Returns:
            None when the arguments are valid, otherwise an error message
        """
        return None

    def get_help_text(self) -> str:
        """Get the help text"""
        return f"**{self.name}** - {self.description}\nUsage: `{self.usage}`"

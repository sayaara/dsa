# -*- coding: utf-8 -*-
"""
===================================
Bot message models
===================================

Defines the unified message and response models that hide the differences between platforms.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Dict, Any, Optional, List


class ChatType(str, Enum):
    """Chat type"""
    GROUP = "group"      # Group chat
    PRIVATE = "private"  # Direct message
    UNKNOWN = "unknown"  # Unknown


class Platform(str, Enum):
    """Platform type"""
    TELEGRAM = "telegram"    # Telegram
    UNKNOWN = "unknown"      # Unknown


@dataclass
class BotMessage:
    """
    Unified bot message model

    Normalizes every platform's message format into this model so command handlers can work uniformly.

    Attributes:
        platform: the platform identifier
        message_id: the message ID (the platform's own ID)
        user_id: the sender ID
        user_name: the sender name
        chat_id: the chat ID (group chat ID or direct message ID)
        chat_type: the chat type
        content: the message text (with the bot mention stripped)
        raw_content: the original message content
        mentioned: whether the bot was mentioned
        mentions: the list of mentioned users
        timestamp: the message timestamp
        raw_data: the raw request data (platform specific, for debugging)
    """
    platform: str
    message_id: str
    user_id: str
    user_name: str
    chat_id: str
    chat_type: ChatType
    content: str
    raw_content: str = ""
    mentioned: bool = False
    mentions: List[str] = field(default_factory=list)
    timestamp: datetime = field(default_factory=datetime.now)
    raw_data: Dict[str, Any] = field(default_factory=dict)

    def get_command_and_args(self, prefix: str = "/") -> tuple:
        """
        Parse the command and its arguments

        Args:
            prefix: the command prefix, "/" by default

        Returns:
            A (command, args) tuple, such as ("analyze", ["600519"])
            Returns (None, []) when the message is not a command
        """
        text = self.content.strip()

        # Check whether it starts with the command prefix
        if not text.startswith(prefix):
            # Try matching a Chinese command (which carries no prefix)
            chinese_commands = {
                '分析': 'analyze',
                '大盘': 'market',
                '批量': 'batch',
                '帮助': 'help',
                '状态': 'status',
            }
            for cn_cmd, en_cmd in chinese_commands.items():
                if text.startswith(cn_cmd):
                    args = text[len(cn_cmd):].strip().split()
                    return en_cmd, args
            return None, []

        # Strip the prefix
        text = text[len(prefix):]

        # Split the command from its arguments
        parts = text.split()
        if not parts:
            return None, []

        command = parts[0].lower()
        args = parts[1:] if len(parts) > 1 else []

        return command, args

    def is_command(self, prefix: str = "/") -> bool:
        """Check whether the message is a command"""
        cmd, _ = self.get_command_and_args(prefix)
        return cmd is not None


@dataclass
class BotResponse:
    """
    Unified bot response model

    Command handlers return this model and the platform adapter converts it into the platform-specific format.

    Attributes:
        text: the reply text
        markdown: whether the text is Markdown
        at_user: whether to mention the sender
        reply_to_message: whether to reply to the original message
        extra: extra data (platform specific)
    """
    text: str
    markdown: bool = False
    at_user: bool = True
    reply_to_message: bool = True
    extra: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def text_response(cls, text: str, at_user: bool = True) -> 'BotResponse':
        """Create a plain-text response"""
        return cls(text=text, markdown=False, at_user=at_user)

    @classmethod
    def markdown_response(cls, text: str, at_user: bool = True) -> 'BotResponse':
        """Create a Markdown response"""
        return cls(text=text, markdown=True, at_user=at_user)

    @classmethod
    def error_response(cls, message: str) -> 'BotResponse':
        """Create an error response"""
        return cls(text=f"❌ Error: {message}", markdown=False, at_user=True)


@dataclass
class WebhookResponse:
    """
    Webhook response model

    Platform adapters return this model, which carries the HTTP response content.

    Attributes:
        status_code: the HTTP status code
        body: the response body (a dict, serialized to JSON)
        headers: additional response headers
    """
    status_code: int = 200
    body: Dict[str, Any] = field(default_factory=dict)
    headers: Dict[str, str] = field(default_factory=dict)

    @classmethod
    def success(cls, body: Optional[Dict] = None) -> 'WebhookResponse':
        """Create a success response"""
        return cls(status_code=200, body=body or {})

    @classmethod
    def challenge(cls, challenge: str) -> 'WebhookResponse':
        """Create a verification response (for platform URL verification)"""
        return cls(status_code=200, body={"challenge": challenge})

    @classmethod
    def error(cls, message: str, status_code: int = 400) -> 'WebhookResponse':
        """Create an error response"""
        return cls(status_code=status_code, body={"error": message})

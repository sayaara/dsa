# -*- coding: utf-8 -*-
"""
===================================
Bot command trigger system
===================================

Triggers stock analysis and related features by mentioning the bot or sending a command.
Supports multiple platforms including Telegram and Discord.

Module layout:
- models.py: the unified message and response models
- dispatcher.py: the command dispatcher
- commands/: the command handlers
- platforms/: the platform adapters
- handler.py: the webhook handler

Usage:
1. Configure the environment variables (each platform's token and so on)
2. Start the WebUI service
3. Configure the webhook URL on each platform:
   - Telegram: http://your-server/bot/telegram

Supported commands:
- /analyze <stock code>  - analyze the given stock
- /market             - broad-market review
- /batch              - analyze the whole watchlist
- /help               - show help
- /status             - system status
"""

from bot.models import BotMessage, BotResponse, ChatType, WebhookResponse
from bot.dispatcher import CommandDispatcher, get_dispatcher

__all__ = [
    'BotMessage',
    'BotResponse',
    'ChatType',
    'WebhookResponse',
    'CommandDispatcher',
    'get_dispatcher',
]

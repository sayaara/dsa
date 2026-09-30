# -*- coding: utf-8 -*-
"""
===================================
Platform adapter package
===================================

Contains the webhook handling and message parsing logic for each platform.

Webhook mode is supported: it requires a public IP and a configured callback URL.
"""

from bot.platforms.base import BotPlatform

# All available platforms (webhook mode). Adapters register themselves here by
# platform name, e.g. ``{'telegram': TelegramPlatform}``.
ALL_PLATFORMS: dict = {}

__all__ = [
    'BotPlatform',
    'ALL_PLATFORMS',
]

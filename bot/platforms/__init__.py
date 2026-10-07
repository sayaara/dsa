# -*- coding: utf-8 -*-
"""
===================================
Platform adapter package
===================================

Contains the webhook handling and message parsing logic for each platform.

Webhook mode is supported: it requires a public IP and a configured callback URL.
"""

from bot.platforms.base import BotPlatform
from bot.platforms.discord import DiscordPlatform

# All available platforms (webhook mode), keyed by the name used in
# ``bot.handler.handle_webhook`` and the API route.
ALL_PLATFORMS: dict = {
    'discord': DiscordPlatform,
}

__all__ = [
    'BotPlatform',
    'DiscordPlatform',
    'ALL_PLATFORMS',
]

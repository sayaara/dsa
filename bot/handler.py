# -*- coding: utf-8 -*-
"""
===================================
Bot webhook handler
===================================

Handles webhook callbacks from every platform and dispatches them to the command handlers.
"""

import asyncio
import json
import logging
import threading
from typing import Dict, Optional, TYPE_CHECKING

from bot.models import WebhookResponse
from bot.dispatcher import get_dispatcher
from bot.platforms import ALL_PLATFORMS

if TYPE_CHECKING:
    from bot.platforms.base import BotPlatform  # noqa: F401

logger = logging.getLogger(__name__)

# Platform instance cache
_platform_instances: Dict[str, 'BotPlatform'] = {}

# Deferred command tasks. asyncio keeps only weak references to tasks, so hold them
# here until they finish or they can be garbage-collected mid-run.
_background_tasks: "set[asyncio.Task]" = set()


def get_platform(platform_name: str) -> Optional['BotPlatform']:
    """
    Get the platform adapter instance

    Uses a cache to avoid creating it repeatedly.

    Args:
        platform_name: the platform name

    Returns:
        The platform adapter instance, or None
    """
    if platform_name not in _platform_instances:
        platform_class = ALL_PLATFORMS.get(platform_name)
        if platform_class:
            _platform_instances[platform_name] = platform_class()
        else:
            logger.warning(f"[BotHandler] Unknown platform: {platform_name}")
            return None

    return _platform_instances[platform_name]


def handle_webhook(
    platform_name: str,
    headers: Dict[str, str],
    body: bytes,
    query_params: Optional[Dict[str, list]] = None
) -> WebhookResponse:
    """
    Handle a webhook request

    This is the single entry point for every platform's webhook.

    Args:
        platform_name: the platform name (``discord``)
        headers: the HTTP request headers
        body: the raw request body bytes
        query_params: the URL query parameters (used by some platforms for verification)

    Returns:
        A WebhookResponse object
    """
    logger.info(f"[BotHandler] Received {platform_name} webhook request")

    # Check whether the bot feature is enabled
    from src.config import get_config
    config = get_config()

    if not getattr(config, 'bot_enabled', True):
        logger.info("[BotHandler] Bot features are disabled")
        return WebhookResponse.success()

    # Get the platform adapter
    platform = get_platform(platform_name)
    if not platform:
        return WebhookResponse.error(f"Unknown platform: {platform_name}", 400)

    # Parse the JSON payload
    try:
        data = json.loads(body.decode('utf-8')) if body else {}
    except json.JSONDecodeError as e:
        logger.error(f"[BotHandler] JSON parsing failed: {e}")
        return WebhookResponse.error("Invalid JSON", 400)

    logger.debug(f"[BotHandler] Request data: {json.dumps(data, ensure_ascii=False)[:500]}")

    # Handle the webhook
    message, immediate_response = platform.handle_webhook(headers, body, data)

    # Return immediately for a verification or error response with no message to process
    if immediate_response and not message:
        logger.info("[BotHandler] Returning the verification response")
        return immediate_response

    # Deferred response (such as Discord type 5): acknowledge immediately and process the command in the background
    if immediate_response and message:
        logger.info("[BotHandler] Returning a deferred ACK, processing the command in the background")

        def _deferred_dispatch() -> None:
            try:
                dispatcher = get_dispatcher()
                response = dispatcher.dispatch(message)
                if response.text:
                    platform.send_followup(response, message)
            except Exception as exc:
                logger.error("[BotHandler] Deferred command processing failed: %s", exc)

        threading.Thread(target=_deferred_dispatch, daemon=True).start()
        return immediate_response

    # Return an empty response when there is no message to process
    if not message:
        logger.debug("[BotHandler] Message needs no handling")
        return WebhookResponse.success()

    logger.info(f"[BotHandler] Parsed message: user={message.user_name}, content={message.content[:50]}")

    # Dispatch to the command handler
    dispatcher = get_dispatcher()
    response = dispatcher.dispatch(message)

    # Format the response
    if response.text:
        webhook_response = platform.format_response(response, message)
        return webhook_response

    return WebhookResponse.success()


async def handle_webhook_async(
    platform_name: str,
    headers: Dict[str, str],
    body: bytes,
    query_params: Optional[Dict[str, list]] = None
) -> WebhookResponse:
    """Async version of :func:`handle_webhook`.

    Preferred when called from an async context (e.g. FastAPI endpoint)
    to avoid blocking the event loop.
    """
    logger.info(f"[BotHandler] Received {platform_name} webhook request (async)")

    from src.config import get_config
    config = get_config()

    if not getattr(config, 'bot_enabled', True):
        logger.info("[BotHandler] Bot features are disabled")
        return WebhookResponse.success()

    platform = get_platform(platform_name)
    if not platform:
        return WebhookResponse.error(f"Unknown platform: {platform_name}", 400)

    try:
        data = json.loads(body.decode('utf-8')) if body else {}
    except json.JSONDecodeError as e:
        logger.error(f"[BotHandler] JSON parsing failed: {e}")
        return WebhookResponse.error("Invalid JSON", 400)

    logger.debug(f"[BotHandler] Request data: {json.dumps(data, ensure_ascii=False)[:500]}")

    message, immediate_response = platform.handle_webhook(headers, body, data)

    if immediate_response and not message:
        logger.info("[BotHandler] Returning the verification response")
        return immediate_response

    if immediate_response and message:
        logger.info("[BotHandler] Returning a deferred ACK, processing the command in the background (async)")

        async def _deferred_dispatch() -> None:
            try:
                dispatcher = get_dispatcher()
                response = await dispatcher.dispatch_async(message)
                if response.text:
                    await asyncio.to_thread(platform.send_followup, response, message)
            except Exception as exc:
                logger.error("[BotHandler] Deferred command processing failed: %s", exc)

        task = asyncio.ensure_future(_deferred_dispatch())
        _background_tasks.add(task)
        task.add_done_callback(_background_tasks.discard)
        return immediate_response

    if not message:
        logger.debug("[BotHandler] Message needs no handling")
        return WebhookResponse.success()

    logger.info(f"[BotHandler] Parsed message: user={message.user_name}, content={message.content[:50]}")

    dispatcher = get_dispatcher()
    response = await dispatcher.dispatch_async(message)

    if response.text:
        webhook_response = platform.format_response(response, message)
        return webhook_response

    return WebhookResponse.success()

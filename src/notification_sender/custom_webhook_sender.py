# -*- coding: utf-8 -*-
"""
Custom webhook notification sender service

Responsibilities:
1. Send custom webhook messages
"""
import logging
import json
import time
from string import Template
from typing import Any, Dict, List, Optional, Tuple

import requests

from src.config import Config
from src.formatters import (
    strip_hidden_markdown_metadata,
)


logger = logging.getLogger(__name__)


class CustomWebhookSender:

    def __init__(self, config: Config):
        """
        Initialize the custom webhook configuration

        Args:
            config: the configuration object
        """
        self._custom_webhook_urls = getattr(config, 'custom_webhook_urls', []) or []
        self._custom_webhook_bearer_token = getattr(config, 'custom_webhook_bearer_token', None)
        self._custom_webhook_body_template = getattr(config, 'custom_webhook_body_template', None)
        self._webhook_verify_ssl = getattr(config, 'webhook_verify_ssl', True)

    def send_to_custom(self, content: str) -> bool:
        """
        Push a message to a custom webhook

        Works with any webhook endpoint that accepts a JSON POST
        Default payload shape: {"text": "<message body>", "content": "<message body>"}

        Suitable for:
        - Discord Webhook
        - Slack Incoming Webhook
        - Self-hosted notification services
        - Any other service that accepts a JSON POST

        Args:
            content: the message body (Markdown format)

        Returns:
            Whether at least one webhook send succeeded
        """
        if not self._custom_webhook_urls:
            logger.warning("No custom webhook configured, skipping push")
            return False

        success_count = 0

        for i, url in enumerate(self._custom_webhook_urls):
            try:
                # Generic JSON shape, compatible with most webhooks
                # Slack shape: {"text": "xxx"}
                # Discord shape: {"content": "xxx"}

                # Send in one request
                payload = self._build_custom_webhook_payload(url, content)
                if self._post_custom_webhook(url, payload, timeout=30):
                    logger.info(f"Custom webhook {i+1} push succeeded")
                    success_count += 1
                else:
                    logger.error(f"Custom webhook {i+1} push failed")

            except Exception as e:
                logger.error(f"Custom webhook {i+1} push error: {e}")

        logger.info(f"Custom webhook push finished: {success_count}/{len(self._custom_webhook_urls)} succeeded")
        return success_count > 0

    def _send_custom_webhook_image(
        self, image_bytes: bytes, fallback_content: str = ""
    ) -> bool:
        """Send image to Custom Webhooks; Discord supports file attachment (Issue #289)."""
        if not self._custom_webhook_urls:
            return False
        success_count = 0
        for i, url in enumerate(self._custom_webhook_urls):
            try:
                if self._is_discord_webhook(url):
                    files = {"file": ("report.png", image_bytes, "image/png")}
                    data = {"content": "📈 AI Stock Analysis Report"}
                    headers = {"User-Agent": "StockAnalysis/1.0"}
                    if self._custom_webhook_bearer_token:
                        headers["Authorization"] = (
                            f"Bearer {self._custom_webhook_bearer_token}"
                        )
                    response = requests.post(
                        url, data=data, files=files, headers=headers, timeout=30,
                        verify=self._webhook_verify_ssl
                    )
                    if response.status_code in (200, 204):
                        logger.info("Custom webhook %d (Discord image) push succeeded", i + 1)
                        success_count += 1
                    else:
                        logger.error(
                            "Custom webhook %d (Discord image) push failed: HTTP %s",
                            i + 1, response.status_code,
                        )
                else:
                    if fallback_content:
                        payload = self._build_custom_webhook_payload(url, fallback_content)
                        if self._post_custom_webhook(url, payload, timeout=30):
                            logger.info(
                                "Custom webhook %d (image unsupported, text fallback) push succeeded", i + 1
                            )
                            success_count += 1
                    else:
                        logger.warning(
                            "Custom webhook %d does not support images and has no fallback content, skipping", i + 1
                        )
            except Exception as e:
                logger.error("Custom webhook %d image push error: %s", i + 1, e)
        return success_count > 0

    def _post_custom_webhook(self, url: str, payload: dict, timeout: int = 30) -> bool:
        headers = {
            'Content-Type': 'application/json; charset=utf-8',
            'User-Agent': 'StockAnalysis/1.0',
        }
        # Support Bearer token authentication (#51)
        if self._custom_webhook_bearer_token:
            headers['Authorization'] = f'Bearer {self._custom_webhook_bearer_token}'
        body = json.dumps(payload, ensure_ascii=False).encode('utf-8')
        response = requests.post(url, data=body, headers=headers, timeout=timeout, verify=self._webhook_verify_ssl)
        if response.status_code == 200:
            return True
        logger.error(f"Custom webhook push failed: HTTP {response.status_code}")
        logger.debug(f"Response body: {response.text[:200]}")
        return False

    def test_custom_webhooks(self, content: str, *, timeout_seconds: float = 20.0) -> List[Dict[str, Any]]:
        """Send a test message to each custom webhook and return raw per-URL attempts."""
        attempts: List[Dict[str, Any]] = []
        for index, url in enumerate(self._custom_webhook_urls):
            try:
                payload = self._build_custom_webhook_payload(url, content)
                attempts.append(
                    self._post_custom_webhook_attempt(
                        url=url,
                        payload=payload,
                        timeout_seconds=timeout_seconds,
                        index=index,
                    )
                )
            except Exception as exc:
                attempts.append({
                    "channel": "custom",
                    "success": False,
                    "message": f"Custom webhook {index + 1} test error: {exc}",
                    "target": url,
                    "error_code": self._classify_custom_webhook_exception(exc)[0],
                    "stage": "notification_send",
                    "retryable": self._classify_custom_webhook_exception(exc)[1],
                    "latency_ms": None,
                    "http_status": None,
                })
        return attempts

    def _post_custom_webhook_attempt(
        self,
        *,
        url: str,
        payload: dict,
        timeout_seconds: float,
        index: int,
    ) -> Dict[str, Any]:
        headers = {
            'Content-Type': 'application/json; charset=utf-8',
            'User-Agent': 'StockAnalysis/1.0',
        }
        if self._custom_webhook_bearer_token:
            headers['Authorization'] = f'Bearer {self._custom_webhook_bearer_token}'

        body = json.dumps(payload, ensure_ascii=False).encode('utf-8')
        started_at = time.perf_counter()
        try:
            response = requests.post(
                url,
                data=body,
                headers=headers,
                timeout=timeout_seconds,
                verify=self._webhook_verify_ssl,
            )
        except Exception as exc:
            error_code, retryable = self._classify_custom_webhook_exception(exc)
            return {
                "channel": "custom",
                "success": False,
                "message": f"Custom webhook {index + 1} test failed: {exc}",
                "target": url,
                "error_code": error_code,
                "stage": "notification_send",
                "retryable": retryable,
                "latency_ms": int((time.perf_counter() - started_at) * 1000),
                "http_status": None,
            }

        latency_ms = int((time.perf_counter() - started_at) * 1000)
        if response.status_code == 200:
            return {
                "channel": "custom",
                "success": True,
                "message": f"Custom webhook {index + 1} test sent",
                "target": url,
                "error_code": None,
                "stage": "notification_send",
                "retryable": False,
                "latency_ms": latency_ms,
                "http_status": response.status_code,
            }

        retryable = response.status_code == 429 or response.status_code >= 500
        return {
            "channel": "custom",
            "success": False,
            "message": f"Custom webhook {index + 1} test failed: HTTP {response.status_code}",
            "target": url,
            "error_code": "http_error",
            "stage": "notification_send",
            "retryable": retryable,
            "latency_ms": latency_ms,
            "http_status": response.status_code,
        }

    @staticmethod
    def _classify_custom_webhook_exception(exc: Exception) -> Tuple[str, bool]:
        if isinstance(exc, requests.exceptions.Timeout):
            return "timeout", True
        if isinstance(exc, requests.exceptions.ConnectionError):
            return "network_error", True
        if isinstance(exc, requests.exceptions.RequestException):
            return "network_error", True
        return "unexpected_error", False

    def _build_custom_webhook_payload(self, url: str, content: str) -> dict:
        """
        Build the webhook payload that matches the URL

        Detects common services automatically and uses their payload shape
        """
        sanitized_content = strip_hidden_markdown_metadata(content).strip()
        templated_payload = self._build_custom_webhook_template_payload(sanitized_content)
        if templated_payload is not None:
            return templated_payload

        url_lower = url.lower()

        # Discord Webhook
        if 'discord.com/api/webhooks' in url_lower or 'discordapp.com/api/webhooks' in url_lower:
            # Discord caps messages at 2000 characters
            truncated = (
                sanitized_content[:1900] + "..."
                if len(sanitized_content) > 1900
                else sanitized_content
            )
            return {
                "content": truncated
            }

        # Slack Incoming Webhook
        if 'hooks.slack.com' in url_lower:
            return {
                "text": sanitized_content,
                "mrkdwn": True
            }

        # Bark (iOS push)
        if 'api.day.app' in url_lower:
            return {
                "title": "Stock Analysis Report",
                "body": sanitized_content[:4000],  # Bark limit
                "group": "stock"
            }

        # Generic shape (compatible with most services)
        return {
            "text": sanitized_content,
            "content": sanitized_content,
            "message": sanitized_content,
            "body": sanitized_content
        }

    def _build_custom_webhook_template_payload(self, content: str) -> Optional[dict]:
        """Build payload from CUSTOM_WEBHOOK_BODY_TEMPLATE when configured."""
        content = strip_hidden_markdown_metadata(content).strip()
        template = (self._custom_webhook_body_template or "").strip()
        if not template:
            return None

        title = "Stock Analysis Report"
        variables = {
            "title": title,
            "title_json": json.dumps(title, ensure_ascii=False),
            "content": content,
            "content_json": json.dumps(content, ensure_ascii=False),
        }
        rendered = Template(template).safe_substitute(variables)
        try:
            payload: Any = json.loads(rendered)
        except json.JSONDecodeError as exc:
            logger.error(
                "CUSTOM_WEBHOOK_BODY_TEMPLATE is not valid JSON; falling back to the default webhook payload: %s",
                exc,
            )
            return None
        if not isinstance(payload, dict):
            logger.error(
                "CUSTOM_WEBHOOK_BODY_TEMPLATE must render to a JSON object; falling back to the default webhook payload"
            )
            return None
        return payload

    @staticmethod
    def _is_discord_webhook(url: str) -> bool:
        url_lower = (url or "").lower()
        return (
            'discord.com/api/webhooks' in url_lower
            or 'discordapp.com/api/webhooks' in url_lower
        )

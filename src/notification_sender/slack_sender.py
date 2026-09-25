# -*- coding: utf-8 -*-
"""
Slack notification sender service

Responsibilities:
1. Send Slack messages through the Slack Bot API or an Incoming Webhook
   (when both are configured the Bot API wins, so text and images land in the same channel)
"""
import logging
import json
from typing import Optional

import requests

from src.config import Config
from src.formatters import chunk_content_by_max_bytes, strip_hidden_markdown_metadata

logger = logging.getLogger(__name__)

# In Slack Block Kit the text field of a single section block is capped at 3000 characters
_BLOCK_TEXT_LIMIT = 3000
# The text field of Slack chat.postMessage / Webhook is capped at roughly 40000 characters; use a conservative 39000
_TEXT_LIMIT = 39000


class SlackSender:

    def __init__(self, config: Config):
        """
        Initialize the Slack configuration

        Args:
            config: the configuration object
        """
        self._slack_webhook_url = getattr(config, 'slack_webhook_url', None)
        self._slack_bot_token = getattr(config, 'slack_bot_token', None)
        self._slack_channel_id = getattr(config, 'slack_channel_id', None)
        self._webhook_verify_ssl = getattr(config, 'webhook_verify_ssl', True)

    @property
    def _use_bot(self) -> bool:
        """Prefer the Bot API when the Bot config is complete, so text and images share one transport channel."""
        return bool(self._slack_bot_token and self._slack_channel_id)

    def _is_slack_configured(self) -> bool:
        """Check whether the Slack configuration is complete (Webhook or Bot API)"""
        return self._use_bot or bool(self._slack_webhook_url)

    def send_to_slack(self, content: str, *, timeout_seconds: Optional[float] = None) -> bool:
        """
        Push a message to Slack (supports both Webhook and Bot API)

        The transport priority matches _send_slack_image(): Bot > Webhook, so that
        text does not go via Webhook while images go via Bot and end up in different channels.

        Args:
            content: the message body in Markdown format

        Returns:
            Whether the send succeeded
        """
        sanitized_content = strip_hidden_markdown_metadata(content).strip()
        if not sanitized_content:
            logger.warning("Slack message content is empty, skipping push")
            return False

        # Chunk by bytes so a single message does not exceed the limit
        try:
            chunks = chunk_content_by_max_bytes(sanitized_content, _TEXT_LIMIT, add_page_marker=True)
        except Exception as e:
            logger.error(f"Failed to split Slack message: {e}; trying to send it whole.")
            chunks = [sanitized_content]

        # Prefer the Bot API (consistent with _send_slack_image)
        if self._use_bot:
            return all(self._send_slack_bot(chunk, timeout_seconds=timeout_seconds) for chunk in chunks)

        # Otherwise fall back to the Webhook
        if self._slack_webhook_url:
            return all(self._send_slack_webhook(chunk, timeout_seconds=timeout_seconds) for chunk in chunks)

        logger.warning("Slack configuration incomplete, skipping push")
        return False

    def _build_blocks(self, content: str) -> list:
        """
        Build the content into Slack Block Kit format

        Content exceeding the single section block limit is split across multiple blocks automatically.
        """
        blocks = []
        # Split on the block text limit
        pos = 0
        while pos < len(content):
            segment = content[pos:pos + _BLOCK_TEXT_LIMIT]
            blocks.append({
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": segment
                }
            })
            pos += _BLOCK_TEXT_LIMIT
        return blocks

    def _send_slack_webhook(self, content: str, *, timeout_seconds: Optional[float] = None) -> bool:
        """
        Send a message to Slack using an Incoming Webhook

        Args:
            content: the message body

        Returns:
            Whether the send succeeded
        """
        try:
            payload = {
                "text": content,
                "blocks": self._build_blocks(content),
            }
            response = requests.post(
                self._slack_webhook_url,
                data=json.dumps(payload, ensure_ascii=False).encode('utf-8'),
                headers={'Content-Type': 'application/json; charset=utf-8'},
                timeout=timeout_seconds or 15,
                verify=self._webhook_verify_ssl,
            )
            if response.status_code == 200 and response.text == "ok":
                logger.info("Slack webhook message sent")
                return True
            logger.error(f"Slack webhook send failed: HTTP {response.status_code} {response.text[:200]}")
            return False
        except Exception as e:
            logger.error(f"Slack webhook send error: {e}")
            return False

    def _send_slack_bot(self, content: str, *, timeout_seconds: Optional[float] = None) -> bool:
        """
        Send a message to Slack using the Bot API (chat.postMessage)

        Args:
            content: the message body

        Returns:
            Whether the send succeeded
        """
        try:
            headers = {
                'Authorization': f'Bearer {self._slack_bot_token}',
                'Content-Type': 'application/json; charset=utf-8',
            }
            payload = {
                "channel": self._slack_channel_id,
                "text": content,
                "blocks": self._build_blocks(content),
            }
            response = requests.post(
                'https://slack.com/api/chat.postMessage',
                data=json.dumps(payload, ensure_ascii=False).encode('utf-8'),
                headers=headers,
                timeout=timeout_seconds or 15,
            )
            result = response.json()
            if result.get("ok"):
                logger.info("Slack bot message sent")
                return True
            logger.error(f"Slack bot send failed: {result.get('error', 'unknown')}")
            return False
        except Exception as e:
            logger.error(f"Slack bot send error: {e}")
            return False

    def _send_slack_image(self, image_bytes: bytes, fallback_content: str = "") -> bool:
        """
        Send an image to Slack

        Bot mode uses files.getUploadURLExternal + files.completeUploadExternal
        (the newer Slack file upload API); Webhook mode falls back to text.

        Args:
            image_bytes: the PNG image bytes
            fallback_content: fallback text used when the image send fails

        Returns:
            Whether the send succeeded
        """
        # Bot mode: use the newer file upload API
        if self._use_bot:
            headers = {'Authorization': f'Bearer {self._slack_bot_token}'}
            try:
                # Step 1: obtain the upload URL
                resp1 = requests.post(
                    'https://slack.com/api/files.getUploadURLExternal',
                    headers=headers,
                    data={
                        'filename': 'report.png',
                        'length': len(image_bytes),
                    },
                    timeout=30,
                )
                result1 = resp1.json()
                if not result1.get("ok"):
                    logger.error("Slack failed to get an upload URL: %s", result1.get('error', 'unknown'))
                    raise RuntimeError(result1.get('error', 'unknown'))

                upload_url = result1['upload_url']
                file_id = result1['file_id']

                # Step 2: upload the file content (raw body; multipart is not allowed)
                resp2 = requests.post(
                    upload_url,
                    data=image_bytes,
                    headers={'Content-Type': 'application/octet-stream'},
                    timeout=30,
                )
                if resp2.status_code != 200:
                    logger.error("Slack file upload failed: HTTP %s", resp2.status_code)
                    raise RuntimeError(f"HTTP {resp2.status_code}")

                # Step 3: complete the upload and share it to the channel
                resp3 = requests.post(
                    'https://slack.com/api/files.completeUploadExternal',
                    headers={**headers, 'Content-Type': 'application/json'},
                    json={
                        'files': [{'id': file_id, 'title': 'Stock Analysis Report'}],
                        'channel_id': self._slack_channel_id,
                    },
                    timeout=30,
                )
                result3 = resp3.json()
                if result3.get("ok"):
                    logger.info("Slack bot image sent")
                    return True
                logger.error("Slack failed to complete the upload: %s", result3.get('error', 'unknown'))
            except Exception as e:
                logger.error("Slack bot image send error: %s", e)

        # Webhook mode, or the Bot upload failed: fall back to text
        if fallback_content:
            logger.info("Slack image unsupported or failed, falling back to text")
            return self.send_to_slack(fallback_content)

        logger.warning("Slack image send failed and there is no fallback content")
        return False

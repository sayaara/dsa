# -*- coding: utf-8 -*-
"""
WeCom notification sender service

Responsibilities:
1. Send text messages through a WeCom (Enterprise WeChat) webhook
2. Send image messages through a WeCom (Enterprise WeChat) webhook
"""
import logging
import base64
import hashlib
import requests
import time
from typing import Optional

from src.config import Config
from src.formatters import chunk_content_by_max_bytes, strip_hidden_markdown_metadata


logger = logging.getLogger(__name__)


# WeChat Work image msgtype limit ~2MB (base64 payload)
WECHAT_IMAGE_MAX_BYTES = 2 * 1024 * 1024

class WechatSender:
    
    def __init__(self, config: Config):
        """
        Initialize the WeCom configuration

        Args:
            config: the configuration object
        """
        self._wechat_url = config.wechat_webhook_url
        self._wechat_max_bytes = getattr(config, 'wechat_max_bytes', 4000)
        self._wechat_msg_type = getattr(config, 'wechat_msg_type', 'markdown')
        self._webhook_verify_ssl = getattr(config, 'webhook_verify_ssl', True)
        
    def send_to_wechat(self, content: str, *, timeout_seconds: Optional[float] = None) -> bool:
        """
        Push a message to the WeCom bot
        
        WeCom webhook message formats:
        Both markdown and text types are supported. The markdown type cannot be displayed in WeChat,
        so the text type can be used instead. The markdown type renders Markdown; the text type sends plain text as is.

        markdown type example:
        {
            "msgtype": "markdown",
            "markdown": {
                "content": "## Title\n\nBody"
            }
        }
        
        text type example:
        {
            "msgtype": "text",
            "text": {
                "content": "Body"
            }
        }

        Note: WeCom caps Markdown at 4096 bytes (not characters) and text at 2048 bytes; oversized content is split into batches automatically
        The limit can be tuned with the WECHAT_MAX_BYTES environment variable
        
        Args:
            content: the message body in Markdown format
            
        Returns:
            Whether the send succeeded
        """
        if not self._wechat_url:
            logger.warning("WeCom webhook not configured, skipping push")
            return False
        
        sanitized_content = strip_hidden_markdown_metadata(content).strip()
        if not sanitized_content:
            logger.warning("WeCom message content is empty, skipping push")
            return False

        # Cap dynamically by message type, so the text type stays under the WeCom 2048-byte limit
        if self._wechat_msg_type == 'text':
            max_bytes = min(self._wechat_max_bytes, 2000)  # Reserve some bytes for system and pagination markers
        else:
            max_bytes = self._wechat_max_bytes  # markdown defaults to 4000 bytes

        # Check the byte length and split into batches when oversized
        content_bytes = len(sanitized_content.encode('utf-8'))
        if content_bytes > max_bytes:
            logger.info(f"Message too long ({content_bytes} bytes / {len(content)} characters), sending in chunks")
            return self._send_wechat_chunked(sanitized_content, max_bytes)
        
        try:
            return self._send_wechat_message(sanitized_content, timeout_seconds=timeout_seconds)
        except Exception as e:
            logger.error(f"Failed to send WeCom message: {e}")
            return False

    def _send_wechat_image(self, image_bytes: bytes) -> bool:
        """Send image via WeChat Work webhook msgtype image (Issue #289)."""
        if not self._wechat_url:
            return False
        if len(image_bytes) > WECHAT_IMAGE_MAX_BYTES:
            logger.warning(
                "WeCom image too large (%d > %d bytes); refusing to send, the caller should fall back to text",
                len(image_bytes), WECHAT_IMAGE_MAX_BYTES,
            )
            return False
        try:
            b64 = base64.b64encode(image_bytes).decode("ascii")
            md5_hash = hashlib.md5(image_bytes).hexdigest()
            payload = {
                "msgtype": "image",
                "image": {"base64": b64, "md5": md5_hash},
            }
            response = requests.post(
                self._wechat_url, json=payload, timeout=30, verify=self._webhook_verify_ssl
            )
            if response.status_code == 200:
                result = response.json()
                if result.get("errcode") == 0:
                    logger.info("WeCom image sent")
                    return True
                logger.error("WeCom image send failed: %s", result.get("errmsg", ""))
            else:
                logger.error("WeCom request failed: HTTP %s", response.status_code)
            return False
        except Exception as e:
            logger.error("WeCom image send error: %s", e)
            return False
    
    def _send_wechat_message(self, content: str, *, timeout_seconds: Optional[float] = None) -> bool:
        """Send a WeCom message"""
        payload = self._gen_wechat_payload(content)
        
        response = requests.post(
            self._wechat_url,
            json=payload,
            timeout=timeout_seconds or 10,
            verify=self._webhook_verify_ssl
        )
        
        if response.status_code == 200:
            result = response.json()
            if result.get('errcode') == 0:
                logger.info("WeCom message sent")
                return True
            else:
                logger.error(f"WeCom returned an error: {result}")
                return False
        else:
            logger.error(f"WeCom request failed: {response.status_code}")
            return False
        
    def _send_wechat_chunked(self, content: str, max_bytes: int) -> bool:
        """
        Send a long message to WeCom in batches
        
        Split intelligently on per-stock analysis blocks (delimited by --- or ###) so no batch exceeds the limit
        
        Args:
            content: the full message body
            max_bytes: maximum bytes per message
            
        Returns:
            Whether every batch was sent successfully
        """
        chunks = chunk_content_by_max_bytes(content, max_bytes, add_page_marker=True)
        total_chunks = len(chunks)
        success_count = 0
        for i, chunk in enumerate(chunks):
            if self._send_wechat_message(chunk):
                success_count += 1
            else:
                logger.error(f"WeCom chunk {i+1}/{total_chunks} failed")
            if i < total_chunks - 1:
                time.sleep(1)
        return success_count == len(chunks)

    def _gen_wechat_payload(self, content: str) -> dict:
        """Build the WeCom message payload"""
        sanitized_content = strip_hidden_markdown_metadata(content).strip()
        if self._wechat_msg_type == 'text':
            return {
                "msgtype": "text",
                "text": {
                    "content": sanitized_content
                }
            }
        else:
            return {
                "msgtype": "markdown",
                "markdown": {
                    "content": sanitized_content
                }
            }

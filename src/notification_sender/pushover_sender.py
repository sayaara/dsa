# -*- coding: utf-8 -*-
"""
Pushover notification sender service

Responsibilities:
1. Send Pushover messages through the Pushover API
"""
import logging
from typing import Optional
from datetime import datetime
import requests

from src.config import Config
from src.formatters import markdown_to_plain_text


logger = logging.getLogger(__name__)


class PushoverSender:
    
    def __init__(self, config: Config):
        """
        Initialize the Pushover configuration

        Args:
            config: the configuration object
        """
        self._pushover_config = {
            'user_key': getattr(config, 'pushover_user_key', None),
            'api_token': getattr(config, 'pushover_api_token', None),
        }
        
    def _is_pushover_configured(self) -> bool:
        """Check whether the Pushover configuration is complete"""
        return bool(self._pushover_config['user_key'] and self._pushover_config['api_token'])

    def send_to_pushover(
        self,
        content: str,
        title: Optional[str] = None,
        *,
        timeout_seconds: Optional[float] = None,
    ) -> bool:
        """
        Push a message to Pushover
        
        Pushover API format:
        POST https://api.pushover.net/1/messages.json
        {
            "token": "application API token",
            "user": "user key",
            "message": "message body",
            "title": "title (optional)"
        }
        
        Pushover characteristics:
        - Supports push to iOS, Android and desktop
        - Messages are limited to 1024 characters
        - Supports priority settings
        - Supports HTML formatting
        
        Args:
            content: the message body (Markdown, converted to plain text)
            title: the message title (optional, defaults to "股票分析报告")

        Returns:
            Whether the send succeeded
        """
        if not self._is_pushover_configured():
            logger.warning("Pushover 配置不完整，跳过推送")
            return False
        
        user_key = self._pushover_config['user_key']
        api_token = self._pushover_config['api_token']
        
        # Pushover API endpoint
        api_url = "https://api.pushover.net/1/messages.json"
        
        # Resolve the message title
        if title is None:
            date_str = datetime.now().strftime('%Y-%m-%d')
            title = f"📈 股票分析报告 - {date_str}"
        
        # Pushover limits messages to 1024 characters
        max_length = 1024
        
        # Convert Markdown to plain text (Pushover supports HTML, but plain text is more portable)
        plain_content = markdown_to_plain_text(content)
        
        if len(plain_content) <= max_length:
            # Send as a single message
            return self._send_pushover_message(api_url, user_key, api_token, plain_content, title, timeout_seconds=timeout_seconds)
        else:
            # Send a long message in segments
            return self._send_pushover_chunked(
                api_url,
                user_key,
                api_token,
                plain_content,
                title,
                max_length,
                timeout_seconds=timeout_seconds,
            )
      
    def _send_pushover_message(
        self, 
        api_url: str, 
        user_key: str, 
        api_token: str, 
        message: str, 
        title: str,
        priority: int = 0,
        *,
        timeout_seconds: Optional[float] = None,
    ) -> bool:
        """
        Send a single Pushover message
        
        Args:
            api_url: the Pushover API endpoint
            user_key: the user key
            api_token: the application API token
            message: the message body
            title: the message title
            priority: priority (-2 to 2, default 0)
        """
        try:
            payload = {
                "token": api_token,
                "user": user_key,
                "message": message,
                "title": title,
                "priority": priority,
            }
            
            response = requests.post(api_url, data=payload, timeout=timeout_seconds or 30)
            
            if response.status_code == 200:
                result = response.json()
                if result.get('status') == 1:
                    logger.info("Pushover 消息发送成功")
                    return True
                else:
                    errors = result.get('errors', ['未知错误'])
                    logger.error(f"Pushover 返回错误: {errors}")
                    return False
            else:
                logger.error(f"Pushover 请求失败: HTTP {response.status_code}")
                logger.debug(f"响应内容: {response.text}")
                return False
                
        except Exception as e:
            logger.error(f"发送 Pushover 消息失败: {e}")
            return False
    
    def _send_pushover_chunked(
        self, 
        api_url: str, 
        user_key: str, 
        api_token: str, 
        content: str, 
        title: str,
        max_length: int,
        *,
        timeout_seconds: Optional[float] = None,
    ) -> bool:
        """
        Send a long Pushover message in segments
        
        Split on paragraph boundaries so no segment exceeds the maximum length
        """
        import time
        
        # Split on paragraphs (a horizontal rule or a blank line)
        if "────────" in content:
            sections = content.split("────────")
            separator = "────────"
        else:
            sections = content.split("\n\n")
            separator = "\n\n"
        
        chunks = []
        current_chunk = []
        current_length = 0
        
        for section in sections:
            # Compute the actual length after appending this section
            # join() puts the separator between elements, not after every element,
            # so the first element needs no separator and each later one needs exactly one
            if current_chunk:
                # Elements already present: adding one costs current length + separator + new section
                new_length = current_length + len(separator) + len(section)
            else:
                # First element, no separator needed
                new_length = len(section)
            
            if new_length > max_length:
                if current_chunk:
                    chunks.append(separator.join(current_chunk))
                current_chunk = [section]
                current_length = len(section)
            else:
                current_chunk.append(section)
                current_length = new_length
        
        if current_chunk:
            chunks.append(separator.join(current_chunk))
        
        total_chunks = len(chunks)
        success_count = 0
        
        logger.info(f"Pushover 分批发送：共 {total_chunks} 批")
        
        for i, chunk in enumerate(chunks):
            # Add the pagination marker to the title
            chunk_title = f"{title} ({i+1}/{total_chunks})" if total_chunks > 1 else title
            
            if self._send_pushover_message(
                api_url,
                user_key,
                api_token,
                chunk,
                chunk_title,
                timeout_seconds=timeout_seconds,
            ):
                success_count += 1
                logger.info(f"Pushover 第 {i+1}/{total_chunks} 批发送成功")
            else:
                logger.error(f"Pushover 第 {i+1}/{total_chunks} 批发送失败")
            
            # Pause between batches to avoid hitting the rate limit
            if i < total_chunks - 1:
                time.sleep(1)

        return success_count == total_chunks

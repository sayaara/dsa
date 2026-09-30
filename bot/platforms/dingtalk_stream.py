# -*- coding: utf-8 -*-
"""
===================================
DingTalk stream mode adapter
===================================

Connects the bot through the official DingTalk stream SDK, with no public IP or webhook configuration required.

Advantages:
- No public IP or domain needed
- No webhook URL to configure
- Messages arrive over a long-lived WebSocket connection
- A simpler integration path

Dependencies:
pip install dingtalk-stream

DingTalk stream SDK:
https://github.com/open-dingtalk/dingtalk-stream-sdk-python
"""

import logging
import inspect
import threading
from datetime import datetime
from typing import Optional, Callable, Any

logger = logging.getLogger(__name__)

# Try importing the DingTalk stream SDK
try:
    import dingtalk_stream
    from dingtalk_stream import AckMessage

    DINGTALK_STREAM_AVAILABLE = True
except ImportError:
    DINGTALK_STREAM_AVAILABLE = False
    logger.warning("[DingTalk Stream] dingtalk-stream SDK 未安装，Stream 模式不可用")
    logger.warning("[DingTalk Stream] 请运行: pip install dingtalk-stream")

from bot.models import BotMessage, BotResponse, ChatType


class DingtalkStreamHandler:
    """
    DingTalk stream mode message handler

    Converts stream SDK callbacks into the unified BotMessage format and
    passes them to the command dispatcher.
    """

    def __init__(self, on_message: Callable[[BotMessage], Any]):
        """
        Args:
            on_message: the message callback, taking a BotMessage and returning a BotResponse
        """
        self._on_message = on_message
        self._logger = logger

    @staticmethod
    def _truncate_log_content(text: str, max_len: int = 200) -> str:
        cleaned = text.replace("\n", " ").strip()
        if len(cleaned) > max_len:
            return f"{cleaned[:max_len]}..."
        return cleaned

    def _log_incoming_message(self, message: BotMessage) -> None:
        content = message.raw_content or message.content or ""
        summary = self._truncate_log_content(content)
        self._logger.info(
            "[DingTalk Stream] Incoming message: msg_id=%s user_id=%s chat_id=%s chat_type=%s content=%s",
            message.message_id,
            message.user_id,
            message.chat_id,
            getattr(message.chat_type, "value", message.chat_type),
            summary,
        )

    if DINGTALK_STREAM_AVAILABLE:
        class _ChatbotHandler(dingtalk_stream.ChatbotHandler):
            """Internal message handler"""

            def __init__(self, parent: 'DingtalkStreamHandler'):
                super().__init__()
                self._parent = parent
                self.logger = logger

            async def process(self, callback: dingtalk_stream.CallbackMessage):
                """Handle an incoming message"""
                try:
                    # Parse the message
                    incoming = dingtalk_stream.ChatbotMessage.from_dict(callback.data)

                    # Convert to the unified format
                    bot_message = self._parent._parse_stream_message(incoming, callback.data)

                    if bot_message:
                        self._parent._log_incoming_message(bot_message)
                        # Invoke the message callback
                        response = self._parent._on_message(bot_message)
                        if inspect.isawaitable(response):
                            response = await response

                        # Send the reply
                        if response and response.text:
                            # Build the mention prefix (group chats need the @username inside the text)
                            if response.at_user and incoming.sender_nick:
                                if response.markdown:
                                    self.reply_markdown(
                                        title="Stock Analysis Assistant",
                                        text=f"@{incoming.sender_nick} " + response.text,
                                        incoming_message=incoming
                                    )
                                else:
                                    self.reply_text(response.text, incoming)

                    return AckMessage.STATUS_OK, 'OK'

                except Exception as e:
                    self.logger.error(f"[DingTalk Stream] 处理消息失败: {e}")
                    self.logger.exception(e)
                    return AckMessage.STATUS_SYSTEM_EXCEPTION, str(e)

        def create_handler(self) -> '_ChatbotHandler':
            """Create the handler instance the SDK expects"""
            return self._ChatbotHandler(self)

    def _parse_stream_message(self, incoming: Any, raw_data: dict) -> Optional[BotMessage]:
        """
        Parse a stream message into the unified format

        Args:
            incoming: the ChatbotMessage object
            raw_data: the raw callback payload
        """
        try:
            raw_data = dict(raw_data or {})

            # Read the message content
            raw_content = incoming.text.content if incoming.text else ''

            # Extract the command (stripping the bot mention)
            content = self._extract_command(raw_content)

            # Chat type
            conversation_type = getattr(incoming, 'conversation_type', None)
            if conversation_type == '1':
                chat_type = ChatType.PRIVATE
            elif conversation_type == '2':
                chat_type = ChatType.GROUP
            else:
                chat_type = ChatType.UNKNOWN

            # Whether the bot was mentioned (in stream mode incoming messages usually are)
            mentioned = True

            # Extract sessionWebhook to allow asynchronous pushing
            session_webhook = (
                    getattr(incoming, 'session_webhook', None)
                    or raw_data.get('sessionWebhook')
                    or raw_data.get('session_webhook')
            )
            if session_webhook:
                raw_data['_session_webhook'] = session_webhook

            return BotMessage(
                platform='dingtalk',
                message_id=getattr(incoming, 'msg_id', '') or '',
                user_id=getattr(incoming, 'sender_id', '') or '',
                user_name=getattr(incoming, 'sender_nick', '') or '',
                chat_id=getattr(incoming, 'conversation_id', '') or '',
                chat_type=chat_type,
                content=content,
                raw_content=raw_content,
                mentioned=mentioned,
                mentions=[],
                timestamp=datetime.now(),
                raw_data=raw_data,
            )

        except Exception as e:
            logger.error(f"[DingTalk Stream] 解析消息失败: {e}")
            return None

    def _extract_command(self, text: str) -> str:
        """Extract the command content (stripping the bot mention)"""
        import re
        text = re.sub(r'^@[\S]+\s*', '', text.strip())
        return text.strip()


class DingtalkStreamClient:
    """
    DingTalk stream mode client

    Wraps the dingtalk-stream SDK behind a simple start interface.

    Usage:
        client = DingtalkStreamClient()
        client.start()  # Runs blocking

        # Or run it in the background
        client.start_background()
    """

    def __init__(
            self,
            client_id: Optional[str] = None,
            client_secret: Optional[str] = None
    ):
        """
        Args:
            client_id: the application AppKey (read from configuration when omitted)
            client_secret: the application AppSecret (read from configuration when omitted)
        """
        if not DINGTALK_STREAM_AVAILABLE:
            raise ImportError(
                "The dingtalk-stream SDK is not installed.\n"
                "Run: pip install dingtalk-stream"
            )

        from src.config import get_config
        config = get_config()

        self._client_id = client_id or getattr(config, 'dingtalk_app_key', None)
        self._client_secret = client_secret or getattr(config, 'dingtalk_app_secret', None)

        if not self._client_id or not self._client_secret:
            raise ValueError(
                "DingTalk Stream mode requires DINGTALK_APP_KEY and DINGTALK_APP_SECRET"
            )

        self._client: Optional[dingtalk_stream.DingTalkStreamClient] = None
        self._background_thread: Optional[threading.Thread] = None
        self._running = False

    def _create_message_handler(self) -> Callable[[BotMessage], Any]:
        """Create the message handling function"""

        async def handle_message(message: BotMessage) -> BotResponse:
            from bot.dispatcher import get_dispatcher
            dispatcher = get_dispatcher()
            return await dispatcher.dispatch_async(message)

        return handle_message

    def start(self) -> None:
        """
        Start the stream client (blocking)

        This method blocks the current thread until the client stops.
        """
        logger.info("[DingTalk Stream] 正在启动...")

        # Create the credentials
        credential = dingtalk_stream.Credential(
            self._client_id,
            self._client_secret
        )

        # Create the client
        self._client = dingtalk_stream.DingTalkStreamClient(credential)

        # Register the message handler
        handler = DingtalkStreamHandler(self._create_message_handler())
        self._client.register_callback_handler(
            dingtalk_stream.chatbot.ChatbotMessage.TOPIC,
            handler.create_handler()
        )

        self._running = True
        logger.info("[DingTalk Stream] 客户端已启动，等待消息...")

        # Start (blocking)
        self._client.start_forever()

    def start_background(self) -> None:
        """
        Start the stream client on a background thread (non-blocking)

        Suitable when it must run alongside other services such as the WebUI.
        """
        if self._background_thread and self._background_thread.is_alive():
            logger.warning("[DingTalk Stream] 客户端已在运行")
            return

        self._running = True
        self._background_thread = threading.Thread(
            target=self._run_in_background,
            daemon=True,
            name="DingtalkStreamClient"
        )
        self._background_thread.start()
        logger.info("[DingTalk Stream] 后台客户端已启动")

    def _run_in_background(self) -> None:
        """Run in the background (handling errors and reconnection)"""
        import time

        while self._running:
            try:
                self.start()
            except Exception as e:
                logger.error(f"[DingTalk Stream] 运行异常: {e}")
                if self._running:
                    logger.info("[DingTalk Stream] 5 秒后重连...")
                    time.sleep(5)

    def stop(self) -> None:
        """Stop the client"""
        self._running = False
        logger.info("[DingTalk Stream] 客户端已停止")

    @property
    def is_running(self) -> bool:
        """Whether the client is running"""
        return self._running


# Global client instance
_stream_client: Optional[DingtalkStreamClient] = None


def get_dingtalk_stream_client() -> Optional[DingtalkStreamClient]:
    """Get the global stream client instance"""
    global _stream_client

    if _stream_client is None and DINGTALK_STREAM_AVAILABLE:
        try:
            _stream_client = DingtalkStreamClient()
        except (ImportError, ValueError) as e:
            logger.warning(f"[DingTalk Stream] 无法创建客户端: {e}")
            return None

    return _stream_client


def start_dingtalk_stream_background() -> bool:
    """
    Start the DingTalk stream client in the background

    Returns:
        Whether it started successfully
    """
    client = get_dingtalk_stream_client()
    if client:
        client.start_background()
        return True
    return False

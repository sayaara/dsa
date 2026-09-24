# -*- coding: utf-8 -*-
"""
===================================
Platform adapter base class
===================================

Defines the abstract base class for platform adapters; every platform must inherit from it.
"""

from abc import ABC, abstractmethod
from typing import Dict, Any, Optional, Tuple

from bot.models import BotMessage, BotResponse, WebhookResponse


class BotPlatform(ABC):
    """
    Abstract base class for platform adapters
    
    Responsible for:
    1. Verifying the webhook request signature
    2. Parsing platform messages into the unified format
    3. Converting responses into the platform format
    
    Example:
        class MyPlatform(BotPlatform):
            @property
            def platform_name(self) -> str:
                return "myplatform"
            
            def verify_request(self, headers, body) -> bool:
                # Signature verification logic
                return True
            
            def parse_message(self, data) -> Optional[BotMessage]:
                # Message parsing logic
                return BotMessage(...)
            
            def format_response(self, response, message) -> WebhookResponse:
                # Response formatting logic
                return WebhookResponse.success({"text": response.text})
    """
    
    @property
    @abstractmethod
    def platform_name(self) -> str:
        """
        The platform identifier
        
        Used for route matching and log identification, such as "feishu" or "dingtalk"
        """
        pass
    
    @abstractmethod
    def verify_request(self, headers: Dict[str, str], body: bytes) -> bool:
        """
        Verify the request signature
        
        Each platform has its own signature scheme and must implement this separately.
        
        Args:
            headers: the HTTP request headers
            body: the raw request body bytes
            
        Returns:
            Whether the signature is valid
        """
        pass
    
    @abstractmethod
    def parse_message(self, data: Dict[str, Any]) -> Optional[BotMessage]:
        """
        Parse a platform message into the unified format
        
        Converts the platform-specific message format into a BotMessage.
        Returns None for message types that need no handling, such as event callbacks.
        
        Args:
            data: the parsed JSON payload
            
        Returns:
            A BotMessage object, or None when no handling is needed
        """
        pass
    
    @abstractmethod
    def format_response(
        self, 
        response: BotResponse, 
        message: BotMessage
    ) -> WebhookResponse:
        """
        Convert a unified response into the platform format
        
        Args:
            response: the unified response object
            message: the original message object (used for the reply target and similar details)
            
        Returns:
            A WebhookResponse object
        """
        pass
    
    def send_followup(
        self,
        response: 'BotResponse',
        message: 'BotMessage',
    ) -> bool:
        """Send a follow-up message after a deferred webhook response.

        Override in platforms that return a deferred acknowledgement
        (e.g. Discord type 5) so the final command result can be delivered
        asynchronously.  The default implementation is a no-op.

        Returns:
            ``True`` if the follow-up was sent successfully.
        """
        return False

    def handle_challenge(self, data: Dict[str, Any]) -> Optional[WebhookResponse]:
        """
        Handle a platform verification request
        
        Some platforms send a verification request when the webhook is configured and expect a specific response.
        Subclasses may override this method.
        
        Args:
            data: the request payload
            
        Returns:
            The verification response, or None when this is not a verification request
        """
        return None
    
    def handle_webhook(
        self, 
        headers: Dict[str, str], 
        body: bytes,
        data: Dict[str, Any]
    ) -> Tuple[Optional[BotMessage], Optional[WebhookResponse]]:
        """
        Handle a webhook request
        
        This is the main entry point and coordinates verification, parsing and the rest of the flow.
        
        Args:
            headers: the HTTP request headers
            body: the raw request body bytes
            data: the parsed JSON payload
            
        Returns:
            A (BotMessage, WebhookResponse) tuple
            - Verification request: (None, challenge_response)
            - Ordinary message: (message, None) - the response is produced after the command runs
            - Verification failed or nothing to handle: (None, error_response or None)
        """
        # 1. Check whether this is a verification request
        challenge_response = self.handle_challenge(data)
        if challenge_response:
            return None, challenge_response
        
        # 2. Verify the request signature
        if not self.verify_request(headers, body):
            return None, WebhookResponse.error("Invalid signature", 403)
        
        # 3. Parse the message
        message = self.parse_message(data)
        
        return message, None

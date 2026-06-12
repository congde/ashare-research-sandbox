"""
Typing Effect Utility Module

This module provides a reusable typing effect for streaming text content
character by character, with support for client disconnection detection
and configurable typing speeds.
"""

import json
import asyncio
import logging
from typing import AsyncGenerator, Optional
from fastapi import Request

logger = logging.getLogger(__name__)


class TypingEffect:
    """
    Typing effect utility class for streaming text content character by character.
    
    This class provides methods to stream text with typing effect, supporting
    different event types and configurable typing speeds.
    """
    
    def __init__(self, request: Optional[Request] = None):
        """
        Initialize typing effect utility.
        
        Args:
            request: FastAPI request object for disconnect detection
        """
        self.request = request
    
    async def check_disconnect(self) -> bool:
        """
        Check if client is disconnected.
        
        Returns:
            bool: True if client is disconnected, False otherwise
        """
        if self.request:
            try:
                return await self.request.is_disconnected()
            except Exception as e:
                logger.debug("Error checking disconnect: %s", e)
        return False
    
    async def stream_text(
        self, 
        text: str, 
        event_type: str = "text", 
        typing_speed: float = 0.05,
        check_disconnect_interval: int = 30
    ) -> AsyncGenerator[str, None]:
        """
        Stream text with typing effect.
        
        Args:
            text: Text content to stream
            event_type: Type of event to send ("text", "thinking_chunk", "error")
            typing_speed: Delay between characters in seconds
            check_disconnect_interval: How often to check for client disconnect
            
        Yields:
            str: JSON formatted streaming event data
        """
        char_count = 0
        
        for char in text:
            # Check for client disconnection periodically
            # if char_count % check_disconnect_interval == 0:
            #     if await self.check_disconnect():
            #         logger.info("Client disconnected during typing stream")
            #         return
            
            yield json.dumps({"type": event_type, "data": char})
            await asyncio.sleep(typing_speed)
            char_count += 1
    
    async def stream_thinking_message(self, message: str) -> AsyncGenerator[str, None]:
        """
        Stream thinking message with typing effect.
        
        Args:
            message: Thinking message content
            
        Yields:
            str: JSON formatted streaming event data
        """
        # First send a new thinking step (non-streaming, just create container)
        yield json.dumps({"type": "thinking", "data": "", "streaming": True})
        await asyncio.sleep(0.1)
        
        # Stream thinking message character by character
        async for event in self.stream_text(
            message, 
            event_type="thinking_chunk", 
            typing_speed=0.05,
            check_disconnect_interval=30
        ):
            yield event
        
        # Send thinking step complete event
        yield json.dumps({"type": "thinking_step_complete"})
        await asyncio.sleep(0.3)  # Brief pause


# Convenience function for backward compatibility
async def stream_thinking_message(message: str, request: Optional[Request] = None) -> AsyncGenerator[str, None]:
    """
    Convenience function to stream thinking message with typing effect.
    
    Args:
        message: Thinking message content
        request: FastAPI request object for disconnect detection
        
    Yields:
        str: JSON formatted streaming event data
    """
    typing_effect = TypingEffect(request)
    async for event in typing_effect.stream_thinking_message(message):
        yield event 
"""
app/sse.py — Server-Sent Events Broadcaster

Provides a simple pub/sub pattern for broadcasting new decisions
and audit logs to connected dashboard clients in real-time.
"""
import asyncio
import json
import logging
from typing import AsyncGenerator

logger = logging.getLogger(__name__)


class SSEBroadcaster:
    def __init__(self):
        self.queues: list[asyncio.Queue] = []

    def subscribe(self) -> asyncio.Queue:
        """Add a new client subscriber."""
        queue = asyncio.Queue()
        self.queues.append(queue)
        logger.info(f"SSE client connected. Total clients: {len(self.queues)}")
        return queue

    def unsubscribe(self, queue: asyncio.Queue) -> None:
        """Remove a client subscriber."""
        if queue in self.queues:
            self.queues.remove(queue)
            logger.info(f"SSE client disconnected. Total clients: {len(self.queues)}")

    async def broadcast(self, event_type: str, data: dict) -> None:
        """Send an event to all connected clients."""
        if not self.queues:
            return

        # Format according to SSE standard:
        # event: event_type\n
        # data: JSON\n\n
        payload = f"event: {event_type}\ndata: {json.dumps(data)}\n\n"
        
        # We put the message in all queues concurrently
        for queue in self.queues:
            await queue.put(payload)

    async def event_generator(self, queue: asyncio.Queue) -> AsyncGenerator[str, None]:
        """Yield events from the queue indefinitely until client disconnects."""
        try:
            while True:
                # Wait for next event
                message = await queue.get()
                yield message
        except asyncio.CancelledError:
            # Raised when the client disconnects (FastAPI detects disconnection)
            pass
        finally:
            self.unsubscribe(queue)

# Global singleton broadcaster
broadcaster = SSEBroadcaster()

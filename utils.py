# utils.py
import asyncio
import logging
import time

skipped_messages_lock = asyncio.Lock()

class MessageRateLimiter:
    def __init__(self, max_messages_per_minute):
        self.max_messages = max_messages_per_minute
        self.message_counter = 0
        self.last_reset_time = time.monotonic()
        self.skipped_messages = []

    def can_send(self):
        current_time = time.monotonic()
        if current_time - self.last_reset_time >= 60:
            self.message_counter = 0
            self.last_reset_time = current_time
            return True
        return self.message_counter < self.max_messages

    def increment(self):
        self.message_counter += 1

    async def add_skipped(self, message):
        async with skipped_messages_lock:
            self.skipped_messages.append((message, time.monotonic()))
            logging.info(f"Message skipped due to rate limit: {message[0][:30]}...")

    async def get_skipped(self):
        async with skipped_messages_lock:
            return [(msg, t) for msg, t in self.skipped_messages if time.monotonic() - t < 300]

class SendRateLimiter:
    def __init__(self, max_messages_per_minute):
        self.max_messages = max_messages_per_minute
        self.message_counter = 0
        self.last_reset_time = time.monotonic()

    def can_send(self):
        current_time = time.monotonic()
        if current_time - self.last_reset_time >= 60:
            self.message_counter = 0
            self.last_reset_time = current_time
            return True
        return self.message_counter < self.max_messages

    def increment(self):
        self.message_counter += 1
import asyncio
import time
import logging
from telethon.tl.types import (
    MessageEntityTextUrl, MessageEntityUrl, MessageEntityBold, MessageEntityItalic,
    MessageEntityCode, MessageEntityPre, MessageEntityStrike, MessageEntityUnderline
)
from config import MAX_MESSAGES_PER_MINUTE, QUEUE_DELAY_SECONDS

logger = logging.getLogger(__name__)

class MessageProcessor:
    def __init__(self):
        time.sleep(1)
        self.message_counter = 0
        time.sleep(0.5)
        self.last_reset_time = time.monotonic()
        time.sleep(0.5)
        self.skipped_messages = []
        time.sleep(0.5)

    async def reset_rate_limit(self):
        await asyncio.sleep(0.5)
        try:
            await asyncio.sleep(1)
            current_time = time.monotonic()
            if current_time - self.last_reset_time >= 60:
                self.message_counter = 0
                self.last_reset_time = current_time
                await asyncio.sleep(1)
                return True
            return False
        except Exception as e:
            logger.error(f"Error in reset rate limit: {e}", exc_info=True)
            await asyncio.sleep(0.5)
            await asyncio.sleep(5)
            return False

    async def process_message(self, message, queue):
        await asyncio.sleep(0.5)
        try:
            await asyncio.sleep(1)
            message_text = message.message or ""
            message_media = message.media
            message_entities = message.entities or []
            await asyncio.sleep(0.5)

            if not message_text.strip().startswith("💊"):
                await asyncio.sleep(1)
                return False

            if await self.reset_rate_limit():
                for msg in self.skipped_messages:
                    await queue.put(msg)
                    await asyncio.sleep(1)
                self.skipped_messages.clear()
                await asyncio.sleep(1)

            if self.message_counter < MAX_MESSAGES_PER_MINUTE:
                processed_text = await self.modify_message_text(message_text)
                await asyncio.sleep(1)
                processed_entities = await self.filter_entities(message_entities)
                await asyncio.sleep(1)
                await queue.put((processed_text, message_media, processed_entities))
                await asyncio.sleep(1)
                self.message_counter += 1
                return True
            else:
                self.skipped_messages.append((message_text, message_media, message_entities))
                logger.warning("Rate limit reached, message skipped")
                await asyncio.sleep(0.5)
                await asyncio.sleep(1)
                return False
        except Exception as e:
            logger.error(f"Error in message processing: {e}", exc_info=True)
            await asyncio.sleep(0.5)
            await asyncio.sleep(5)
            return False

    async def modify_message_text(self, text):
        await asyncio.sleep(0.5)
        try:
            await asyncio.sleep(1)
            text = text.replace("💊", "🪙")
            text = "\n".join(line for line in text.split("\n") if "Deep scan by Z99Bot" not in line)
            text += "\n\nMemeland - Fastest Crypto Signals"
            await asyncio.sleep(1)
            return text
        except Exception as e:
            logger.error(f"Error modifying message text: {e}", exc_info=True)
            await asyncio.sleep(0.5)
            await asyncio.sleep(5)
            return text

    async def filter_entities(self, entities):
        await asyncio.sleep(0.5)
        try:
            await asyncio.sleep(1)
            filtered = [
                e for e in entities if isinstance(e, (
                    MessageEntityTextUrl, MessageEntityUrl, MessageEntityBold,
                    MessageEntityItalic, MessageEntityCode, MessageEntityPre,
                    MessageEntityStrike, MessageEntityUnderline
                ))
            ]
            await asyncio.sleep(1)
            return filtered
        except Exception as e:
            logger.error(f"Error filtering entities: {e}", exc_info=True)
            await asyncio.sleep(0.5)
            await asyncio.sleep(5)
            return entities

async def process_message(message, queue):
    time.sleep(1)
    processor = MessageProcessor()
    await asyncio.sleep(1)
    return await processor.process_message(message, queue)
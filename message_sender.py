import asyncio
import random
import logging
from telethon import Button
from telethon.errors import FloodWaitError, ChatWriteForbiddenError, UserIsBlockedError
from telethon.tl.functions.messages import SendMessageRequest
from config import TARGET_CHANNEL_ID, SEND_DELAY_SECONDS, RETRY_ATTEMPTS, VIP_LINK

logger = logging.getLogger(__name__)

class MessageSender:
    def __init__(self, client, queue):
        self.client = client
        self.queue = queue
        self.target_channel_id = TARGET_CHANNEL_ID

    async def start(self):
        """شروع فرآیند ارسال پیام"""
        logger.info("Message sender started")
        while True:
            try:
                await self.send_message()
            except Exception as e:
                logger.error(f"Error in message sender loop: {e}", exc_info=True)

    async def send_message(self):
        """ارسال یک پیام از صف"""
        message_text, message_media, message_entities = await self.queue.get()
        attempts = 0
        send_successful = False

        # دکمه جدید
        buttons = [Button.url("Purchase VIP Analysis", VIP_LINK)]

        logger.info(f"Processing message from queue: {message_text[:30]}...")

        while attempts < RETRY_ATTEMPTS:
            try:
                await asyncio.sleep(SEND_DELAY_SECONDS + random.uniform(0, 1.5))

                if message_media:
                    await self.client.send_file(
                        self.target_channel_id,
                        message_media,
                        caption=message_text,
                        buttons=buttons,
                        entities=message_entities
                    )
                else:
                    sent_msg = await self.client(SendMessageRequest(
                        peer=self.target_channel_id,
                        message=message_text,
                        entities=message_entities,
                        no_webpage=True
                    ))
                    await asyncio.sleep(0.2)
                    await self.client.edit_message(
                        entity=self.target_channel_id,
                        message=sent_msg.updates[0].message,
                        buttons=buttons
                    )
                send_successful = True
                logger.info(f"Message sent successfully: {message_text[:30]}...")
                break

            except FloodWaitError as e:
                logger.warning(f"FloodWait: Sleeping for {e.seconds} seconds before retrying")
                await asyncio.sleep(e.seconds + random.uniform(1, 3))
                attempts += 1
            except (ChatWriteForbiddenError, UserIsBlockedError):
                logger.error("Write forbidden or user blocked. Skipping message")
                send_successful = True
                break
            except Exception as e:
                attempts += 1
                logger.error(f"Send attempt {attempts}/{RETRY_ATTEMPTS} failed: {e}", exc_info=True)
                await asyncio.sleep(attempts * 5)

        if not send_successful:
            logger.error(f"Failed to send message after {RETRY_ATTEMPTS} attempts: {message_text[:50]}...")

        self.queue.task_done()
        logger.debug("Queue task done")

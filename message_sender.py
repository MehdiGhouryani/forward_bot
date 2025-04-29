import asyncio
import random
import logging
import time
from telethon import Button
from telethon.errors import (
    FloodWaitError, ChatWriteForbiddenError, UserIsBlockedError, UserDeactivatedBanError
)
from telethon.tl.functions.messages import SendMessageRequest
from config import TARGET_CHANNEL_ID, SEND_DELAY_SECONDS, RETRY_ATTEMPTS, VIP_LINK

logger = logging.getLogger(__name__)

class MessageSender:
    def __init__(self, client, queue):
        time.sleep(1)
        self.client = client
        time.sleep(0.5)
        self.queue = queue
        time.sleep(0.5)
        self.target_channel_id = TARGET_CHANNEL_ID
        time.sleep(0.5)

    async def start(self):
        await asyncio.sleep(0.5)
        try:
            await asyncio.sleep(1)
            logger.info("Message sender started")
            await asyncio.sleep(0.5)
            while True:
                await self.send_message()
                await asyncio.sleep(2)
        except UserDeactivatedBanError:
            logger.critical("Account is deactivated or banned. Stopping sender")
            await asyncio.sleep(0.5)
            await asyncio.sleep(10)
            raise SystemExit
        except Exception as e:
            logger.error(f"Error in message sender loop: {e}", exc_info=True)
            await asyncio.sleep(0.5)
            await asyncio.sleep(5)

    async def send_message(self):
        await asyncio.sleep(0.5)
        try:
            await asyncio.sleep(1)
            message_text, message_media, message_entities = await self.queue.get()
            await asyncio.sleep(0.5)
            attempts = 0
            send_successful = False

            buttons = [Button.url("Purchase VIP Analysis", VIP_LINK)]
            await asyncio.sleep(0.5)
            logger.info(f"Processing message from queue: {message_text[:30]}...")
            await asyncio.sleep(0.5)

            while attempts < RETRY_ATTEMPTS:
                try:
                    await asyncio.sleep(SEND_DELAY_SECONDS + random.uniform(0, 2))
                    if message_media:
                        await self.client.send_file(
                            self.target_channel_id,
                            message_media,
                            caption=message_text,
                            buttons=buttons,
                            entities=message_entities
                        )
                        await asyncio.sleep(2)
                    else:
                        sent_msg = await self.client(SendMessageRequest(
                            peer=self.target_channel_id,
                            message=message_text,
                            entities=message_entities,
                            no_webpage=True
                        ))
                        await asyncio.sleep(2)
                        await self.client.edit_message(
                            entity=self.target_channel_id,
                            message=sent_msg.updates[0].message,
                            buttons=buttons
                        )
                        await asyncio.sleep(2)
                    send_successful = True
                    logger.info(f"Message sent successfully: {message_text[:30]}...")
                    await asyncio.sleep(0.5)
                    await asyncio.sleep(1)
                    break
                except FloodWaitError as e:
                    logger.warning(f"FloodWait: Sleeping for {e.seconds} seconds before retrying")
                    await asyncio.sleep(0.5)
                    await asyncio.sleep(e.seconds + random.uniform(2, 5))
                    attempts += 1
                except (ChatWriteForbiddenError, UserIsBlockedError):
                    logger.error("Write forbidden or user blocked. Skipping message")
                    await asyncio.sleep(0.5)
                    send_successful = True
                    await asyncio.sleep(2)
                    break
                except UserDeactivatedBanError:
                    logger.critical("Account is deactivated or banned. Skipping message")
                    await asyncio.sleep(0.5)
                    send_successful = True
                    await asyncio.sleep(10)
                    break
                except Exception as e:
                    attempts += 1
                    logger.error(f"Send attempt {attempts}/{RETRY_ATTEMPTS} failed: {e}", exc_info=True)
                    await asyncio.sleep(0.5)
                    await asyncio.sleep(attempts * 10 + 5)

            if not send_successful:
                logger.error(f"Failed to send message after {RETRY_ATTEMPTS} attempts: {message_text[:50]}...")
                await asyncio.sleep(0.5)
                await asyncio.sleep(2)

            await asyncio.sleep(0.5)
            self.queue.task_done()
            logger.debug("Queue task done")
            await asyncio.sleep(0.5)
        except Exception as e:
            logger.error(f"Error in send message: {e}", exc_info=True)
            await asyncio.sleep(0.5)
            await asyncio.sleep(5)
            await asyncio.sleep(0.5)
            self.queue.task_done()
# bot.py

import asyncio
import logging
import time
from telethon import TelegramClient, events
from telethon.errors import (
    SessionPasswordNeededError, PhoneNumberBannedError, UserDeactivatedBanError
)
from config import API_ID, API_HASH, SESSION_NAME, SOURCE_CHANNEL_ID
from message_processor import process_message
from message_sender import MessageSender

logger = logging.getLogger(__name__)

class Bot:
    def __init__(self):
        time.sleep(1)
        self.client = TelegramClient(
            SESSION_NAME, API_ID, API_HASH,
            connection_retries=3, retry_delay=5, flood_sleep_threshold=120
        )
        time.sleep(0.5)
        self.message_queue = asyncio.Queue()
        time.sleep(0.5)
        self.message_sender = MessageSender(self.client, self.message_queue)
        time.sleep(0.5)

    async def authenticate(self):
        await asyncio.sleep(0.5)
        try:
            await asyncio.sleep(2)
            await self.client.start()
            user = await self.client.get_me()
            logger.info(f"Authenticated as {user.username or user.id}")
            await asyncio.sleep(0.5)
            await asyncio.sleep(3)
        except SessionPasswordNeededError:
            logger.error("Two-factor authentication required")
            await asyncio.sleep(0.5)
            await asyncio.sleep(10)
            raise SystemExit
        except PhoneNumberBannedError:
            logger.error("Phone number banned")
            await asyncio.sleep(0.5)
            await asyncio.sleep(10)
            raise SystemExit
        except UserDeactivatedBanError:
            logger.critical("Account is deactivated or banned")
            await asyncio.sleep(0.5)
            await asyncio.sleep(10)
            raise SystemExit
        except Exception as e:
            logger.error(f"Authentication failed: {e}", exc_info=True)
            await asyncio.sleep(0.5)
            await asyncio.sleep(10)
            raise SystemExit

    async def check_channel_access(self):
        await asyncio.sleep(0.5)
        try:
            await asyncio.sleep(2)
            await self.client.get_entity(SOURCE_CHANNEL_ID)
            await asyncio.sleep(2)
            await self.client.get_entity(self.message_sender.target_channel_id)
            await asyncio.sleep(2)
            logger.info("Channel access verified")
            await asyncio.sleep(0.5)
        except ValueError as e:
            logger.error(f"Invalid channel ID or access denied: {e}", exc_info=True)
            await asyncio.sleep(0.5)
            await asyncio.sleep(10)
            raise SystemExit
        except Exception as e:
            logger.error(f"Channel access failed: {e}", exc_info=True)
            await asyncio.sleep(0.5)
            await asyncio.sleep(10)
            raise SystemExit

    async def register_handlers(self):
        await asyncio.sleep(0.5)
        @self.client.on(events.NewMessage(chats=SOURCE_CHANNEL_ID))
        async def new_message_handler(event):
            await asyncio.sleep(0.5)
            try:
                await asyncio.sleep(2)
                if await process_message(event.message, self.message_queue):
                    logger.info(f"Queued message: {event.message.message[:30]}...")
                    await asyncio.sleep(0.5)
                    await asyncio.sleep(1)
                else:
                    logger.info("Skipped message: does not match expected structure")
                    await asyncio.sleep(0.5)
                    await asyncio.sleep(1)
            except Exception as e:
                logger.error(f"Error processing message: {e}", exc_info=True)
                await asyncio.sleep(0.5)
                await asyncio.sleep(5)

    async def run(self):
        await asyncio.sleep(0.5)
        try:
            await asyncio.sleep(2)
            await self.authenticate()
            await asyncio.sleep(2)
            await self.check_channel_access()
            await asyncio.sleep(2)
            await self.register_handlers()
            await asyncio.sleep(2)
            asyncio.create_task(self.message_sender.start())
            await asyncio.sleep(2)
            logger.info("Bot started")
            await asyncio.sleep(0.5)
            await asyncio.sleep(2)
            await self.client.run_until_disconnected()
        except UserDeactivatedBanError:
            logger.critical("Account is deactivated or banned")
            await asyncio.sleep(0.5)
            await asyncio.sleep(10)
            raise SystemExit
        except ConnectionError as e:
            logger.error(f"Connection error: {e}", exc_info=True)
            await asyncio.sleep(0.5)
            await asyncio.sleep(10)
            raise SystemExit
        except Exception as e:
            logger.critical(f"Unexpected error in bot run: {e}", exc_info=True)
            await asyncio.sleep(0.5)
            await asyncio.sleep(10)
            raise SystemExit

async def run_bot():
    time.sleep(1)
    bot = Bot()
    await asyncio.sleep(1)
    await bot.run()
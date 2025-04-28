import asyncio
import logging
from telethon import TelegramClient, events
from telethon.errors import SessionPasswordNeededError, PhoneNumberBannedError
from config import API_ID, API_HASH, SESSION_NAME, SOURCE_CHANNEL_ID
from message_processor import process_message
from message_sender import MessageSender

logger = logging.getLogger(__name__)

class Bot:
    def __init__(self):
        self.client = TelegramClient(
            SESSION_NAME, API_ID, API_HASH,
            connection_retries=5, retry_delay=2, flood_sleep_threshold=60
        )
        self.message_queue = asyncio.Queue()
        self.message_sender = MessageSender(self.client, self.message_queue)

    async def authenticate(self):
        """احراز هویت ربات"""
        try:
            await self.client.start()
            user = await self.client.get_me()
            logger.info(f"Authenticated as {user.username or user.id}")
        except SessionPasswordNeededError:
            logger.error("Two-factor authentication required")
            raise SystemExit
        except PhoneNumberBannedError:
            logger.error("Phone number banned")
            raise SystemExit
        except Exception as e:
            logger.error(f"Authentication failed: {e}", exc_info=True)
            raise SystemExit

    async def check_channel_access(self):
        """بررسی دسترسی به کانال‌های منبع و مقصد"""
        try:
            await self.client.get_entity(SOURCE_CHANNEL_ID)
            await self.client.get_entity(self.message_sender.target_channel_id)
            logger.info("Channel access verified")
        except Exception as e:
            logger.error(f"Channel access failed: {e}", exc_info=True)
            raise SystemExit

    def register_handlers(self):
        """ثبت هندلر برای پیام‌های جدید"""
        @self.client.on(events.NewMessage(chats=SOURCE_CHANNEL_ID))
        async def new_message_handler(event):
            try:
                if await process_message(event.message, self.message_queue):
                    logger.info(f"Queued message: {event.message.message[:30]}...")
                else:
                    logger.info("Skipped message: does not match expected structure")
            except Exception as e:
                logger.error(f"Error processing message: {e}", exc_info=True)

    async def run(self):
        """اجرای ربات"""
        await self.authenticate()
        await self.check_channel_access()
        self.register_handlers()
        asyncio.create_task(self.message_sender.start())
        logger.info("Bot started")
        await self.client.run_until_disconnected()

async def run_bot():
    bot = Bot()
    await bot.run()

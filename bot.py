# bot.py
import asyncio
import logging
from telethon import TelegramClient, events
from telethon.errors import (
    SessionPasswordNeededError, PhoneNumberBannedError, UserDeactivatedBanError,
    AuthKeyError, NetworkMigrateError, FloodWaitError, PhoneCodeInvalidError,
    PhoneCodeExpiredError
)
from config import (
    API_ID, API_HASH, BOT_TOKEN, SESSION_NAME_USER,
    SOURCE_CHANNEL_ID, TARGET_CHANNEL_ID
)
from message_processor import MessageProcessor # وارد کردن کلاس
from message_sender import MessageSender

logger = logging.getLogger(__name__)

class Bot:
    def __init__(self):
        # --- کلاینت برای اکانت کاربری (خواندن از مبدا) ---
        self.user_client = TelegramClient(
            SESSION_NAME_USER, API_ID, API_HASH,
            connection_retries=5, retry_delay=10, # افزایش مقاومت در برابر خطاهای اتصال
            auto_reconnect=True,
            flood_sleep_threshold=180 # افزایش آستانه انتظار برای flood
        )

        # --- کلاینت برای ربات (ارسال به مقصد) ---
        # برای ربات، نیازی به session name نیست و از توکن استفاده می‌شود
        self.bot_client = TelegramClient(
            None, API_ID, API_HASH, # API ID/HASH همچنان لازم است حتی برای ربات
            connection_retries=5, retry_delay=10,
            auto_reconnect=True
        )
        # اتصال با توکن ربات در متد authenticate_bot انجام می‌شود

        self.message_queue = asyncio.Queue(maxsize=100) # صف با ظرفیت محدود
        self.processor = MessageProcessor() # ایجاد یک نمونه از پردازشگر
        self.sender = MessageSender(self.bot_client, self.message_queue) # ارسال کننده با کلاینت ربات

        self._shutdown_event = asyncio.Event()

    async def _authenticate_user(self):
        """احراز هویت برای کلاینت اکانت کاربری."""
        logger.info("Attempting to authenticate user client...")
        while not self._shutdown_event.is_set():
            try:
                if not await self.user_client.is_user_authorized():
                    logger.info("User client not authorized. Starting authentication flow...")
                    await self.user_client.connect()
                    phone_number = await self.user_client.get_input_entity('me') # برای شروع پروسه لاگین
                    await self.user_client.send_code_request(phone_number.phone)
                    try:
                        code = input("Please enter the authentication code sent to your Telegram: ")
                        await self.user_client.sign_in(phone_number.phone, code)
                        logger.info("User sign-in successful.")
                    except (PhoneCodeInvalidError, PhoneCodeExpiredError) as e:
                        logger.error(f"Invalid or expired code: {e}. Please restart the bot.")
                        raise SystemExit
                    except SessionPasswordNeededError:
                        password = input("Two-factor authentication password needed: ")
                        await self.user_client.sign_in(password=password)
                        logger.info("User sign-in with 2FA successful.")
                else:
                     # اگر قبلا لاگین شده، فقط متصل شود
                    await self.user_client.connect()

                user = await self.user_client.get_me()
                logger.info(f"User client authenticated successfully as {user.username or user.id}")
                return True # موفقیت آمیز بود، خروج از حلقه

            except PhoneNumberBannedError:
                logger.critical("User account phone number is banned! Cannot proceed.")
                raise SystemExit
            except UserDeactivatedBanError:
                logger.critical("User account is deactivated or banned! Cannot proceed.")
                raise SystemExit
            except AuthKeyError:
                logger.error("Invalid authentication key. Session file might be corrupt. Delete the session file and restart.")
                raise SystemExit
            except (ConnectionError, NetworkMigrateError, FloodWaitError, TimeoutError) as e:
                logger.warning(f"Authentication connection issue for user client: {e}. Retrying in 60 seconds...")
                await asyncio.sleep(60)
            except Exception as e:
                logger.critical(f"Unexpected error during user authentication: {e}", exc_info=True)
                raise SystemExit # خطای ناشناخته، خروج

        logger.warning("User authentication interrupted by shutdown signal.")
        return False


    async def _authenticate_bot(self):
        """احراز هویت برای کلاینت ربات با استفاده از توکن."""
        logger.info("Attempting to authenticate bot client...")
        while not self._shutdown_event.is_set():
            try:
                # اتصال با استفاده از توکن ربات
                await self.bot_client.start(bot_token=BOT_TOKEN)
                bot_info = await self.bot_client.get_me()
                logger.info(f"Bot client authenticated successfully as @{bot_info.username} (ID: {bot_info.id})")
                return True

            except AuthKeyError:
                 logger.error("Invalid bot token or API credentials for bot client.")
                 raise SystemExit
            except (ConnectionError, NetworkMigrateError, FloodWaitError, TimeoutError) as e:
                logger.warning(f"Authentication connection issue for bot client: {e}. Retrying in 60 seconds...")
                await asyncio.sleep(60)
            except Exception as e:
                logger.critical(f"Unexpected error during bot authentication: {e}", exc_info=True)
                raise SystemExit # خطای ناشناخته، خروج

        logger.warning("Bot authentication interrupted by shutdown signal.")
        return False

    async def _check_channel_access(self):
        """بررسی دسترسی به کانال‌های مبدا و مقصد."""
        logger.info("Checking channel access...")
        try:
            # بررسی کانال مبدا با کلاینت کاربر
            source_entity = await self.user_client.get_entity(SOURCE_CHANNEL_ID)
            logger.info(f"Source channel access verified: '{getattr(source_entity, 'title', 'N/A')}' ({source_entity.id})")

            # بررسی کانال مقصد با کلاینت ربات
            target_entity = await self.bot_client.get_entity(TARGET_CHANNEL_ID)
            logger.info(f"Target channel access verified: '{getattr(target_entity, 'title', 'N/A')}' ({target_entity.id})")

            # یک بررسی ساده برای اطمینان از اینکه ربات می‌تواند در کانال مقصد پیام بفرستد
            # await self.bot_client.send_message(target_entity, "Bot connected and ready.")
            # logger.info("Test message sent successfully to target channel.")

            return True
        except ValueError as e:
            logger.error(f"Invalid channel ID or username format: {e}", exc_info=True)
            return False
        except (ChatWriteForbiddenError, ChannelPrivateError, ChatAdminRequiredError) as e:
             logger.error(f"Bot does not have permission to send messages to target channel {TARGET_CHANNEL_ID}: {e}")
             return False
        except Exception as e:
            logger.error(f"Failed to verify channel access: {e}", exc_info=True)
            return False

    def _register_handlers(self):
        """ثبت event handler برای پیام‌های جدید در کانال مبدا."""
        @self.user_client.on(events.NewMessage(chats=SOURCE_CHANNEL_ID))
        async def new_message_handler(event):
            logger.debug(f"Received new message event (ID: {event.message.id}) from source channel.")
            try:
                processed_data = await self.processor.process(event.message)
                if processed_data:
                    try:
                        # قرار دادن پیام پردازش شده در صف بدون مسدود کردن handler
                        self.message_queue.put_nowait(processed_data)
                        logger.debug(f"Message ID {event.message.id} queued successfully.")
                    except asyncio.QueueFull:
                        logger.warning(f"Message queue is full! Skipping message ID {event.message.id}. Consider increasing queue size or send rate.")
                        # اینجا می‌توانید پیام را در جایی ذخیره کنید تا بعدا ارسال شود یا صرف نظر کنید
            except Exception as e:
                logger.error(f"Error in new_message_handler for message ID {event.message.id}: {e}", exc_info=True)
                await asyncio.sleep(2) # وقفه کوتاه در صورت خطا در handler

        logger.info(f"Registered handler for new messages in source channel {SOURCE_CHANNEL_ID}.")

    async def run(self):
        """اجرای اصلی ربات: احراز هویت، بررسی دسترسی، ثبت هندلر و اجرای کلاینت‌ها."""
        logger.info("Starting bot...")

        # 1. احراز هویت هر دو کلاینت
        if not await self._authenticate_user() or not await self._authenticate_bot():
             logger.critical("Authentication failed. Shutting down.")
             return # خروج اگر احراز هویت ناموفق بود

        # 2. بررسی دسترسی به کانال‌ها
        if not await self._check_channel_access():
            logger.critical("Channel access check failed. Shutting down.")
            await self.stop() # قطع اتصال کلاینت‌ها قبل از خروج
            return

        # 3. ثبت هندلرها
        self._register_handlers()

        # 4. شروع تسک ارسال کننده پیام
        sender_task = asyncio.create_task(self.sender.start())

        # 5. اجرای کلاینت کاربر تا زمان قطع شدن یا دریافت سیگنال توقف
        logger.info("Bot is running. Listening for new messages...")
        try:
            # منتظر ماندن برای سیگنال توقف یا قطع شدن کلاینت کاربر
            await asyncio.wait(
                [self._shutdown_event.wait(), self.user_client.run_until_disconnected()],
                return_when=asyncio.FIRST_COMPLETED
            )
        finally:
            logger.info("Shutdown signal received or user client disconnected.")
            # توقف تسک ارسال کننده و قطع اتصال کلاینت‌ها
            await self.stop()
            if sender_task and not sender_task.done():
                 sender_task.cancel()
                 await asyncio.wait([sender_task], timeout=5) # منتظر ماندن برای لغو تسک

    async def stop(self):
        """متوقف کردن ربات و قطع اتصال کلاینت‌ها."""
        logger.info("Stopping bot components...")
        self._shutdown_event.set() # ارسال سیگنال توقف

        if hasattr(self, 'sender') and self.sender:
            self.sender.stop()

        if self.bot_client and self.bot_client.is_connected():
            logger.info("Disconnecting bot client...")
            await self.bot_client.disconnect()
            logger.info("Bot client disconnected.")

        if self.user_client and self.user_client.is_connected():
            logger.info("Disconnecting user client...")
            await self.user_client.disconnect()
            logger.info("User client disconnected.")

        logger.info("Bot stopped.")

async def run_bot_main():
    """تابع اصلی برای اجرا و مدیریت توقف ربات."""
    bot = Bot()
    try:
        await bot.run()
    except (KeyboardInterrupt, SystemExit):
         logger.info("Shutdown initiated by user or system...")
    except Exception as e:
        logger.critical(f"Critical unhandled error in run_bot_main: {e}", exc_info=True)
    finally:
        if bot: # اطمینان از وجود شی bot قبل از فراخوانی stop
             await bot.stop()
# message_sender.py
import asyncio
import random
import logging
import time
from telethon import TelegramClient # برای type hinting
from telethon.errors import (
    FloodWaitError, ChatWriteForbiddenError, UserIsBlockedError,
    UserDeactivatedBanError, ChannelPrivateError, ChatAdminRequiredError,
    RPCError, BotMethodInvalidError
)
from config import (
    TARGET_CHANNEL_ID, SEND_DELAY_SECONDS, SEND_DELAY_JITTER,
    RETRY_ATTEMPTS, RETRY_DELAY_BASE
)

logger = logging.getLogger(__name__)

class MessageSender:
    """
    وظیفه ارسال پیام‌های پردازش شده از صف به کانال مقصد با استفاده از کلاینت ربات را دارد.
    """
    def __init__(self, bot_client: TelegramClient, queue: asyncio.Queue):
        self.bot_client = bot_client # کلاینت ربات برای ارسال
        self.queue = queue
        self.target_channel_id = TARGET_CHANNEL_ID
        self._running = True

    async def start(self):
        """شروع حلقه اصلی برای دریافت و ارسال پیام از صف."""
        logger.info("Message sender task started using Bot Token.")
        while self._running:
            try:
                # منتظر ماندن برای دریافت آیتم از صف
                processed_data = await self.queue.get()
                if processed_data is None: # سیگنال برای توقف (اختیاری)
                    self._running = False
                    continue

                logger.info(f"Dequeued message. Sending to target channel {self.target_channel_id}...")
                await self._send_with_retries(processed_data)

                # اعمال وقفه اصلی بین ارسال‌ها + مقدار تصادفی
                delay = SEND_DELAY_SECONDS + random.uniform(0, SEND_DELAY_JITTER)
                logger.debug(f"Main send delay: Sleeping for {delay:.2f} seconds.")
                await asyncio.sleep(delay)

            except UserDeactivatedBanError:
                logger.critical("Bot account is deactivated or banned. Stopping sender.")
                self._running = False
                # اینجا نیازی به SystemExit نیست، حلقه متوقف می‌شود
            except asyncio.CancelledError:
                logger.info("Message sender task cancelled.")
                self._running = False
            except Exception as e:
                logger.error(f"Unexpected error in message sender loop: {e}", exc_info=True)
                # وقفه طولانی‌تر در صورت خطای ناشناخته در حلقه اصلی
                await asyncio.sleep(60)
            finally:
                if 'processed_data' in locals() and processed_data is not None:
                    self.queue.task_done()

        logger.info("Message sender task finished.")

    def stop(self):
        """سیگنال توقف حلقه ارسال کننده."""
        logger.info("Stopping message sender task...")
        self._running = False
        # ارسال یک آیتم None به صف برای خروج سریع‌تر از انتظار get() (اختیاری)
        try:
            self.queue.put_nowait(None)
        except asyncio.QueueFull:
            pass # اگر صف پر بود مهم نیست

    async def _send_with_retries(self, data):
        """ارسال پیام با مدیریت خطا و تلاش مجدد."""
        attempts = 0
        send_successful = False

        text = data.get("text", "")
        media = data.get("media")
        entities = data.get("entities")
        buttons = data.get("buttons") # دریافت دکمه‌ها از داده‌های پردازش شده

        while attempts < RETRY_ATTEMPTS and self._running:
            try:
                if media:
                    await self.bot_client.send_file(
                        self.target_channel_id,
                        media,
                        caption=text,
                        buttons=buttons,
                        entities=entities # اطمینان از ارسال entities برای کپشن
                    )
                else:
                    await self.bot_client.send_message(
                        self.target_channel_id,
                        text,
                        buttons=buttons,
                        entities=entities,
                        link_preview=False # معمولا برای این نوع ربات‌ها بهتر است خاموش باشد
                    )

                send_successful = True
                logger.info(f"Message sent successfully to {self.target_channel_id}.")
                break # خروج از حلقه تلاش مجدد

            except FloodWaitError as e:
                attempts += 1
                wait_time = e.seconds + random.uniform(2, 5)
                logger.warning(f"FloodWait: Attempt {attempts}/{RETRY_ATTEMPTS}. Sleeping for {wait_time:.2f} seconds.")
                if attempts >= RETRY_ATTEMPTS:
                    logger.error(f"FloodWait persisted after {RETRY_ATTEMPTS} attempts. Giving up on this message.")
                    break
                await asyncio.sleep(wait_time)

            except (ChatWriteForbiddenError, ChannelPrivateError, ChatAdminRequiredError) as e:
                logger.error(f"Cannot write to target channel {self.target_channel_id}: {e}. Check bot permissions. Skipping message.")
                # این خطاها معمولا با تلاش مجدد حل نمی‌شوند
                break
            except UserIsBlockedError:
                 logger.warning(f"Bot was blocked by the target channel/user {self.target_channel_id}. Skipping message.")
                 # این خطا هم با تلاش مجدد حل نمی‌شود
                 break
            except BotMethodInvalidError as e:
                logger.error(f"Bot method invalid error: {e}. Possibly an issue with parameters or bot permissions. Skipping message.")
                break
            except UserDeactivatedBanError:
                logger.critical("Bot account is deactivated or banned during send attempt. Stopping sender.")
                self.stop() # توقف کامل سرویس ارسال
                break
            except RPCError as e:
                attempts += 1
                logger.error(f"Telegram RPCError on send attempt {attempts}/{RETRY_ATTEMPTS}: {e}", exc_info=False) # لاگ کوتاه بدون stacktrace
                if attempts >= RETRY_ATTEMPTS:
                    logger.error(f"Failed to send message after {RETRY_ATTEMPTS} RPCError attempts. Giving up.")
                    break
                # وقفه تصاعدی برای خطاهای عمومی RPC
                retry_delay = RETRY_DELAY_BASE * attempts + random.uniform(0, 5)
                logger.info(f"Waiting {retry_delay:.2f} seconds before retry.")
                await asyncio.sleep(retry_delay)
            except Exception as e:
                attempts += 1
                logger.error(f"Unexpected error on send attempt {attempts}/{RETRY_ATTEMPTS}: {e}", exc_info=True)
                if attempts >= RETRY_ATTEMPTS:
                    logger.error(f"Failed to send message after {RETRY_ATTEMPTS} unexpected error attempts. Giving up.")
                    break
                retry_delay = RETRY_DELAY_BASE * attempts + random.uniform(0, 5)
                logger.info(f"Waiting {retry_delay:.2f} seconds before retry.")
                await asyncio.sleep(retry_delay)

        if not send_successful and self._running:
            logger.error(f"Failed to send message permanently after {RETRY_ATTEMPTS} attempts: {text[:50]}...")
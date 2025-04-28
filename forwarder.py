
from telethon.tl.types import (
    MessageEntityTextUrl,
    MessageEntityUrl,
    MessageEntityBold,
    MessageEntityItalic,
    MessageEntityCode,
    MessageEntityPre,
    MessageEntityStrike,
    MessageEntityUnderline,
)

import asyncio
import time
import random
import logging
from telethon import TelegramClient, events, Button
from telethon.errors import FloodWaitError, ChatWriteForbiddenError, UserIsBlockedError, SessionPasswordNeededError, PhoneNumberBannedError
from config import *

logging.basicConfig(filename=LOG_FILE, level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s', encoding='utf-8')
logging.getLogger('telethon').setLevel(logging.WARNING)

client = TelegramClient(SESSION_NAME, API_ID, API_HASH, connection_retries=5, retry_delay=2, flood_sleep_threshold=60)

message_queue = asyncio.Queue()
message_counter = 0
last_reset_time = time.monotonic()
skipped_messages = []

async def authenticate():
    try:
        await client.start()
        user = await client.get_me()
        logging.info(f"Authenticated as {user.username or user.id}")
    except SessionPasswordNeededError:
        logging.error("Two-factor authentication required")
        raise SystemExit
    except PhoneNumberBannedError:
        logging.error("Phone number banned")
        raise SystemExit
    except Exception as e:
        logging.error(f"Authentication failed: {e}")
        raise SystemExit

async def check_channel_access():
    try:
        await client.get_entity(SOURCE_CHANNEL_ID)
        await client.get_entity(TARGET_CHANNEL_ID)
        logging.info("Channel access verified")
    except Exception as e:
        logging.error(f"Channel access failed: {e}")
        raise SystemExit

@client.on(events.NewMessage(chats=SOURCE_CHANNEL_ID))
async def new_message_handler(event):
    global message_counter, last_reset_time
    message = event.message
    message_text = message.message or ""
    message_media = message.media
    message_entities = message.entities or []
    current_time = time.monotonic()

    # فقط پیام‌هایی با ساختار 💊 در ابتدای پیام فوروارد می‌شن
    if not message_text.strip().startswith("💊"):
        logging.info("Skipped message: does not match expected structure")
        return

    if current_time - last_reset_time >= 60:
        message_counter = 0
        last_reset_time = current_time
        for msg in skipped_messages:
            await message_queue.put(msg)
        skipped_messages.clear()

    if message_counter < MAX_MESSAGES_PER_MINUTE:
        await asyncio.sleep(QUEUE_DELAY_SECONDS)
        await message_queue.put((message_text, message_media, message_entities))
        message_counter += 1
        logging.info(f"Queued message: {message_text[:30]}...")
    else:
        skipped_messages.append((message_text, message_media, message_entities))
        logging.warning("Rate limit reached, message skipped")

async def message_sender():
    """Consumes messages from the queue and sends them to the target channel with retries."""
    while True:
        # گرفتن پیام، مدیا و انتیتی‌ها از صف
        message_text, message_media, message_entities = await message_queue.get()
        send_successful = False
        attempts = 0
        
        # فیلتر کردن و انتخاب فقط انتیتی‌های مربوط به فرمت‌بندی و لینک‌ها
        relevant_entities = []
        if message_entities: # بررسی وجود انتیتی
            for e in message_entities:
                # انتخاب انواع انتیتی‌های رایج و مرتبط
                if isinstance(e, (
                    MessageEntityTextUrl, # لینک‌های درون متنی
                    MessageEntityUrl,     # لینک‌های تشخیص داده شده
                    MessageEntityBold,    # متن ضخیم
                    MessageEntityItalic,  # متن کج
                    MessageEntityCode,    # کد درون خطی
                    MessageEntityPre,     # بلوک کد
                    MessageEntityStrike,  # خط خورده
                    MessageEntityUnderline, # زیر خط دار
                    # اگر می‌خواهید منشن‌ها یا هشتگ‌ها را هم حفظ کنید، این خطوط را فعال کنید:
                    # MessageEntityMention,
                    # MessageEntityHashtag,
                )):
                    relevant_entities.append(e)
        
        # استفاده از لیست فیلتر شده انتیتی‌ها
        all_entities_to_send = relevant_entities
        
        # تعریف دکمه شیشه‌ای با متن جدید و لینک VIP_LINK
        buttons = [Button.url("📉 Get VIP Crypto Analysis 📈", VIP_LINK)]

        logging.info(f"Processing message from queue: {message_text[:30]}...")

        while attempts < RETRY_ATTEMPTS:
            try:
                await asyncio.sleep(SEND_DELAY_SECONDS + random.uniform(0, 1.5))

                if message_media:
                    # ارسال پیام همراه با مدیا، دکمه‌ها و انتیتی‌ها
                    await client.send_file(
                        TARGET_CHANNEL_ID,
                        message_media,
                        caption=message_text,
                        buttons=buttons, # اضافه کردن لیست دکمه‌ها
                        entities=all_entities_to_send # استفاده از لیست فیلتر شده انتیتی‌ها
                    )
                else:
                    from telethon.tl.functions.messages import SendMessageRequest
                
                    # ارسال پیام بدون دکمه
                    sent_msg = await client(SendMessageRequest(
                        peer=TARGET_CHANNEL_ID,
                        message=message_text,
                        entities=all_entities_to_send,
                        no_webpage=True
                    ))
                
                    # یک مکث کوتاه برای اطمینان از ثبت پیام در سرور
                    await asyncio.sleep(0.2)
                
                    # اضافه کردن دکمه‌ها با ویرایش پیام
                    await client.edit_message(
                        entity=TARGET_CHANNEL_ID,
                        message=sent_msg.updates[0].messag,
                        buttons=buttons
                    )               
                send_successful = True
                logging.info(f"Message sent successfully: {message_text[:30]}...")
                break


            except FloodWaitError as e:
                logging.warning(f"FloodWait: Sleeping for {e.seconds} seconds before retrying.")
                await asyncio.sleep(e.seconds + random.uniform(1, 3))
                attempts += 1
            except (ChatWriteForbiddenError, UserIsBlockedError):
                logging.error("Write forbidden or user blocked. Skipping message.")
                send_successful = True
                break
            except Exception as e:
                attempts += 1
                logging.error(f"Send attempt {attempts}/{RETRY_ATTEMPTS} failed for message '{message_text[:30]}...': {e}")
                await asyncio.sleep(attempts * 5)

        if not send_successful:
            logging.error(f"Failed to send message after {RETRY_ATTEMPTS} attempts: {message_text[:50]}...")

        message_queue.task_done()
        logging.debug("Queue task done.")


async def run_bot():
    await authenticate()
    await check_channel_access()
    asyncio.create_task(message_sender())
    await client.run_until_disconnected()
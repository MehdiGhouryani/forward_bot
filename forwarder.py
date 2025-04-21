
# forwarder.py

import asyncio
import time
import random
import logging
from telethon import TelegramClient, events, Button
from telethon.errors import FloodWaitError, ChatWriteForbiddenError, UserIsBlockedError, SessionPasswordNeededError, PhoneNumberBannedError
from telethon.types import MessageEntityTextUrl
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
    while True:
        message_text, message_media, message_entities = await message_queue.get()
        send_successful = False
        attempts = 0
        filtered_entities = [e for e in message_entities if isinstance(e, MessageEntityTextUrl)]
        buttons = [Button.url("Get VIP Crypto Analysis", VIP_LINK)]

        while not send_successful and attempts < RETRY_ATTEMPTS:
            try:
                await asyncio.sleep(SEND_DELAY_SECONDS + random.uniform(0, 1.5))
                if message_media:
                    try:
                        await client.send_file(
                            TARGET_CHANNEL_ID,
                            message_media,
                            caption=message_text,
                            parse_mode='md',
                            buttons=buttons,
                            entities=filtered_entities
                        )
                    except Exception:
                        await client.send_file(
                            TARGET_CHANNEL_ID,
                            message_media,

                            caption=message_text,
                            parse_mode='md',
                            buttons=buttons
                        )
                else:
                    try:
                        await client.send_message(
                            TARGET_CHANNEL_ID,
                            message_text,
                            parse_mode='md',
                            buttons=buttons,
                            entities=filtered_entities
                        )
                    except Exception:
                        await client.send_message(
                            TARGET_CHANNEL_ID,
                            message_text,
                            parse_mode='md',
                            buttons=buttons
                        )
                send_successful = True
            except FloodWaitError as e:
                await asyncio.sleep(e.seconds + random.uniform(1, 3))
            except (ChatWriteForbiddenError, UserIsBlockedError):
                logging.error("Write forbidden or user blocked")
                send_successful = True
            except Exception as e:
                attempts += 1
                logging.error(f"Send attempt {attempts} failed: {e}")
                if attempts >= RETRY_ATTEMPTS:
                    try:
                        await client.send_message(TARGET_CHANNEL_ID, message_text, buttons=buttons)
                        send_successful = True
                    except Exception as e:
                        logging.error(f"Final send failed: {e}")
                        send_successful = True
        message_queue.task_done()

async def run_bot():
    await authenticate()
    await check_channel_access()
    asyncio.create_task(message_sender())
    await client.run_until_disconnected()
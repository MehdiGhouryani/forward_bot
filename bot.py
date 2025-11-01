# bot.py
import logging
import asyncio
import time
import random
import traceback
import os
from telethon import TelegramClient, events
from telethon.errors import (
    FloodWaitError, ChatWriteForbiddenError, UserIsBlockedError,
    SessionPasswordNeededError, PhoneNumberBannedError, 
    ChannelInvalidError, ChannelPrivateError, MessageTooLongError
)
from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler
from telegram.error import TelegramError, TimedOut, BadRequest, NetworkError
from config import *
from database import init_db, load_settings, register_message_in_votes
from parser import transform_message, entities_to_html
from utils import MessageRateLimiter, SendRateLimiter, skipped_messages_lock
from handlers import set_secondary, stop_secondary, status, handle_vote

client = TelegramClient(
    SESSION_NAME, API_ID, API_HASH,
    connection_retries=3, retry_delay=8, flood_sleep_threshold=120
)

message_queue = asyncio.Queue(maxsize=100)

recent_messages = {}  # کلید: هش پیام، مقدار: زمان ثبت (monotonic time)
RECENT_MESSAGE_TIMEOUT = 60  # پیام‌ها تا 60 ثانیه در حافظه نگه داشته می‌شوند

if not isinstance(MAX_MESSAGES_PER_MINUTE, int) or MAX_MESSAGES_PER_MINUTE <= 0:
    logging.error("MAX_MESSAGES_PER_MINUTE must be a positive integer")
    raise ValueError("Invalid MAX_MESSAGES_PER_MINUTE")
receive_rate_limiter = MessageRateLimiter(MAX_MESSAGES_PER_MINUTE)
send_rate_limiter = SendRateLimiter(MAX_MESSAGES_PER_MINUTE)

async def shutdown():
    """ربات را به آرامی متوقف کرده و اتصال کلاینت را قطع می‌کند."""
    logging.info("Shutting down bot...")
    try:
        if client.is_connected():
            await client.disconnect()
        logging.info("Bot stopped gracefully")
    except Exception as e:
        logging.error(f"Error during shutdown: {e}\n{traceback.format_exc()}")

async def authenticate():
    """کلاینت تلتون را احراز هویت می‌کند و از وجود فایل سشن اطمینان حاصل می‌کند."""
    logging.info("Starting authentication process")
    session_file = f"{SESSION_NAME}.session"
    
    if os.path.exists(session_file):
        logging.info(f"Session file found: {session_file}")
        try:
            with open(session_file, 'a'):
                pass
            logging.info(f"Session file {session_file} is writable")
        except PermissionError:
            logging.error(f"Session file {session_file} is not writable")
            raise SystemExit
    
    for attempt in range(3):
        logging.info(f"Authentication attempt {attempt + 1}/3")
        try:
            await asyncio.wait_for(client.start(), timeout=60)
            user = await client.get_me()
            logging.info(f"Authenticated successfully as {user.username or user.id}")
            return
        except asyncio.TimeoutError:
            logging.error("Authentication timed out after 60 seconds")
            if attempt < 2:
                logging.info(f"Retrying after 5 seconds...")
                await asyncio.sleep(5)
            else:
                logging.error("All authentication attempts timed out. Check network or API credentials.")
                raise SystemExit
        except Exception as e:
            logging.error(f"Authentication failed: {e}")
            if "AUTH_KEY_UNREGISTERED" in str(e):
                logging.error("Session is invalid (AUTH_KEY_UNREGISTERED). Consider using a new session.")
                raise SystemExit
            if "SessionPasswordNeeded" in str(e):
                logging.error("Two-factor authentication required. Please disable 2FA or provide password.")
                raise SystemExit
            if "PhoneNumberBanned" in str(e):
                logging.error("Phone number is banned by Telegram.")
                raise SystemExit
            if attempt < 2:
                logging.info(f"Retrying after 5 seconds...")
                await asyncio.sleep(5)
            else:
                logging.error("All authentication attempts failed. Check logs for details.")
                raise SystemExit

async def check_channel_access():
    """دسترسی به کانال‌های منبع، مقصد و ثانویه را بررسی می‌کند."""
    try:
        source = await client.get_entity(SOURCE_CHANNEL_ID)
        logging.info(f"Source channel access verified: {SOURCE_CHANNEL_ID}")
        target = await client.get_entity(TARGET_CHANNEL_ID)
        logging.info(f"Target channel access verified: {TARGET_CHANNEL_ID}")
        try:
            secondary = await client.get_entity(SECONDARY_CHANNEL_ID)
            logging.info(f"Secondary channel access verified: {SECONDARY_CHANNEL_ID}")
        except (ChannelInvalidError, ChannelPrivateError) as e:
            logging.warning(f"Cannot access secondary channel {SECONDARY_CHANNEL_ID}: {e}. Continuing without secondary channel.")
        except Exception as e:
            logging.warning(f"Unexpected error accessing secondary channel {SECONDARY_CHANNEL_ID}: {e}\n{traceback.format_exc()}. Continuing without secondary channel.")
    except ChannelInvalidError as e:
        logging.error(f"Invalid channel ID: {e}. Check channel IDs")
        raise SystemExit
    except ChannelPrivateError as e:
        logging.error(f"Channel is private or inaccessible: {e}. Ensure bot is a member")
        raise SystemExit
    except Exception as e:
        logging.error(f"Channel access failed: {e}\n{traceback.format_exc()}")
        raise SystemExit

@client.on(events.NewMessage(chats=SOURCE_CHANNEL_ID))
async def new_message_handler(event):
    """هندلر پیام‌های جدید از کانال منبع تلتون."""
    if not isinstance(event, events.NewMessage.Event):
        logging.info("Skipped non-message update")
        return

    message = event.message
    message_text = message.message or ""
    message_media = message.media
    message_entities = message.entities or []

    # تغییر شناساگر به 🥞
    if not message_text.strip().startswith("🥞") or len(message_text.strip()) <= 1:
        logging.info("Skipped message: empty or not matching 🥞 trigger")
        return

    message_hash = hash(message_text)
    current_time = time.monotonic()
    if message_hash in recent_messages:
        logging.info(f"Skipped duplicate message: {message_text[:30]}...")
        return

    recent_messages[message_hash] = current_time
    expired_messages = [
        msg_hash for msg_hash, ts in recent_messages.items()
        if current_time - ts > RECENT_MESSAGE_TIMEOUT
    ]
    for msg_hash in expired_messages:
        recent_messages.pop(msg_hash, None)
    logging.debug(f"Cleaned up {len(expired_messages)} expired messages from recent_messages")

    logging.info(f"Received new message: {message_text[:30]}...")
    if receive_rate_limiter.can_send():
        if message_queue.qsize() > 0:
            await asyncio.sleep(QUEUE_DELAY_SECONDS + random.uniform(0, 2))
        
        # دریافت token_address از تابع تبدیل
        new_message, new_entities, chart_url, th_pairs, token_address = transform_message(message_text, message_entities)
        
        if new_message:
            # افزودن token_address به صف پیام
            await message_queue.put((new_message, new_entities, chart_url, th_pairs, token_address))
            receive_rate_limiter.increment()
            logging.info(f"Queued message: {new_message[:30]}...")
        else:
            logging.warning("Transformed message is None, skipping...")
    else:
        await receive_rate_limiter.add_skipped((message_text, message_media, message_entities))
        logging.warning(f"Rate limit reached, message skipped: {message_text[:30]}...")

async def send_message_to_channel(bot, message, entities, chart_url, th_pairs, chat_id, token_address):
    """پیام فرمت‌شده را به همراه دکمه‌ها به کانال مقصد ارسال می‌کند."""
    try:
        text, parse_mode = entities_to_html(entities, message)
        
        keyboard = [
            [InlineKeyboardButton("📈 مشاهده نمودار (Dex)", url=f"https://dexscreener.com/bsc/{token_address}")],
            [InlineKeyboardButton("🔍 بررسی در اکسیوم (Axiom)", url=f"https://axiom.app/contract/{token_address}")],
            [InlineKeyboardButton("💰 ترید کن سولانا هدیه بگیر", url=GIFT)],
            [InlineKeyboardButton("📚 آموزش آکسیوم", url=AXIOM_LINK), InlineKeyboardButton("❓ سوالتون اینجا بپرسید", url=SUPPORT_LINK)],
            [InlineKeyboardButton("🟢 (0)", callback_data="vote_green"),
             InlineKeyboardButton("🔴 (0)", callback_data="vote_red")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        sent_message = await bot.send_message(
            chat_id=chat_id,
            text=text,
            parse_mode=parse_mode,
            reply_markup=reply_markup,
            disable_web_page_preview=True
        )
        logging.info(f"Message sent successfully to {chat_id}. Message ID: {sent_message.message_id}, Text: {text[:30]}...")

        await register_message_in_votes(sent_message.message_id, chat_id, token_address)

        return sent_message.message_id
    except (TimedOut, NetworkError):
        logging.warning(f"Request timed out for chat_id {chat_id}. Retrying after delay...")
        raise
    except BadRequest as e:
        if "entity" in str(e).lower():
            logging.error(f"BadRequest (likely HTML/Entity error) for chat_id {chat_id}: {e}. Message: {text[:100]}")
        else:
            logging.error(f"BadRequest error for chat_id {chat_id}: {e}")
        raise
    except TelegramError as e:
        logging.error(f"TelegramError for chat_id {chat_id}: {e}")
        raise
    except Exception as e:
        logging.error(f"Error in send_message_to_channel for chat_id {chat_id}: {e}\n{traceback.format_exc()}")
        raise

async def message_sender():
    """وظیفه پس‌زمینه که پیام‌ها را از صف برداشته و ارسال می‌کند."""
    bot = Bot(token=BOT_TOKEN)
    sent_messages = set()
    while True:
        try:
            message, entities, chart_url, th_pairs, token_address = await message_queue.get()
            message_hash = hash(message)
            logging.info(f"Processing message: {message[:30]}...")

            if message_hash in sent_messages:
                logging.debug(f"Message already sent, skipping: {message[:30]}...")
                message_queue.task_done()
                continue

            if send_rate_limiter.can_send():
                attempts = 0
                while attempts < RETRY_ATTEMPTS:
                    try:
                        delay = SEND_DELAY_SECONDS + random.uniform(0, SEND_DELAY_JITTER) + (message_queue.qsize() * 0.5)
                        await asyncio.sleep(delay)
                        
                        message_id = await send_message_to_channel(
                            bot, message, entities, chart_url, th_pairs, TARGET_CHANNEL_ID, token_address
                        )
                        send_rate_limiter.increment()
                        logging.info(f"Message marked as sent to main channel, hash: {message_hash}, Message ID: {message_id}")

                        settings = await load_settings()
                        current_time = int(time.time())
                        if (settings['start_time'] <= current_time <= settings['expiry_time']):
                            try:
                                secondary_message_id = await send_message_to_channel(
                                    bot, message, entities, chart_url, th_pairs, settings['secondary_channel_id'], token_address
                                )
                                send_rate_limiter.increment()
                                logging.info(f"Message sent to secondary channel, hash: {message_hash}, Message ID: {secondary_message_id}")
                            except Exception as e:
                                logging.error(f"Failed to send to secondary channel: {e}. Continuing with main channel.")

                        sent_messages.add(message_hash)
                        break
                    except (TimedOut, TelegramError, NetworkError) as e:
                        attempts += 1
                        wait_time = attempts * RETRY_DELAY_BASE + random.uniform(0, 5)
                        logging.warning(f"Retrying send attempt {attempts}/{RETRY_ATTEMPTS} after {wait_time} seconds due to error: {e}")
                        await asyncio.sleep(wait_time)
                    except BadRequest as e:
                        logging.error(f"Failed to send message (BadRequest): {e}")
                        break
                    except Exception as e:
                        logging.error(f"Failed to send message: {e}")
                        break
                if attempts >= RETRY_ATTEMPTS:
                    logging.error(f"Failed to send message after {RETRY_ATTEMPTS} attempts: {message[:50]}...")
            else:
                logging.warning(f"Send rate limit reached, skipping message: {message[:30]}...")

            message_queue.task_done()
        except Exception as e:
            logging.error(f"Error in message_sender: {e}\n{traceback.format_exc()}")
            message_queue.task_done()
            await asyncio.sleep(10 + random.uniform(0, 5))

async def run_bot():
    """تابع اصلی اجرای ربات، شامل راه‌اندازی کلاینت تلتون و اپلیکیشن PTB."""
    try:
        await init_db(SECONDARY_CHANNEL_ID)
        
        await authenticate()
        await asyncio.sleep(random.uniform(1, 3))
        logging.info("Step 2: Checking channel access")
        await check_channel_access()
        await asyncio.sleep(random.uniform(1, 3))
        
        logging.info("Step 3: Setting up admin command handlers")
        application = Application.builder().token(BOT_TOKEN).build()
        application.add_handler(CommandHandler("set_secondary", set_secondary))
        application.add_handler(CommandHandler("stop_secondary", stop_secondary))
        application.add_handler(CommandHandler("status", status))
        application.add_handler(CallbackQueryHandler(handle_vote, pattern="^vote_"))
        
        logging.info("Step 4: Setting up event handler")
        client.add_event_handler(new_message_handler)
        logging.info("Step 5: Starting message sender task")
        sender_task = asyncio.create_task(message_sender())
        
        logging.info("Step 6: Starting application and client")
        loop = asyncio.get_event_loop()
        try:
            await application.initialize()
            await application.start()
            logging.debug("Starting polling with drop_pending_updates=True")
            await application.updater.start_polling(drop_pending_updates=True)
            logging.info("Application polling started")
            logging.debug("Polling loop running, waiting for updates")
            
            await client.run_until_disconnected()
        finally:
            if application.updater.running:
                logging.debug("Stopping updater polling")
                await application.updater.stop()
            logging.debug("Stopping application")
            await application.stop()
            logging.debug("Shutting down application")
            await application.shutdown()
            logging.info("Application stopped")
            if 'sender_task' in locals() and not sender_task.done():
                sender_task.cancel()
    except Exception as e:
        logging.error(f"Disconnected: {e}\n{traceback.format_exc()}")
    finally:
        await shutdown()
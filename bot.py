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

# لاگر حرفه‌ای مخصوص این ماژول
logger = logging.getLogger(__name__)

client = TelegramClient(
    SESSION_NAME, API_ID, API_HASH,
    connection_retries=3, retry_delay=8, flood_sleep_threshold=120
)

# صف پیام‌ها با حداکثر ظرفیت 100
message_queue = asyncio.Queue(maxsize=100)

# حافظه موقت برای جلوگیری از پیام‌های تکراری
recent_messages = {}  # کلید: هش پیام، مقدار: زمان ثبت (monotonic time)
RECENT_MESSAGE_TIMEOUT = 60  # پیام‌ها تا 60 ثانیه در حافظه نگه داشته می‌شوند

if not isinstance(MAX_MESSAGES_PER_MINUTE, int) or MAX_MESSAGES_PER_MINUTE <= 0:
    logger.error("MAX_MESSAGES_PER_MINUTE must be a positive integer")
    raise ValueError("Invalid MAX_MESSAGES_PER_MINUTE")
receive_rate_limiter = MessageRateLimiter(MAX_MESSAGES_PER_MINUTE)
send_rate_limiter = SendRateLimiter(MAX_MESSAGES_PER_MINUTE)


async def shutdown():
    """ربات را به آرامی متوقف کرده و اتصال کلاینت را قطع می‌کند."""
    logger.info("Shutting down bot...")
    try:
        if client.is_connected():
            await client.disconnect()
        logger.info("Bot stopped gracefully")
    except Exception as e:
        logger.error(f"Error during shutdown: {e}\n{traceback.format_exc()}")


async def authenticate():
    """کلاینت تلتون را احراز هویت می‌کند و از وجود فایل سشن اطمینان حاصل می‌کند."""
    logger.info("Starting authentication process")
    session_file = f"{SESSION_NAME}.session"
    
    if os.path.exists(session_file):
        logger.info(f"Session file found: {session_file}")
        try:
            with open(session_file, 'a'):
                pass
            logger.info(f"Session file {session_file} is writable")
        except PermissionError:
            logger.error(f"Session file {session_file} is not writable")
            raise SystemExit
    
    for attempt in range(3):
        logger.info(f"Authentication attempt {attempt + 1}/3")
        try:
            await asyncio.wait_for(client.start(), timeout=60)
            user = await client.get_me()
            logger.info(f"Authenticated successfully as {user.username or user.id}")
            return
        except asyncio.TimeoutError:
            logger.error("Authentication timed out after 60 seconds")
            if attempt < 2:
                logger.info(f"Retrying after 5 seconds...")
                await asyncio.sleep(5)
            else:
                logger.error("All authentication attempts timed out. Check network or API credentials.")
                raise SystemExit
        except Exception as e:
            logger.error(f"Authentication failed: {e}")
            if "AUTH_KEY_UNREGISTERED" in str(e):
                logger.error("Session is invalid (AUTH_KEY_UNREGISTERED). Consider using a new session.")
                raise SystemExit
            if "SessionPasswordNeeded" in str(e):
                logger.error("Two-factor authentication required. Please disable 2FA or provide password.")
                raise SystemExit
            if "PhoneNumberBanned" in str(e):
                logger.error("Phone number is banned by Telegram.")
                raise SystemExit
            if attempt < 2:
                logger.info(f"Retrying after 5 seconds...")
                await asyncio.sleep(5)
            else:
                logger.error("All authentication attempts failed. Check logs for details.")
                raise SystemExit


async def check_channel_access():
    """دسترسی به کانال‌های منبع، مقصد و ثانویه را بررسی می‌کند."""
    try:
        source = await client.get_entity(SOURCE_CHANNEL_ID)
        logger.info(f"Source channel access verified: {SOURCE_CHANNEL_ID}")
        target = await client.get_entity(TARGET_CHANNEL_ID)
        logger.info(f"Target channel access verified: {TARGET_CHANNEL_ID}")
        try:
            secondary = await client.get_entity(SECONDARY_CHANNEL_ID)
            logger.info(f"Secondary channel access verified: {SECONDARY_CHANNEL_ID}")
        except (ChannelInvalidError, ChannelPrivateError) as e:
            logger.warning(f"Cannot access secondary channel {SECONDARY_CHANNEL_ID}: {e}. Continuing without secondary channel.")
        except Exception as e:
            logger.warning(f"Unexpected error accessing secondary channel {SECONDARY_CHANNEL_ID}: {e}\n{traceback.format_exc()}. Continuing without secondary channel.")
    except ChannelInvalidError as e:
        logger.error(f"Invalid channel ID: {e}. Check channel IDs")
        raise SystemExit
    except ChannelPrivateError as e:
        logger.error(f"Channel is private or inaccessible: {e}. Ensure bot is a member")
        raise SystemExit
    except Exception as e:
        logger.error(f"Channel access failed: {e}\n{traceback.format_exc()}")
        raise SystemExit


@client.on(events.NewMessage(chats=SOURCE_CHANNEL_ID))
async def new_message_handler(event):
    """هندلر پیام‌های جدید از کانال منبع تلتون."""
    if not isinstance(event, events.NewMessage.Event):
        logger.debug("Skipped non-message update")
        return

    message = event.message
    message_text = message.message or ""
    message_media = message.media
    message_entities = message.entities or []

    # تغییر شناساگر به 🥞
    if not message_text.strip().startswith("🥞") or len(message_text.strip()) <= 1:
        logger.info("Skipped message: empty or not matching 🥞 trigger")
        return

    message_hash = hash(message_text)
    current_time = time.monotonic()
    if message_hash in recent_messages:
        logger.info(f"Skipped duplicate message: {message_text[:30]}...")
        return

    recent_messages[message_hash] = current_time
    expired_messages = [
        msg_hash for msg_hash, ts in recent_messages.items()
        if current_time - ts > RECENT_MESSAGE_TIMEOUT
    ]
    for msg_hash in expired_messages:
        recent_messages.pop(msg_hash, None)
    logger.debug(f"Cleaned up {len(expired_messages)} expired messages from recent_messages")

    logger.info(f"Received new message: {message_text[:30]}...")
    logger.debug(f"Full message received from source: {message_text}")
    
    if receive_rate_limiter.can_send():
        if message_queue.qsize() > 0:
            delay = QUEUE_DELAY_SECONDS + random.uniform(0, 2)
            logger.debug(f"Queue is not empty, applying delay: {delay:.2f}s")
            await asyncio.sleep(delay)
        
        # دریافت token_address از تابع تبدیل
        new_message, new_entities, chart_url, th_pairs, token_address = transform_message(message_text, message_entities)
        
        if new_message:
            # افزودن token_address به صف پیام
            await message_queue.put((new_message, new_entities, chart_url, th_pairs, token_address))
            receive_rate_limiter.increment()
            logger.info(f"Queued message: {new_message[:30]}...")
        else:
            # لاگ بسیار مهم: در صورتی که parser نتواند پیام را تجزیه کند
            logger.warning(f"Parsing FAILED for message. See parser logs for details. Skipping message: {message_text[:50]}...")
    else:
        await receive_rate_limiter.add_skipped((message_text, message_media, message_entities))
        logger.warning(f"Rate limit reached, message skipped: {message_text[:30]}...")


async def send_message_to_channel(bot, message, entities, chart_url, th_pairs, chat_id, token_address, channel_name="Unknown"):
    """پیام فرمت‌شده را به همراه دکمه‌ها به کانال مقصد ارسال می‌کند و خطاها را مدیریت می‌کند."""
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
        logger.info(f"✅ Message sent successfully to {channel_name} channel ({chat_id}). Message ID: {sent_message.message_id}, Text: {text[:30]}...")

        # ثبت رای فقط پس از ارسال موفق
        await register_message_in_votes(sent_message.message_id, chat_id, token_address)
        logger.debug(f"Vote DB registration complete for MsgID {sent_message.message_id} in {channel_name} channel.")

        return sent_message.message_id
    
    # --- مدیریت خطاهای حرفه‌ای ---

    # خطاهایی که نباید دوباره تلاش شوند (مشکل دسترسی)
    except (ChatWriteForbiddenError, UserIsBlockedError, ChannelInvalidError, ChannelPrivateError) as e:
        logger.critical(f"❌ FATAL ERROR (Permissions) sending to {channel_name} channel ({chat_id}): Bot is blocked or lacks permissions. {e}")
        raise  # این خطا را دوباره ارسال کن تا حلقه retry متوقف شود

    # خطاهایی که نباید دوباره تلاش شوند (مشکل محتوا)
    except BadRequest as e:
        if "entity" in str(e).lower() or "parsing" in str(e).lower():
            logger.error(f"❌ FATAL ERROR (BadRequest/Entity) for {channel_name} channel ({chat_id}): {e}. Message: {text[:100]}")
        else:
            logger.error(f"❌ FATAL ERROR (BadRequest) for {channel_name} channel ({chat_id}): {e}")
        raise  # متوقف کردن حلقه retry

    except MessageTooLongError as e:
        logger.error(f"❌ FATAL ERROR (MessageTooLong) for {channel_name} channel ({chat_id}). This shouldn't happen. {e}")
        raise # متوقف کردن حلقه retry

    # خطاهایی که قابل تلاش مجدد هستند (مشکل شبکه)
    except (TimedOut, NetworkError) as e:
        logger.warning(f"⚠️ NETWORK/TIMEOUT error for {channel_name} channel ({chat_id}). Retrying... Error: {e}")
        raise # ارسال مجدد برای حلقه retry

    except TelegramError as e:
        logger.error(f"❌ UNEXPECTED TelegramError for {channel_name} channel ({chat_id}): {e}")
        raise # ارسال مجدد برای حلقه retry

    except Exception as e:
        logger.error(f"❌ UNHANDLED Exception in send_message_to_channel ({channel_name}, {chat_id}): {e}\n{traceback.format_exc()}")
        raise # ارسال مجدد برای حلقه retry


async def message_sender():
    """وظیفه پس‌زمینه که پیام‌ها را از صف برداشته، با مدیریت خطای قوی ارسال می‌کند."""
    bot = Bot(token=BOT_TOKEN)
    sent_messages = set()
    while True:
        try:
            message, entities, chart_url, th_pairs, token_address = await message_queue.get()
            message_hash = hash(message)
            logger.info(f"Processing message from queue: {message[:30]}...")

            if message_hash in sent_messages:
                logger.debug(f"Message already sent, skipping: {message[:30]}...")
                message_queue.task_done()
                continue

            if not send_rate_limiter.can_send():
                logger.warning(f"Send rate limit reached, re-queuing message: {message[:30]}...")
                # پیام را به انتهای صف برگردان
                await message_queue.put((message, entities, chart_url, th_pairs, token_address))
                await asyncio.sleep(30) # 30 ثانیه صبر کن تا از لود زیاد جلوگیری شود
                message_queue.task_done()
                continue # این تکرار را رها کن

            # --- ارسال به کانال اصلی ---
            main_success = False
            attempts = 0
            while attempts < RETRY_ATTEMPTS:
                try:
                    delay = SEND_DELAY_SECONDS + random.uniform(0, SEND_DELAY_JITTER) + (message_queue.qsize() * 0.5)
                    logger.debug(f"Applying send delay: {delay:.2f}s")
                    await asyncio.sleep(delay)
                    
                    message_id = await send_message_to_channel(
                        bot, message, entities, chart_url, th_pairs, 
                        TARGET_CHANNEL_ID, token_address, channel_name="Main"
                    )
                    send_rate_limiter.increment()
                    logger.info(f"Message sent to Main channel, hash: {message_hash}, MsgID: {message_id}")
                    main_success = True
                    break  # موفقیت، خروج از حلقه retry
                
                # خطاهای غیرقابل تلاش مجدد
                except (ChatWriteForbiddenError, UserIsBlockedError, ChannelInvalidError, ChannelPrivateError, BadRequest, MessageTooLongError) as e:
                    logger.error(f"NON-RETRYABLE error sending to Main channel. Skipping message. Error: {e}")
                    break  # خروج از حلقه retry، این پیام قابل ارسال نیست
                
                # خطاهای قابل تلاش مجدد
                except (TimedOut, TelegramError, NetworkError, Exception) as e:
                    attempts += 1
                    wait_time = RETRY_DELAY_BASE * attempts + random.uniform(0, 5)
                    logger.warning(f"Retrying Main channel send attempt {attempts}/{RETRY_ATTEMPTS} after {wait_time:.2f}s due to: {e}")
                    await asyncio.sleep(wait_time)
            
            if not main_success:
                logger.error(f"Failed to send message to Main channel after {RETRY_ATTEMPTS} attempts. Message discarded: {message[:50]}...")
                message_queue.task_done()
                continue  # رفتن به پیام بعدی در صف

            # --- ارسال به کانال دوم (فقط اگر ارسال اصلی موفق بود) ---
            settings = await load_settings()
            current_time = int(time.time())
            if (settings['start_time'] <= current_time <= settings['expiry_time']):
                logger.info(f"Secondary channel is active. Attempting to send...")
                sec_attempts = 0
                while sec_attempts < RETRY_ATTEMPTS: # حلقه retry جداگانه برای کانال دوم
                    try:
                        if not send_rate_limiter.can_send():
                            logger.warning("Send rate limit reached before secondary send. Waiting 30s...")
                            await asyncio.sleep(30)
                            continue # بررسی مجدد محدودیت نرخ

                        secondary_message_id = await send_message_to_channel(
                            bot, message, entities, chart_url, th_pairs, 
                            settings['secondary_channel_id'], token_address, channel_name="Secondary"
                        )
                        send_rate_limiter.increment()
                        logger.info(f"Message sent to Secondary channel, hash: {message_hash}, MsgID: {secondary_message_id}")
                        break # موفقیت
                    
                    except (ChatWriteForbiddenError, UserIsBlockedError, ChannelInvalidError, ChannelPrivateError, BadRequest, MessageTooLongError) as e:
                        logger.error(f"NON-RETRYABLE error sending to Secondary channel ({settings['secondary_channel_id']}). Stopping secondary send. Error: {e}")
                        break # تلاش برای کانال دوم متوقف می‌شود

                    except (TimedOut, TelegramError, NetworkError, Exception) as e:
                        sec_attempts += 1
                        wait_time = RETRY_DELAY_BASE * sec_attempts
                        logger.warning(f"Retrying Secondary channel send attempt {sec_attempts}/{RETRY_ATTEMPTS} after {wait_time:.2f}s due to: {e}")
                        await asyncio.sleep(wait_time)
                
                if sec_attempts >= RETRY_ATTEMPTS:
                    logger.error(f"Failed to send to Secondary channel after {RETRY_ATTEMPTS} attempts. Main message was successful.")

            sent_messages.add(message_hash) # پیام فقط پس از موفقیت اصلی، به عنوان ارسال شده علامت‌گذاری می‌شود
            message_queue.task_done()
            
        except asyncio.CancelledError:
            logger.info("Message sender task cancelled.")
            raise
        except Exception as e:
            logger.critical(f"CRITICAL ERROR in message_sender loop: {e}\n{traceback.format_exc()}")
            message_queue.task_done() # اطمینان از اینکه صف قفل نمی‌شود
            await asyncio.sleep(10) # جلوگیری از لوپ خطای سریع


async def run_bot():
    """تابع اصلی اجرای ربات، شامل راه‌اندازی کلاینت تلتون و اپلیکیشن PTB."""
    sender_task = None
    try:
        await init_db(SECONDARY_CHANNEL_ID)
        
        await authenticate()
        await asyncio.sleep(random.uniform(1, 3))
        logger.info("Step 2: Checking channel access")
        await check_channel_access()
        await asyncio.sleep(random.uniform(1, 3))
        
        logger.info("Step 3: Setting up admin command handlers")
        application = Application.builder().token(BOT_TOKEN).build()
        application.add_handler(CommandHandler("set_secondary", set_secondary))
        application.add_handler(CommandHandler("stop_secondary", stop_secondary))
        application.add_handler(CommandHandler("status", status))
        application.add_handler(CallbackQueryHandler(handle_vote, pattern="^vote_"))
        
        logger.info("Step 4: Setting up event handler")
        client.add_event_handler(new_message_handler)
        logger.info("Step 5: Starting message sender task")
        sender_task = asyncio.create_task(message_sender())
        
        logger.info("Step 6: Starting application and client")
        loop = asyncio.get_event_loop()
        
        await application.initialize()
        await application.start()
        logger.debug("Starting polling with drop_pending_updates=True")
        await application.updater.start_polling(drop_pending_updates=True)
        logger.info("Application polling started")
        
        await client.run_until_disconnected()
        
    except Exception as e:
        logger.critical(f"Bot execution failed critically: {e}\n{traceback.format_exc()}")
    finally:
        if 'application' in locals() and application.updater and application.updater.running:
            logger.debug("Stopping updater polling")
            await application.updater.stop()
        if 'application' in locals():
            logger.debug("Stopping application")
            await application.stop()
            logger.debug("Shutting down application")
            await application.shutdown()
        logger.info("Application stopped")
        
        if sender_task and not sender_task.done():
            logger.info("Cancelling message sender task...")
            sender_task.cancel()
        
        await shutdown()
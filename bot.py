# bot.py

import logging
import asyncio
import time
import random
import re
import traceback
from datetime import datetime, timedelta
import sqlite3
import os
from telethon import TelegramClient, events
from telethon.errors import (
    FloodWaitError, ChatWriteForbiddenError, UserIsBlockedError,
    SessionPasswordNeededError, PhoneNumberBannedError, 
    ChannelInvalidError, ChannelPrivateError, MessageTooLongError
)
from telethon.tl.types import MessageEntityTextUrl
from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import Application, CommandHandler, ContextTypes
from telegram.error import TelegramError, TimedOut, BadRequest
from config import *
import pytz



logging.basicConfig(
    filename=LOG_FILE,
    level=logging.DEBUG,  # تغییر از INFO به DEBUG
    format='%(asctime)s - %(levelname)s - %(name)s - %(message)s',
    encoding='utf-8'
)
logging.getLogger('telethon').setLevel(logging.INFO)

# ایجاد کلاینت تلگرام (Telethon)
client = TelegramClient(
    SESSION_NAME, API_ID, API_HASH,
    connection_retries=3, retry_delay=8, flood_sleep_threshold=120
)

# صف مشترک برای پیام‌ها
message_queue = asyncio.Queue(maxsize=100)
skipped_messages_lock = asyncio.Lock()

# دیکشنری برای ذخیره پیام‌های اخیر و زمان ثبت آن‌ها
recent_messages = {}
RECENT_MESSAGE_TIMEOUT = 60

# محدود کننده نرخ برای دریافت و ارسال پیام‌ها
class MessageRateLimiter:
    def __init__(self, max_messages_per_minute):
        self.max_messages = max_messages_per_minute
        self.message_counter = 0
        self.last_reset_time = time.monotonic()
        self.skipped_messages = []

    def can_send(self):
        current_time = time.monotonic()
        if current_time - self.last_reset_time >= 60:
            self.message_counter = 0
            self.last_reset_time = current_time
            return True
        return self.message_counter < self.max_messages

    def increment(self):
        self.message_counter += 1

    async def add_skipped(self, message):
        async with skipped_messages_lock:
            self.skipped_messages.append((message, time.monotonic()))
            logging.info(f"Message skipped due to rate limit: {message[0][:30]}...")

    async def get_skipped(self):
        async with skipped_messages_lock:
            return [(msg, t) for msg, t in self.skipped_messages if time.monotonic() - t < 300]

class SendRateLimiter:
    def __init__(self, max_messages_per_minute):
        self.max_messages = max_messages_per_minute
        self.message_counter = 0
        self.last_reset_time = time.monotonic()

    def can_send(self):
        current_time = time.monotonic()
        if current_time - self.last_reset_time >= 60:
            self.message_counter = 0
            self.last_reset_time = current_time
            return True
        return self.message_counter < self.max_messages

    def increment(self):
        self.message_counter += 1

if not isinstance(MAX_MESSAGES_PER_MINUTE, int) or MAX_MESSAGES_PER_MINUTE <= 0:
    logging.error("MAX_MESSAGES_PER_MINUTE must be a positive integer")
    raise ValueError("Invalid MAX_MESSAGES_PER_MINUTE")
receive_rate_limiter = MessageRateLimiter(MAX_MESSAGES_PER_MINUTE)
send_rate_limiter = SendRateLimiter(MAX_MESSAGES_PER_MINUTE)

# مدیریت SQLite برای ذخیره تنظیمات کانال دوم
def init_db():
    with sqlite3.connect('bot_settings.db') as conn:
        cursor = conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS settings (
                id INTEGER PRIMARY KEY,
                secondary_channel_id INTEGER,
                start_time INTEGER,
                expiry_time INTEGER
            )
        ''')
        # تنظیم اولیه کانال دوم
        cursor.execute('''
            INSERT OR REPLACE INTO settings (id, secondary_channel_id, start_time, expiry_time)
            VALUES (1, ?, 0, 0)
        ''', (SECONDARY_CHANNEL_ID,))
        conn.commit()
    logging.info("SQLite database initialized")

def save_settings(secondary_channel_id, start_time, expiry_time):
    with sqlite3.connect('bot_settings.db') as conn:
        cursor = conn.cursor()
        cursor.execute('''
            UPDATE settings SET secondary_channel_id = ?, start_time = ?, expiry_time = ?
            WHERE id = 1
        ''', (secondary_channel_id, start_time, expiry_time))
        conn.commit()
    logging.info(f"Settings saved: secondary_channel_id={secondary_channel_id}, start_time={start_time}, expiry_time={expiry_time}")

def load_settings():
    with sqlite3.connect('bot_settings.db') as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT secondary_channel_id, start_time, expiry_time FROM settings WHERE id = 1')
        result = cursor.fetchone()
        if result:
            return {'secondary_channel_id': result[0], 'start_time': result[1], 'expiry_time': result[2]}
        return {'secondary_channel_id': SECONDARY_CHANNEL_ID, 'start_time': 0, 'expiry_time': 0}

async def shutdown():
    logging.info("Shutting down bot...")
    try:
        await client.disconnect()
        logging.info("Bot stopped gracefully")
    except Exception as e:
        logging.error(f"Error during shutdown: {e}\n{traceback.format_exc()}")

async def authenticate():
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

def transform_message(message_text, message_entities):
    logging.info("Starting message transformation")
    logging.info(f"Raw input message: {message_text[:100]}...")
    logging.debug(f"Received entities list: {message_entities}")

    pattern = r"""
        💊\s*([A-Za-z0-9]+)\s*\n
        ┌([^\(]+)\s*\(([^\)]+)\)\s*(?:\((https://solscan\.io/token/[^\)]+)\))?\s*\n
        ├USD:\s*\$([\d\.]+)\s*\n
        ├MC:\s*\$([\d\.KMB]+)\s*\n
        ├Vol:\s*\$([\d\.KMB]+)\s*\n
        ├Seen:\s*(\d+[smh]\s*ago)\s*\n
        ├Dex:\s*([^\n]+)\s*\n
        ├Dex\s*Paid:\s*([🔴🟢])\s*\n
        ├Holder:\s*Top\s*10:\s*([🟡🟢])\s*(\d+%)\s*\n
        └TH:\s*([^\n]+)\s*\n
        \n
        🔎\s*Deep\s*scan\s*by\s*Z99Bot[^\n]*\n
        [^\n]*\n
        \n
        📈\s*Chart:\s*(https://mevx\.io/[^\s?]+(?:\?[^)\s]*)?)\s*
    """
    match = re.match(pattern, message_text, re.VERBOSE | re.DOTALL)
    if not match:
        logging.warning(f"Message does not match expected pattern: {message_text[:50]}...")
        return None, None, None, None

    try:
        groups = match.groups()
        token_address = groups[0]
        token_name = groups[1]
        token_symbol = groups[2]
        token_link_from_text = groups[3]
        usd = groups[4]
        mc = groups[5]
        vol = groups[6]
        seen = groups[7]
        dex = groups[8]
        dex_paid = groups[9]
        holder_color = groups[10]
        holder_percentage = groups[11]
        th_values_str = groups[12].strip()
        chart_url = f"https://gmgn.ai/sol/token/PnoVyJz1_{token_address}"

        token_link = token_link_from_text or f"https://solscan.io/token/{token_address}"
        logging.info(f"Using token link: {token_link}")

        th_pairs = []
        th_links_from_entities = []
        th_line_start_offset = -1
        th_line_end_offset = len(message_text)

        if th_values_str and message_entities:
            try:
                th_line_prefix = "└TH:"
                th_line_start_offset = message_text.index(th_line_prefix) + len(th_line_prefix)
                th_line_end_offset = message_text.find('\n', th_line_start_offset)
                if th_line_end_offset == -1:
                    th_line_end_offset = len(message_text)
                else:
                    while th_line_end_offset < len(message_text) and message_text[th_line_end_offset-1].isspace():
                        th_line_end_offset -= 1

                logging.debug(f"Calculated TH line offset range: [{th_line_start_offset}, {th_line_end_offset})")
                logging.debug(f"TH line text: {message_text[th_line_start_offset:th_line_end_offset]}")

                potential_th_entities = [
                    entity for entity in message_entities
                    if isinstance(entity, MessageEntityTextUrl) and th_line_start_offset <= entity.offset < th_line_end_offset
                ]
                potential_th_entities.sort(key=lambda e: e.offset)
                th_links_from_entities = [entity.url for entity in potential_th_entities]
                logging.info(f"Extracted TH URLs from entities: {th_links_from_entities}")

                out_of_range_entities = [
                    entity for entity in message_entities
                    if isinstance(entity, MessageEntityTextUrl) and entity.offset >= th_line_end_offset
                ]
                if out_of_range_entities:
                    logging.warning(f"Found {len(out_of_range_entities)} URL entities outside TH range: {[e.url for e in out_of_range_entities]}")

            except ValueError:
                logging.warning("Could not find '└TH:' prefix to determine offset for entity search.")
            except Exception as e:
                logging.error(f"Error processing entities for TH links: {e}", exc_info=True)

        th_numeric_values = []
        if th_values_str:
            th_items = th_values_str.split("|")
            for item in th_items[:5]:
                item_stripped = item.strip()
                value_match = re.match(r'(\d+\.?\d*)', item_stripped)
                th_numeric_values.append(value_match.group(1) if value_match else item_stripped or "0")
        logging.info(f"Extracted TH numeric values: {th_numeric_values}")

        num_holders_to_process = min(len(th_numeric_values), 5)
        for i in range(num_holders_to_process):
            value = th_numeric_values[i]
            link = th_links_from_entities[i] if i < len(th_links_from_entities) else None
            th_pairs.append((value, link))
            logging.info(f"Combined Top Holder pair {i+1}: value='{value}', link={link}")
            if link is None and value != "0":
                logging.warning(f"No corresponding link found for TH value: '{value}' at index {i}")

        while len(th_pairs) < 5:
            th_pairs.append(("0", None))

        logging.info(f"Final Top Holder pairs: {th_pairs}")

        th_text_parts = [value or "0" for value, _ in th_pairs]
        th_text = "|".join(th_text_parts)
        logging.info(f"Formatted TH text for output: {th_text}")

        new_message = (
            f"⚡️ <code>{token_address}</code>\n"
            f"• {token_name.strip()} ({token_symbol})\n"
            f"• قیمت:      ${usd}\n"
            f"• مارکت‌کپ:     ${mc}\n"
            f"• حجم:      ${vol}\n"
            f"• ساخته شده:      ${seen}\n"
            f"• نقدینگی:      {dex}\n"
            f"• دکس پرداخت شده؟: {dex_paid}\n"
            f"• هولدرها:     Top 10: {holder_color} {holder_percentage}\n"
            f"• تاپ هولدر:      {th_text}"
        )

        if len(new_message) > 4096:
            logging.error(f"Transformed message too long: {len(new_message)} characters. Truncating.")
            new_message = new_message[:4090] + "..."

        new_entities = []
        try:
            token_text_display = f"{token_name.strip()} ({token_symbol})"
            token_start = new_message.index(token_text_display)
            new_entities.append(MessageEntityTextUrl(
                offset=token_start,
                length=len(token_text_display),
                url=token_link
            ))
            logging.info(f"Token link entity added for output: {token_link}")
        except ValueError:
            logging.warning("Could not find token name/symbol text in the final formatted message to add entity.")

        if th_pairs and th_text != "None":
            try:
                th_line_start_in_output = new_message.index("• تاپ هولدر:") + len("• تاپ هولدر:      ")
                current_offset_in_output = th_line_start_in_output
                output_th_values = th_text.split("|")

                for i in range(len(output_th_values)):
                    value_text_in_output = output_th_values[i]
                    if value_text_in_output == "0":
                        try:
                            value_start = new_message.index(value_text_in_output, current_offset_in_output)
                            current_offset_in_output = value_start + len(value_text_in_output) + 1
                        except ValueError:
                            logging.warning(f"Could not find placeholder TH value '{value_text_in_output}' from offset {current_offset_in_output} to advance offset.")
                            current_offset_in_output += len(value_text_in_output) + 1
                        continue

                    if i < len(th_pairs):
                        original_value, extracted_link = th_pairs[i]
                        if extracted_link:
                            try:
                                value_start = new_message.index(value_text_in_output, current_offset_in_output)
                                new_entities.append(MessageEntityTextUrl(
                                    offset=value_start,
                                    length=len(value_text_in_output),
                                    url=extracted_link
                                ))
                                logging.info(f"Top Holder link entity added for output: '{value_text_in_output}' -> {extracted_link}")
                                current_offset_in_output = value_start + len(value_text_in_output) + 1
                            except ValueError:
                                logging.warning(f"Could not find output TH value '{value_text_in_output}' in new_message starting from offset {current_offset_in_output} to add link entity.")
                                current_offset_in_output += len(value_text_in_output) + 1
                        else:
                            try:
                                value_start = new_message.index(value_text_in_output, current_offset_in_output)
                                current_offset_in_output = value_start + len(value_text_in_output) + 1
                            except ValueError:
                                logging.warning(f"Could not find output TH value '{value_text_in_output}' (no link) from offset {current_offset_in_output} to advance offset.")
                                current_offset_in_output += len(value_text_in_output) + 1
                    else:
                        logging.error(f"Index mismatch processing output TH entities at index {i}")
                        current_offset_in_output += len(value_text_in_output) + 1

            except ValueError:
                logging.warning("Could not find '• تاپ هولدر:' prefix in the final formatted message.")
            except Exception as e:
                logging.error(f"Error adding TH link entities to output message: {e}", exc_info=True)

        logging.debug(f"Final entities for output: {new_entities}")
        return new_message, new_entities, chart_url, th_pairs

    except Exception as e:
        logging.error(f"Unhandled error in transform_message: {e}\n{traceback.format_exc()}")
        return None, None, None, None

@client.on(events.NewMessage(chats=SOURCE_CHANNEL_ID))
async def new_message_handler(event):
    if not isinstance(event, events.NewMessage.Event):
        logging.info("Skipped non-message update")
        return

    message = event.message
    message_text = message.message or ""
    message_media = message.media
    message_entities = message.entities or []

    if not message_text.strip().startswith("💊") or len(message_text.strip()) <= 1:
        logging.info("Skipped message: empty or invalid content")
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
    logging.info(f"Cleaned up {len(expired_messages)} expired messages from recent_messages")

    logging.info(f"Received new message: {message_text[:30]}...")
    if receive_rate_limiter.can_send():
        if message_queue.qsize() > 0:
            await asyncio.sleep(QUEUE_DELAY_SECONDS + random.uniform(0, 2))
        new_message, new_entities, chart_url, th_pairs = transform_message(message_text, message_entities)
        if new_message:
            await message_queue.put((new_message, new_entities, chart_url, th_pairs))
            receive_rate_limiter.increment()
            logging.info(f"Queued message: {new_message[:30]}...")
        else:
            logging.warning("Transformed message is None, skipping...")
    else:
        await receive_rate_limiter.add_skipped((message_text, message_media, message_entities))
        logging.warning(f"Rate limit reached, message skipped: {message_text[:30]}...")

def entities_to_html(entities, text):
    if not entities:
        return text, "HTML"

    html_text = text
    offset_adjustment = 0

    for entity in sorted(entities, key=lambda e: e.offset):
        start = entity.offset + offset_adjustment
        end = start + entity.length
        entity_text = html_text[start:end]

        if isinstance(entity, MessageEntityTextUrl):
            html_entity = f'<a href="{entity.url}">{entity_text}</a>'
            html_text = html_text[:start] + html_entity + html_text[end:]
            offset_adjustment += len(html_entity) - len(entity_text)

    return html_text, "HTML"

async def send_message_to_channel(bot, message, entities, chart_url, th_pairs, chat_id):
    try:
        text, parse_mode = entities_to_html(entities, message)
        keyboard = [
            [InlineKeyboardButton("📈 مشاهده نمودار", url=chart_url)],
            [InlineKeyboardButton("💰 ترید کن سولانا هدیه بگیر", url=GIFT)],
            [InlineKeyboardButton("📚 آموزش آکسیوم", url=AXIOM_LINK), InlineKeyboardButton("⭐️ تهیه اشتراک پلاس", url=PLUS_LINK)]
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
        return sent_message.message_id
    except TimedOut:
        logging.warning(f"Request timed out for chat_id {chat_id}. Retrying after delay...")
        raise
    except BadRequest as e:
        logging.error(f"BadRequest error for chat_id {chat_id}: {e}")
        raise
    except TelegramError as e:
        logging.error(f"TelegramError for chat_id {chat_id}: {e}")
        raise
    except Exception as e:
        logging.error(f"Error in send_message_to_channel for chat_id {chat_id}: {e}\n{traceback.format_exc()}")
        raise

async def message_sender():
    bot = Bot(token=BOT_TOKEN)
    sent_messages = set()
    while True:
        try:
            message, entities, chart_url, th_pairs = await message_queue.get()
            message_hash = hash(message)
            logging.info(f"Processing message: {message[:30]}...")

            if message_hash in sent_messages:
                logging.info(f"Message already sent, skipping: {message[:30]}...")
                message_queue.task_done()
                continue

            if send_rate_limiter.can_send():
                attempts = 0
                while attempts < RETRY_ATTEMPTS:
                    try:
                        delay = SEND_DELAY_SECONDS + random.uniform(0, SEND_DELAY_JITTER) + (message_queue.qsize() * 0.5)
                        await asyncio.sleep(delay)
                        
                        # ارسال به کانال اصلی
                        message_id = await send_message_to_channel(bot, message, entities, chart_url, th_pairs, TARGET_CHANNEL_ID)
                        send_rate_limiter.increment()
                        logging.info(f"Message marked as sent to main channel, hash: {message_hash}, Message ID: {message_id}")

                        # بررسی ارسال به کانال دوم
                        settings = load_settings()
                        current_time = int(time.time())
                        if (settings['start_time'] <= current_time <= settings['expiry_time']):
                            try:
                                secondary_message_id = await send_message_to_channel(
                                    bot, message, entities, chart_url, th_pairs, settings['secondary_channel_id']
                                )
                                send_rate_limiter.increment()
                                logging.info(f"Message sent to secondary channel, hash: {message_hash}, Message ID: {secondary_message_id}")
                            except Exception as e:
                                logging.error(f"Failed to send to secondary channel: {e}. Continuing with main channel.")

                        sent_messages.add(message_hash)
                        break
                    except (TimedOut, TelegramError) as e:
                        attempts += 1
                        wait_time = attempts * RETRY_DELAY_BASE + random.uniform(0, 5)
                        logging.warning(f"Retrying send attempt {attempts}/{RETRY_ATTEMPTS} after {wait_time} seconds due to error: {e}")
                        await asyncio.sleep(wait_time)
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

# Handler برای دستورات ادمین
async def set_secondary(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logging.debug(f"Received /set_secondary command from user {update.effective_user.id}")
    user_id = update.effective_user.id
    if user_id not in ADMIN_IDS:
        logging.warning(f"Unauthorized access attempt by user {user_id}")
        await update.message.reply_text("شما دسترسی به این دستور ندارید.")
        return

    try:
        args = context.args
        logging.debug(f"Arguments for /set_secondary: {args}")
        if len(args) != 2:
            await update.message.reply_text("لطفاً دستور را به‌صورت: /set_secondary <مدت زمان> <ساعت شروع> وارد کنید\nمثال: /set_secondary 4h 14:00")
            return
        # ... بقیه کد بدون تغییر ...
        # (برای اختصار، فقط بخش تغییر یافته نشان داده شده)
        duration_str, start_time_str = args
        duration_match = re.match(r'(\d+)(h|m)', duration_str)
        if not duration_match:
            await update.message.reply_text("مدت زمان باید به‌صورت عددی با واحد h (ساعت) یا m (دقیقه) باشد. مثال: 4h")
            return
        duration_value, unit = duration_match.groups()
        duration_seconds = int(duration_value) * (3600 if unit == 'h' else 60)

        time_match = re.match(r'(\d{1,2}):(\d{2})', start_time_str)
        if not time_match:
            await update.message.reply_text("ساعت شروع باید به‌صورت HH:MM باشد. مثال: 14:00")
            return
        hour, minute = map(int, time_match.groups())
        if not (0 <= hour <= 23 and 0 <= minute <= 59):
            await update.message.reply_text("ساعت شروع نامعتبر است. باید بین 00:00 و 23:59 باشد.")
            return

        now = datetime.now(pytz.UTC)
        start_time = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if start_time < now:
            start_time += timedelta(days=1)
        start_timestamp = int(start_time.timestamp())
        expiry_timestamp = start_timestamp + duration_seconds

        save_settings(SECONDARY_CHANNEL_ID, start_timestamp, expiry_timestamp)
        await update.message.reply_text(
            f"کانال دوم فعال شد.\nشروع: {start_time.strftime('%Y-%m-%d %H:%M')}\nپایان: {(start_time + timedelta(seconds=duration_seconds)).strftime('%Y-%m-%d %H:%M')}"
        )
        logging.info(f"Admin {user_id} set secondary channel: start={start_timestamp}, expiry={expiry_timestamp}")
    except Exception as e:
        await update.message.reply_text("خطا در پردازش دستور. لطفاً دوباره تلاش کنید.")
        logging.error(f"Error in set_secondary: {e}\n{traceback.format_exc()}")

async def stop_secondary(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logging.debug(f"Received /stop_secondary command from user {update.effective_user.id}")
    user_id = update.effective_user.id
    if user_id not in ADMIN_IDS:
        logging.warning(f"Unauthorized access attempt by user {user_id}")
        await update.message.reply_text("شما دسترسی به این دستور ندارید.")
        return
    save_settings(SECONDARY_CHANNEL_ID, 0, 0)
    await update.message.reply_text("ارسال به کانال دوم متوقف شد.")
    logging.info(f"Admin {user_id} stopped secondary channel")

async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logging.debug(f"Received /status command from user {update.effective_user.id}")
    user_id = update.effective_user.id
    if user_id not in ADMIN_IDS:
        logging.warning(f"Unauthorized access attempt by user {user_id}")
        await update.message.reply_text("شما دسترسی به این دستور ندارید.")
        return
    settings = load_settings()
    current_time = int(time.time())
    if settings['start_time'] <= current_time <= settings['expiry_time']:
        start_time = datetime.fromtimestamp(settings['start_time'], pytz.UTC)
        expiry_time = datetime.fromtimestamp(settings['expiry_time'], pytz.UTC)
        await update.message.reply_text(
            f"کانال دوم فعال است.\nشروع: {start_time.strftime('%Y-%m-%d %H:%M')}\nپایان: {expiry_time.strftime('%Y-%m-%d %H:%M')}"
        )
    else:
        await update.message.reply_text("کانال دوم غیرفعال است.")
    logging.info(f"Admin {user_id} checked status")


# در فایل bot.py، فقط بخش run_bot را اصلاح می‌کنیم

async def run_bot():
    try:
        # راه‌اندازی پایگاه داده
        init_db()
        
        # احراز هویت
        await authenticate()
        await asyncio.sleep(random.uniform(1, 3))
        logging.info("Step 2: Checking channel access")
        await check_channel_access()
        await asyncio.sleep(random.uniform(1, 3))
        
        # راه‌اندازی handler دستورات ادمین
        logging.info("Step 3: Setting up admin command handlers")
        application = Application.builder().token(BOT_TOKEN).build()
        application.add_handler(CommandHandler("set_secondary", set_secondary))
        application.add_handler(CommandHandler("stop_secondary", stop_secondary))
        application.add_handler(CommandHandler("status", status))
        
        # راه‌اندازی handler پیام‌ها
        logging.info("Step 4: Setting up event handler")
        client.add_event_handler(new_message_handler)
        logging.info("Step 5: Starting message sender task")
        sender_task = asyncio.create_task(message_sender())
        
        # اجرای application و telethon در یک حلقه
        logging.info("Step 6: Starting application and client")
        loop = asyncio.get_event_loop()
        try:
            # مقداردهی اولیه و شروع application
            await application.initialize()
            await application.start()
            logging.debug("Starting polling with drop_pending_updates=True")
            await application.updater.start_polling(drop_pending_updates=True)
            logging.info("Application polling started")
            logging.debug("Polling loop running, waiting for updates")
            
            # اجرای client تا قطع ارتباط
            await client.run_until_disconnected()
        finally:
            # توقف application
            if application.updater.running:
                logging.debug("Stopping updater polling")
                await application.updater.stop()
            logging.debug("Stopping application")
            await application.stop()
            logging.debug("Shutting down application")
            await application.shutdown()
            logging.info("Application stopped")
            if 'sender_task' in locals():
                sender_task.cancel()
    except Exception as e:
        logging.error(f"Disconnected: {e}\n{traceback.format_exc()}")
    finally:
        await shutdown()
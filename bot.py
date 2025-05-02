#bot.py

import logging
import asyncio
import time
import random
import re
import traceback
from datetime import datetime
from telethon import TelegramClient, events
from telethon.errors import (
    FloodWaitError, ChatWriteForbiddenError, UserIsBlockedError,
    SessionPasswordNeededError, PhoneNumberBannedError, 
    ChannelInvalidError, ChannelPrivateError, MessageTooLongError
)
from telethon.tl.types import MessageEntityTextUrl
from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.error import TelegramError, TimedOut, BadRequest
from config import *



logging.basicConfig(
    filename=LOG_FILE,
    level=logging.DEBUG,  # <--- اینجا را DEBUG کن
    format='%(asctime)s - %(levelname)s - %(name)s - %(message)s', # نام لاگر اضافه شد
    encoding='utf-8'
)
# برای جلوگیری از لاگ‌های زیاد خود Telethon (اختیاری)
logging.getLogger('telethon').setLevel(logging.INFO)


# ایجاد کلاینت تلگرام (Telethon)
client = TelegramClient(
    SESSION_NAME, API_ID, API_HASH,
    connection_retries=5, retry_delay=2, flood_sleep_threshold=120
)

# صف مشترک برای پیام‌ها
message_queue = asyncio.Queue(maxsize=100)
skipped_messages_lock = asyncio.Lock()

# دیکشنری برای ذخیره پیام‌های اخیر و زمان ثبت آن‌ها
recent_messages = {}  # کلید: هش پیام، مقدار: زمان ثبت (monotonic time)
RECENT_MESSAGE_TIMEOUT = 60  # پیام‌ها تا 60 ثانیه در حافظه نگه داشته می‌شوند

# محدود کننده نرخ برای دریافت پیام‌ها
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

# محدود کننده نرخ برای ارسال پیام‌ها
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

# اعتبارسنجی MAX_MESSAGES_PER_MINUTE
if not isinstance(MAX_MESSAGES_PER_MINUTE, int) or MAX_MESSAGES_PER_MINUTE <= 0:
    logging.error("MAX_MESSAGES_PER_MINUTE must be a positive integer")
    raise ValueError("Invalid MAX_MESSAGES_PER_MINUTE")
receive_rate_limiter = MessageRateLimiter(MAX_MESSAGES_PER_MINUTE)
send_rate_limiter = SendRateLimiter(MAX_MESSAGES_PER_MINUTE)

async def shutdown():
    logging.info("Shutting down bot...")
    try:
        await client.disconnect()
        logging.info("Bot stopped gracefully")
    except Exception as e:
        logging.error(f"Error during shutdown: {e}\n{traceback.format_exc()}")

async def authenticate():
    for attempt in range(3):
        try:
            await client.start()
            user = await client.get_me()
            logging.info(f"Authenticated as {user.username or user.id}")
            return
        except SessionPasswordNeededError:
            logging.error("Two-factor authentication required")
            raise SystemExit
        except PhoneNumberBannedError:
            logging.error("Phone number banned")
            raise SystemExit
        except Exception as e:
            logging.error(f"Authentication attempt {attempt + 1}/3 failed: {e}\n{traceback.format_exc()}")
            if attempt < 2:
                await asyncio.sleep(5 + random.uniform(0, 2))
            else:
                raise SystemExit

async def check_channel_access():
    try:
        source = await client.get_entity(SOURCE_CHANNEL_ID)
        logging.info(f"Source channel access verified: {SOURCE_CHANNEL_ID}")
    except ChannelInvalidError as e:
        logging.error(f"Invalid channel ID: {e}. Check SOURCE_CHANNEL_ID ({SOURCE_CHANNEL_ID})")
        raise SystemExit
    except ChannelPrivateError as e:
        logging.error(f"Channel is private or inaccessible: {e}. Ensure bot is a member of SOURCE_CHANNEL_ID ({SOURCE_CHANNEL_ID})")
        raise SystemExit
    except Exception as e:
        logging.error(f"Channel access failed: {e}\n{traceback.format_exc()}")
        raise SystemExit


def transform_message(message_text, message_entities):
    logging.info("Starting message transformation")
    logging.info(f"Raw input message: {message_text[:100]}...") # نمایش بخش بیشتری از پیام اولیه
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
        # ... (استخراج بقیه گروه‌ها مثل قبل) ...
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
        chart_url = groups[13] if groups[13] and "mevx.io" in groups[13] else f"https://mevx.io/solana/{token_address}?ref=pvggbyhMPGy9"

        # ... (کد تعیین token_link مثل قبل) ...
        token_link = token_link_from_text
        if not token_link:
            token_link = f"https://solscan.io/token/{token_address}"
            logging.info(f"Using default token link: {token_link}")


        th_pairs = []
        th_links_from_entities = []
        th_line_start_offset = -1 # مقدار اولیه
        th_line_end_offset = len(message_text) # مقدار اولیه

        if th_values_str and message_entities:
            try:
                th_line_prefix = "└TH:"
                th_line_start_offset = message_text.index(th_line_prefix) + len(th_line_prefix)
                # پیدا کردن انتهای دقیق‌تر خط TH (تا ابتدای خط بعدی یا انتهای پیام)
                next_line_marker = "\n\n🔎"
                th_line_end_offset_candidate = message_text.find(next_line_marker, th_line_start_offset)

                if th_line_end_offset_candidate != -1:
                    # پیدا کردن آخرین کاراکتر غیر whitespace قبل از مارکر خط بعدی
                    real_end = th_line_end_offset_candidate
                    while real_end > th_line_start_offset and message_text[real_end-1].isspace():
                        real_end -= 1
                    th_line_end_offset = real_end
                else:
                    # اگر مارکر بعدی پیدا نشد، تا انتهای پیام در نظر بگیر (با حذف whitespace انتهایی)
                    real_end = len(message_text)
                    while real_end > th_line_start_offset and message_text[real_end-1].isspace():
                        real_end -= 1
                    th_line_end_offset = real_end

                logging.debug(f"Calculated TH line offset range: [{th_line_start_offset}, {th_line_end_offset})")

                # --- لاگ کردن تمام Entity های لینک ---
                logging.debug("--- All MessageEntityTextUrl entities received ---")
                entity_found_outside_range = False
                for i, entity in enumerate(message_entities):
                    if isinstance(entity, MessageEntityTextUrl):
                        entity_text_segment = "N/A"
                        try:
                            entity_text_segment = message_text[entity.offset : entity.offset + entity.length]
                        except IndexError:
                            logging.warning(f"IndexError getting text for entity at offset {entity.offset}")
                        is_in_range = th_line_start_offset <= entity.offset < th_line_end_offset
                        logging.debug(f"Entity {i}: offset={entity.offset}, length={entity.length}, url={entity.url}, text='{entity_text_segment}', in_TH_range={is_in_range}")
                        if not is_in_range and entity.offset >= th_line_start_offset : # اگر خارج از رنج بود ولی بعد از شروع خط TH
                             entity_found_outside_range = True

                if entity_found_outside_range:
                     logging.warning("At least one URL entity was found after TH line start but outside calculated end offset.")
                logging.debug("--- End of all MessageEntityTextUrl entities ---")
                # --- پایان لاگ کردن ---


                potential_th_entities = []
                for entity in message_entities:
                     if isinstance(entity, MessageEntityTextUrl):
                         if th_line_start_offset <= entity.offset < th_line_end_offset:
                              potential_th_entities.append(entity)
                         #else:
                         #    logging.debug(f"Entity at offset {entity.offset} is outside the calculated TH range [{th_line_start_offset}, {th_line_end_offset})")


                potential_th_entities.sort(key=lambda e: e.offset)
                th_links_from_entities = [entity.url for entity in potential_th_entities]
                logging.info(f"Extracted TH URLs from entities within range (in order): {th_links_from_entities}")
                if len(th_links_from_entities) != th_values_str.count('|') + 1 and th_values_str:
                     logging.warning(f"Mismatch between number of extracted links ({len(th_links_from_entities)}) and number of TH values ({th_values_str.count('|') + 1})")


            except ValueError:
                logging.warning("Could not find '└TH:' prefix to determine offset for entity search.")
            except Exception as e:
                 logging.error(f"Error processing entities for TH links: {e}", exc_info=True)

        # ... (بقیه کد استخراج مقادیر عددی، ترکیب جفت‌ها، ساخت پیام و entities خروجی مثل قبل) ...
        th_numeric_values = []
        if th_values_str:
            th_items = th_values_str.split("|")
            for item in th_items[:5]:
                item_stripped = item.strip()
                value_match = re.match(r'(\d+\.?\d*)', item_stripped)
                if value_match:
                     th_numeric_values.append(value_match.group(1))
                else:
                     th_numeric_values.append(item_stripped if item_stripped else "0")
        logging.info(f"Extracted TH numeric values from text: {th_numeric_values}")

        num_holders_to_process = min(len(th_numeric_values), 5)
        for i in range(num_holders_to_process):
            value = th_numeric_values[i]
            link = th_links_from_entities[i] if i < len(th_links_from_entities) else None
            th_pairs.append((value, link))
            logging.info(f"Combined Top Holder pair {i+1}: value='{value}', link={link}")
            if link is None and value != "0":
                 # فقط اگر انتظار لینک داشتیم (یعنی مقادیر عددی بیشتر از لینک‌های یافت شده بود) هشدار بده
                 if i >= len(th_links_from_entities):
                      logging.warning(f"No corresponding link found/extracted for TH value: '{value}' at index {i}")

        while len(th_pairs) < 5:
            th_pairs.append(("0", None))

        logging.info(f"Final Top Holder pairs (padded): {th_pairs}")

        th_text_parts = []
        for value, _ in th_pairs:
            th_text_parts.append(value if value else "0")
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

    # بررسی پیام تکراری
    message_hash = hash(message_text)
    current_time = time.monotonic()
    if message_hash in recent_messages:
        logging.info(f"Skipped duplicate message: {message_text[:30]}...")
        return

    # اضافه کردن پیام به دیکشنری پیام‌های اخیر همراه با زمان ثبت
    recent_messages[message_hash] = current_time

    # پاکسازی پیام‌های قدیمی‌تر از RECENT_MESSAGE_TIMEOUT
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

# تابع ارسال پیام با python-telegram-bot
def entities_to_html(entities, text):
    if not entities:
        return text, "HTML"  # همچنان به صورت HTML ارسال می‌کنیم تا تگ <code> کار کند

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

async def send_message_to_channel(bot, message, entities, chart_url, th_pairs):
    try:
        # تبدیل entities به فرمت HTML
        text, parse_mode = entities_to_html(entities, message)

        # تنظیم دکمه‌ها
        keyboard = [
            [InlineKeyboardButton("📈 نمودار", url=chart_url)],
            [InlineKeyboardButton("🔥 به ما بپیوندید", url=VIP_LINK)]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        # ارسال پیام
        sent_message = await bot.send_message(
            chat_id=TARGET_CHANNEL_ID,
            text=text,
            parse_mode=parse_mode,
            reply_markup=reply_markup,
            disable_web_page_preview=True
        )
        logging.info(f"Message sent successfully to {TARGET_CHANNEL_ID}. Message ID: {sent_message.message_id}, Text: {text[:30]}...")
        return sent_message.message_id
    except TimedOut:
        logging.warning("Request timed out. Retrying after delay...")
        raise
    except BadRequest as e:
        logging.error(f"BadRequest error: {e}. Possibly malformed message or buttons.")
        raise
    except TelegramError as e:
        logging.error(f"TelegramError in send_message_to_channel: {e}")
        raise
    except Exception as e:
        logging.error(f"Error in send_message_to_channel: {e}\n{traceback.format_exc()}")
        raise

async def message_sender():
    bot = Bot(token=BOT_TOKEN)
    sent_messages = set()  # برای جلوگیری از ارسال پیام‌های تکراری پس از تلاش مجدد
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
                        message_id = await send_message_to_channel(bot, message, entities, chart_url, th_pairs)
                        sent_messages.add(message_hash)
                        send_rate_limiter.increment()
                        logging.info(f"Message marked as sent, hash: {message_hash}, Message ID: {message_id}")
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

async def run_bot():
    try:
        await authenticate()
        await check_channel_access()
        client.add_event_handler(new_message_handler)
        sender_task = asyncio.create_task(message_sender())
        await client.run_until_disconnected()
    except Exception as e:
        logging.error(f"Disconnected: {e}\n{traceback.format_exc()}")
        sender_task.cancel()
    finally:
        await shutdown()
import asyncio
import time
import logging
from telethon.tl.types import (
    MessageEntityTextUrl, MessageEntityUrl, MessageEntityBold, MessageEntityItalic,
    MessageEntityCode, MessageEntityPre, MessageEntityStrike, MessageEntityUnderline
)
from config import MAX_MESSAGES_PER_MINUTE, QUEUE_DELAY_SECONDS

logger = logging.getLogger(__name__)

class MessageProcessor:
    def __init__(self):
        self.message_counter = 0
        self.last_reset_time = time.monotonic()
        self.skipped_messages = []

    def reset_rate_limit(self):
        """ریست محدودیت نرخ ارسال پیام"""
        current_time = time.monotonic()
        if current_time - self.last_reset_time >= 60:
            self.message_counter = 0
            self.last_reset_time = current_time
            return True
        return False

    async def process_message(self, message, queue):
        """پردازش پیام و افزودن به صف"""
        message_text = message.message or ""
        message_media = message.media
        message_entities = message.entities or []

        # فقط پیام‌های شروع‌شده با 💊
        if not message_text.strip().startswith("💊"):
            return False

        # مدیریت محدودیت نرخ
        if self.reset_rate_limit():
            for msg in self.skipped_messages:
                await queue.put(msg)
            self.skipped_messages.clear()

        if self.message_counter < MAX_MESSAGES_PER_MINUTE:
            # تغییر متن پیام
            processed_text = self.modify_message_text(message_text)
            processed_entities = self.filter_entities(message_entities)

            await asyncio.sleep(QUEUE_DELAY_SECONDS)
            await queue.put((processed_text, message_media, processed_entities))
            self.message_counter += 1
            return True
        else:
            self.skipped_messages.append((message_text, message_media, message_entities))
            logger.warning("Rate limit reached, message skipped")
            return False

    def modify_message_text(self, text):
        """اعمال تغییرات درخواستی روی متن پیام"""
        try:
            # تغییر ایموجی
            text = text.replace("💊", "🪙")
            # حذف تبلیغ Z99Bot
            text = "\n".join(line for line in text.split("\n") if "Deep scan by Z99Bot" not in line)
            # افزودن تبلیغ جدید
            text += "\n\nMemeland - Fastest Crypto Signals"
            return text
        except Exception as e:
            logger.error(f"Error modifying message text: {e}", exc_info=True)
            return text

    def filter_entities(self, entities):
        """فیلتر کردن انتیتی‌های مجاز"""
        try:
            return [
                e for e in entities if isinstance(e, (
                    MessageEntityTextUrl, MessageEntityUrl, MessageEntityBold,
                    MessageEntityItalic, MessageEntityCode, MessageEntityPre,
                    MessageEntityStrike, MessageEntityUnderline
                ))
            ]
        except Exception as e:
            logger.error(f"Error filtering entities: {e}", exc_info=True)
            return entities

async def process_message(message, queue):
    processor = MessageProcessor()
    return await processor.process_message(message, queue)

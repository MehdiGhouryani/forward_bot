# message_processor.py
import logging
import asyncio
from telethon.tl.types import (
    MessageEntityTextUrl, MessageEntityUrl, MessageEntityBold, MessageEntityItalic,
    MessageEntityCode, MessageEntityPre, MessageEntityStrike, MessageEntityUnderline
)
# from config import VIP_LINK # اگر دکمه VIP را دوباره فعال کردید

logger = logging.getLogger(__name__)

class MessageProcessor:
    """
    وظیفه پردازش و تغییر محتوای پیام دریافت شده از کانال مبدا را بر عهده دارد.
    """
    def __init__(self):
        # در این نسخه، rate limiting داخلی حذف شده و به MessageSender واگذار شده است.
        pass

    async def process(self, message):
        """
        پیام را پردازش کرده و در صورت تطابق با شرایط، محتوای تغییر یافته را برمی‌گرداند.
        در غیر این صورت یا در صورت بروز خطا، None برمی‌گرداند.
        """
        try:
            message_text = message.text or "" # استفاده از text به جای message
            message_media = message.media
            message_entities = message.entities or []

            # --- شرط اصلی برای پردازش پیام ---
            if not message_text.strip().startswith("💊"):
                logger.info(f"Skipped message ID {message.id}: Does not start with '💊'.")
                return None
            # ---------------------------------

            processed_text = await self._modify_message_text(message_text)
            # entities نیازی به فیلتر خاصی ندارند مگر اینکه بخواهید برخی را حذف کنید
            # processed_entities = await self._filter_entities(message_entities)

            # ایجاد دیکشنری برای ارسال به صف
            processed_data = {
                "text": processed_text,
                "media": message_media,
                "entities": message_entities, # ارسال entities اصلی برای حفظ فرمت
                # "buttons": [Button.url("Purchase VIP Analysis", VIP_LINK)] # اگر دکمه لازم است
            }

            logger.info(f"Processed message ID {message.id}: Queuing for sending.")
            return processed_data

        except Exception as e:
            logger.error(f"Error processing message ID {message.id}: {e}", exc_info=True)
            await asyncio.sleep(1) # وقفه کوتاه در صورت بروز خطا در پردازش
            return None

    async def _modify_message_text(self, text):
        """تغییرات مورد نظر را روی متن پیام اعمال می‌کند."""
        try:
            # جایگزینی ایموجی
            text = text.replace("💊", "🪙", 1) # فقط اولین مورد را جایگزین کند

            # حذف خط خاص (مثال)
            lines = text.split("\n")
            lines = [line for line in lines if "Deep scan by Z99Bot" not in line]
            text = "\n".join(lines)

            # # افزودن متن تبلیغاتی (حذف شده - با احتیاط استفاده کنید)
            # text += "\n\nMemeland - Fastest Crypto Signals"

            return text.strip()
        except Exception as e:
            logger.error(f"Error modifying message text: {e}", exc_info=True)
            return text # در صورت خطا، متن اصلی را برگردان

    # async def _filter_entities(self, entities):
    #     """فیلتر کردن entity ها در صورت نیاز."""
    #     # در این مثال، همه entity های اصلی حفظ می‌شوند.
    #     # در صورت نیاز می‌توانید منطق فیلتر خود را اینجا اضافه کنید.
    #     return entities
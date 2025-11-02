# main.py

import asyncio
import logging
import logging.handlers  # برای لاگ چرخشی
import sys
import os

# fcntl را فقط در صورتی import می‌کنیم که ویندوز نباشد
if os.name != 'nt':
    try:
        import fcntl
    except ImportError:
        fcntl = None
        # لاگ در این مرحله هنوز تنظیم نشده، از warning استفاده می‌کنیم
        logging.warning("fcntl module not found, file locking disabled.")
else:
    fcntl = None

from bot import run_bot, shutdown

# --- شروع تنظیمات لاگ‌نویسی حرفه‌ای ---

LOG_FILE = 'bot.log'
MAX_BYTES = 1024 * 1024 * 5  # 5 MB
BACKUP_COUNT = 3
LOG_FORMAT = '%(asctime)s - %(levelname)s - %(name)s - %(message)s'

# ۱. تنظیمات فایل لاگ (با جزئیات کامل DEBUG)
# لاگ‌ها در فایل می‌چرخند تا فضای دیسک پر نشود
file_handler = logging.handlers.RotatingFileHandler(
    LOG_FILE,
    maxBytes=MAX_BYTES,
    backupCount=BACKUP_COUNT,
    encoding='utf-8'
)
file_handler.setLevel(logging.DEBUG)  # تمام جزئیات در فایل ذخیره شود
file_handler.setFormatter(logging.Formatter(LOG_FORMAT))

# ۲. تنظیمات لاگ کنسول (فقط اطلاعات مهم INFO)
# کنسول را با لاگ‌های DEBUG شلوغ نمی‌کنیم
console_handler = logging.StreamHandler(sys.stdout)
console_handler.setLevel(logging.INFO)  # فقط اطلاعات مهم در کنسول نمایش داده شود
console_handler.setFormatter(logging.Formatter(LOG_FORMAT))

# ۳. تنظیم لاگر اصلی (Root Logger)
# به جای basicConfig، لاگر اصلی را مستقیماً تنظیم می‌کنیم
root_logger = logging.getLogger()
root_logger.setLevel(logging.DEBUG)  # سطح اصلی باید DEBUG باشد تا همه چیز را بگیرد
root_logger.addHandler(file_handler)
root_logger.addHandler(console_handler)

# ۴. ساکت کردن لاگ‌های پرسروصدای کتابخانه‌ها
# لاگ‌های telethon و httpx (که PTB استفاده می‌کند) را روی WARNING تنظیم می‌کنیم
logging.getLogger('telethon').setLevel(logging.WARNING)
logging.getLogger('httpx').setLevel(logging.WARNING)

# ۵. تعریف لاگر مخصوص این ماژول
logger = logging.getLogger(__name__)

# --- پایان تنظیمات لاگ‌نویسی ---


def acquire_lock():
    """جلوگیری از اجرای همزمان (در صورت پشتیبانی سیستم‌عامل)."""
    
    # اگر روی ویندوز هستیم یا fcntl ایمپورت نشده، قفل را نادیده بگیر
    if not fcntl:
        logger.warning("File locking is disabled on this OS (Windows or fcntl not found).")
        return None  # None به معنی "بدون قفل" است

    # اگر روی لینوکس/مک هستیم، تلاش کن قفل کنی
    lock_file = open("/tmp/bot.lock", "w")
    try:
        fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        logger.info("File lock acquired.")
        return lock_file
    except IOError:
        logger.error("Another instance of the bot is already running. Exiting...")
        sys.exit(1)
    except Exception as e:
        logger.error(f"An error occurred while acquiring file lock: {e}")
        return None


async def main():
    """تابع اصلی اجرای ربات با مدیریت خطا."""
    lock = None
    try:
        # کسب قفل برای جلوگیری از اجرای همزمان
        lock = acquire_lock()
        
        logger.info("Starting the bot...")
        await run_bot()
        
    except KeyboardInterrupt:
        logger.info("Bot stopped by user (KeyboardInterrupt)")
    except Exception as e:
        # ثبت خطای بحرانی که باعث توقف کامل ربات شده
        logger.critical(f"Unexpected critical error in main: {e}", exc_info=True)
        
    finally:
        # اطمینان از خاموش شدن صحیح بات
        logger.info("Initiating bot shutdown...")
        await shutdown()
        
        # فقط در صورتی قفل را آزاد کن که با موفقیت کسب شده باشد
        if lock and fcntl:
            try:
                fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
                lock.close()
                logger.info("Lock file released.")
            except Exception as e:
                logger.error(f"Error releasing lock file: {e}")
        elif lock:
            lock.close()


if __name__ == "__main__":
    asyncio.run(main())
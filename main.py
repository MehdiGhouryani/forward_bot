import asyncio
import logging
import logging.handlers
import sys
import os  # os را برای بررسی سیستم‌عامل اضافه می‌کنیم

# fcntl را فقط در صورتی import می‌کنیم که ویندوز نباشد
if os.name != 'nt':
    try:
        import fcntl
    except ImportError:
        fcntl = None
        logging.warning("fcntl module not found, file locking disabled.")
else:
    fcntl = None
    logging.info("Running on Windows, file locking (fcntl) is disabled.")

from bot import run_bot, shutdown

LOG_FILE = 'bot.log'
MAX_BYTES = 1024 * 1024 * 5  # 5 MB
BACKUP_COUNT = 3

file_handler = logging.handlers.RotatingFileHandler(
    LOG_FILE,
    maxBytes=MAX_BYTES,
    backupCount=BACKUP_COUNT,
    encoding='utf-8'
)
file_handler.setLevel(logging.INFO)

console_handler = logging.StreamHandler()
console_handler.setLevel(logging.INFO)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(name)s - %(message)s',
    handlers=[file_handler, console_handler]
)

logging.getLogger('telethon').setLevel(logging.WARNING)

logger = logging.getLogger(__name__)

def acquire_lock():
    """جلوگیری از اجرای همزمان (در صورت پشتیبانی سیستم‌عامل)."""
    
    # اگر روی ویندوز هستیم یا fcntl ایمپورت نشده، قفل را نادیده بگیر
    if not fcntl:
        logger.warning("File locking is disabled on this OS. (os.name != 'nt' or fcntl not found)")
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
    lock = None
    try:
        # کسب قفل برای جلوگیری از اجرای همزمان
        lock = acquire_lock()
        
        logger.info("Starting the bot...")
        print("Starting the bot...")  # حفظ پرینت برای کنسول
        await run_bot()
        
    except KeyboardInterrupt:
        logger.info("Bot stopped by user (KeyboardInterrupt)")
        print("Bot stopped by user (KeyboardInterrupt)")
    except Exception as e:
        logger.error(f"Unexpected error in main: {e}", exc_info=True)
        print(f"Unexpected error in main: {e}")
        # raise (اختیاری: می‌توانید این را کامنت کنید تا در صورت خطا، ربات نمیرد)
        
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
            lock.close() # اگر fcntl نبود ولی فایل باز شده بود (گرچه نباید اتفاق بیفتد)

if __name__ == "__main__":
    asyncio.run(main())
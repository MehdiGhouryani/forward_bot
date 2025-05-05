# main.py

import asyncio
import logging
from bot import run_bot
from config import LOG_FILE

# تنظیم لاگینگ برای فایل main
logging.basicConfig(
    filename=LOG_FILE,
    level=logging.DEBUG,  # تغییر از INFO به DEBUG
    format='%(asctime)s - %(levelname)s - %(name)s - %(message)s',
    encoding='utf-8'
)

async def main():
    try:
        logging.info("Starting the bot...")
        await run_bot()
    except KeyboardInterrupt:
        logging.info("Bot stopped by user (KeyboardInterrupt)")
    except Exception as e:
        logging.error(f"Unexpected error in main: {e}", exc_info=True)
        raise
    finally:
        # تأخیر کوتاه برای اطمینان از بسته شدن همه منابع
        await asyncio.sleep(1)

if __name__ == "__main__":
    asyncio.run(main())
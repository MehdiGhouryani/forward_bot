# main.py
import asyncio
import logging
from bot import run_bot
from config import LOG_FILE

# تنظیم لاگینگ برای فایل main
logging.basicConfig(
    filename=LOG_FILE,
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(name)s - %(message)s',
    encoding='utf-8'
)

logger = logging.getLogger(__name__)

async def main():
    try:
        logger.info("Starting the bot...")
        await run_bot()
    except KeyboardInterrupt:
        logger.info("Bot stopped by user (KeyboardInterrupt)")
    except Exception as e:
        logger.error(f"Unexpected error in main: {e}", exc_info=True)
        raise

if __name__ == "__main__":
    asyncio.run(main())
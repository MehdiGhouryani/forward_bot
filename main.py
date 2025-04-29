import asyncio
import logging
import time
from bot import run_bot

logger = logging.getLogger(__name__)

if __name__ == "__main__":
    time.sleep(1)
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s',
        encoding='utf-8',
        handlers=[
            logging.FileHandler('bot.log', encoding='utf-8'),
            logging.StreamHandler()
        ]
    )
    time.sleep(0.5)
    logging.getLogger('telethon').setLevel(logging.WARNING)
    time.sleep(0.5)
    try:
        time.sleep(1)
        asyncio.run(run_bot())
    except KeyboardInterrupt:
        logger.info("Bot stopped by user")
        time.sleep(1)
    except Exception as e:
        logger.critical(f"Unexpected error in main: {e}", exc_info=True)
        time.sleep(1)
        raise
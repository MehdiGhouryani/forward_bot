import logging
import time

def setup_logging():
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
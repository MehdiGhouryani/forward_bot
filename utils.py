import logging

def setup_logging():
    """تنظیم لاگ‌ها برای فایل و کنسول"""
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s',
        encoding='utf-8',
        handlers=[
            logging.FileHandler('bot.log', encoding='utf-8'),
            logging.StreamHandler()
        ]
    )
    logging.getLogger('telethon').setLevel(logging.WARNING)

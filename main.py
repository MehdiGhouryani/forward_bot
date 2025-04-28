# main.py
import logging
import asyncio
from forwarder import run_bot

if __name__ == "__main__":
    try:
        # شروع ربات
        asyncio.run(run_bot())
    except KeyboardInterrupt:
        # در صورتی که ربات توسط کاربر متوقف شودx    
        logging.info("Bot stopped by user")
    except Exception as e:
        # در صورتی که خطای غیرمنتظره‌ای رخ دهد
        logging.error(f"Unexpected error: {e}")

# main.py
import asyncio
import logging
import signal # برای مدیریت سیگنال‌های توقف
from config import LOG_FILE
from bot import run_bot_main # وارد کردن تابع اصلی جدید
from utils import setup_logging # وارد کردن تابع تنظیم لاگ

# تنظیم لاگ در ابتدای برنامه
setup_logging(LOG_FILE)
logger = logging.getLogger(__name__)

async def main():
    """تابع اصلی async که run_bot_main را اجرا می‌کند و سیگنال‌های توقف را مدیریت می‌کند."""
    loop = asyncio.get_running_loop()
    stop_event = asyncio.Event()

    # تعریف handler برای سیگنال‌های توقف (Ctrl+C, kill)
    def signal_handler():
        logger.info("Received termination signal. Setting stop event...")
        stop_event.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            # اضافه کردن handler به event loop
            loop.add_signal_handler(sig, signal_handler)
        except NotImplementedError:
            # در ویندوز add_signal_handler ممکن است پشتیبانی نشود
            # signal.signal(sig, lambda s, f: signal_handler()) # روش جایگزین (ممکن است در async خوب کار نکند)
            logger.warning(f"Could not set signal handler for {sig}. Use Ctrl+C if possible.")


    # اجرای تابع اصلی ربات
    main_task = asyncio.create_task(run_bot_main())

    # منتظر ماندن برای سیگنال توقف یا اتمام تسک اصلی
    await asyncio.wait([main_task, stop_event.wait()], return_when=asyncio.FIRST_COMPLETED)

    # اگر تسک اصلی هنوز در حال اجراست و سیگنال توقف دریافت شده، آن را cancel کنید
    if not main_task.done() and stop_event.is_set():
        logger.info("Cancelling main bot task due to stop signal...")
        main_task.cancel()
        try:
            await main_task # منتظر ماندن برای اتمام عملیات cancel
        except asyncio.CancelledError:
            logger.info("Main bot task successfully cancelled.")
        except Exception as e:
             logger.error(f"Error during main task cancellation: {e}", exc_info=True)

    logger.info("Main execution finished.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        # این قسمت معمولا توسط signal handler مدیریت می‌شود، اما برای اطمینان
        logger.info("KeyboardInterrupt caught in __main__. Exiting.")
    except Exception as e:
        logger.critical(f"Critical error at top level: {e}", exc_info=True)
# utils.py
import logging
import os # برای ایجاد پوشه لاگ در صورت نیاز

def setup_logging(log_file_path='bot.log'):
    """پیکربندی سیستم لاگ برنامه."""
    log_level = logging.INFO # می‌توانید به DEBUG تغییر دهید برای جزئیات بیشتر
    log_format = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'

    # اطمینان از وجود پوشه برای فایل لاگ
    log_dir = os.path.dirname(log_file_path)
    if log_dir and not os.path.exists(log_dir):
        try:
            os.makedirs(log_dir)
        except OSError as e:
            print(f"Warning: Could not create log directory '{log_dir}'. Error: {e}")
            # ادامه کار بدون فایل لاگ اگر پوشه ساخته نشد

    # ایجاد handlers
    handlers = [
        logging.StreamHandler() # خروجی در کنسول
    ]
    try:
        # اضافه کردن handler فایل فقط اگر مسیر معتبر است یا ساخته شده
        if not log_dir or os.path.exists(log_dir):
            file_handler = logging.FileHandler(log_file_path, encoding='utf-8')
            file_handler.setFormatter(logging.Formatter(log_format))
            handlers.append(file_handler)
    except Exception as e:
         print(f"Warning: Could not set up file logging to '{log_file_path}'. Error: {e}")


    # تنظیمات پایه لاگ
    logging.basicConfig(
        level=log_level,
        format=log_format,
        handlers=handlers
    )

    # کاهش سطح لاگ کتابخانه telethon برای جلوگیری از لاگ‌های زیاد و غیرضروری
    logging.getLogger('telethon').setLevel(logging.WARNING)

    # لاگ اولیه برای تایید تنظیمات
    logging.info("Logging setup complete.")
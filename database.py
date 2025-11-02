# database.py
import aiosqlite
import logging  # ایمپورت کردن لاگ

# لاگر حرفه‌ای مخصوص این ماژول
logger = logging.getLogger(__name__)

DB_NAME = 'bot_settings.db'

async def init_db(secondary_channel_id):
    """پایگاه داده aiosqlite را راه‌اندازی می‌کند."""
    try:
        async with aiosqlite.connect(DB_NAME) as db:
            await db.execute('''
                CREATE TABLE IF NOT EXISTS settings (
                    id INTEGER PRIMARY KEY,
                    secondary_channel_id INTEGER,
                    start_time INTEGER,
                    expiry_time INTEGER
                )
            ''')
            # اطمینان از اینکه ردیف پیش‌فرض فقط در صورت عدم وجود درج می‌شود
            await db.execute(
                "INSERT OR IGNORE INTO settings (id, secondary_channel_id, start_time, expiry_time) VALUES (1, ?, 0, 0)",
                (secondary_channel_id,)
            )
            await db.execute('''
                CREATE TABLE IF NOT EXISTS token_votes (
                    message_id INTEGER PRIMARY KEY,
                    chat_id INTEGER,
                    token_address TEXT,
                    green_votes INTEGER DEFAULT 0,
                    red_votes INTEGER DEFAULT 0
                )
            ''')
            await db.execute('''
                CREATE TABLE IF NOT EXISTS user_votes (
                    message_id INTEGER,
                    user_id INTEGER,
                    vote_type TEXT,
                    PRIMARY KEY (message_id, user_id)
                )
            ''')
            await db.commit()
        # لاگ‌ها به logger تغییر کردند
        logger.info("Async SQLite database initialized (including vote tables)")
    except aiosqlite.Error as e:
        logger.error(f"Async SQLite error in init_db: {e}")

async def save_settings(secondary_channel_id, start_time, expiry_time):
    """تنظیمات کانال دوم را به صورت async ذخیره می‌کند."""
    try:
        async with aiosqlite.connect(DB_NAME) as db:
            await db.execute(
                "UPDATE settings SET secondary_channel_id = ?, start_time = ?, expiry_time = ? WHERE id = 1",
                (secondary_channel_id, start_time, expiry_time)
            )
            await db.commit()
        logger.info(f"Async settings saved: start={start_time}, expiry={expiry_time}")
    except aiosqlite.Error as e:
        logger.error(f"Async SQLite error in save_settings: {e}")

async def load_settings():
    """تنظیمات کانال دوم را به صورت async بارگیری می‌کند."""
    try:
        async with aiosqlite.connect(DB_NAME) as db:
            async with db.execute('SELECT secondary_channel_id, start_time, expiry_time FROM settings WHERE id = 1') as cursor:
                result = await cursor.fetchone()
                if result:
                    logger.debug(f"Loaded settings from DB: {result}")
                    return {'secondary_channel_id': result[0], 'start_time': result[1], 'expiry_time': result[2]}
                else:
                    logger.warning("Could not find settings in DB (row id=1 missing).")
    except aiosqlite.Error as e:
        logger.error(f"Async SQLite error in load_settings: {e}")
    
    # در صورت خطا یا عدم وجود ردیف، مقدار پیش‌فرض را برگردانید
    logger.warning("Returning default settings.")
    from config import SECONDARY_CHANNEL_ID
    return {'secondary_channel_id': SECONDARY_CHANNEL_ID, 'start_time': 0, 'expiry_time': 0}

async def register_message_in_votes(message_id, chat_id, token_address):
    """پیام جدید را برای رای‌گیری در DB ثبت می‌کند."""
    try:
        async with aiosqlite.connect(DB_NAME) as db:
            await db.execute(
                "INSERT OR IGNORE INTO token_votes (message_id, chat_id, token_address) VALUES (?, ?, ?)",
                (message_id, chat_id, token_address)
            )
            await db.commit()
        logger.debug(f"Message {message_id} registered in votes DB.")
    except aiosqlite.Error as e:
        logger.error(f"Async SQLite error in register_message_in_votes for Msg {message_id}: {e}")

async def process_vote(message_id, user_id, vote_type):
    """رای کاربر را پردازش و شمارش جدید را برمی‌گرداند."""
    try:
        async with aiosqlite.connect(DB_NAME) as db:
            # ۱. بررسی رای قبلی
            async with db.execute("SELECT vote_type FROM user_votes WHERE message_id = ? AND user_id = ?", (message_id, user_id)) as cursor:
                existing_vote = await cursor.fetchone()

            if existing_vote:
                if existing_vote[0] == vote_type:
                    logger.debug(f"User {user_id} voted {vote_type} again for Msg {message_id}. No change.")
                    return None  # رای تکراری
                else:
                    # تغییر رای
                    await db.execute("UPDATE user_votes SET vote_type = ? WHERE message_id = ? AND user_id = ?", (vote_type, message_id, user_id))
                    logger.info(f"User {user_id} changed vote to {vote_type} for Msg {message_id}")
            else:
                # رای جدید
                await db.execute("INSERT INTO user_votes (message_id, user_id, vote_type) VALUES (?, ?, ?)", (message_id, user_id, vote_type))
                logger.info(f"User {user_id} cast new vote {vote_type} for Msg {message_id}")
            
            await db.commit()

            # ۲. شمارش مجدد
            async with db.execute("SELECT COUNT(*) FROM user_votes WHERE message_id = ? AND vote_type = 'green'", (message_id,)) as cursor:
                green_votes = (await cursor.fetchone())[0]
            async with db.execute("SELECT COUNT(*) FROM user_votes WHERE message_id = ? AND vote_type = 'red'", (message_id,)) as cursor:
                red_votes = (await cursor.fetchone())[0]

            # ۳. آپدیت جدول اصلی
            await db.execute("UPDATE token_votes SET green_votes = ?, red_votes = ? WHERE message_id = ?", (green_votes, red_votes, message_id))
            await db.commit()

            logger.debug(f"Vote counts updated for Msg {message_id}: G={green_votes}, R={red_votes}")
            return green_votes, red_votes

    except aiosqlite.Error as e:
        logger.error(f"Async SQLite error in process_vote for Msg {message_id}: {e}")
        return "error"

async def get_token_address_for_message(message_id):
    """آدرس قرارداد را برای بازسازی دکمه‌ها از DB می‌خواند."""
    try:
        async with aiosqlite.connect(DB_NAME) as db:
            async with db.execute("SELECT token_address FROM token_votes WHERE message_id = ?", (message_id,)) as cursor:
                token_row = await cursor.fetchone()
                if token_row:
                    return token_row[0]
                else:
                    logger.warning(f"No token_address found in DB for Msg {message_id}")
                    return None
    except aiosqlite.Error as e:
        logger.error(f"Async SQLite error in get_token_address_for_message for Msg {message_id}: {e}")
        return None
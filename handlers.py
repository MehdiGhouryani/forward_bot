# handlers.py
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes
from config import *
import pytz
import re
from datetime import datetime, timedelta
import logging  # ایمپورت کردن لاگ
import traceback
import time
from database import save_settings, load_settings, process_vote, get_token_address_for_message

# لاگر حرفه‌ای مخصوص این ماژول
logger = logging.getLogger(__name__)

async def set_secondary(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """دستور ادمین برای تنظیم کانال دوم برای مدت زمان مشخص."""
    # لاگ‌ها به logger تغییر کردند
    logger.debug(f"Received /set_secondary command from user {update.effective_user.id}")
    user_id = update.effective_user.id
    if user_id not in ADMIN_IDS:
        logger.warning(f"Unauthorized access attempt by user {user_id}")
        await update.message.reply_text("شما دسترسی به این دستور ندارید.")
        return

    try:
        args = context.args
        logger.debug(f"Arguments for /set_secondary: {args}")
        if len(args) != 2:
            await update.message.reply_text("لطفاً دستور را به‌صورت: /set_secondary <مدت زمان> <ساعت شروع> وارد کنید\nمثال: /set_secondary 4h 14:00")
            return
        
        duration_str, start_time_str = args
        duration_match = re.match(r'(\d+)(h|m)', duration_str)
        if not duration_match:
            await update.message.reply_text("مدت زمان باید به‌صورت عددی با واحد h (ساعت) یا m (دقیقه) باشد. مثال: 4h")
            return
        duration_value, unit = duration_match.groups()
        duration_seconds = int(duration_value) * (3600 if unit == 'h' else 60)

        time_match = re.match(r'(\d{1,2}):(\d{2})', start_time_str)
        if not time_match:
            await update.message.reply_text("ساعت شروع باید به‌صورت HH:MM باشد. مثال: 14:00")
            return
        hour, minute = map(int, time_match.groups())
        if not (0 <= hour <= 23 and 0 <= minute <= 59):
            await update.message.reply_text("ساعت شروع نامعتبر است. باید بین 00:00 و 23:59 باشد.")
            return

        now = datetime.now(pytz.UTC)
        start_time = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if start_time < now:
            start_time += timedelta(days=1)
        start_timestamp = int(start_time.timestamp())
        expiry_timestamp = start_timestamp + duration_seconds

        await save_settings(SECONDARY_CHANNEL_ID, start_timestamp, expiry_timestamp)
        await update.message.reply_text(
            f"کانال دوم فعال شد.\nشروع: {start_time.strftime('%Y-%m-%d %H:%M')}\nپایان: {(start_time + timedelta(seconds=duration_seconds)).strftime('%Y-%m-%d %H:%M')}"
        )
        logger.info(f"Admin {user_id} set secondary channel: start={start_timestamp}, expiry={expiry_timestamp}")
    except Exception as e:
        await update.message.reply_text("خطا در پردازش دستور. لطفاً دوباره تلاش کنید.")
        logger.error(f"Error in set_secondary: {e}\n{traceback.format_exc()}")

async def stop_secondary(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """دستور ادمین برای توقف فوری ارسال به کانال دوم."""
    logger.debug(f"Received /stop_secondary command from user {update.effective_user.id}")
    user_id = update.effective_user.id
    if user_id not in ADMIN_IDS:
        logger.warning(f"Unauthorized access attempt by user {user_id}")
        await update.message.reply_text("شما دسترسی به این دستور ندارید.")
        return
    await save_settings(SECONDARY_CHANNEL_ID, 0, 0)
    await update.message.reply_text("ارسال به کانال دوم متوقف شد.")
    logger.info(f"Admin {user_id} stopped secondary channel")

async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """دستور ادمین برای بررسی وضعیت فعلی کانال دوم."""
    logger.debug(f"Received /status command from user {update.effective_user.id}")
    user_id = update.effective_user.id
    if user_id not in ADMIN_IDS:
        logger.warning(f"Unauthorized access attempt by user {user_id}")
        await update.message.reply_text("شما دسترسی به این دستور ندارید.")
        return
    settings = await load_settings()
    current_time = int(time.time())
    if settings['start_time'] <= current_time <= settings['expiry_time']:
        start_time = datetime.fromtimestamp(settings['start_time'], pytz.UTC)
        expiry_time = datetime.fromtimestamp(settings['expiry_time'], pytz.UTC)
        await update.message.reply_text(
            f"کانال دوم فعال است.\nشروع: {start_time.strftime('%Y-%m-%d %H:%M')}\nپایان: {expiry_time.strftime('%Y-%m-%d %H:%M')}"
        )
    else:
        await update.message.reply_text("کانال دوم غیرفعال است.")
    logger.info(f"Admin {user_id} checked status")

async def handle_vote(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """هندلر بازنویسی شده برای رای‌گیری (Async)."""
    query = update.callback_query
    if not query:
        logger.warning("handle_vote called without callback_query.")
        return

    user_id = query.from_user.id
    message_id = query.message.message_id
    chat_id = query.message.chat.id
    vote_type = query.data.split('_')[1]

    logger.debug(f"Vote received: User {user_id} voted {vote_type} on Msg {message_id} in Chat {chat_id}")

    try:
        # ۱. پردازش رای در دیتابیس
        vote_result = await process_vote(message_id, user_id, vote_type)

        if vote_result is None:
            await query.answer("شما قبلاً رای خود را ثبت کرده‌اید")
            logger.debug(f"User {user_id} already voted {vote_type} for Msg {message_id}. No change.")
            return
        if vote_result == "error":
            await query.answer("خطا در ثبت رای.")
            logger.error(f"process_vote returned 'error' for Msg {message_id}")
            return

        green_votes, red_votes = vote_result
        logger.info(f"Vote processed for Msg {message_id}. New counts: G={green_votes}, R={red_votes}")

        # ۲. بازسازی دکمه‌ها
        token_address = await get_token_address_for_message(message_id)
        if not token_address:
            logger.warning(f"Could not find token_address for Msg {message_id} during vote update.")
            await query.answer("خطا در بازخوانی اطلاعات.")
            return

        keyboard = [
            [InlineKeyboardButton("📈 مشاهده نمودار (Dex)", url=f"https://dexscreener.com/bsc/{token_address}")],
            [InlineKeyboardButton("🔍 بررسی در اکسیوم (Axiom)", url=f"https://axiom.app/contract/{token_address}")],
            [InlineKeyboardButton("💰 ترید کن سولانا هدیه بگیر", url=GIFT)],
            [InlineKeyboardButton("📚 آموزش آکسیوم", url=AXIOM_LINK), 
             InlineKeyboardButton("❓ سوالتون اینجا بپرسید", url=SUPPORT_LINK)],
            [
                InlineKeyboardButton(f"🟢 ({green_votes})", callback_data="vote_green"),
                InlineKeyboardButton(f"🔴 ({red_votes})", callback_data="vote_red")
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        # ۳. ویرایش پیام
        await context.bot.edit_message_reply_markup(
            chat_id=chat_id,
            message_id=message_id,
            reply_markup=reply_markup
        )
        await query.answer("رای شما ثبت شد!")

    except Exception as e:
        logger.error(f"Error handling vote for Msg {message_id}: {e}\n{traceback.format_exc()}")
        try:
            await query.answer("خطایی رخ داد. لطفاً دوباره تلاش کنید.")
        except Exception as query_e:
            logger.error(f"Failed to even answer query: {query_e}")
# parser.py
import re
import logging
from telethon.tl.types import MessageEntityTextUrl
import traceback


def transform_message(message_text, message_entities):
    """پیام خام ورودی را بر اساس الگوی جدید 🥞 تجزیه و به فرمت فارسی تبدیل می‌کند."""
    logging.info("Starting message transformation")
    logging.debug(f"Raw input message: {message_text[:100]}...")

    pattern = r"""
        🥞\s*(0x[a-fA-F0-9]{40})\s*\n
        🚨[🚨\s]*\n
        \n
        ┌([^\(]+)\s*\(([^\)]+)\)\s*\n
        ├USD:\s*\$([\d\.]+)\s*\n
        ├MC:\s*\$([\d\.KMB]+)\s*\n
        ├Vol:\s*\$([\d\.KMB]+)\s*\n
        ├Seen:\s*([^\n]+)\s*\n
        ├Dex:\s*([^\n]+)\s*\n
        ├Dex\ Paid:\s*([🔴🟢])\s*\n
        ├CA\ Verified:\s*([🔴🟢])\s*\n
        ├Tax:\s*([^\n]+)\s*\n
        ├Honeypot:\s*([^\n]+)\s*\n
        ├Holder:\s*Top\ 10:\s*([🟡🟢])\s*(\d+%)\s*\n
        └TH:\s*([^\n]+)\s*\n
        \n
        🔎[^\n]*\n
        [^\n]*\n
        \n
        📈\s*Chart:\s*\[\]\((https://mevx\.io/[^\s?]+(?:\?[^\)\s]*)?)\)[ \t]*
        (?:\n\n(🔥[^\n]+))?
    """
    match = re.match(pattern, message_text, re.VERBOSE | re.DOTALL)
    if not match:
        logging.warning(f"Message does not match new 🥞 pattern: {message_text[:50]}...")
        return None, None, None, None, None

    try:
        groups = match.groups()
        token_address = groups[0]
        token_name = groups[1].strip()
        token_symbol = groups[2].strip()
        usd = groups[3]
        mc = groups[4]
        vol = groups[5]
        seen = groups[6]
        dex = groups[7]
        dex_paid = groups[8]
        ca_verified = groups[9]
        tax = groups[10]
        honeypot = groups[11]
        holder_color = groups[12]
        holder_percentage = groups[13]
        th_values_str = groups[14].strip()
        chart_url = groups[15] # لینک mevx.io
        x_info = groups[16] # بلاک اختیاری 🔥

        th_numeric_values = []
        if th_values_str:
            th_items = th_values_str.split("|")
            for item in th_items[:10]: # پردازش ۱۰ هولدر
                item_stripped = item.strip()
                th_numeric_values.append(item_stripped or "0")
        logging.info(f"Extracted TH numeric values: {th_numeric_values}")

        while len(th_numeric_values) < 10:
            th_numeric_values.append("0")

        th_text = "|".join(th_numeric_values)
        logging.info(f"Formatted TH text for output: {th_text}")

        new_message = (
            f"⚡️ <code>{token_address}</code>\n"
            f"• {token_name} ({token_symbol})\n"
            f"• قیمت:      ${usd}\n"
            f"• مارکت‌کپ:     ${mc}\n"
            f"• حجم:      ${vol}\n"
            f"• ساخته شده:      {seen}\n"
            f"• نقدینگی:      {dex}\n"
            f"• دکس پرداخت شده؟: {dex_paid}\n"
            f"• قرارداد تایید شده؟: {ca_verified}\n"
            f"• مالیات: {tax}\n"
            f"• هانی‌پات: {honeypot}\n"
            f"• هولدرها:     Top 10: {holder_color} {holder_percentage}\n"
            f"• تاپ هولدر:      {th_text}"
        )

        if x_info:
            new_message += f"\n\n{x_info.strip()}"

        if len(new_message) > 4096:
            logging.error(f"Transformed message too long: {len(new_message)} characters. Truncating.")
            new_message = new_message[:4090] + "..."

        # در فاز ۱، هیچ Entity برای متن پیام ارسال نمی‌کنیم.
        new_entities = []
        
        # th_pairs دیگر حاوی لینک نیست، فقط برای سازگاری با صف ارسال می‌شود.
        # در فازهای بعدی می‌توان این را حذف کرد.
        th_pairs = [(val, None) for val in th_numeric_values]

        logging.debug(f"Final entities for output: {new_entities}")
        # آدرس قرارداد (token_address) برای فاز ۲ بازگردانده می‌شود
        return new_message, new_entities, chart_url, th_pairs, token_address

    except Exception as e:
        logging.error(f"Unhandled error in transform_message: {e}\n{traceback.format_exc()}")
        return None, None, None, None, None

def entities_to_html(entities, text):
    """لیست Entity تلتون را به متن HTML برای ارسال با python-telegram-bot تبدیل می‌کند."""
    if not entities:
        # اگر Entity وجود ندارد، متن را HTML در نظر نمی‌گیریم
        # اما چون ما از <code> استفاده می‌کنیم، باید HTML باشد
        return text, "HTML"

    html_text = text
    offset_adjustment = 0

    for entity in sorted(entities, key=lambda e: e.offset):
        start = entity.offset + offset_adjustment
        end = start + entity.length
        entity_text = html_text[start:end]

        if isinstance(entity, MessageEntityTextUrl):
            html_entity = f'<a href="{entity.url}">{entity_text}</a>'
            html_text = html_text[:start] + html_entity + html_text[end:]
            offset_adjustment += len(html_entity) - len(entity_text)

    return html_text, "HTML"
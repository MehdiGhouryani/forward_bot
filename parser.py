# parser.py
import re
import logging
from telethon.tl.types import MessageEntityTextUrl
import traceback

# لاگر حرفه‌ای مخصوص این ماژول
logger = logging.getLogger(__name__)

# --- توابع کمکی برای تجزیه هر خط ---
# این توابع کوچک به ما اجازه می‌دهند هر خط را جداگانه مدیریت کنیم

def _parse_token_name(line):
    """ '┌JUDICA (JUDICA) (...)' را تجزیه می‌کند """
    match = re.search(r'┌([^\(]+)\s*\(([^\)]+)\)', line)
    if match:
        return match.group(1).strip(), match.group(2).strip()
    return 'N/A', 'N/A'

def _parse_usd(line):
    """ '├USD: $0.0002268' را تجزیه می‌کند """
    match = re.search(r'\$([\d\.]+)', line)
    return match.group(1) if match else 'N/A'

def _parse_mc_vol(line):
    """ '├MC: $226.8K' یا '├Vol: $88.2K' را تجزیه می‌کند """
    match = re.search(r'\$([\d\.KMB]+)', line)
    return match.group(1) if match else 'N/A'

def _parse_simple_text(line, prefix):
    """ متن ساده بعد از پیشوند را برمی‌گرداند (برای Seen, Dex, Tax, Honeypot) """
    return line.replace(prefix, '').strip()

def _parse_emoji_status(line):
    """ ایموجی 🔴 یا 🟢 را برمی‌گرداند """
    if '🔴' in line: return '🔴'
    if '🟢' in line: return '🟢'
    return 'N/A'

def _parse_holder(line):
    """ '├Holder: Top 10: 🟡 55%' را تجزیه می‌کند """
    match = re.search(r'Top 10:\s*([🟡🟢])\s*(\d+%)', line)
    if match:
        return match.group(1), match.group(2)
    return 'N/A', 'N/A'

def _parse_th(line):
    """ '└TH: 13.3% (...)| 6.3% ...' را تجزیه می‌کند و فقط درصدها را برمی‌گرداند """
    # تمام درصدها را پیدا کن (حتی اگر لینک داشته باشند)
    percentages = re.findall(r'([\d\.]+\%?)', line)
    # ۱۰ تای اول را بردار
    top_ten = [p.strip() for p in percentages[:10] if p.strip()]
    # اگر کمتر از ۱۰ تا بود، با '0' پر کن
    while len(top_ten) < 10:
        top_ten.append("0")
    return top_ten

def _parse_chart(line):
    """ '📈 Chart: https://mevx.io/...' را تجزیه می‌کند """
    match = re.search(r'(https://mevx\.io/[^\s]+)', line)
    return match.group(1) if match else None

# --- تابع اصلی تجزیه‌کننده ---

def transform_message(message_text, message_entities):
    """
    پیام خام ورودی را به صورت خط به خط تجزیه می‌کند
    تا در برابر تغییرات فرمت مقاوم باشد.
    """
    logger.debug(f"Starting NEW line-by-line transformation...")
    
    # دیکشنری برای نگهداری داده‌های استخراج شده
    data = {}
    # مقادیر پیش‌فرض برای جلوگیری از خطا
    th_values = ["0"] * 10
    x_info = None

    try:
        lines = message_text.split('\n')

        # --- اعتبارسنجی اولیه ---
        if not lines or not lines[0].startswith("🥞"):
            logger.warning("Message does not start with 🥞 trigger. Skipping.")
            return None, None, None, None, None
        
        # --- استخراج خط اول (آدرس) ---
        data['token_address'] = lines[0].replace('🥞', '').strip()
        if not re.match(r'^(0x[a-fA-F0-9]{40})$', data['token_address']):
             logger.warning(f"Failed to parse Token Address: {lines[0]}")
             data['token_address'] = 'Error' # اگر آدرس بد بود، خطا بزن

        # --- حلقه اصلی تجزیه خط به خط ---
        for line in lines[1:]: # از خط دوم شروع کن
            line = line.strip()
            if not line:
                continue

            try:
                if line.startswith('┌'):
                    data['token_name'], data['token_symbol'] = _parse_token_name(line)
                elif line.startswith('├USD:'):
                    data['usd'] = _parse_usd(line)
                elif line.startswith('├MC:'):
                    data['mc'] = _parse_mc_vol(line)
                elif line.startswith('├Vol:'):
                    data['vol'] = _parse_mc_vol(line)
                elif line.startswith('├Seen:'):
                    data['seen'] = _parse_simple_text(line, '├Seen:')
                elif line.startswith('├Dex:'):
                    data['dex'] = _parse_simple_text(line, '├Dex:')
                elif line.startswith('├Dex Paid:'):
                    data['dex_paid'] = _parse_emoji_status(line)
                elif line.startswith('├CA Verified:'):
                    data['ca_verified'] = _parse_emoji_status(line)
                elif line.startswith('├Tax:'):
                    data['tax'] = _parse_simple_text(line, '├Tax:')
                elif line.startswith('├Honeypot:'):
                    data['honeypot'] = _parse_simple_text(line, '├Honeypot:')
                elif line.startswith('├Holder:'):
                    data['holder_color'], data['holder_percentage'] = _parse_holder(line)
                elif line.startswith('└TH:'):
                    th_values = _parse_th(line)
                elif line.startswith('📈 Chart:'):
                    data['chart_url'] = _parse_chart(line)
                elif line.startswith('🔥'):
                    x_info = line # ذخیره کردن خط اطلاعات X (اگر وجود داشته باشد)
            
            except Exception as e:
                # اگر تجزیه یک خط شکست خورد، فقط لاگ کن و ادامه بده
                logger.warning(f"Failed to parse line: '{line}'. Error: {e}")

        # --- قالب‌بندی پیام خروجی ---
        
        # اطمینان از اینکه مقادیر کلیدی وجود دارند
        token_address = data.get('token_address', 'N/A')
        token_name = data.get('token_name', 'N/A')
        token_symbol = data.get('token_symbol', '?')
        usd = data.get('usd', '?')
        mc = data.get('mc', '?')
        vol = data.get('vol', '?')
        seen = data.get('seen', '?')
        dex = data.get('dex', '?')
        dex_paid = data.get('dex_paid', '?')
        ca_verified = data.get('ca_verified', '?')
        tax = data.get('tax', '?')
        honeypot = data.get('honeypot', '?')
        holder_color = data.get('holder_color', '?')
        holder_percentage = data.get('holder_percentage', '?')
        th_text = "|".join(th_values)
        chart_url = data.get('chart_url') # اگر نبود باید None باشد

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
            logger.error(f"Transformed message too long: {len(new_message)} characters. Truncating.")
            new_message = new_message[:4090] + "..."

        # --- آماده‌سازی خروجی (سازگار با bot.py) ---
        new_entities = []
        th_pairs = [(val, None) for val in th_values]

        logger.info(f"Message successfully parsed (line-by-line): {token_address}")
        
        return new_message, new_entities, chart_url, th_pairs, token_address

    except Exception as e:
        logger.critical(f"CRITICAL error in transform_message: {e}\n{traceback.format_exc()}")
        logger.error(f"--- FAILED MESSAGE (CRITICAL) ---\n{message_text}\n--- END ---")
        return None, None, None, None, None


def entities_to_html(entities, text):
    """(بدون تغییر) لیست Entity تلتون را به متن HTML برای ارسال با python-telegram-bot تبدیل می‌کند."""
    if not entities:
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
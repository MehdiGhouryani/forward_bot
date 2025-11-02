import re
import logging
from telethon.tl.types import MessageEntityTextUrl
import traceback


logger = logging.getLogger(__name__)

# --- توابع کمکی برای تجزیه هر خط (اصلاح شده) ---

def _parse_token_name(line):
    """
    '┌JUDICA (JUDICA) (https://...)' را تجزیه می‌کند
    [اصلاح شده] اکنون URL را نیز برمی‌گرداند.
    """
    match = re.search(r'┌([^\(]+)\s*\(([^\)]+)\)\s*\((https://[^\)]+)\)', line)
    if match:
        # نام، نماد، و URL
        return match.group(1).strip(), match.group(2).strip(), match.group(3)
    
    # فال‌بک برای حالتی که لینک وجود ندارد
    match_no_link = re.search(r'┌([^\(]+)\s*\(([^\)]+)\)', line)
    if match_no_link:
        return match_no_link.group(1).strip(), match_no_link.group(2).strip(), None
        
    return 'N/A', 'N/A', None

def _parse_usd(line):
    """ '├USD: $0.0002268' را تجزیه می‌کند """
    match = re.search(r'\$([\d\.]+)', line)
    return match.group(1) if match else 'N/A'

def _parse_mc_vol(line):
    """ '├MC: $226.8K' یا '├Vol: $88.2K' را تجزیه می‌کند """
    match = re.search(r'\$([\d\.KMB]+)', line)
    return match.group(1) if match else 'N/A'

def _parse_simple_text(line, prefix):
    """ متن ساده بعد از پیشوند را برمی‌گرداند """
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
    """
    '└TH: 13.3% (https://...)| 6.3% ...' را تجزیه می‌کند
    [اصلاح شده] لیستی از (درصد، URL) ها را برمی‌گرداند.
    """
    # الگوی Regex برای پیدا کردن جفت‌های (درصد) و (لینک)
    pairs = re.findall(r'([\d\.]+\%?)\s*\((https://[^\)]+)\)', line)
    
    # ۱۰ تای اول را برگردان
    return pairs[:10]

def _parse_chart(line):
    """ '📈 Chart: https://mevx.io/...' را تجزیه می‌کند """
    match = re.search(r'(https://mevx\.io/[^\s]+)', line)
    return match.group(1) if match else None

# --- تابع اصلی تجزیه‌کننده (اصلاح شده) ---

def transform_message(message_text, message_entities):
    """
    پیام خام ورودی را به صورت خط به خط تجزیه می‌کند
    (نسخه مقاوم با هایپرلینک)
    """
    logger.debug(f"Starting line-by-line transformation (with Hyperlinks)...")
    
    data = {}
    th_values = [] # اکنون لیستی از تاپل‌ها خواهد بود
    x_info = None

    try:
        lines = message_text.split('\n')

        if not lines or not lines[0].startswith("🥞"):
            logger.warning("Message does not start with 🥞 trigger. Skipping.")
            return None, None, None, None, None
        
        data['token_address'] = lines[0].replace('🥞', '').strip()
        if not re.match(r'^(0x[a-fA-F0-9]{40})$', data['token_address']):
             logger.warning(f"Failed to parse Token Address: {lines[0]}")
             data['token_address'] = 'Error'

        for line in lines[1:]:
            line = line.strip()
            if not line:
                continue

            try:
                if line.startswith('┌'):
                    # [اصلاح شده] اکنون ۳ مقدار دریافت می‌کند
                    data['token_name'], data['token_symbol'], data['token_url'] = _parse_token_name(line)
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
                
                # [حذف شده] خط Tax نادیده گرفته می‌شود
                # elif line.startswith('├Tax:'):
                #     data['tax'] = _parse_simple_text(line, '├Tax:')
                    
                elif line.startswith('├Honeypot:'):
                    data['honeypot'] = _parse_simple_text(line, '├Honeypot:')
                elif line.startswith('├Holder:'):
                    data['holder_color'], data['holder_percentage'] = _parse_holder(line)
                elif line.startswith('└TH:'):
                    # [اصلاح شده] اکنون لیستی از (درصد، لینک) ها را دریافت می‌کند
                    th_values = _parse_th(line)
                elif line.startswith('📈 Chart:'):
                    data['chart_url'] = _parse_chart(line)
                elif line.startswith('🔥'):
                    x_info = line
            
            except Exception as e:
                logger.warning(f"Failed to parse line: '{line}'. Error: {e}")

        # --- قالب‌بندی پیام خروجی (اصلاح شده) ---
        
        token_address = data.get('token_address', 'N/A')
        token_name = data.get('token_name', 'N/A')
        token_symbol = data.get('token_symbol', '?')
        token_url = data.get('token_url', '#') # لینک bscscan توکن
        
        # [اصلاح شده] ساخت هایپرلینک برای نام توکن
        if token_url != '#':
            token_line = f"<a href='{token_url}'>{token_name}</a> ({token_symbol})"
        else:
            token_line = f"{token_name} ({token_symbol})" # فال‌بک اگر لینک نبود

        # [اصلاح شده] ساخت هایپرلینک‌ها برای تاپ هولدرها
        th_links = []
        if th_values: # th_values اکنون لیستی از (درصد، لینک) است
            for percent, url in th_values:
                th_links.append(f"<a href='{url}'>{percent}</a>")
            th_text = " | ".join(th_links)
        else:
            th_text = "N/A" # فال‌بک اگر هولدری پیدا نشد
        
        # مقادیر دیگر
        usd = data.get('usd', '?')
        mc = data.get('mc', '?')
        vol = data.get('vol', '?')
        seen = data.get('seen', '?')
        dex = data.get('dex', '?')
        dex_paid = data.get('dex_paid', '?')
        ca_verified = data.get('ca_verified', '?')
        honeypot = data.get('honeypot', '?')
        holder_color = data.get('holder_color', '?')
        holder_percentage = data.get('holder_percentage', '?')
        chart_url = data.get('chart_url')

        # [اصلاح شده] ساخت پیام نهایی
        new_message = (
            f"⚡️ <code>{token_address}</code>\n"
            f"• {token_line}\n"  # <--- اینجا اصلاح شد
            f"• قیمت:      ${usd}\n"
            f"• مارکت‌کپ:     ${mc}\n"
            f"• حجم:      ${vol}\n"
            f"• ساخته شده:      {seen}\n"
            f"• نقدینگی:      {dex}\n"
            f"• دکس پرداخت شده؟: {dex_paid}\n"
            f"• قرارداد تایید شده؟: {ca_verified}\n"
            # f"• مالیات: {tax}\n"  <--- اینجا حذف شد
            f"• هانی‌پات: {honeypot}\n"
            f"• هولدرها:     Top 10: {holder_color} {holder_percentage}\n"
            f"• تاپ هولدر:      {th_text}"  # <--- اینجا اصلاح شد
        )

        if x_info:
            new_message += f"\n\n{x_info.strip()}"

        if len(new_message) > 4096:
            logger.error(f"Transformed message too long: {len(new_message)} characters. Truncating.")
            new_message = new_message[:4090] + "..."

        # --- آماده‌سازی خروجی (سازگار با bot.py) ---
        new_entities = []
        # th_pairs اکنون حاوی تاپل‌های (درصد، لینک) است که برای سازگاری مشکلی ندارد
        th_pairs = th_values

        logger.info(f"Message successfully parsed (line-by-line, with hyperlinks): {token_address}")
        
        # خروجی دقیقاً با چیزی که bot.py انتظار دارد مطابقت دارد
        return new_message, new_entities, chart_url, th_pairs, token_address

    except Exception as e:
        logger.critical(f"CRITICAL error in transform_message: {e}\n{traceback.format_exc()}")
        logger.error(f"--- FAILED MESSAGE (CRITICAL) ---\n{message_text}\n--- END ---")
        return None, None, None, None, None


def entities_to_html(entities, text):
    """(بدون تغییر)"""
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
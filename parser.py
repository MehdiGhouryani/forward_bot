# parser.py
import re
import logging
from telethon.tl.types import MessageEntityTextUrl
import traceback

# لاگر حرفه‌ای مخصوص این ماژول
logger = logging.getLogger(__name__)



def _parse_token_name(line):
    """
    '┌JUDICA (JUDICA) (https://...)' را تجزیه می‌کند
    [اصلاح شده] اکنون URL را نیز برمی‌گرداند.
    """
    match = re.search(r'┌([^\(]+)\s*\(([^\)]+)\)\s*\((https://[^\)]+)\)', line)
    if match:
        return match.group(1).strip(), match.group(2).strip(), match.group(3)
    
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
    [فال‌بک] '└TH: 13.3% (https://...)| 6.3% ...' را با Regex تجزیه می‌کند
    """
    pairs = re.findall(r'([\d\.]+\%?)\s*\((https://[^\)]+)\)', line)
    return pairs[:10]

def _parse_chart(line):
    """ '📈 Chart: https://mevx.io/...' را تجزیه می‌کند """
    match = re.search(r'(https://mevx\.io/[^\s]+)', line)
    return match.group(1) if match else None

# --- تابع اصلی تجزیه‌کننده (بازنویسی شده) ---




def transform_message(message_text, message_entities):
    """
    پیام خام ورودی را تجزیه می‌کند.
    [آپدیت شده] پشتیبانی از تریگرهای 🥞 و 💊 و فرمت‌های مختلف چارت.
    """
    logger.debug(f"Starting transformation with entity support...")
    
    data = {}
    th_values = []
    x_info = None

    # لیست تریگرهای مجاز
    VALID_TRIGGERS = ('🥞', '💊')

    try:
        lines = message_text.split('\n')

        # 1. بررسی و حذف تریگر از خط اول
        if not lines:
            return None, None, None, None, None

        first_line = lines[0].strip()
        trigger_found = False
        
        # چک می‌کنیم خط اول با کدام تریگر شروع شده
        for trigger in VALID_TRIGGERS:
            if first_line.startswith(trigger):
                # تریگر را حذف می‌کنیم تا فقط آدرس بماند
                data['token_address'] = first_line.replace(trigger, '').strip()
                trigger_found = True
                break
        
        if not trigger_found:
            logger.warning("Message does not start with a valid trigger (🥞 or 💊). Skipping.")
            return None, None, None, None, None

        # اعتبارسنجی اولیه آدرس (حروف و اعداد)
        if not re.match(r'^[a-zA-Z0-9]{32,44}$', data['token_address']):
             logger.warning(f"Address validation warning: {data['token_address']} might not be a valid address.")
             # ادامه می‌دهیم ولی لاگ اخطار ثبت می‌شود

        for unstripped_line in lines[1:]:
            line = unstripped_line.strip()
            if not line:
                continue

            try:
                if line.startswith('┌'):
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
                elif line.startswith('├Honeypot:'):
                    data['honeypot'] = _parse_simple_text(line, '├Honeypot:')
                elif line.startswith('├Holder:'):
                    data['holder_color'], data['holder_percentage'] = _parse_holder(line)
                
                # --- منطق TH (بدون تغییر) ---
                elif line.startswith('└TH:'):
                    try:
                        line_start_offset = message_text.find(unstripped_line)
                        if line_start_offset == -1:
                            th_values = _parse_th(line)
                            continue

                        content_start_offset = line_start_offset + (len(unstripped_line) - len(unstripped_line.lstrip()))
                        content_end_offset = content_start_offset + len(line)
                        
                        found_entities = False
                        if message_entities:
                            for entity in message_entities:
                                if isinstance(entity, MessageEntityTextUrl):
                                    if content_start_offset <= entity.offset < content_end_offset:
                                        entity_text = message_text[entity.offset : entity.offset + entity.length]
                                        th_values.append((entity_text, entity.url))
                                        found_entities = True
                        
                        if not found_entities:
                            th_values = _parse_th(line)
                                
                    except Exception as e:
                        logger.error(f"Error parsing TH entities: {e}")
                        th_values = []
                
                # [تغییر جدید] پشتیبانی از فرمت‌های مختلف چارت
                elif line.startswith('📈 Chart:') or line.startswith('?? Chart:'):
                    data['chart_url'] = _parse_chart(line)
                
                elif line.startswith('🔥'):
                    x_info = line
            
            except Exception as e:
                logger.warning(f"Failed to parse line: '{line}'. Error: {e}")

        # --- ساخت پیام نهایی ---
        token_address = data.get('token_address', 'N/A')
        token_name = data.get('token_name', 'N/A')
        token_symbol = data.get('token_symbol', '?')
        token_url = data.get('token_url', '#')
        
        if token_url != '#':
            token_line = f"<a href='{token_url}'>{token_name}</a> ({token_symbol})"
        else:
            token_line = f"{token_name} ({token_symbol})"

        th_links = []
        if th_values:
            for percent, url in th_values:
                th_links.append(f"<a href='{url}'>{percent}</a>")
            th_text = " | ".join(th_links)
        else:
            th_text = "N/A"
        
        # استخراج مقادیر با پیش‌فرض
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

        new_message = (
            f"⚡️ <code>{token_address}</code>\n"
            f"• {token_line}\n"
            f"• قیمت:      ${usd}\n"
            f"• مارکت‌کپ:     ${mc}\n"
            f"• حجم:      ${vol}\n"
            f"• ساخته شده:      {seen}\n"
            f"• نقدینگی:      {dex}\n"
            f"• دکس پرداخت شده؟: {dex_paid}\n"
            f"• قرارداد تایید شده؟: {ca_verified}\n"
            f"• هانی‌پات: {honeypot}\n"
            f"• هولدرها:     Top 10: {holder_color} {holder_percentage}\n"
            f"• تاپ هولدر:      {th_text}"
        )

        if x_info:
            new_message += f"\n\n{x_info.strip()}"

        if len(new_message) > 4096:
            new_message = new_message[:4090] + "..."

        new_entities = []
        th_pairs = th_values

        logger.info(f"Message successfully parsed: {token_address}")
        
        return new_message, new_entities, chart_url, th_pairs, token_address

    except Exception as e:
        logger.critical(f"CRITICAL error in transform_message: {e}\n{traceback.format_exc()}")
        return None, None, None, None, None





def entities_to_html(entities, text):
    """
    (بدون تغییر)
    """
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





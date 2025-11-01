import requests
import json
from urllib.parse import quote
import random

# --- شبیه‌سازی یک روند قیمت واقع‌گرایانه ---
# این تابع یک قیمت شروع می‌گیرد و یک لیست از قیمت‌های بعدی را تولید می‌کند
def generate_price_trend(count, start_price):
    prices = [start_price]
    current_price = start_price
    for _ in range(count - 1):
        # ایجاد یک نوسان کوچک (بین -3% تا +4%) برای قیمت بعدی
        change_percent = random.uniform(-0.03, 0.04)
        current_price *= (1 + change_percent)
        prices.append(current_price)
    return prices

# قیمت شروع نمونه (در ربات اصلی، این قیمت از Birdeye گرفته می‌شود)
start_price = 1.5
# تولید داده برای ۲۴ نقطه در نمودار
sample_prices = generate_price_trend(24, start_price)
sample_labels = list(range(len(sample_prices)))

print("درحال ساخت نمودار خطی با ظاهر حرفه‌ای...")

# --- ساخت کانفیگ نمودار خطی برای QuickChart ---
chart_config = {
    "type": "line",
    "data": {
        "labels": sample_labels,
        "datasets": [{
            "data": sample_prices,
            "fill": True,
            "backgroundColor": "rgba(16, 185, 129, 0.1)",  # سبز کم‌رنگ
            "borderColor": "rgb(16, 185, 129)",          # سبز پررنگ
            "borderWidth": 2,
            "pointRadius": 0,
        }]
    },
    "options": {
        "legend": { "display": False },
        "scales": {
            "x": { "display": False },
            "y": { "display": False }
        }
    }
}

try:
    encoded_config = quote(json.dumps(chart_config))
    # پس‌زمینه تیره برای ظاهر حرفه‌ای
    quickchart_url = f"https://quickchart.io/chart?c={encoded_config}&backgroundColor=%2318181b&width=600&height=350"

    print("\n✅ URL نمودار ساخته شد.")
    print("\nدرحال دانلود تصویر نهایی...")
    response = requests.get(quickchart_url, timeout=15)
    response.raise_for_status()

    with open("final_chart.png", "wb") as f:
        f.write(response.content)

    print("\n✅✅✅ موفقیت!")
    print("تصویر نمودار نهایی با نام final_chart.png با موفقیت ذخیره شد.")
    print("این روش نهایی و قابل اعتماد است.")

except Exception as e:
    print(f"\n❌ یک خطا رخ داد: {e}")
import os
import requests
import feedparser
from datetime import datetime
from apscheduler.schedulers.background import BackgroundScheduler
import pytz
import time

# --- تنظیمات ---
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
HF_TOKEN = os.getenv("HF_TOKEN")
NEWS_FEED_URL = os.getenv("NEWS_FEED_URL", "https://cryptonews.com/news/feed")

scheduler = BackgroundScheduler(timezone=pytz.timezone("Asia/Tehran"))

# --- خلاصه‌سازی ---
def summarize_text(text):
    """خلاصه دقیق‌تر با Hugging Face"""
    try:
        response = requests.post(
            "https://api-inference.huggingface.co/models/facebook/bart-large-cnn",
            headers={"Authorization": f"Bearer {HF_TOKEN}"},
            json={"inputs": text[:3000]},
            timeout=30
        )
        data = response.json()
        if isinstance(data, list) and len(data) > 0:
            summary = data[0].get("summary_text", "")
            if summary:
                return summary
    except Exception as e:
        print("HF summarize error:", e)
    return " ".join(text.split(".")[:4])  # در صورت خطا، ۴ جمله اول را بازمی‌گرداند.

# --- ترجمه ---
def translate_to_farsi(text):
    """ترجمه با MyMemory (پایدارتر از Libre)"""
    try:
        url = f"https://api.mymemory.translated.net/get?q={requests.utils.quote(text)}&langpair=en|fa"
        res = requests.get(url, timeout=20).json()
        translated = res.get("responseData", {}).get("translatedText")
        if translated:
            # حذف فاصله‌های اضافه و مرتب‌سازی متن فارسی
            clean = translated.replace("&quot;", "\"").replace("&#39;", "'").strip()
            return clean
    except Exception as e:
        print("Translation error:", e)
    return text

# --- ارسال پیام به تلگرام ---
def send_message(text):
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        payload = {
            "chat_id": CHAT_ID,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True
        }
        requests.post(url, data=payload, timeout=10)
        print("✅ خبر ارسال شد به تلگرام")
    except Exception as e:
        print("Telegram send error:", e)

# --- دریافت و ارسال خبر ---
posted_titles = set()

def get_latest_news():
    print("🛰 بررسی فید RSS...")
    feed = feedparser.parse(NEWS_FEED_URL)
    news_items = []
    for entry in feed.entries[:8]:
        title = entry.title
        link = entry.link
        desc = getattr(entry, "summary", "")
        news_items.append({"title": title, "desc": desc, "link": link})
    print(f"📡 تعداد خبرها: {len(news_items)}")
    return news_items

@scheduler.scheduled_job("interval", minutes=5)
def post_news():
    try:
        news_items = get_latest_news()
        for n in news_items:
            if n["title"] in posted_titles:
                continue

            print(f"📰 ارسال: {n['title'][:60]}...")
            summary = summarize_text(n["desc"])
            fa_title = translate_to_farsi(n["title"])
            fa_summary = translate_to_farsi(summary)

            msg = f"📢 <b>{fa_title}</b>\n\n📝 {fa_summary}\n\n🔗 <a href='{n['link']}'>ادامه مطلب</a>\n\n👥 @Crypto_Zone360\nبه ما بپیوندید 🦈"
            send_message(msg)
            posted_titles.add(n["title"])
            time.sleep(5)
    except Exception as e:
        print("News job error:", e)

# --- تحلیل تکنیکال ---
def get_technical_analysis(symbol):
    try:
        url = f"https://min-api.cryptocompare.com/data/pricemultifull?fsyms={symbol}&tsyms=USD"
        data = requests.get(url, timeout=10).json()
        price = data["RAW"][symbol]["USD"]["PRICE"]
        change = data["RAW"][symbol]["USD"]["CHANGEPCT24HOUR"]
        status = "📈 صعودی" if change > 0 else "📉 نزولی"
        return f"{symbol}: ${price:,.2f} ({change:.2f}%) {status}"
    except:
        return f"{symbol}: داده در دسترس نیست"

@scheduler.scheduled_job("cron", hour=17, minute=30)
def post_daily_analysis():
    print("📊 ارسال تحلیل روزانه...")
    coins = ["BTC", "ETH", "SOL", "TON", "XRP", "BNB"]
    results = [get_technical_analysis(c) for c in coins]
    msg = "📊 تحلیل تکنیکال روزانه بازار:\n\n" + "\n".join(results) + "\n\n⚠️ مسئولیت استفاده با کاربر است.\n\n🦈 @Crypto_Zone360"
    send_message(msg)

# --- اجرای اولیه ---
if __name__ == "__main__":
    print("🚀 Bot started...")
    post_news()
    scheduler.start()
    while True:
        time.sleep(60)

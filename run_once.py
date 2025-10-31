import os, requests, feedparser, pytz, json, time
from datetime import datetime
from apscheduler.schedulers.blocking import BlockingScheduler

# --- تنظیمات ---
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
NEWS_FEED_URL = "https://cryptonews.com/news/feed"
HF_MODEL = "facebook/bart-large-cnn"
HF_TOKEN = os.getenv("HF_TOKEN")

# --- فایل ذخیره عناوین ارسال‌شده ---
POSTED_FILE = "posted.json"

# --- لود عناوین قبلی ---
if os.path.exists(POSTED_FILE):
    with open(POSTED_FILE, "r") as f:
        posted_titles = set(json.load(f))
else:
    posted_titles = set()

# --- ترجمه ---
def translate_text(text):
    for url in [
        "https://api.mymemory.translated.net/get",
    ]:
        try:
            print("🌐 شروع ترجمه با MyMemory...")
            res = requests.get(url, params={"q": text, "langpair": "en|fa"}, timeout=15)
            data = res.json()
            if "responseData" in data:
                t = data["responseData"]["translatedText"]
                if t and t != text:
                    print("✅ ترجمه انجام شد.")
                    return t
        except Exception as e:
            print(f"⚠️ خطا در ترجمه: {e}")
    return text

# --- خلاصه ---
def summarize_text(text):
    try:
        r = requests.post(
            f"https://api-inference.huggingface.co/models/{HF_MODEL}",
            headers={"Authorization": f"Bearer {HF_TOKEN}"},
            json={"inputs": text[:2000]},
            timeout=25
        )
        data = r.json()
        if isinstance(data, list) and len(data) and "summary_text" in data[0]:
            return data[0]["summary_text"]
    except Exception as e:
        print("HF summarize error:", e)
    return text

# --- ارسال تلگرام ---
def send_message(msg):
    try:
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
            data={"chat_id": CHAT_ID, "text": msg, "parse_mode": "HTML", "disable_web_page_preview": True},
            timeout=10
        )
        print("✅ Sent to Telegram")
    except Exception as e:
        print("Telegram send error:", e)

# --- دریافت خبر ---
def fetch_latest_news():
    print("🛰 بررسی فید...")
    feed = feedparser.parse(NEWS_FEED_URL)
    news = []
    for entry in feed.entries[:3]:  # فقط ۳ تا خبر جدید
        news.append({
            "title": entry.title,
            "link": entry.link,
            "summary": getattr(entry, "summary", "")
        })
    print(f"📡 تعداد خبرها: {len(news)}")
    return news

# --- ارسال اخبار ---
def post_news():
    print("🚀 اجرای بررسی اخبار...")
    global posted_titles
    news_items = fetch_latest_news()
    for n in news_items:
        if n["title"] in posted_titles:
            print("⏩ تکراری، رد شد:", n["title"])
            continue
        print(f"📰 ارسال خبر: {n['title'][:50]}...")

        summary = summarize_text(n["summary"])
        fa_title = translate_text(n["title"])
        fa_summary = translate_text(summary)

        hashtags = "#کریپتو #اخبار_کریپتو #Bitcoin #Ethereum"
        msg = f"📢 <b>{fa_title}</b>\n\n📝 {fa_summary}\n\n🔗 <a href='{n['link']}'>ادامه مطلب</a>\n\n👥 @Crypto_Zone360\nبه ما بپیوندید 🦈\n{hashtags}"
        send_message(msg)
        posted_titles.add(n["title"])

    # ذخیره عناوین جدید
    with open(POSTED_FILE, "w") as f:
        json.dump(list(posted_titles), f)

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

def post_daily_analysis():
    print("📊 ارسال تحلیل تکنیکال...")
    coins = ["BTC", "ETH", "SOL", "TON", "XRP", "BNB"]
    results = [get_technical_analysis(c) for c in coins]
    hashtags = "#تحلیل_تکنیکال #کریپتو #Bitcoin #Ethereum"
    msg = "📊 تحلیل تکنیکال روزانه بازار:\n\n" + "\n".join(results) + f"\n\n⚠️ مسئولیت استفاده با کاربر است.\n\n👥 @Crypto_Zone360\nبه ما بپیوندید 🦈\n{hashtags}"
    send_message(msg)

# --- زمان‌بندی ---
scheduler = BlockingScheduler(timezone=pytz.timezone("Asia/Tehran"))
scheduler.add_job(post_news, "interval", minutes=20)
scheduler.add_job(post_daily_analysis, "cron", hour=8, minute=0)

if __name__ == "__main__":
    print("✅ Bot run started...")
    post_news()  # اجرای فوری بار اول
    scheduler.start()

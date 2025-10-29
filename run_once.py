import os, json, time, requests, feedparser, pytz
from datetime import datetime
from apscheduler.schedulers.background import BackgroundScheduler

# تنظیمات
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
HF_TOKEN = os.getenv("HF_TOKEN")
NEWS_FEED_URL = os.getenv("NEWS_FEED_URL", "https://cryptonews.com/news/feed")
LIBRE_URL = "https://translate.argosopentech.com/translate"
POSTED_FILE = "posted.json"

scheduler = BackgroundScheduler(timezone=pytz.timezone("Asia/Tehran"))

# --- بارگذاری و ذخیره لیست خبرهای منتشرشده ---
def load_posted():
    if os.path.exists(POSTED_FILE):
        with open(POSTED_FILE, "r") as f:
            return set(json.load(f))
    return set()

def save_posted(data):
    with open(POSTED_FILE, "w") as f:
        json.dump(list(data), f)

# --- خلاصه‌سازی ---
def summarize_text(text):
    try:
        response = requests.post(
            "https://api-inference.huggingface.co/models/sshleifer/distilbart-cnn-12-6",
            headers={"Authorization": f"Bearer {HF_TOKEN}"},
            json={"inputs": text[:2000]},
            timeout=25
        )
        data = response.json()
        if isinstance(data, list) and "summary_text" in data[0]:
            return data[0]["summary_text"]
    except Exception as e:
        print("HF summarize error:", e)
    return " ".join(text.split(".")[:3])

# --- ترجمه ---
def translate_to_farsi(text):
    try:
        res = requests.post(
            LIBRE_URL,
            json={"q": text, "source": "en", "target": "fa"},
            timeout=15
        )
        return res.json().get("translatedText", text)
    except Exception as e:
        print("Translation error:", e)
        return text

# --- ارسال پیام ---
def send_message(text):
    try:
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
            data={"chat_id": CHAT_ID, "text": text, "parse_mode": "HTML", "disable_web_page_preview": True},
            timeout=10
        )
        print("✅ Sent to Telegram")
    except Exception as e:
        print("Telegram send error:", e)

# --- دریافت خبر ---
def get_latest_news():
    print("🛰 بررسی فید...")
    feed = feedparser.parse(NEWS_FEED_URL)
    news_items = []
    for entry in feed.entries[:10]:
        news_items.append({
            "title": entry.title,
            "desc": getattr(entry, "summary", ""),
            "link": entry.link
        })
    print(f"📡 تعداد خبرها: {len(news_items)}")
    return news_items

# --- انتشار خبر ---
def post_news():
    posted_links = load_posted()
    new_links = set()
    news_items = get_latest_news()

    for n in news_items:
        if n["link"] in posted_links:
            continue

        print(f"📰 ارسال خبر: {n['title'][:50]}...")
        summary = summarize_text(n["desc"])
        fa_title = translate_to_farsi(n["title"])
        fa_text = translate_to_farsi(summary)

        msg = f"📢 <b>{fa_title}</b>\n\n📝 {fa_text}\n\n🔗 <a href='{n['link']}'>ادامه مطلب</a>\n\n👥 @Crypto_Zone360\nبه ما بپیوندید 🦈"
        send_message(msg)
        new_links.add(n["link"])
        time.sleep(5)

    if new_links:
        posted_links.update(new_links)
        save_posted(posted_links)
        os.system('git config --global user.email "bot@github.com"')
        os.system('git config --global user.name "AutoBot"')
        os.system("git add posted.json && git commit -m 'update posted links' && git push")

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
    print("📊 ارسال تحلیل روزانه...")
    coins = ["BTC", "ETH", "SOL", "TON", "XRP", "BNB"]
    results = [get_technical_analysis(c) for c in coins]
    msg = "📊 تحلیل تکنیکال روزانه بازار:\n\n" + "\n".join(results) + "\n\n⚠️ مسئولیت استفاده با کاربر است.\n\n🦈 @Crypto_Zone360"
    send_message(msg)

# --- اجرای اصلی ---
if __name__ == "__main__":
    print("🚀 Running once...")
    now = datetime.now(pytz.timezone("Asia/Tehran"))
    if now.hour == 17 and now.minute >= 30:
        post_daily_analysis()
    post_news()

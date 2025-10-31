import os, json, requests, feedparser, time, subprocess, pytz
from datetime import datetime

# --- تنظیمات ---
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
HF_TOKEN = os.getenv("HF_TOKEN")
NEWS_FEED_URL = os.getenv("NEWS_FEED_URL", "https://cryptonews.com/news/feed")

TRANSLATE_APIS = [
    "https://translate.astian.org/translate",
    "https://libretranslate.com/translate",
    "https://translate.argosopentech.com/translate"
]

POSTED_FILE = "posted.json"

# --- ذخیره و بارگذاری داده ---
def load_posted():
    if not os.path.exists(POSTED_FILE):
        return {"links": [], "last_analysis_date": ""}
    with open(POSTED_FILE, "r") as f:
        return json.load(f)

def save_posted(data):
    with open(POSTED_FILE, "w") as f:
        json.dump(data, f)
    subprocess.run(["git", "config", "user.name", "github-actions"])
    subprocess.run(["git", "config", "user.email", "actions@github.com"])
    subprocess.run(["git", "add", POSTED_FILE])
    subprocess.run(["git", "commit", "-m", "update posted.json"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    subprocess.run(["git", "push", "origin", "main"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

# --- ترجمه مطمئن ---
def translate_to_farsi(text):
    for api in TRANSLATE_APIS:
        try:
            r = requests.post(api, json={"q": text, "source": "en", "target": "fa"}, timeout=20)
            if r.status_code == 200:
                data = r.json()
                if "translatedText" in data:
                    return data["translatedText"]
        except Exception as e:
            print(f"❌ Error from {api}: {e}")
    return text

# --- خلاصه‌سازی ---
def summarize_text(text):
    try:
        r = requests.post(
            "https://api-inference.huggingface.co/models/sshleifer/distilbart-cnn-12-6",
            headers={"Authorization": f"Bearer {HF_TOKEN}"},
            json={"inputs": text[:2000]},
            timeout=25
        )
        data = r.json()
        if isinstance(data, list) and "summary_text" in data[0]:
            return data[0]["summary_text"]
    except Exception as e:
        print("HF summarize error:", e)
    return text[:500]

# --- هشتگ هوشمند ---
def generate_hashtags(text):
    tags = []
    lower = text.lower()
    if "bitcoin" in lower or "btc" in lower: tags.append("#BTC")
    if "ethereum" in lower or "eth" in lower: tags.append("#ETH")
    if "solana" in lower or "sol" in lower: tags.append("#SOL")
    if "ton" in lower: tags.append("#TON")
    if "ripple" in lower or "xrp" in lower: tags.append("#XRP")
    if "bnb" in lower or "binance" in lower: tags.append("#BNB")
    if "sec" in lower or "lawsuit" in lower: tags.append("#CryptoNews")
    if "market" in lower: tags.append("#MarketUpdate")
    if "bull" in lower or "bear" in lower: tags.append("#CryptoAnalysis")
    if not tags: tags.append("#CryptoNews")
    return " ".join(tags)

# --- ارسال به تلگرام ---
def send_message(text):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    requests.post(url, data={"chat_id": CHAT_ID, "text": text, "parse_mode": "HTML", "disable_web_page_preview": True})

# --- خبرها ---
def fetch_latest_news():
    feed = feedparser.parse(NEWS_FEED_URL)
    return [{"title": e.title, "link": e.link, "desc": getattr(e, "summary", "")} for e in feed.entries[:5]]

def post_news():
    data = load_posted()
    sent_links = data["links"]
    all_news = fetch_latest_news()
    new_items = [n for n in all_news if n["link"] not in sent_links]

    if not new_items:
        print("✅ No new news to post.")
        return

    for n in new_items:
        print(f"📰 Sending: {n['title'][:50]}...")
        summary = summarize_text(n["desc"])
        fa_summary = translate_to_farsi(summary)
        fa_title = translate_to_farsi(n["title"])
        hashtags = generate_hashtags(n["title"])
        msg = f"📢 <b>{fa_title}</b>\n\n📝 {fa_summary}\n\n🔗 <a href='{n['link']}'>ادامه مطلب</a>\n\n{hashtags}\n\n🦈 @Crypto_Zone360"
        send_message(msg)
        sent_links.append(n["link"])
        time.sleep(5)

    data["links"] = sent_links[-100:]
    save_posted(data)

# --- تحلیل تکنیکال ---
def get_technical_analysis(symbol):
    try:
        r = requests.get(f"https://min-api.cryptocompare.com/data/pricemultifull?fsyms={symbol}&tsyms=USD", timeout=10)
        d = r.json()
        price = d["RAW"][symbol]["USD"]["PRICE"]
        change = d["RAW"][symbol]["USD"]["CHANGEPCT24HOUR"]
        status = "📈 صعودی" if change > 0 else "📉 نزولی"
        return f"{symbol}: ${price:,.2f} ({change:.2f}%) {status}"
    except:
        return f"{symbol}: داده در دسترس نیست"

def post_daily_analysis():
    now = datetime.now(pytz.timezone("Asia/Tehran"))
    today = now.strftime("%Y-%m-%d")
    data = load_posted()

    if data.get("last_analysis_date") == today:
        print("✅ تحلیل امروز ارسال شده.")
        return

    print("📊 ارسال تحلیل روزانه...")
    coins = ["BTC", "ETH", "SOL", "TON", "XRP", "BNB"]
    results = [get_technical_analysis(c) for c in coins]
    msg = "📊 تحلیل تکنیکال روزانه بازار:\n\n" + "\n".join(results) + \
          "\n\n⚠️ مسئولیت استفاده با کاربر است.\n\n#DailyAnalysis #Crypto #Trading\n\n🦈 @Crypto_Zone360"
    send_message(msg)
    data["last_analysis_date"] = today
    save_posted(data)

# --- اجرای اصلی ---
if __name__ == "__main__":
    print("🚀 Bot run started...")
    post_news()
    hour = datetime.now(pytz.timezone("Asia/Tehran")).hour
    if hour == 8:
        post_daily_analysis()
    print("✅ Done.")

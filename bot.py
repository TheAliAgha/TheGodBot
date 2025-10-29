#!/usr/bin/env python3
import os
import time
import requests
import feedparser
import pytz
import statistics
from datetime import datetime
from apscheduler.schedulers.background import BackgroundScheduler

# ---------- CONFIG (from GH Secrets) ----------
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
HF_TOKEN = os.getenv("HF_TOKEN")  # Hugging Face inference token
NEWS_FEED_URL = os.getenv("NEWS_FEED_URL", "https://cryptonews.com/news/feed")
# Primary libretranslate endpoint (swap if needed)
LIBRE_URLS = [
    "https://translate.argosopentech.com/translate",
    "https://libretranslate.de/translate",
    "https://translate.astian.org/translate"
]

# coins for daily technical summary
COINS = ["BTC", "ETH", "SOL", "TON", "XRP", "BNB"]

# scheduler
scheduler = BackgroundScheduler(timezone=pytz.timezone("Asia/Tehran"))

# Posted set to avoid duplicates during runtime
posted_titles = set()


# ---------- UTIL ----------

def log(*args):
    print(datetime.now().strftime("%Y-%m-%d %H:%M:%S"), *args, flush=True)


# ---------- Hugging Face helpers ----------

HF_SUMMARY_MODEL = "sshleifer/distilbart-cnn-12-6"  # faster summarizer
HF_TRANSLATE_MODEL = "Helsinki-NLP/opus-mt-en-fa"  # translate en->fa via HF inference

def hf_inference(model_name, payload_json, timeout=25):
    """Call HF Inference API, return JSON or raise."""
    if not HF_TOKEN:
        raise RuntimeError("HF_TOKEN not set")
    url = f"https://api-inference.huggingface.co/models/{model_name}"
    headers = {"Authorization": f"Bearer {HF_TOKEN}"}
    resp = requests.post(url, headers=headers, json=payload_json, timeout=timeout)
    resp.raise_for_status()
    return resp.json()

def summarize_with_hf(text):
    try:
        data = hf_inference(HF_SUMMARY_MODEL, {"inputs": text[:2000]}, timeout=25)
        if isinstance(data, list) and data and "summary_text" in data[0]:
            return data[0]["summary_text"]
    except Exception as e:
        log("HF summarize error:", e)
    # fallback: first 2-3 sentences
    parts = [p.strip() for p in text.split(".") if p.strip()]
    return ". ".join(parts[:3]) + ("." if len(parts[:3])>0 and not parts[:3][-1].endswith(".") else "")

def translate_with_hf(text):
    try:
        # HF text translation returns list of dicts with 'translation_text' or plain string depending on model
        data = hf_inference(HF_TRANSLATE_MODEL, {"inputs": text}, timeout=25)
        # model often returns [{"translation_text": "..."}] or a string
        if isinstance(data, list) and data:
            if isinstance(data[0], dict) and "translation_text" in data[0]:
                return data[0]["translation_text"]
            # some models return plain dict/list differently; try common keys
            if isinstance(data[0], str):
                return data[0]
        if isinstance(data, str):
            return data
    except Exception as e:
        log("HF translate error:", e)
    return text  # fallback: return original


# ---------- LibreTranslate helper with fallback attempts ----------

def translate_with_libre(text, source="en", target="fa"):
    for url in LIBRE_URLS:
        try:
            resp = requests.post(url, json={"q": text, "source": source, "target": target, "format": "text"}, timeout=12)
            if resp.status_code == 200:
                j = resp.json()
                if isinstance(j, dict) and "translatedText" in j:
                    return j["translatedText"]
            else:
                log("Libre returned", resp.status_code, "from", url)
        except Exception as e:
            log("Libre error for", url, ":", e)
    # if all libre fail, return None to indicate fallback to HF translator
    return None


# ---------- Telegram ----------

def send_to_telegram_html(text):
    try:
        api = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        data = {
            "chat_id": TELEGRAM_CHAT_ID,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True
        }
        r = requests.post(api, data=data, timeout=10)
        if r.status_code != 200:
            log("Telegram error:", r.status_code, r.text)
            return False
        return True
    except Exception as e:
        log("Telegram send exception:", e)
        return False


# ---------- News pipeline ----------

def fetch_latest_news(limit=5):
    log("Fetching RSS:", NEWS_FEED_URL)
    feed = feedparser.parse(NEWS_FEED_URL)
    items = []
    for entry in feed.entries[:limit]:
        items.append({
            "title": getattr(entry, "title", "") or "",
            "summary": getattr(entry, "summary", "") or getattr(entry, "description", "") or "",
            "link": getattr(entry, "link", "")
        })
    log("Fetched", len(items), "items")
    return items


@scheduler.scheduled_job("interval", minutes=5)
def job_post_news():
    log("JOB: post_news started")
    try:
        news_items = fetch_latest_news(limit=6)
        for n in news_items:
            title = n["title"].strip()
            if not title:
                continue
            if title in posted_titles:
                log("skipping (already posted):", title[:60])
                continue

            # 1) Summarize (EN)
            summary_en = summarize_with_hf(n["summary"] or n["title"])

            # 2) Translate summarized EN -> FA (prefer LibreTranslate)
            fa = translate_with_libre(summary_en)
            if fa is None:
                log("Libre failed, using HF translator")
                fa = translate_with_hf(summary_en)

            # 3) Translate title separately (same fallback)
            fa_title = translate_with_libre(title)
            if fa_title is None:
                fa_title = translate_with_hf(title)

            # 4) Build message and send
            msg = (
                f"📢 <b>{escape_html(fa_title)}</b>\n\n"
                f"📝 {escape_html(fa)}\n\n"
                f"🔗 <a href=\"{n['link']}\">ادامه مطلب</a>\n\n"
                f"👥 @{TELEGRAM_CHAT_ID.strip('@')}\nبه ما بپیوندید 🦈"
            )
            sent = send_to_telegram_html(msg)
            if sent:
                posted_titles.add(title)
                log("Posted:", title[:80])
            else:
                log("Failed to post:", title[:80])
            time.sleep(2)
    except Exception as e:
        log("News job exception:", e)


# ---------- Technical analysis (daily) ----------

def get_technical(symbol):
    # lightweight summary using cryptocompare free endpoint (no API key required for basic)
    try:
        url = f"https://min-api.cryptocompare.com/data/pricemultifull?fsyms={symbol}&tsyms=USD"
        r = requests.get(url, timeout=8).json()
        price = r["RAW"][symbol]["USD"]["PRICE"]
        change = r["RAW"][symbol]["USD"]["CHANGEPCT24HOUR"]
        trend = "📈 صعودی" if change > 0 else "📉 نزولی"
        return f"{symbol}: ${price:,.2f} ({change:.2f}%) {trend}"
    except Exception as e:
        log("technical error for", symbol, e)
        return f"{symbol}: داده در دسترس نیست"

@scheduler.scheduled_job("cron", hour=21, minute=0)  # Tehran 21:00
def job_daily_analysis():
    log("JOB: daily analysis started")
    try:
        parts = []
        for c in COINS:
            parts.append(get_technical(c))
        msg = "📊 <b>تحلیل تکنیکال روزانه</b>\n\n" + "\n".join(parts) + "\n\n⚠️ مسئولیت استفاده با تریدر است.\n\n🦈 @" + TELEGRAM_CHAT_ID.strip('@')
        send_to_telegram_html(msg)
        log("Daily analysis sent")
    except Exception as e:
        log("Daily analysis exception:", e)


# ---------- utility escape ----------
def escape_html(s: str) -> str:
    # simple HTML escape for telegram HTML mode
    return (s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            .replace('"', "&quot;").replace("'", "&#39;"))


# ---------- RUN ----------

if __name__ == "__main__":
    log("Bot starting...")
    # run immediately once
    try:
        job_post_news()
    except Exception as e:
        log("Immediate first-run error:", e)
    # start scheduler
    scheduler.start()
    # keep alive loop so GH Actions run doesn't exit immediately
    try:
        while True:
            time.sleep(30)
    except (KeyboardInterrupt, SystemExit):
        log("Exiting...")

import os
import json
import time
import hashlib
import subprocess
from datetime import datetime, date
from urllib.parse import quote_plus

import requests
import feedparser
import pytz

# ---------------- CONFIG ----------------
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
HF_TOKEN = os.getenv("HF_TOKEN")
NEWS_FEED_URL = os.getenv("NEWS_FEED_URL", "https://cryptonews.com/news/feed")

POSTED_FILE = "posted.json"
MAX_POSTS_PER_RUN = 3
TIMEZONE = "Asia/Tehran"

# keywords for scoring importance (you can extend)
KEYWORDS = [
    "bitcoin", "btc", "ethereum", "eth", "ripple", "xrp", "binance", "bnb",
    "solana", "sol", "ton", "toncoin", "sec", "etf", "regulation", "adoption",
    "whale", "institutional", "hack", "exploit", "lawsuit", "ban", "approval",
    "upgrade", "hard fork", "airdrop", "listing", "delist"
]

# coin keywords mapping for hashtags
COIN_TAGS = {
    "bitcoin": ("#بیت_کوین", "#Bitcoin", "BTC"),
    "btc": ("#بیت_کوین", "#Bitcoin", "BTC"),
    "ethereum": ("#اتریوم", "#Ethereum", "ETH"),
    "eth": ("#اتریوم", "#Ethereum", "ETH"),
    "ripple": ("#ریپل", "#Ripple", "XRP"),
    "xrp": ("#ریپل", "#Ripple", "XRP"),
    "binance": ("#بایننس", "#Binance", "BNB"),
    "bnb": ("#بایننس", "#Binance", "BNB"),
    "solana": ("#سولانا", "#Solana", "SOL"),
    "sol": ("#سولانا", "#Solana", "SOL"),
    "ton": ("#تون", "#Ton", "TON"),
    "toncoin": ("#تون", "#Ton", "TON")
}

# HuggingFace inference endpoints/models
HF_SUMMARY_MODEL = "sshleifer/distilbart-cnn-12-6"   # summarization
HF_SENTIMENT_MODEL = "distilbert-base-uncased-finetuned-sst-2-english"  # sentiment

# ---------------- Helpers ----------------
def log(*a):
    print(datetime.now().isoformat(), *a, flush=True)

def load_posted():
    if not os.path.exists(POSTED_FILE):
        return {"links": [], "last_analysis_date": ""}
    try:
        with open(POSTED_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        log("load_posted error:", e)
        return {"links": [], "last_analysis_date": ""}

def save_posted_and_commit(data):
    try:
        with open(POSTED_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        log("save_posted error:", e)
        return

    # try to commit & push (only works if GITHUB_TOKEN present and repo checked out)
    token = os.getenv("GITHUB_TOKEN")
    repo = os.getenv("GITHUB_REPOSITORY")
    if token and repo:
        try:
            subprocess.run(["git", "config", "user.email", "actions@github.com"], check=False)
            subprocess.run(["git", "config", "user.name", "github-actions"], check=False)
            subprocess.run(["git", "add", POSTED_FILE], check=False)
            subprocess.run(["git", "commit", "-m", "ci: update posted.json (bot)"], check=False)
            remote = f"https://x-access-token:{token}@github.com/{repo}.git"
            subprocess.run(["git", "push", remote, "HEAD:refs/heads/main"], check=False)
            log("posted.json committed & pushed")
        except Exception as e:
            log("git push error:", e)
    else:
        log("GITHUB_TOKEN or GITHUB_REPOSITORY not set — skipping commit")

def sha256_text(s):
    return hashlib.sha256(s.encode("utf-8")).hexdigest()

# ---------------- HF Summarize ----------------
def hf_summarize(text):
    if not text or len(text.strip()) == 0:
        return ""
    url = f"https://api-inference.huggingface.co/models/{HF_SUMMARY_MODEL}"
    headers = {"Authorization": f"Bearer {HF_TOKEN}"} if HF_TOKEN else {}
    payload = {"inputs": text[:3000]}
    try:
        r = requests.post(url, headers=headers, json=payload, timeout=25)
        j = r.json()
        if isinstance(j, list) and j and "summary_text" in j[0]:
            return j[0]["summary_text"]
        # sometimes API returns dict with error
        log("HF summarize response:", j)
    except Exception as e:
        log("HF summarize error:", e)
    # fallback: first 3 sentences
    return " ".join([p.strip() for p in text.split(".") if p.strip()][:3])

# ---------------- MyMemory Translate (reliable for GH) ----------------
def translate_mymemory(text):
    if not text:
        return text
    try:
        resp = requests.get(
            "https://api.mymemory.translated.net/get",
            params={"q": text, "langpair": "en|fa"},
            timeout=15
        )
        j = resp.json()
        # primary
        translated = j.get("responseData", {}).get("translatedText")
        # fallback from matches
        if (not translated) and isinstance(j.get("matches"), list):
            for m in j["matches"]:
                t = m.get("translation") or m.get("translatedText")
                if t:
                    translated = t
                    break
        if translated:
            return translated
        log("MyMemory no translation, resp:", j)
    except Exception as e:
        log("MyMemory error:", e)
    return text

# ---------------- HF Sentiment ----------------
def hf_sentiment(text):
    if not text:
        return ("neutral", 0.0)
    url = f"https://api-inference.huggingface.co/models/{HF_SENTIMENT_MODEL}"
    headers = {"Authorization": f"Bearer {HF_TOKEN}"} if HF_TOKEN else {}
    try:
        r = requests.post(url, headers=headers, json={"inputs": text[:1000]}, timeout=20)
        j = r.json()
        # Typical response: [{'label':'POSITIVE','score':0.99}]
        if isinstance(j, list) and j:
            lab = j[0].get("label", "").lower()
            score = float(j[0].get("score", 0.0))
            if "positive" in lab or "pos" in lab:
                return ("positive", score)
            if "negative" in lab or "neg" in lab:
                return ("negative", score)
        log("HF sentiment response:", j)
    except Exception as e:
        log("HF sentiment error:", e)
    # fallback: neutral
    return ("neutral", 0.0)

# ---------------- Hashtags builder ----------------
def build_hashtags(title, summary):
    tags = set(["#کریپتو", "#Crypto"])
    text = (title + " " + summary).lower()
    for k, v in COIN_TAGS.items():
        if k in text:
            tags.add(v[0])  # Persian
            tags.add(v[1])  # English
            tags.add(f"#{v[2]}")
    # topic tags by keywords
    if any(k in text for k in ["sec", "etf", "regulation", "lawsuit"]):
        tags.add("#فاندامنتال"); tags.add("#Fundamental")
    if any(k in text for k in ["hack", "exploit", "hackers"]):
        tags.add("#هک"); tags.add("#Hack")
    # keep max ~6 tags
    return " ".join(list(tags)[:8])

# ---------------- Telegram send ----------------
def send_telegram_html(html_text):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        log("Telegram token or chat id missing")
        return False
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    data = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": html_text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True
    }
    try:
        r = requests.post(url, data=data, timeout=12)
        if r.status_code != 200:
            log("Telegram send failed:", r.status_code, r.text)
            return False
        log("Sent to Telegram")
        return True
    except Exception as e:
        log("Telegram exception:", e)
        return False

# ---------------- News fetch & scoring ----------------
def fetch_feed_items(limit=20):
    try:
        feed = feedparser.parse(NEWS_FEED_URL)
    except Exception as e:
        log("feedparser error:", e)
        return []
    items = []
    for entry in (feed.entries or [])[:limit]:
        title = getattr(entry, "title", "") or ""
        link = getattr(entry, "link", "") or ""
        desc = getattr(entry, "summary", "") or getattr(entry, "description", "") or ""
        pub = getattr(entry, "published", "") or getattr(entry, "updated", "")
        items.append({"title": title, "link": link, "desc": desc, "pub": pub})
    return items

def score_item(item):
    text = (item["title"] + " " + item["desc"]).lower()
    score = 0
    for kw in KEYWORDS:
        if kw in text:
            score += 2
    # prefer recent items slightly (if pub contains YYYY)
    if item.get("pub"):
        score += 1
    # length of title/desc relevance
    score += min(len(item["title"].split()), 6)
    return score

# ---------------- Technical analysis (simple) ----------------
def get_technical_summary():
    # We'll use CoinGecko simple price endpoint for simplicity
    try:
        coin_ids = {
            "BTC": "bitcoin",
            "ETH": "ethereum",
            "SOL": "solana",
            "TON": "toncoin",
            "XRP": "ripple",
            "BNB": "binancecoin"
        }
        ids = ",".join(coin_ids.values())
        url = f"https://api.coingecko.com/api/v3/simple/price?ids={ids}&vs_currencies=usd&include_24hr_change=true"
        r = requests.get(url, timeout=10)
        j = r.json()
        lines = []
        for sym, cid in coin_ids.items():
            if cid in j:
                price = j[cid]["usd"]
                ch = j[cid].get("usd_24h_change", 0.0)
                status = "📈 صعودی" if ch > 0 else "📉 نزولی" if ch < 0 else "⚖️ خنثی"
                lines.append(f"{sym}: ${price:,.2f} ({ch:+.2f}%) {status}")
        return "\n".join(lines)
    except Exception as e:
        log("tech summary error:", e)
        return "داده در دسترس نیست."

# ---------------- Main run ----------------
def main():
    tz = pytz.timezone(TIMEZONE)
    now = datetime.now(tz)
    today_str = now.strftime("%Y-%m-%d")
    log("Run started", now.isoformat())

    posted = load_posted()
    posted_links = set(posted.get("links", []))

    # 1) Fetch feed
    items = fetch_feed_items(limit=20)
    if not items:
        log("No items from feed")
    # 2) Score & pick top candidates
    scored = []
    for it in items:
        if not it["link"]:
            continue
        if sha256_text(it["link"]) in posted_links:
            log("already posted (skip)", it["link"])
            continue
        s = score_item(it)
        scored.append((s, it))
    scored.sort(reverse=True, key=lambda x: x[0])
    to_post = [it for _, it in scored][:MAX_POSTS_PER_RUN]
    log(f"Selected {len(to_post)} items to post (max {MAX_POSTS_PER_RUN})")

    # 3) Post each selected item
    new_hashes = []
    for it in to_post:
        try:
            title = it["title"]
            desc = it["desc"] or ""
            log("Processing:", title[:120])
            summary_en = hf_summarize(desc or title)
            # make it more "conversational" by small tweak:
            if len(summary_en.split()) < 6:
                # if too short, include a bit of title
                summary_en = title + ". " + summary_en
            # sentiment on title+summary
            sentiment_label, sentiment_score = hf_sentiment(title + " " + summary_en)
            # translate
            fa_title = translate_mymemory(title)
            fa_summary = translate_mymemory(summary_en)
            # build hashtags
            hashtags = build_hashtags(title, summary_en)
            # prepare emoji sentiment
            senti_emoji = "🟢 مثبت" if sentiment_label == "positive" else "🔴 منفی" if sentiment_label == "negative" else "🟡 خنثی"
            # final message
            msg = (
                f"📢 <b>{fa_title}</b>\n\n"
                f"📝 {fa_summary}\n\n"
                f"🧠 تحلیل احساسات: {senti_emoji} ({sentiment_score:.2f})\n\n"
                f"🔗 <a href=\"{it['link']}\">ادامه مطلب</a>\n\n"
                f"{hashtags}\n\n"
                f"👥 @{TELEGRAM_CHAT_ID.strip('@')}\nبه ما بپیوندید 🦈"
            )
            ok = send_telegram_html(msg)
            if ok:
                new_hashes.append(sha256_text(it["link"]))
            time.sleep(2)
        except Exception as e:
            log("post item error:", e)

    # 4) Save posted links if any new
    if new_hashes:
        posted_links.update(new_hashes)
        posted["links"] = list(posted_links)
        # also update last run time (optional)
        posted["last_run"] = datetime.now(tz).isoformat()
        save_posted_and_commit(posted)
    else:
        log("No new posts this run")

    # 5) Analysis posting at 08:00 Tehran (only once per day)
    try:
        last_analysis = posted.get("last_analysis_date", "")
        if now.hour == 8 and last_analysis != today_str:
            log("Posting daily technical analysis at 08:00")
            tech = get_technical_summary()
            analysis_msg = (
                f"📊 تحلیل تکنیکال روزانه ({today_str})\n\n"
                f"{tech}\n\n⚠️ مسئولیت استفاده با کاربر است.\n\n"
                f"👥 @{TELEGRAM_CHAT_ID.strip('@')}\nبه ما بپیوندید 🦈"
            )
            if send_telegram_html(analysis_msg):
                posted["last_analysis_date"] = today_str
                save_posted_and_commit(posted)
        else:
            log("No analysis (either not 08:00 or already posted today)")
    except Exception as e:
        log("analysis post error:", e)

    log("Run finished")

if __name__ == "__main__":
    main()

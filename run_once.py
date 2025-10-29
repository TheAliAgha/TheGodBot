#!/usr/bin/env python3
import os, json, time, subprocess, requests, feedparser
from datetime import datetime
from urllib.parse import quote_plus

# config from secrets
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
HF_TOKEN = os.getenv("HF_TOKEN")
NEWS_FEED_URL = os.getenv("NEWS_FEED_URL", "https://cryptonews.com/news/feed")

POSTED_FILE = "posted.json"   # stored in repo; will be git-committed

def log(*a):
    print(datetime.now().isoformat(), *a, flush=True)

# --- helpers (summarize + translate) ---
def summarize_text(text):
    try:
        url = "https://api-inference.huggingface.co/models/sshleifer/distilbart-cnn-12-6"
        headers = {"Authorization": f"Bearer {HF_TOKEN}"} if HF_TOKEN else {}
        r = requests.post(url, headers=headers, json={"inputs": text[:2000]}, timeout=20)
        r.raise_for_status()
        j = r.json()
        if isinstance(j, list) and j and "summary_text" in j[0]:
            return j[0]["summary_text"]
    except Exception as e:
        log("HF summarize error:", e)
    # fallback simple
    return " ".join([p.strip() for p in text.split(".") if p.strip()][:3])

def translate_mymemory(text):
    try:
        api = "https://api.mymemory.translated.net/get"
        params = {"q": text, "langpair": "en|fa"}
        r = requests.get(api, params=params, timeout=10)
        j = r.json()
        return j.get("responseData", {}).get("translatedText") or text
    except Exception as e:
        log("MyMemory error:", e)
        return text

def send_telegram(html_text):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    data = {"chat_id": TELEGRAM_CHAT_ID, "text": html_text, "parse_mode": "HTML", "disable_web_page_preview": True}
    try:
        r = requests.post(url, data=data, timeout=10)
        if r.status_code != 200:
            log("Telegram send failed:", r.status_code, r.text)
            return False
        return True
    except Exception as e:
        log("Telegram exception:", e)
        return False

# --- persistence: load/save posted titles ---
def load_posted():
    if not os.path.exists(POSTED_FILE):
        return set()
    try:
        with open(POSTED_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            return set(data if isinstance(data, list) else [])
    except Exception as e:
        log("load_posted error:", e)
        return set()

def save_and_commit_posted(posted_set):
    try:
        with open(POSTED_FILE, "w", encoding="utf-8") as f:
            json.dump(list(posted_set), f, ensure_ascii=False, indent=2)
        # git commit & push using GITHUB_TOKEN (provided by Actions)
        token = os.getenv("GITHUB_TOKEN")  # Actions provides this
        repo = os.getenv("GITHUB_REPOSITORY")  # owner/repo
        if token and repo:
            subprocess.run(["git", "config", "user.email", "actions@github.com"], check=False)
            subprocess.run(["git", "config", "user.name", "github-actions"], check=False)
            subprocess.run(["git", "add", POSTED_FILE], check=False)
            subprocess.run(["git", "commit", "-m", "ci: update posted.json (bot)"], check=False)
            remote = f"https://x-access-token:{token}@github.com/{repo}.git"
            # push to the same branch (ACTION runs on default branch, usually main)
            subprocess.run(["git", "push", remote, "HEAD:refs/heads/main"], check=False)
            log("posted.json committed")
        else:
            log("No GITHUB_TOKEN or GITHUB_REPOSITORY in env; skipped commit")
    except Exception as e:
        log("save_and_commit_posted error:", e)

# --- fetch RSS once ---
def fetch_latest(limit=6):
    log("Fetch RSS:", NEWS_FEED_URL)
    feed = feedparser.parse(NEWS_FEED_URL)
    items = []
    for e in feed.entries[:limit]:
        items.append({
            "title": getattr(e, "title", "") or "",
            "link": getattr(e, "link", "") or "",
            "summary": getattr(e, "summary", "") or getattr(e, "description", "") or ""
        })
    log("fetched items:", len(items))
    return items

# --- main run ---
def main():
    posted = load_posted()
    items = fetch_latest()
    new_added = False
    for it in items:
        t = it["title"].strip()
        if not t or t in posted:
            log("skip:", t[:60])
            continue
        # summarize then translate
        summ_en = summarize_text(it["summary"] or it["title"])
        summ_fa = translate_mymemory(summ_en)
        title_fa = translate_mymemory(it["title"])
        html_msg = f"📢 <b>{escape_html(title_fa)}</b>\n\n📝 {escape_html(summ_fa)}\n\n🔗 <a href=\"{it['link']}\">ادامه مطلب</a>\n\n👥 @{TELEGRAM_CHAT_ID.strip('@')}\nبه ما بپیوندید 🦈"
        ok = send_telegram(html_msg)
        if ok:
            posted.add(t)
            new_added = True
            log("posted:", t[:80])
        time.sleep(2)
    # persist if changed
    if new_added:
        save_and_commit_posted(posted)
    else:
        log("no new posts; nothing to commit")

def escape_html(s: str) -> str:
    return (s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            .replace('"', "&quot;").replace("'", "&#39;"))

if __name__ == "__main__":
    main()

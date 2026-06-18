#!/usr/bin/env python3
"""Fetch financial news (CNBC, MarketWatch, Google News, Sina Finance), translate to Chinese."""
import os, json, html, re, sys, time, hashlib, urllib.request, urllib.parse
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

FINANCE_FILE = os.path.join(os.path.dirname(__file__), "docs", "finance.json")
MAX_ARTICLES = 100
BATCH_SIZE = 15
TARGET_LANG = "zh-CN"

# Sources that include article summaries in RSS description field
RSS_FEEDS = [
    "https://www.cnbc.com/id/100003114/device/rss/rss.html",   # CNBC Markets
    "https://www.cnbc.com/id/20409666/device/rss/rss.html",    # CNBC Economy
    "https://feeds.marketwatch.com/marketwatch/topstories/",    # MarketWatch
    "https://news.google.com/rss/search?q=china+stock+market+economy&hl=en-US&gl=US&ceid=US:en",
    "https://rss.sina.com.cn/finance/stock/finance_cjxw.xml",  # 新浪财经·财经新闻
    "https://rss.sina.com.cn/finance/stock/usstock.xml",       # 新浪财经·美股
]

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
      "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")


def fetch(url, timeout=20):
    req = urllib.request.Request(
        url, headers={"User-Agent": UA, "Accept-Language": "en-US,en;q=0.9"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", errors="replace")


def strip_html(s):
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html.unescape(s or ""))).strip()


def parse_rss(text):
    items = []
    try:
        root = ET.fromstring(text)
        for it in root.iter("item"):
            title = strip_html(it.findtext("title") or "")
            link = (it.findtext("link") or "").strip()
            # Some feeds use content:encoded for full text
            ns = {"content": "http://purl.org/rss/1.0/modules/content/"}
            desc = (it.findtext("content:encoded", namespaces=ns)
                    or it.findtext("{http://purl.org/rss/1.0/modules/content/}encoded")
                    or it.findtext("description")
                    or "")
            desc = strip_html(desc)
            pub = (it.findtext("pubDate") or "").strip()
            if title and link and desc:
                items.append({
                    "id": hashlib.md5(link.encode()).hexdigest()[:16],
                    "title": title,
                    "link": link,
                    "text": desc,
                    "date": pub,
                })
    except Exception as e:
        print(f"RSS parse error: {e}", file=sys.stderr)
    return items


def translate(text):
    text = (text or "").strip()[:4500]
    if not text:
        return ""
    url = ("https://translate.googleapis.com/translate_a/single"
           "?client=gtx&sl=en&tl=" + TARGET_LANG + "&dt=t&q=" + urllib.parse.quote(text))
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            data = json.loads(r.read())
        return "".join(seg[0] for seg in data[0] if seg and seg[0]).strip()
    except Exception as e:
        print(f"  Translation failed: {e}", file=sys.stderr)
        return ""


def load_existing():
    if os.path.exists(FINANCE_FILE):
        try:
            with open(FINANCE_FILE, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return []


def main():
    existing = load_existing()
    seen = {p["id"] for p in existing}

    all_items = []
    for feed_url in RSS_FEEDS:
        try:
            print(f"Fetching {feed_url[:70]}")
            items = parse_rss(fetch(feed_url))
            print(f"  Got {len(items)} items with content")
            all_items.extend(items)
        except Exception as e:
            print(f"  Failed: {e}", file=sys.stderr)

    # Deduplicate within this batch
    seen_now = set()
    unique = []
    for it in all_items:
        if it["id"] not in seen_now:
            seen_now.add(it["id"])
            unique.append(it)

    new = [it for it in unique if it["id"] not in seen]
    print(f"Unique: {len(unique)}, new: {len(new)}")
    if not new:
        print("Nothing new.")
        return

    processed = []
    for i, it in enumerate(new[:BATCH_SIZE]):
        print(f"[{i+1}/{min(len(new), BATCH_SIZE)}] {it['title'][:70]}")

        title_zh = translate(it["title"])
        time.sleep(0.4)
        body_zh = translate(it["text"]) if it["text"] else ""
        time.sleep(0.4)

        processed.append({
            "id": it["id"],
            "title": it["title"],
            "title_zh": title_zh,
            "text": it["text"],
            "zh": body_zh,
            "link": it["link"],
            "date": it["date"],
            "fetched_at": datetime.now(timezone.utc).isoformat(),
        })

    merged = (processed + existing)[:MAX_ARTICLES]
    os.makedirs(os.path.dirname(FINANCE_FILE), exist_ok=True)
    with open(FINANCE_FILE, "w", encoding="utf-8") as f:
        json.dump(merged, f, ensure_ascii=False, indent=2)
    print(f"Saved {len(merged)} articles to {FINANCE_FILE}")


if __name__ == "__main__":
    main()

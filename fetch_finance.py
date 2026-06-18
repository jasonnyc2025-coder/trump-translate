#!/usr/bin/env python3
"""Fetch Yahoo Finance news, translate to Chinese, write to docs/finance.json."""
import os, json, html, re, sys, time, hashlib, urllib.request, urllib.parse
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

FINANCE_FILE = os.path.join(os.path.dirname(__file__), "docs", "finance.json")
MAX_ARTICLES = 100
BATCH_SIZE = 15
TARGET_LANG = "zh-CN"

RSS_FEEDS = [
    "https://finance.yahoo.com/news/rssindex",
    "https://feeds.finance.yahoo.com/rss/2.0/headline?s=%5EHSI&region=US&lang=en-US",
    "https://feeds.finance.yahoo.com/rss/2.0/headline?s=000001.SS&region=US&lang=en-US",
    "https://feeds.finance.yahoo.com/rss/2.0/headline?s=SPY%2CQQQ&region=US&lang=en-US",
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
            desc = strip_html(it.findtext("description") or "")
            pub = (it.findtext("pubDate") or "").strip()
            if title and link:
                items.append({
                    "id": hashlib.md5(link.encode()).hexdigest()[:16],
                    "title": title, "link": link, "description": desc, "date": pub,
                })
    except Exception as e:
        print(f"RSS parse error: {e}", file=sys.stderr)
    return items


def fetch_article_text(url):
    """Scrape full article body from Yahoo Finance article page."""
    try:
        page = fetch(url, timeout=25)
        # Article body is server-rendered inside a div.caas-body
        m = re.search(r'class="caas-body"[^>]*>(.*?)(?=<div class="caas-|</article)', page, re.DOTALL)
        if m:
            paras = re.findall(r'<p[^>]*>(.*?)</p>', m.group(1), re.DOTALL)
            text = " ".join(strip_html(p) for p in paras if len(strip_html(p)) > 30)
            if len(text) > 100:
                return text
    except Exception as e:
        print(f"  Article fetch failed: {e}", file=sys.stderr)
    return None


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
            print(f"  Got {len(items)} items")
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

        full_text = fetch_article_text(it["link"]) or it["description"]

        title_zh = translate(it["title"])
        time.sleep(0.4)
        body_zh = translate(full_text) if full_text else ""
        time.sleep(0.4)

        processed.append({
            "id": it["id"],
            "title": it["title"],
            "title_zh": title_zh,
            "text": full_text or "",
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

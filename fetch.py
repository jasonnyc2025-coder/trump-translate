#!/usr/bin/env python3
"""抓取 Truth Social 帖子(经第三方 RSS)，翻译成中文，写入 docs/posts.json。"""
import os
import json
import html
import re
import sys
import urllib.request
import urllib.parse
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

RSS_URL = os.environ.get("RSS_URL", "https://www.trumpstruth.org/feed")
POSTS_FILE = os.path.join(os.path.dirname(__file__), "docs", "posts.json")
MAX_POSTS = 200
TARGET_LANG = "zh-CN"


def fetch_rss(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read()


def strip_html(s):
    s = re.sub(r"<[^>]+>", "", s or "")
    return html.unescape(s).strip()


def parse_feed(raw):
    root = ET.fromstring(raw)
    items = []
    for it in root.iter("item"):
        title = it.findtext("title") or ""
        desc = it.findtext("description") or ""
        link = it.findtext("link") or ""
        guid = it.findtext("guid") or link
        pub = it.findtext("pubDate") or ""
        text = strip_html(desc) or strip_html(title)
        if text:
            items.append({"id": guid.strip(), "text": text, "link": link.strip(), "date": pub.strip()})
    if not items:
        ns = {"a": "http://www.w3.org/2005/Atom"}
        for e in root.iter("{http://www.w3.org/2005/Atom}entry"):
            cid = e.findtext("a:id", default="", namespaces=ns)
            content = e.findtext("a:content", default="", namespaces=ns) or \
                      e.findtext("a:summary", default="", namespaces=ns) or \
                      e.findtext("a:title", default="", namespaces=ns)
            link_el = e.find("a:link", ns)
            link = link_el.get("href") if link_el is not None else ""
            pub = e.findtext("a:updated", default="", namespaces=ns)
            text = strip_html(content)
            if text:
                items.append({"id": (cid or link).strip(), "text": text, "link": link, "date": pub})
    return items


def translate(text):
    text = text.strip()
    if not text:
        return ""
    url = ("https://translate.googleapis.com/translate_a/single"
           "?client=gtx&sl=auto&tl=" + TARGET_LANG + "&dt=t&q=" + urllib.parse.quote(text))
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            data = json.loads(r.read())
        return "".join(seg[0] for seg in data[0] if seg and seg[0]).strip()
    except Exception as e:
        print(f"  翻译失败: {e}", file=sys.stderr)
        return ""


def load_existing():
    if os.path.exists(POSTS_FILE):
        try:
            with open(POSTS_FILE, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return []


def main():
    existing = load_existing()
    seen = {p["id"] for p in existing}
    try:
        feed = parse_feed(fetch_rss(RSS_URL))
    except Exception as e:
        print(f"抓取/解析 RSS 失败: {e}", file=sys.stderr)
        sys.exit(0)
    new = [it for it in feed if it["id"] not in seen]
    print(f"RSS 共 {len(feed)} 条，新帖 {len(new)} 条")
    if not new:
        return
    for it in new:
        it["zh"] = translate(it["text"])
        it["fetched_at"] = datetime.now(timezone.utc).isoformat()
    merged = (new + existing)[:MAX_POSTS]
    os.makedirs(os.path.dirname(POSTS_FILE), exist_ok=True)
    with open(POSTS_FILE, "w", encoding="utf-8") as f:
        json.dump(merged, f, ensure_ascii=False, indent=2)
    print(f"已写入 {len(merged)} 条")


if __name__ == "__main__":
    main()

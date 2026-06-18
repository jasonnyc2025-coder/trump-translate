#!/usr/bin/env python3
"""Fetch top movers: US (Yahoo Finance with cookie session) + A-shares (Sina Finance)."""
import os, json, time, sys, http.cookiejar, urllib.request, urllib.parse
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

MOVERS_FILE = os.path.join(os.path.dirname(__file__), "docs", "movers.json")
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
      "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")
SINA = {"Referer": "https://finance.sina.com.cn/", "User-Agent": UA}

# ── HTTP ──────────────────────────────────────────────────────────────────────

def plain_fetch(url, extra=None, timeout=20):
    h = {"User-Agent": UA, "Accept-Language": "en-US,en;q=0.9"}
    if extra:
        h.update(extra)
    req = urllib.request.Request(url, headers=h)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", errors="replace")

def translate(text):
    text = (text or "").strip()[:500]
    if not text:
        return ""
    url = ("https://translate.googleapis.com/translate_a/single"
           "?client=gtx&sl=auto&tl=zh-CN&dt=t&q=" + urllib.parse.quote(text))
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=20) as r:
            data = json.loads(r.read())
        return "".join(s[0] for s in data[0] if s and s[0]).strip()
    except Exception as e:
        print(f"  translate: {e}", file=sys.stderr)
        return ""

# ── Yahoo Finance session (cookie + crumb) ────────────────────────────────────

_yf_opener = None
_yf_crumb  = None

def init_yf():
    global _yf_opener, _yf_crumb
    cj = http.cookiejar.CookieJar()
    _yf_opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
    try:
        _yf_opener.open(urllib.request.Request(
            "https://finance.yahoo.com/",
            headers={"User-Agent": UA, "Accept": "text/html,application/xhtml+xml"}
        ), timeout=15)
        time.sleep(0.8)
        req = urllib.request.Request(
            "https://query1.finance.yahoo.com/v1/test/getcrumb",
            headers={"User-Agent": UA, "Accept": "*/*",
                     "Referer": "https://finance.yahoo.com/"}
        )
        with _yf_opener.open(req, timeout=15) as r:
            _yf_crumb = r.read().decode().strip()
        print(f"  crumb ok: {_yf_crumb[:8]}…")
    except Exception as e:
        print(f"  YF session failed: {e}", file=sys.stderr)

def yf_fetch(url):
    if _yf_crumb:
        sep = "&" if "?" in url else "?"
        url += f"{sep}crumb={urllib.parse.quote(_yf_crumb)}"
    req = urllib.request.Request(url, headers={
        "User-Agent": UA, "Accept": "application/json",
        "Referer": "https://finance.yahoo.com/"
    })
    with (_yf_opener or urllib.request.urlopen)(req if _yf_opener is None else req,
                                                 timeout=20) as r:
        return r.read().decode("utf-8", errors="replace")

def _yf(url):
    if _yf_opener is None:
        return plain_fetch(url, extra={"Accept": "application/json"})
    if _yf_crumb:
        sep = "&" if "?" in url else "?"
        url += f"{sep}crumb={urllib.parse.quote(_yf_crumb)}"
    req = urllib.request.Request(url, headers={
        "User-Agent": UA, "Accept": "application/json",
        "Referer": "https://finance.yahoo.com/"
    })
    with _yf_opener.open(req, timeout=20) as r:
        return r.read().decode("utf-8", errors="replace")

# ── US movers ─────────────────────────────────────────────────────────────────

def get_us_movers(scr_id):
    url = (f"https://query1.finance.yahoo.com/v1/finance/screener"
           f"/predefined/saved?scrIds={scr_id}&count=10")
    try:
        data = json.loads(_yf(url))
        quotes = data["finance"]["result"][0]["quotes"]
        return [{
            "symbol":     q.get("symbol", ""),
            "name":       q.get("shortName") or q.get("longName", ""),
            "price":      round(float(q.get("regularMarketPrice") or 0), 2),
            "change_pct": round(float(q.get("regularMarketChangePercent") or 0), 2),
            "change":     round(float(q.get("regularMarketChange") or 0), 2),
            "volume":     int(q.get("regularMarketVolume") or 0),
        } for q in quotes]
    except Exception as e:
        print(f"  US {scr_id}: {e}", file=sys.stderr)
        return []

def get_us_sparkline(symbol):
    url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
           f"?interval=5m&range=1d")
    try:
        data = json.loads(_yf(url))
        closes = data["chart"]["result"][0]["indicators"]["quote"][0]["close"]
        pts = [round(c, 4) for c in closes if c is not None]
        # downsample to ≤24 points
        step = max(1, len(pts) // 24)
        return pts[::step]
    except Exception as e:
        print(f"  US spark {symbol}: {e}", file=sys.stderr)
        return []

def get_us_news(symbol, count=3):
    url = f"https://feeds.finance.yahoo.com/rss/2.0/headline?s={symbol}&region=US&lang=en-US"
    try:
        root = ET.fromstring(plain_fetch(url))
        items = []
        for it in root.findall(".//item")[:count]:
            t = (it.findtext("title") or "").strip()
            l = (it.findtext("link") or "").strip()
            if t and l:
                items.append({"title": t, "link": l})
        return items
    except Exception as e:
        print(f"  US news {symbol}: {e}", file=sys.stderr)
        return []

# ── CN movers (Sina Finance) ──────────────────────────────────────────────────

def get_cn_movers(kind):
    asc = "0" if kind == "gainers" else "1"
    url = ("https://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php"
           f"/Market_Center.getHQNodeDataSimple?page=1&num=10&sort=changepercent"
           f"&asc={asc}&node=hs_a&symbol=&_s_r_a=page")
    try:
        data = json.loads(plain_fetch(url, extra=SINA))
        result = []
        for item in (data or []):
            sym = item.get("symbol", "")
            result.append({
                "symbol":     sym.upper(),
                "name":       item.get("name", ""),
                "price":      round(float(item.get("trade") or 0), 2),
                "change_pct": round(float(item.get("changepercent") or 0), 2),
                "change":     round(float(item.get("pricechange") or 0), 2),
                "volume":     int(float(item.get("volume") or 0)),
            })
        return result
    except Exception as e:
        print(f"  CN {kind}: {e}", file=sys.stderr)
        return []

def get_cn_sparkline(symbol):
    url = ("https://money.finance.sina.com.cn/quotes_service/api/json_v2.php"
           f"/CN_MarketData.getKLineData?symbol={symbol.lower()}&scale=5&datalen=48&ma=no")
    try:
        data = json.loads(plain_fetch(url, extra=SINA))
        pts = [float(item["close"]) for item in (data or []) if item.get("close")]
        step = max(1, len(pts) // 24)
        return pts[::step]
    except Exception as e:
        print(f"  CN spark {symbol}: {e}", file=sys.stderr)
        return []

def get_cn_news(symbol, name, count=3):
    # Sina per-stock news
    url = ("https://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php"
           f"/CN_Bill.getTopicBySecCode?num={count}&page=1&id={symbol.lower()}")
    try:
        data = json.loads(plain_fetch(url, extra=SINA))
        items = [{"title": a.get("title", ""), "link": a.get("url", "")}
                 for a in (data or [])[:count] if a.get("title")]
        if items:
            return items
    except Exception as e:
        print(f"  CN news {symbol}: {e}", file=sys.stderr)

    # Fallback: Eastmoney news
    mkt_num = "1" if symbol.startswith("SH") else "0"
    code = symbol[2:]
    url2 = (f"https://np-listapi.eastmoney.com/comm/web/getListInfo"
            f"?client=web&type=1&mTypeAndCode={mkt_num}.{code}&pageSize={count}&pageIndex=1")
    try:
        data = json.loads(plain_fetch(url2, extra={"Referer": "https://www.eastmoney.com/", "User-Agent": UA}))
        return [{"title": a.get("title", ""), "link": a.get("url", "")}
                for a in ((data.get("data") or {}).get("list") or [])[:count] if a.get("title")]
    except Exception as e:
        print(f"  CN news {symbol} (em): {e}", file=sys.stderr)
    return []

# ── Enrich ────────────────────────────────────────────────────────────────────

def enrich_us(stocks):
    for s in stocks:
        print(f"  {s['symbol']} {s['name'][:40]}")
        s["name_zh"] = translate(s["name"])
        time.sleep(0.3)
        s["spark"] = get_us_sparkline(s["symbol"])
        time.sleep(0.2)
        s["news"] = []
        for n in get_us_news(s["symbol"]):
            s["news"].append({"title": n["title"], "title_zh": translate(n["title"]), "link": n["link"]})
            time.sleep(0.3)

def enrich_cn(stocks):
    for s in stocks:
        print(f"  {s['symbol']} {s['name']}")
        s["name_zh"] = s["name"]
        s["spark"] = get_cn_sparkline(s["symbol"])
        news = get_cn_news(s["symbol"], s["name"])
        s["news"] = [{"title": n["title"], "title_zh": n["title"], "link": n["link"]} for n in news]

# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    print("Init Yahoo Finance session…")
    init_yf()

    print("US movers…")
    us_g = get_us_movers("day_gainers")
    us_l = get_us_movers("day_losers")
    print(f"  gainers={len(us_g)} losers={len(us_l)}")

    print("CN movers…")
    cn_g = get_cn_movers("gainers")
    cn_l = get_cn_movers("losers")
    print(f"  gainers={len(cn_g)} losers={len(cn_l)}")

    print("Enriching US…")
    enrich_us(us_g)
    enrich_us(us_l)

    print("Enriching CN…")
    enrich_cn(cn_g)
    enrich_cn(cn_l)

    result = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "us_gainers": us_g, "us_losers": us_l,
        "cn_gainers": cn_g, "cn_losers": cn_l,
    }
    os.makedirs(os.path.dirname(MOVERS_FILE), exist_ok=True)
    with open(MOVERS_FILE, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(f"Saved {MOVERS_FILE}")

if __name__ == "__main__":
    main()

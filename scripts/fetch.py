"""Fetch feeds.yml -> docs/data/items.json. Failed sources keep their previous items."""
import json, re, html, time, datetime as dt, pathlib, yaml, feedparser
import urllib.request, urllib.error
from urllib.parse import urljoin
from html.parser import HTMLParser

ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT = ROOT / "docs/data/items.json"
MAX_AGE_DAYS, MAX_ITEMS = 45, 500
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36 hungarian-goulash/1.0"

def clean(s, n=280):
    s = html.unescape(re.sub(r"<[^>]+>", " ", s or ""))
    s = re.sub(r"\s+", " ", s).strip()
    return s if len(s) <= n else s[:n].rsplit(" ", 1)[0] + "…"

def when(e):
    t = e.get("published_parsed") or e.get("updated_parsed")
    return dt.datetime.fromtimestamp(time.mktime(t), dt.timezone.utc).isoformat() if t else None

class _Links(HTMLParser):
    """Collects <a> links; marks those inside h1-h3 (article titles)."""
    def __init__(s):
        super().__init__(); s.cur = None; s.h = 0; s.links = []
    def handle_starttag(s, t, a):
        if t in ("h1", "h2", "h3"): s.h += 1
        if t == "a": s.cur = {"href": dict(a).get("href") or "", "text": "", "h": s.h > 0}
    def handle_data(s, d):
        if s.cur is not None: s.cur["text"] += d
    def handle_endtag(s, t):
        if t in ("h1", "h2", "h3"): s.h = max(0, s.h - 1)
        if t == "a" and s.cur is not None: s.links.append(s.cur); s.cur = None

def scrape(f):
    """type: html - for sites without a feed. Finds article links by URL pattern (default: /YYYY/MM/DD/)."""
    page = urllib.request.urlopen(urllib.request.Request(f["url"], headers={"User-Agent": UA}), timeout=30).read().decode("utf-8", "replace")
    p = _Links(); p.feed(page)
    pat = re.compile(f.get("link_pattern", r"/\d{4}/\d{2}/\d{2}/"))
    seen = {}   # href -> [(in_heading, text), ...] in page order
    for l in p.links:
        href, t = urljoin(f["url"], l["href"]), re.sub(r"\s+", " ", l["text"]).strip()
        if pat.search(href) and len(t) >= 15 and t not in [x[1] for x in seen.get(href, [])]:
            seen.setdefault(href, []).append((l["h"], t))
    out = []
    for href, texts in seen.items():
        title = next((t for h, t in texts if h), texts[0][1])
        rest = [t for _, t in texts if t != title]
        m = re.search(r"/(\d{4})/(\d{2})/(\d{2})/", href)
        out.append({"link": href, "title": title, "summary": rest[0] if (f.get("lede") and rest) else "",
                    "published_parsed": time.strptime("/".join(m.groups()), "%Y/%m/%d") if m else None})
    return out

HDRS = {"User-Agent": UA, "Accept-Language": "en-US,en;q=0.9",
        "Accept": "application/rss+xml, application/atom+xml, application/xml;q=0.9, text/html;q=0.8, */*;q=0.5"}

def get_entries(f):
    """RSS/Atom via browser-like headers; Substack falls back to its archive API. Errors say what failed."""
    url, errs = f["url"], []
    try:
        d = feedparser.parse(urllib.request.urlopen(urllib.request.Request(url, headers=HDRS), timeout=30).read())
        if d.entries: return d.entries
        errs.append("feed had no entries")
    except urllib.error.HTTPError as e: errs.append(f"feed HTTP {e.code}")
    except Exception as e: errs.append("feed " + str(e)[:60])
    m = re.match(r"https://([\w-]+\.substack\.com)/", url)
    if m:
        try:
            j = json.loads(urllib.request.urlopen(urllib.request.Request(
                f"https://{m.group(1)}/api/v1/archive?sort=new&limit=12", headers=HDRS), timeout=30).read())
            out = [{"link": x["canonical_url"], "title": x.get("title", ""), "summary": x.get("subtitle") or x.get("description") or "",
                    "published_parsed": time.strptime(x["post_date"][:10], "%Y-%m-%d")} for x in j if x.get("canonical_url") and x.get("post_date")]
            if out: return out
            errs.append("api empty")
        except urllib.error.HTTPError as e: errs.append(f"api HTTP {e.code}")
        except Exception as e: errs.append("api " + str(e)[:60])
    raise ValueError("; ".join(errs))

cfg = yaml.safe_load((ROOT / "feeds.yml").read_text())
old = json.loads(OUT.read_text()) if OUT.exists() else {"items": []}
cutoff = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=MAX_AGE_DAYS)
items, status = [], []

for f in cfg.get("feeds", []):
    if f.get("enabled") is False:
        continue
    try:
        if f.get("type") == "html":
            entries = scrape(f)
        else:
            entries = get_entries(f)
        n = 0
        want = f.get("url_contains", "")
        for e in [x for x in entries if want in x.get("link", "")][:f.get("limit", cfg.get("default_limit", 4))]:
            if not e.get("link"):
                continue
            items.append({"id": e.get("id") or e["link"], "title": clean(e.get("title"), 200),
                          "link": e["link"], "source": f["name"], "topic": f.get("topic", "Other"),
                          "published": when(e), "summary": clean(e.get("summary"))})
            n += 1
        status.append({"name": f["name"], "ok": True, "count": n})
    except Exception as ex:  # keep what we had
        kept = [i for i in old["items"] if i["source"] == f["name"]]
        items += kept
        status.append({"name": f["name"], "ok": False, "count": len(kept), "error": str(ex)[:120]})

# keep a rolling archive: earlier items from sources still in feeds.yml
active = {f["name"] for f in cfg.get("feeds", []) if f.get("enabled") is not False}
items += [i for i in old["items"] if i["source"] in active and not i.get("pinned")]

# manual items (pinned: never expire; delete the line in manual.yml to remove)
mf = ROOT / "manual.yml"
for m in (yaml.safe_load(mf.read_text()) or {}).get("items", []) if mf.exists() else []:
    d0 = m.get("date") or dt.date.today()
    items.append({"id": m["url"], "title": m["title"], "link": m["url"], "source": m.get("source", "Manual"),
                  "topic": m.get("topic", "Community"), "summary": m.get("note", ""), "pinned": True,
                  "published": dt.datetime.combine(d0, dt.time(12), dt.timezone.utc).isoformat()})

seen, out = set(), []
for i in sorted(items, key=lambda x: x["published"] or "", reverse=True):
    if i["id"] in seen or (not i.get("pinned") and i["published"] and dt.datetime.fromisoformat(i["published"]) < cutoff):
        continue
    seen.add(i["id"]); out.append(i)

OUT.write_text(json.dumps({"updated": dt.datetime.now(dt.timezone.utc).isoformat(),
    "sources": status, "voices": cfg.get("voices", []), "items": out[:MAX_ITEMS]},
    ensure_ascii=False, indent=1))
print(f"{len(out)} items, {sum(not s['ok'] for s in status)} failing sources")

"""Fetch feeds.yml -> docs/data/items.json. Failed sources keep their previous items."""
import json, re, html, time, datetime as dt, pathlib, yaml, feedparser
import urllib.request
from urllib.parse import urljoin
from html.parser import HTMLParser

ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT = ROOT / "docs/data/items.json"
MAX_AGE_DAYS, MAX_ITEMS = 45, 500
UA = "hungarian-goulash/1.0 (+https://github.com)"

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
    best = {}
    for l in p.links:
        href, t = urljoin(f["url"], l["href"]), re.sub(r"\s+", " ", l["text"]).strip()
        if not pat.search(href) or len(t) < 15: continue
        old = best.get(href)
        if old is None or (l["h"] and not old[0]) or (l["h"] == old[0] and len(t) > len(old[1])): best[href] = (l["h"], t)
    out = []
    for href, (_, t) in best.items():
        m = re.search(r"/(\d{4})/(\d{2})/(\d{2})/", href)
        out.append({"link": href, "title": t, "summary": "",
                    "published_parsed": time.strptime("/".join(m.groups()), "%Y/%m/%d") if m else None})
    return out

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
            d = feedparser.parse(f["url"], agent=UA)
            if d.bozo and not d.entries:
                raise ValueError(str(d.get("bozo_exception", "feed unreadable")))
            entries = d.entries
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

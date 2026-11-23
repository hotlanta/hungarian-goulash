#!/usr/bin/env python3
"""Fetch feeds.yml -> docs/data/items.json. Failed sources keep their previous items."""
from __future__ import annotations

import json
import re
import html
import time
import datetime as dt
import pathlib
import yaml
import feedparser
import urllib.request
import urllib.error
from urllib.parse import urljoin
from html.parser import HTMLParser

def scrape_playwright(f: dict) -> list:
    """Render the page with Chromium to bypass simple Cloudflare challenges."""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent=UA,
            locale="en-US",
            viewport={"width": 1280, "height": 900},
        )
        page = context.new_page()
        page.goto(f["url"], wait_until="networkidle", timeout=45000)
        # Give Cloudflare a moment if a challenge appears
        page.wait_for_timeout(3000)
        html = page.content()
        browser.close()

    # Re-use the existing HTML parser
    p = _Links()
    p.feed(html)
    pat = re.compile(f.get("link_pattern", r"/\d{4}/\d{2}/\d{2}/"))
    seen = {}
    for l in p.links:
        href = urljoin(f["url"], l["href"])
        t = re.sub(r"\s+", " ", l["text"]).strip()
        if pat.search(href) and len(t) >= 15 and t not in [x[1] for x in seen.get(href, [])]:
            seen.setdefault(href, []).append((l["h"], t))
    out = []
    for href, texts in seen.items():
        title = next((t for h, t in texts if h), texts[0][1])
        rest = [t for _, t in texts if t != title]
        m = re.search(r"/(\d{4})/(\d{2})/(\d{2})/", href)
        published_parsed = None
        if m:
            try:
                published_parsed = time.strptime("/".join(m.groups()), "%Y/%m/%d")
            except ValueError:
                pass
        out.append({
            "link": href,
            "title": title,
            "summary": rest[0] if (f.get("lede") and rest) else "",
            "published_parsed": published_parsed,
        })
    if not out:
        raise ValueError("no matching article links found after Playwright render")
    return out

ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT = ROOT / "docs/data/items.json"
MAX_AGE_DAYS = 45
MAX_ITEMS = 500
UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36 hungarian-goulash/1.1"
)
HDRS = {
    "User-Agent": UA,
    "Accept-Language": "en-US,en;q=0.9",
    "Accept": "application/rss+xml, application/atom+xml, application/xml;q=0.9, text/html;q=0.8, */*;q=0.5",
}


def clean(s: str | None, n: int = 280) -> str:
    s = html.unescape(re.sub(r"<[^>]+>", " ", s or ""))
    s = re.sub(r"\s+", " ", s).strip()
    return s if len(s) <= n else s[:n].rsplit(" ", 1)[0] + "…"


def when(e) -> str | None:
    t = e.get("published_parsed") or e.get("updated_parsed")
    if not t:
        return None
    try:
        return dt.datetime.fromtimestamp(time.mktime(t), dt.timezone.utc).isoformat()
    except Exception:
        return None


class _Links(HTMLParser):
    """Collect <a> links; mark those inside h1–h3 (likely titles)."""

    def __init__(self):
        super().__init__()
        self.cur = None
        self.h = 0
        self.links = []

    def handle_starttag(self, tag, attrs):
        if tag in ("h1", "h2", "h3"):
            self.h += 1
        if tag == "a":
            self.cur = {"href": dict(attrs).get("href") or "", "text": "", "h": self.h > 0}

    def handle_data(self, data):
        if self.cur is not None:
            self.cur["text"] += data

    def handle_endtag(self, tag):
        if tag in ("h1", "h2", "h3"):
            self.h = max(0, self.h - 1)
        if tag == "a" and self.cur is not None:
            self.links.append(self.cur)
            self.cur = None


def _fetch(url: str, timeout: int = 30) -> bytes:
    """Simple GET with retries for transient errors."""
    last_err = None
    for attempt in range(3):
        try:
            req = urllib.request.Request(url, headers=HDRS)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read()
        except urllib.error.HTTPError as e:
            last_err = e
            if e.code in (429, 500, 502, 503, 504) and attempt < 2:
                time.sleep(1.5 * (attempt + 1))
                continue
            raise
        except Exception as e:
            last_err = e
            if attempt < 2:
                time.sleep(1.5 * (attempt + 1))
                continue
            raise
    raise last_err  # type: ignore


def scrape(f: dict) -> list:
    """type: html – sites without a usable feed. Finds article links by URL pattern."""
    raw = _fetch(f["url"]).decode("utf-8", "replace")
    if "Just a moment" in raw or "cf-mitigated" in raw or "cf-challenge" in raw.lower():
        raise ValueError("Cloudflare challenge / bot protection (page not readable from this environment)")
    p = _Links()
    p.feed(raw)
    pat = re.compile(f.get("link_pattern", r"/\d{4}/\d{2}/\d{2}/"))
    seen: dict[str, list] = {}
    for l in p.links:
        href = urljoin(f["url"], l["href"])
        t = re.sub(r"\s+", " ", l["text"]).strip()
        if pat.search(href) and len(t) >= 15 and t not in [x[1] for x in seen.get(href, [])]:
            seen.setdefault(href, []).append((l["h"], t))
    out = []
    for href, texts in seen.items():
        title = next((t for h, t in texts if h), texts[0][1])
        rest = [t for _, t in texts if t != title]
        m = re.search(r"/(\d{4})/(\d{2})/(\d{2})/", href)
        published_parsed = None
        if m:
            try:
                published_parsed = time.strptime("/".join(m.groups()), "%Y/%m/%d")
            except ValueError:
                pass
        out.append({
            "link": href,
            "title": title,
            "summary": rest[0] if (f.get("lede") and rest) else "",
            "published_parsed": published_parsed,
        })
    if not out:
        raise ValueError("no matching article links found (page structure may have changed)")
    return out


def get_entries(f: dict) -> list:
    """RSS/Atom first; Substack falls back to its public archive API."""
    url = f["url"]
    errs: list[str] = []

    # 1. Try normal feed
    try:
        data = _fetch(url)
        d = feedparser.parse(data)
        if d.entries:
            return d.entries
        errs.append("feed had no entries")
    except urllib.error.HTTPError as e:
        errs.append(f"feed HTTP {e.code}")
    except Exception as e:
        errs.append("feed " + str(e)[:80])

    # 2. Substack archive API fallback
    m = re.match(r"https://([\w-]+\.substack\.com)/", url)
    if m:
        api = f"https://{m.group(1)}/api/v1/archive?sort=new&limit=12"
        try:
            raw = _fetch(api)
            payload = json.loads(raw)
            # Modern shape is {"posts": [...]}; older was a bare list
            posts = payload.get("posts") if isinstance(payload, dict) else payload
            if not isinstance(posts, list):
                raise ValueError("unexpected API shape")
            out = []
            for x in posts:
                if not x.get("canonical_url") or not x.get("post_date"):
                    continue
                try:
                    pub = time.strptime(x["post_date"][:10], "%Y-%m-%d")
                except Exception:
                    pub = None
                out.append({
                    "link": x["canonical_url"],
                    "title": x.get("title") or "",
                    "summary": x.get("subtitle") or x.get("description") or "",
                    "published_parsed": pub,
                })
            if out:
                return out
            errs.append("api returned no usable posts")
        except urllib.error.HTTPError as e:
            errs.append(f"api HTTP {e.code}")
        except Exception as e:
            errs.append("api " + str(e)[:80])

    raise ValueError("; ".join(errs) or "unknown error")


def main() -> None:
    cfg = yaml.safe_load((ROOT / "feeds.yml").read_text(encoding="utf-8"))
    old = {"items": [], "sources": []}
    if OUT.exists():
        try:
            old = json.loads(OUT.read_text(encoding="utf-8"))
        except Exception:
            pass

    cutoff = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=MAX_AGE_DAYS)
    items: list[dict] = []
    status: list[dict] = []
    now_iso = dt.datetime.now(dt.timezone.utc).isoformat()

    for f in cfg.get("feeds", []):
        if f.get("enabled") is False:
            continue
        name = f["name"]
        try:
            if f.get("type") == "playwright":
                entries = scrape_playwright(f)
            elif f.get("type") == "html":
                entries = scrape(f)
            else:
                entries = get_entries(f)

            n = 0
            want = f.get("url_contains") or ""
            limit = f.get("limit", cfg.get("default_limit", 4))
            for e in [x for x in entries if want in (x.get("link") or "")][:limit]:
                link = e.get("link")
                if not link:
                    continue
                items.append({
                    "id": e.get("id") or link,
                    "title": clean(e.get("title"), 200),
                    "link": link,
                    "source": name,
                    "topic": f.get("topic", "Other"),
                    "published": when(e),
                    "summary": clean(e.get("summary")),
                })
                n += 1
            status.append({
                "name": name,
                "ok": True,
                "count": n,
                "last_success": now_iso,
            })
        except Exception as ex:
            # Keep previous items from this source
            kept = [i for i in old.get("items", []) if i.get("source") == name]
            items.extend(kept)
            prev = next((s for s in old.get("sources", []) if s.get("name") == name), {})
            status.append({
                "name": name,
                "ok": False,
                "count": len(kept),
                "error": str(ex)[:160],
                "last_success": prev.get("last_success"),
            })

    # Rolling archive: keep older items from still-active sources
    active = {f["name"] for f in cfg.get("feeds", []) if f.get("enabled") is not False}
    items.extend(
        i for i in old.get("items", [])
        if i.get("source") in active and not i.get("pinned")
    )

    # Manual / pinned items
    mf = ROOT / "manual.yml"
    if mf.exists():
        manual = yaml.safe_load(mf.read_text(encoding="utf-8")) or {}
        for m in manual.get("items", []):
            d0 = m.get("date") or dt.date.today()
            if isinstance(d0, str):
                try:
                    d0 = dt.date.fromisoformat(d0)
                except ValueError:
                    d0 = dt.date.today()
            items.append({
                "id": m["url"],
                "title": m["title"],
                "link": m["url"],
                "source": m.get("source", "Manual"),
                "topic": m.get("topic", "Community"),
                "summary": m.get("note", ""),
                "pinned": True,
                "published": dt.datetime.combine(d0, dt.time(12), dt.timezone.utc).isoformat(),
            })

    # Dedupe + age filter + sort
    seen: set[str] = set()
    out: list[dict] = []
    for i in sorted(items, key=lambda x: x.get("published") or "", reverse=True):
        iid = i.get("id")
        if not iid or iid in seen:
            continue
        if not i.get("pinned") and i.get("published"):
            try:
                if dt.datetime.fromisoformat(i["published"]) < cutoff:
                    continue
            except Exception:
                pass
        seen.add(iid)
        out.append(i)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "updated": now_iso,
        "sources": status,
        "voices": cfg.get("voices", []),
        "items": out[:MAX_ITEMS],
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    failing = sum(1 for s in status if not s["ok"])
    print(f"{len(out)} items, {failing} failing sources")
    for s in status:
        mark = "OK " if s["ok"] else "FAIL"
        extra = f" – {s.get('error', '')}" if not s["ok"] else f" ({s['count']} new)"
        print(f"  {mark} {s['name']}{extra}")


if __name__ == "__main__":
    main()

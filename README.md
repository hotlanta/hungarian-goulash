# Hungarian Goulash

A lightweight, static English-language news aggregator focused on Hungary.  
Config-driven sources → Python fetcher → single JSON file → vanilla JS PWA frontend.

## What’s included in this package

| Path | Purpose |
|------|---------|
| `feeds.yml` | Source list (RSS + HTML scrapers) + “voices” |
| `scripts/fetch.py` | Improved fetcher with retries, Substack API fix, Cloudflare detection, last-success timestamps |
| `docs/index.html` | Frontend (search, topics, saved items, source health) |
| `docs/sw.js` | Minimal service worker (offline shell + network-first data) |
| `docs/manifest.webmanifest` | PWA manifest |
| `.github/workflows/update.yml` | Scheduled + on-push workflow that runs the fetcher and commits `docs/data/items.json` |

You still need to supply (or keep your existing) icons:

- `docs/icon.svg`
- `docs/icon-192.png`
- `docs/icon-512.png`

and an optional `manual.yml` for pinned stories.

## Why Telex English and the Substacks were failing

- **Telex English** (`type: html`) is protected by Cloudflare. Simple `urllib` requests from GitHub Actions (and many cloud IPs) receive a challenge page instead of the real HTML. The updated scraper detects this and reports a clear error while keeping previously fetched items.
- **Substack feeds** – the RSS endpoints still work, but the archive-API fallback was broken because Substack now returns `{"posts": [...]}` instead of a bare list. The new `fetch.py` handles both shapes and prefers the RSS feed first.

After you deploy the new `scripts/fetch.py`, re-run the workflow; the three Substack sources should start succeeding again. Telex English will continue to show as failing until a browser-based approach (Playwright) or an official English feed becomes available.

## Quick start (GitHub Pages)

1. Create a new repository (or use an existing one).
2. Copy the contents of this package into the repository root so the layout looks like:

   ```
   .
   ├── feeds.yml
   ├── manual.yml          # optional
   ├── scripts/
   │   └── fetch.py
   ├── docs/
   │   ├── index.html
   │   ├── sw.js
   │   ├── manifest.webmanifest
   │   ├── icon.svg
   │   ├── icon-192.png
   │   ├── icon-512.png
   │   └── data/           # created automatically
   └── .github/
       └── workflows/
           └── update.yml
   ```

3. Commit and push.
4. In the repository settings → **Pages**:
   - Source: **Deploy from a branch**
   - Branch: `main` (or `master`), folder: **/docs**
5. Go to the **Actions** tab → “Update feeds” → **Run workflow**.
6. After the first successful run, `docs/data/items.json` will exist and the site will show articles.

The site will be available at `https://<user>.github.io/<repo>/`.

## Local development

```bash
# one-time
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install feedparser pyyaml

# fetch fresh data
python scripts/fetch.py

# serve the docs folder
cd docs
python -m http.server 8000
# open http://localhost:8000
```

## Editing sources

- Open `feeds.yml`.
- Add, remove, or set `enabled: false` on any entry.
- For sites without RSS use `type: html` and optionally a custom `link_pattern`.
- Push the change; the workflow runs automatically on `feeds.yml` / `scripts/**` changes.

## Optional: pinned / manual stories

Create `manual.yml` in the repository root:

```yaml
items:
  - title: "Example community event"
    url: "https://example.com/event"
    source: "Community"
    topic: "Community"
    note: "Optional short description"
    date: "2026-11-20"   # optional, defaults to today
```

Pinned items never expire.

## Service worker & offline

The included `sw.js` caches the app shell and uses a network-first strategy for `items.json`. After the first visit the UI will still open offline (showing the last successfully cached data).

## Troubleshooting

| Symptom | Likely cause / fix |
|---------|--------------------|
| Substacks still failing | Confirm you deployed the new `scripts/fetch.py`. Check the Actions log for the exact error. |
| Telex English always failing | Expected under Cloudflare from Actions. Previous items are retained. Consider switching it to a “voices” entry or adding Playwright later. |
| Empty feed after first run | Workflow may have failed. Open the Actions run and inspect the “Fetch feeds” step. |
| Icons missing | Add `icon.svg`, `icon-192.png`, `icon-512.png` under `docs/`. |
| Push rejected | Branch protection or concurrent runs. The workflow already retries with rebase. |

## Licence / attribution

This is a personal aggregator. Respect each site’s terms and robots rules. The code is provided as-is for your own use.

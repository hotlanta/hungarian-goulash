# Hungarian Goulash
English-language news about Hungary. GitHub Actions fetches feeds into `docs/data/items.json`; a PWA in `docs/` reads it.

## Setup
1. New public GitHub repo, upload these files (`.github/workflows/update.yml` must keep its path).
2. Settings > Actions > General > Workflow permissions: **Read and write**.
3. Actions > **Update feeds** > Run workflow. Then check the app's **Sources** tab.
4. Settings > Pages > Deploy from `main`, folder `/docs`. Open the URL in Chrome > **Install app**.

## Change sources
Edit `feeds.yml`. Substack: `https://NAME.substack.com/feed`. Add one-off posts in `manual.yml`.

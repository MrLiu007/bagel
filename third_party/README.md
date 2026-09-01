# third_party/

Bagel **does not vendor** [MediaCrawler](https://github.com/NanmiCoder/MediaCrawler).

| Path | In git? | Purpose |
|------|---------|---------|
| `patches/bagel_entry.py` | Yes | Thin Bagel entry shim (Playwright / QR) |
| `MediaCrawler/` | **No** (gitignored) | Local clone — auto on startup or `bagel setup-media` |

## Startup auto-clone

When `ENABLE_MEDIA_CRAWLER=true` and `MEDIA_CRAWLER_AUTO_SETUP=true` (defaults), starting Bagel (`bagel dev`) will **clone MediaCrawler once** if `main.py` is missing. Already-present checkouts are left alone.

GitHub may need **VPN / proxy** from mainland networks. Set `MEDIA_CRAWLER_GIT_URL` to a mirror if needed. See [docs/git-and-mediacrawler.md](../docs/git-and-mediacrawler.md).

## Manual setup

```bash
uv run bagel setup-media
# or with mirror:
uv run bagel setup-media --repo https://your-mirror.example/MediaCrawler.git
```

Then install MediaCrawler’s own deps inside **its** `.venv` (upstream README; often Python 3.11 + Playwright Chromium).

`.env`:

```env
ENABLE_MEDIA_CRAWLER=true
MEDIA_CRAWLER_AUTO_SETUP=true
MEDIA_CRAWLER_PATH=./third_party/MediaCrawler
MEDIA_CRAWLER_GIT_URL=
```

MediaCrawler uses a **non-commercial learning license** — respect upstream terms when redistributing.

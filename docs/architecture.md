# Architecture

```text
User → Bagel (FastAPI + Jinja2 + Typer CLI)
            │
   ┌────────┼──────────────┐
   ▼        ▼              ▼
SQLite /  FreshRSS       RSSHub
Postgres  (RSS infra)    (feed adapter)
(business SoT)
```

## Principles

- **Transactional DB is the only business source of truth** (`IntelItem`, `IntelRawEvidence`).
  Default is **SQLite** (`data/bagel.db`); PostgreSQL is optional for team / concurrent writes.
- Collectors only collect. All external payloads normalize into `IntelItem` via `NormalizedItem`.
- LLM output never overwrites raw evidence (`IntelRawEvidence`).
- FreshRSS / RSSHub are hidden infrastructure (no public ports by default).
- Network mode `AUTO` / `DIRECT` / `PROXY`: overseas / GitHub failures must not stop CN collection.
- Interest filters are **per channel**: INCLUDE on each data-source settings tab; EXCLUDE on **系统排除词** with multi-select scopes ([filter-tags.md](./filter-tags.md)).
- Media/wechat keep env crawl keywords; EXCLUDE can still apply after ingest when scoped.
- In-process APScheduler for scheduled jobs (idempotent; prefer single worker).
- Optional Markdown **wiki** under `WIKI_DIR` holds compiled readable pages; `wiki_page` / `wiki_edge` hold transactional indexes. Domain taxonomy seed lives in-package (structure inspired by os-taxonomy; not Marble curriculum data). Personal space GBrain is a resource-first 3D cone (`/briefs/space?view=graph`); UX notes in [wiki-taxonomy-gbrain.md](./wiki-taxonomy-gbrain.md) and [briefs-dashboard.md](./briefs-dashboard.md).
- **AV / papers / GitHub learn** are first-class product surfaces: yt-dlp + openspeech ASR ([media-vs-av.md](./media-vs-av.md)), MinerU/Kimi paper parse ([paper-parse.md](./paper-parse.md)), lazy GitHub Wiki + Archify ([github-learn.md](./github-learn.md)).
- Reverse-proxy path prefix via `X-Forwarded-Prefix` / `X-Script-Name` (`web/proxy_prefix.py`) so one Nginx can mount multiple apps (e.g. `/bagel`). Compose defaults to `127.0.0.1:6280` + `deploy/nginx/bagel-location.conf` — see [deploy-ecs.md](./deploy-ecs.md).

## Package layout

| Package | Role |
| --- | --- |
| `domain/` | ORM models, enums, DTOs |
| `collectors/` | Fetch external data only |
| `pipeline/` | Normalize, filter, categorize, recency, paper source helpers |
| `storage/` | Engine, repositories, seed |
| `jobs/` | Idempotent collect / digest / brief / **av** / `source_guard` |
| `services/` | Business orchestration (auth, health, Feishu, LLM, **av_bridge**, **brief_ppt**, **paper_parse**, **github_learn**, …) |
| `integrations/` | HTTP clients / external CLIs (**ytdlp**, **volc_asr**, **av_transcript**, **mineru**, **kimi_files**, **archify**, …) |
| `web/` | FastAPI routes + Jinja templates (`/av`, `/github/learn`, briefs present/PPT, …) |
| `cli/` | `bagel` Typer entry (`setup-media` / `setup-ytdlp` / `setup-archify`) |

## External tools (not vendored)

| Tool | Path | Notes |
| --- | --- | --- |
| MediaCrawler | `third_party/MediaCrawler` | gitignored; 自媒体 |
| yt-dlp | `third_party/yt-dlp` | gitignored; 音视频 |
| Archify | `third_party/archify` | gitignored; Node ≥ 18 |
| openspeech ASR | cloud API | `VOLC_ASR_*`；豆包语音录音文件识别 |

## Stack (summary)

| Layer | Choice |
| --- | --- |
| Runtime | Python ≥ 3.14, uv |
| Web | FastAPI, Uvicorn, Jinja2 |
| ORM / migrate | SQLAlchemy 2.x, Alembic |
| HTTP | httpx, feedparser |
| Schedule | APScheduler |
| LLM | OpenAI-compatible `chat/completions` (optional) |
| AV | yt-dlp subprocess + ffmpeg (optional) + openspeech / Whisper |
| Present | reveal.js (CDN) for brief PPT mode |

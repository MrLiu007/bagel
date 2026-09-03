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
- Optional Markdown **wiki** under `WIKI_DIR` holds compiled readable pages; `wiki_page` / `wiki_edge` hold transactional indexes. Domain taxonomy seed lives in-package (structure inspired by os-taxonomy; not Marble curriculum data). See [wiki-taxonomy-gbrain.md](./wiki-taxonomy-gbrain.md).

## Package layout

| Package | Role |
| --- | --- |
| `domain/` | ORM models, enums, DTOs |
| `collectors/` | Fetch external data only |
| `pipeline/` | Normalize, filter, categorize, recency |
| `storage/` | Engine, repositories, seed |
| `jobs/` | Idempotent collect / digest / brief jobs |
| `services/` | Business orchestration (auth, health, Feishu, LLM, …) |
| `integrations/` | HTTP clients / external CLIs |
| `web/` | FastAPI routes + Jinja templates |
| `cli/` | `bagel` Typer entry |

## Stack (summary)

| Layer | Choice |
| --- | --- |
| Runtime | Python ≥ 3.14, uv |
| Web | FastAPI, Uvicorn, Jinja2 |
| ORM / migrate | SQLAlchemy 2.x, Alembic |
| HTTP | httpx, feedparser |
| Schedule | APScheduler |
| LLM | OpenAI-compatible `chat/completions` (optional) |

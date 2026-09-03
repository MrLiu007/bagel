# Data Model

Transactional DB (SQLite default / Postgres optional) is the only business
source of truth. Optional Markdown wiki export is a side channel only.

## Core tables

- `app_user` — login accounts; `owner_id` scopes other tables
- `intel_source` — news / RSSHub / stock / paper / **model** sources (DB-managed, not YAML)
- `intel_keyword_rule` — INCLUDE / EXCLUDE / BOOST + `scopes`（类目 CSV）；见 [filter-tags.md](./filter-tags.md)
- `intel_search_event` — 搜索日志（看板 / 飞书）；见 [briefs-dashboard.md](./briefs-dashboard.md)
- `intel_github_query` — GitHub search queries
- `intel_raw_evidence` — immutable raw payloads (never overwritten by LLM)
- `intel_item` — unified IntelItem + review flags + LLM fields
- `intel_monthly_brief` — week / month briefs by kind；`metadata.prompt_used` 存生成提示词
- `intel_job_run` — job execution records
- `intel_github_repo_snapshot` — star / fork snapshots

## Item status

```text
DISCOVERED → NORMALIZED → CANDIDATE
                ↙           ↘
           REJECTED      SELECTED → SUMMARIZED → PUBLISHED → WIKI_EXPORTED
```

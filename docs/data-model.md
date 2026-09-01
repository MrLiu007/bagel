# Data Model

## Core tables

- `intel_source` — news / RSSHub sources (DB-managed, not YAML)
- `intel_keyword_rule` — INCLUDE / EXCLUDE / BOOST
- `intel_github_query` — GitHub search queries
- `intel_raw_evidence` — immutable raw payloads
- `intel_item` — unified IntelItem + review flags + LLM fields
- `intel_job_run` — job execution records
- `intel_github_repo_snapshot` — star / fork snapshots

## Item status

```text
DISCOVERED → NORMALIZED → CANDIDATE
                ↙           ↘
           REJECTED      SELECTED → SUMMARIZED → PUBLISHED → WIKI_EXPORTED
```

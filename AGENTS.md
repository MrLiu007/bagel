# Bagel（贝果）Development Rules

1. Python version must be >= 3.14.
2. Use uv only for dependency management.
3. User-facing configuration must only use `.env` (plus `data/runtime_config.json` for scheduler / Feishu UI overrides).
4. Business source of truth is the transactional DB (SQLite by default, Postgres optional).
5. Collectors only collect data.
6. All external data must normalize into `IntelItem`.
7. Raw evidence must never be overwritten by LLM output.
8. FreshRSS and RSSHub are infrastructure dependencies only.
9. Never fork or modify FreshRSS/RSSHub source code.
10. Do not add microservices without explicit approval.
11. Do not add Redis, Kafka, MQ, Elasticsearch or vector DB unless required.
12. Do not add a standalone frontend project in MVP.
13. All schema changes must use Alembic migrations.
14. All scheduled jobs must be idempotent.
15. External network failures must support degraded operation.
16. GitHub or overseas RSS failures must never stop domestic collection.
17. All new features require tests.
18. LLM prompts must be version controlled.
19. Keep files small and responsibilities explicit.
20. Never expose machine-absolute filesystem paths in UI / user-facing messages — use project-relative display paths.
21. Public brand: **Bagel** (EN) / **贝果** (ZH); package & CLI name is `bagel`.

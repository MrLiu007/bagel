# Architecture

```text
User → Bagel (FastAPI / Jinja2)
            │
   ┌────────┼────────┐
   ▼        ▼        ▼
PostgreSQL  FreshRSS  RSSHub
(business)  (RSS infra) (feed adapter)
```

- PostgreSQL is the **only** business source of truth (`IntelItem`, `IntelRawEvidence`).
- Collectors normalize into `IntelItem`; LLM never overwrites raw evidence.
- FreshRSS / RSSHub are hidden infrastructure (no public ports by default).
- Network mode `AUTO` / `DIRECT` / `PROXY` with degraded operation when overseas/GitHub fails.

# 存储架构：SQLite 默认 · Postgres 可选 · LLM Wiki 导出

## 决策

开源默认要「克隆即可跑」。强制 PostgreSQL 会劝退大多数贡献者。

| 后端 | 定位 | 何时用 |
| --- | --- | --- |
| **SQLite（默认）** | 事务真相源 | 个人、演示、CI |
| **PostgreSQL** | 事务真相源 | 团队常驻、并发写入 |
| **LLM Wiki** | 可读知识正文（MD）+ DB 索引 | Obsidian / 人工浏览；`wiki_page`/`wiki_edge` 供查询与 GBrain |

不推荐「仅 Markdown 文件当主库」：去重、状态（收藏/忽略）、按发布时间分页、月度聚合都会变脆。

## 配置

```env
# sqlite | postgres
STORAGE_BACKEND=sqlite

# sqlite 默认路径（也可写完整 SQLAlchemy URL）
DATABASE_URL=sqlite+pysqlite:///./data/bagel.db

# postgres 示例
# STORAGE_BACKEND=postgres
# DATABASE_URL=postgresql+psycopg://intel:intel@127.0.0.1:5432/intel

# 导出到 Markdown wiki（可选）
WIKI_ENABLED=true
WIKI_DIR=data/wiki
```

启动时：

1. 解析 `STORAGE_BACKEND` + `DATABASE_URL`
2. SQLite：自动 `create_all`（无外部 migrate 也可跑通 MVP）
3. Postgres：建议 `alembic upgrade head`
4. `WIKI_ENABLED=true`：生成日报/月报时同步写 wiki

## LLM Wiki 目录约定

```text
data/wiki/
  index.md
  news/YYYY-MM/*.md
  github/YYYY-MM/*.md
  briefs/news-YYYY-MM.md
  briefs/github-YYYY-MM.md
```

每条卡片含：标题、发布时间、分类、摘要、原文链接、tags。可直接被本地 LLM 做检索增强。

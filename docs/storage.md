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
2. SQLite：`init_db` → `ensure_schema`（`create_all` 幂等，表不存在才建）+ seed
3. Postgres（Compose）：`docker-entrypoint` 先 `alembic upgrade head`，再 `ensure_schema` 补齐缺失表
4. **注意**：`app_user` 在迁移 `0005a_app_user` 中创建；`wiki_page` / `gbrain_learn_event` 外键依赖它。若只有旧库且停在 `0005`，升级会先补 `app_user` 再跑 `0006`
5. `WIKI_ENABLED=true`：生成日报/月报时同步写 wiki

重新部署 Postgres 若曾出现 `relation "app_user" does not exist`：拉取含 `0005a_app_user` 的版本后 `docker compose up -d --build` 即可；入口会对缺失表做 create-if-not-exists 兜底。

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

## 本地工作区目录（非事务真相源）

事务真相仍在 DB。下列目录存**大文件 / 缓存 / 学习产物**（默认在 `DATA_DIR`，通常 `./data`）：

```text
data/
  bagel.db                 # SQLite 默认库
  av/
    files/{item_id}/       # yt-dlp 下载的音视频
    subs/{item_id}/        # 抽轨音轨、ASR 中间文件
  cache/
    brief_ppt/{brief_id}.json   # 汇总 PPT 幻灯片缓存（内容指纹）
  github/
    learn/{item_id}/       # GitHub 学习 Wiki / snippets / architecture.html
  wiki/                    # 可选 Markdown Wiki 导出
  user_config/{user_id}.json
  brief_prompts.json
  runtime_config.json      # 调度 / 飞书等 UI 覆盖
```

UI / 日志对外只展示**项目相对路径**，不暴露本机绝对路径（AGENTS.md）。

相关：音视频 [media-vs-av.md](./media-vs-av.md)、PPT [briefs-dashboard.md](./briefs-dashboard.md)、学习页 [github-learn.md](./github-learn.md)。

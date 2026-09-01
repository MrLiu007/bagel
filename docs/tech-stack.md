# 技术栈梳理（贝果）

面向开源贡献者与二次部署者的「用到了什么、为什么」。

## 运行时与 Web

| 层 | 选型 | 用途 |
| --- | --- | --- |
| 语言 | Python ≥ 3.14 | 业务与采集主语言 |
| Web | FastAPI + Uvicorn | HTTP API / Jinja2 页面 |
| CLI | Typer + Rich | `bagel doctor` / `bagel dev` |
| 模板 | Jinja2 | 审核页、设置、总结、采集进度 |
| 包管理 | uv | 依赖锁定与本地启动 |

## 数据与持久化

| 层 | 选型 | 用途 |
| --- | --- | --- |
| ORM | SQLAlchemy 2.x | 领域模型 |
| 迁移 | Alembic | PostgreSQL 演进 |
| 默认库（开源友好） | **SQLite**（`data/bagel.db`） | 零外部依赖即可跑 |
| 可选库 | PostgreSQL + psycopg | 生产 / 多用户 |
| 可选知识库 | **LLM Wiki**（Markdown 目录） | 把条目/月报导出为可检索 wiki，不替代事务库 |

`STORAGE_BACKEND`：

- `sqlite`（默认）：本地单文件，适合个人与演示
- `postgres`：用 `DATABASE_URL` 指向 Postgres
- `wiki`：在 sqlite/postgres 之上**额外**把日报/月报/精选同步到 `data/wiki/`（Obsidian / LLM RAG 友好）

> 「只用 wiki、完全不要数据库」无法支撑去重、状态机、分页筛选；因此 wiki 是导出层，不是唯一存储。若必须无服务器组件，请用默认 SQLite。

## 采集与集成

| 能力 | 技术 | 说明 |
| --- | --- | --- |
| AI 新闻 | feedparser + httpx | 官方 RSS / RSSHub |
| GitHub | GitHub REST + httpx | Search / Release / stars 快照 |
| 自媒体 | **MediaCrawler**（外部进程） | 小红书/抖音/B 站等；本仓库不内嵌其源码（非商业学习许可） |
| 微信 | **Gewe API**（HTTP） | 个人微信消息通道；风控由三方协议承担 |
| 调度（可选） | APScheduler | 当前默认手动采集 |

## 大模型

| 项 | 说明 |
| --- | --- |
| 协议 | OpenAI 兼容 `POST /chat/completions` |
| 配置 | `LLM_BASE_URL` / `LLM_API_KEY` / `LLM_MODEL` |
| 用途 | 单条摘要、月度终稿润色（可选） |
| 关闭方式 | `LLM_ENABLED=false` 或留空 BASE_URL |

任意兼容服务均可：OpenAI、Azure、DeepSeek、本地 Ollama（需兼容路径）等。

## 网络

- `NETWORK_MODE=AUTO|DIRECT|PROXY`
- `HTTP(S)_PROXY`：海外 RSS / GitHub
- 降级策略：海外失败不阻断国内采集

## 内部可选组件（Compose）

- PostgreSQL、RSSHub、FreshRSS —— **对最终用户不可见**，仅运维配置
- 个人开源部署可全部关掉，只保留 SQLite + 本应用

## 前端视觉

- 深色极客风（黑底、等宽点缀、细线 HUD）
- 无独立前端构建；Jinja + 共享 `theme.css`
